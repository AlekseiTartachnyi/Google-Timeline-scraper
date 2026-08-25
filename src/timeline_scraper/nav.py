"""Navigate Google Maps to the Timeline screen using the accessibility tree."""

import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from .adb import ADBError, dump_ui, dump_ui_xml, shell, tap
from .extract import parse_bounds_center
from .naming import stamp_date

logger = logging.getLogger(__name__)

_MAPS_PACKAGE = "com.google.android.apps.maps"
_MAPS_ACTIVITY = "com.google.android.maps.MapsActivity"

_LAUNCH_WAIT_S = 2.5
_TAP_WAIT_S = 1.5
_RETRY_WAIT_S = 2.0
_MAX_ATTEMPTS = 3


def launch_maps(serial: str | None = None) -> None:
    """Force-stop Maps then launch it fresh so no previous state is restored."""
    logger.info("Force-stopping Google Maps to clear previous state")
    shell(f"am force-stop {_MAPS_PACKAGE}", serial=serial)
    time.sleep(0.5)
    logger.info("Launching Google Maps")
    shell(
        f"am start -n {_MAPS_PACKAGE}/{_MAPS_ACTIVITY}",
        serial=serial,
    )
    time.sleep(_LAUNCH_WAIT_S)


_TIMELINE_LABELS = {"Timeline", "Your Timeline", "timeline"}


def find_element_by_text(root: ET.Element, text: str) -> ET.Element | None:
    """Return the first node whose text or content-desc equals text."""
    for node in root.iter("node"):
        if node.get("text") == text or node.get("content-desc") == text:
            return node
    return None


def _find_timeline_element(root: ET.Element) -> ET.Element | None:
    """Return the first node that looks like a Timeline menu entry."""
    for node in root.iter("node"):
        text = node.get("text", "")
        desc = node.get("content-desc", "")
        if text in _TIMELINE_LABELS or desc in _TIMELINE_LABELS:
            return node
        if "timeline" in text.lower() or "timeline" in desc.lower():
            return node
    return None


def tap_element(node: ET.Element, serial: str | None = None) -> None:
    """Tap the center of a UI node using its bounds attribute."""
    point = parse_bounds_center(node.get("bounds", ""))
    if point is None:
        raise ADBError(f"Node is not on screen: {ET.tostring(node, encoding='unicode')}")
    tap(*point, serial=serial)


def _find_profile_button(root: ET.Element) -> ET.Element | None:
    """Find the profile / account icon that opens the Maps side menu."""
    for node in root.iter("node"):
        rid = node.get("resource-id", "").lower()
        desc = node.get("content-desc", "").lower()
        if "account" in rid or "profile" in rid:
            return node
        if "account" in desc or "profile" in desc or "signed in" in desc:
            return node
    return None


def _is_on_timeline(root: ET.Element) -> bool:
    """Return True if the current screen appears to be the Timeline screen."""
    for node in root.iter("node"):
        if "timeline" in node.get("resource-id", "").lower():
            return True
        if node.get("text", "") in ("Timeline", "Your Timeline"):
            return True
    return False


def reach_timeline(serial: str | None = None) -> None:
    """Navigate from the Maps home screen to the Timeline screen.

    Strategy:
      1. Dump the UI and check whether we are already on Timeline.
      2. If a clickable "Timeline" element exists, tap it directly.
      3. Otherwise, find the profile / account button, open the menu,
         then tap "Timeline" from there.
      Retries up to _MAX_ATTEMPTS times with a short delay between attempts.

    Raises:
        RuntimeError: If Timeline cannot be reached after all attempts.
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        logger.info("Navigating to Timeline (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
        root = dump_ui(serial=serial)

        if _is_on_timeline(root):
            logger.info("Already on the Timeline screen")
            return

        # Direct tap if "Timeline" is already visible as a clickable element
        node = _find_timeline_element(root)
        if node is not None and node.get("clickable") == "true":
            logger.info("Tapping visible Timeline element: %r", node.get("text"))
            tap_element(node, serial=serial)
            time.sleep(_TAP_WAIT_S)
            if _is_on_timeline(dump_ui(serial=serial)):
                logger.info("Reached Timeline screen")
                return

        # Open the account/profile menu and look for Timeline there
        profile = _find_profile_button(root)
        if profile is not None:
            logger.info("Opening profile menu")
            tap_element(profile, serial=serial)
            time.sleep(_TAP_WAIT_S)
            root = dump_ui(serial=serial)
            node = _find_timeline_element(root)
            if node is not None:
                logger.info("Tapping Timeline in profile menu: %r", node.get("text"))
                tap_element(node, serial=serial)
                time.sleep(_TAP_WAIT_S)
                if _is_on_timeline(dump_ui(serial=serial)):
                    logger.info("Reached Timeline screen")
                    return
            else:
                logger.warning("Timeline item not found in profile menu")
        else:
            logger.warning("Profile button not found in UI tree")

        logger.warning("Timeline not reached; retrying in %.0fs", _RETRY_WAIT_S)
        time.sleep(_RETRY_WAIT_S)

    raise RuntimeError(
        f"Could not reach the Timeline screen after {_MAX_ATTEMPTS} attempts. "
        "Make sure Google Maps is installed, the UI language is English, "
        "and the app is on the home screen."
    )


def _accessible_date_label(d: date) -> str:
    """Return the calendar's accessibility label for a date.

    Matches the content-desc format observed on day cells, e.g.
    "Thursday, August 20, 2026". Built without %-d/%#d since those
    zero-pad-stripping strftime codes aren't portable to Windows.
    """
    return f"{d.strftime('%A, %B')} {d.day}, {d.year}"


_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
_MONTH_ABBR = tuple(name[:3] for name in _MONTH_NAMES)

_DATE_RE = re.compile(
    r"\b(" + "|".join((*_MONTH_NAMES, *_MONTH_ABBR)) + r")\b.*?\d",
    re.IGNORECASE,
)


def _day_labels(d: date) -> tuple[str, ...]:
    """Return the spellings of one date the screen might carry.

    The calendar cell was measured to read "Thursday, August 20, 2026". What
    the day screen itself reads has not been measured, so the shorter forms
    are checked too.
    """
    return (
        _accessible_date_label(d),
        f"{_MONTH_NAMES[d.month - 1]} {d.day}",
        f"{_MONTH_ABBR[d.month - 1]} {d.day}",
    )


def _looks_like_a_date(value: str) -> bool:
    """Return True if the label reads like a date at all."""
    return bool(_DATE_RE.search(value))


def _bounds_rect(value: str) -> tuple[int, int, int, int] | None:
    """Return '[l,t][r,b]' as (left, top, right, bottom), or None."""
    try:
        left, top, right, bottom = (
            int(c) for c in value.replace("][", ",").strip("[]").split(",")
        )
    except ValueError:
        return None
    return left, top, right, bottom


def top_labels(root: ET.Element, fraction: float = 0.15) -> list[str]:
    """Return what is written across the top of the screen, topmost first.

    This is the measurement the day screen has never given up: what the
    calendar chip reads once a day other than today is showing.
    """
    height = 0
    for node in root.iter("node"):
        rect = _bounds_rect(node.get("bounds", ""))
        if rect:
            height = max(height, rect[3])
    if not height:
        return []

    found: list[tuple[int, str]] = []
    for node in root.iter("node"):
        rect = _bounds_rect(node.get("bounds", ""))
        if not rect or rect[1] > height * fraction:
            continue
        for value in (node.get("text", ""), node.get("content-desc", "")):
            if value:
                found.append((rect[1], value))
    found.sort(key=lambda pair: pair[0])

    labels: list[str] = []
    for _, value in found:
        if value not in labels:
            labels.append(value)
    return labels


def _save_dump(xml: str, dump_dir: Path | None, label: str, target: date) -> Path | None:
    """Save the screen that defeated the code, so it can be read off later."""
    if dump_dir is None:
        return None
    dump_dir.mkdir(parents=True, exist_ok=True)
    path = dump_dir / f"dump_{label}_{stamp_date(target)}_{datetime.now():%H-%M-%S}.xml"
    path.write_text(xml, encoding="utf-8")
    logger.error("Saved the screen as %s", path)
    return path


def _find_calendar_control(root: ET.Element) -> ET.Element | None:
    """Return the control that opens the month calendar.

    On the Timeline screen as Maps opens it, the control reads "Today" — that
    is measured. Every day is reached from that freshly launched screen, so
    the fallback below only matters if Maps restores a day despite the
    force-stop: the topmost clickable node that reads like a date at all,
    since the chip lives in the app bar. Which one matched is logged.
    """
    node = find_element_by_text(root, "Today")
    if node is not None:
        logger.debug("Calendar control found by its 'Today' label")
        return node

    candidates: list[tuple[int, ET.Element]] = []
    for node in root.iter("node"):
        if node.get("clickable") != "true":
            continue
        for value in (node.get("text", ""), node.get("content-desc", "")):
            if value and _looks_like_a_date(value):
                point = parse_bounds_center(node.get("bounds", ""))
                if point is not None:
                    candidates.append((point[1], node))
                break

    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    top, node = candidates[0]
    logger.warning(
        "No 'Today' label; falling back to a date-like control at y=%d: text=%r desc=%r",
        top,
        node.get("text"),
        node.get("content-desc"),
    )
    return node


def _confirm_day(target: date, serial: str | None = None) -> bool:
    """Return True if the screen names the day that was asked for.

    The trips of a wrong day must never be filed under the date that was
    requested, so what the screen says is read back and logged either way.
    """
    root = dump_ui(serial=serial)
    wanted = _day_labels(target)
    for node in root.iter("node"):
        for value in (node.get("text", ""), node.get("content-desc", "")):
            if value and any(w in value for w in wanted):
                logger.info("Day %s is showing: %r", target.isoformat(), value)
                return True

    logger.warning(
        "Could not confirm %s is showing. Top of the screen reads: %s",
        target.isoformat(),
        top_labels(root) or "nothing with a label",
    )
    return False


def go_to_date(
    target: date,
    serial: str | None = None,
    dump_dir: Path | None = None,
) -> bool:
    """From the Timeline screen, open the calendar and select a specific date.

    Taps the control that opens the month calendar, then taps the day cell
    whose content-desc matches the target date's accessible label. Returns
    whether the opened day could be confirmed on screen. Does not page across
    months yet — the target date must fall within whatever month the calendar
    opens to.

    Raises:
        RuntimeError: If the calendar control or the target day cell isn't found.
    """
    xml = dump_ui_xml(serial=serial)
    control = _find_calendar_control(ET.fromstring(xml))
    if control is None:
        path = _save_dump(xml, dump_dir, "calendar-not-found", target)
        raise RuntimeError(
            "Calendar control not found on the Timeline screen: no 'Today' label "
            "and nothing clickable that reads like a date."
            + (f" The screen is saved as {path}." if path else "")
        )
    tap_element(control, serial=serial)
    time.sleep(_TAP_WAIT_S)

    xml = dump_ui_xml(serial=serial)
    label = _accessible_date_label(target)
    day_node = find_element_by_text(ET.fromstring(xml), label)
    if day_node is None:
        path = _save_dump(xml, dump_dir, "day-cell-not-found", target)
        raise RuntimeError(
            f"Calendar day cell not found for {label!r}. The calendar does not "
            "page across months yet, so the date must be in the month it opens to."
            + (f" The screen is saved as {path}." if path else "")
        )
    logger.info("Tapping calendar day: %r", label)
    tap_element(day_node, serial=serial)
    time.sleep(_TAP_WAIT_S)
    return _confirm_day(target, serial=serial)
