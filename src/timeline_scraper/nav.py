"""Navigate Google Maps to the Timeline screen using the accessibility tree."""

import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET

from .adb import ADBError, dump_ui, dump_ui_xml, keyevent, shell, tap
from .extract import parse_bounds_center, scroll_to_top
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
# What a calendar day cell reads: "Thursday, August 20, 2026".
_DAY_CELL_RE = re.compile(
    r"^[A-Za-z]+day,\s+(" + "|".join(_MONTH_NAMES) + r")\s+\d{1,2},\s+\d{4}$"
)
# Icon-only controls carry no date, only a name for what they open.
_CALENDAR_WORDS = ("calendar", "choose date", "select date", "date picker", "show date")

# The chip sits in the app bar. Rows of the day list start below it, and one
# of those must never be tapped by mistake.
_TOP_STRIP = 0.25


def _day_labels(d: date) -> tuple[str, ...]:
    """Return the spellings of one date the screen might carry."""
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
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _screen_height(root: ET.Element) -> int:
    """Return the tallest bottom edge in the tree — the screen height."""
    height = 0
    for node in root.iter("node"):
        rect = _bounds_rect(node.get("bounds", ""))
        if rect:
            height = max(height, rect[3])
    return height


def top_labels(root: ET.Element, fraction: float = _TOP_STRIP) -> list[str]:
    """Return what is written across the top of the screen, topmost first."""
    height = _screen_height(root)
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


def _calendar_candidates(root: ET.Element) -> list[tuple[str, ET.Element]]:
    """Return what might open the month calendar, best first.

    Clickability is not required. These are virtual nodes of a web page: the
    node carrying the label and the node carrying the click handler are not
    the same, and a tap lands on screen coordinates either way. What keeps a
    trip row from being tapped is position — only the app bar is searched —
    and the check that the calendar actually opened afterwards.
    """
    height = _screen_height(root) or 1
    exact: list[tuple[int, ET.Element]] = []
    dated: list[tuple[int, ET.Element]] = []
    named: list[tuple[int, ET.Element]] = []
    rest: list[tuple[int, ET.Element]] = []

    for node in root.iter("node"):
        rect = _bounds_rect(node.get("bounds", ""))
        if not rect:
            continue
        text = node.get("text", "")
        desc = node.get("content-desc", "")
        rid = node.get("resource-id", "").lower()
        top = rect[1]

        if "Today" in (text, desc):
            exact.append((top, node))
            continue
        if top > height * _TOP_STRIP:
            continue
        if any(_looks_like_a_date(v) for v in (text, desc) if v):
            dated.append((top, node))
            continue
        haystack = f"{text} {desc} {rid}".lower()
        if any(word in haystack for word in _CALENDAR_WORDS):
            named.append((top, node))
        elif text or desc:
            # Last resort: the chip may read something this code has never
            # seen ("Yesterday"). Tapping it is safe — the calendar either
            # opens or the tap is undone.
            rest.append((top, node))

    candidates: list[tuple[str, ET.Element]] = []
    for why, group in (
        ("'Today'", exact),
        ("a date label", dated),
        ("its name", named),
        ("guesswork", rest),
    ):
        for _, node in sorted(group, key=lambda pair: pair[0]):
            candidates.append((why, node))
    return candidates


def _calendar_is_open(root: ET.Element) -> bool:
    """Return True if day cells are on screen, i.e. the calendar opened."""
    for node in root.iter("node"):
        for value in (node.get("content-desc", ""), node.get("text", "")):
            if value and _DAY_CELL_RE.match(value):
                return True
    return False


def open_calendar(
    target: date,
    serial: str | None = None,
    dump_dir: Path | None = None,
    max_taps: int = 4,
) -> ET.Element:
    """Open the month calendar from the Timeline screen and return its tree.

    The day list is put back at its first row first: collecting a day leaves
    the list at the bottom, and the date header scrolls away with it. Then the
    candidates in the app bar are tapped in turn until day cells appear —
    tapping and checking, rather than assuming which node is the chip.

    Raises:
        RuntimeError: If no tap opened the calendar.
    """
    scroll_to_top(serial=serial)

    xml = dump_ui_xml(serial=serial)
    root = ET.fromstring(xml)
    if _calendar_is_open(root):
        logger.info("Calendar is already open")
        return root

    candidates = _calendar_candidates(root)
    logger.debug("Calendar candidates: %d", len(candidates))

    for why, node in candidates[:max_taps]:
        logger.info(
            "Opening the calendar by %s: text=%r desc=%r bounds=%s",
            why,
            node.get("text"),
            node.get("content-desc"),
            node.get("bounds"),
        )
        tap_element(node, serial=serial)
        time.sleep(_TAP_WAIT_S)
        opened = dump_ui(serial=serial)
        if _calendar_is_open(opened):
            return opened
        logger.warning("That tap did not open the calendar; stepping back")
        keyevent("KEYCODE_BACK", serial=serial)
        time.sleep(_TAP_WAIT_S)

    path = _save_dump(xml, dump_dir, "calendar-not-found", target)
    raise RuntimeError(
        "Nothing on the Timeline screen opened the calendar. The top of the "
        f"screen reads: {top_labels(root) or 'nothing with a label'}."
        + (f" The screen is saved as {path}." if path else "")
    )


# What the day bar reads: "Tue, Aug 11, 2026", measured on the phone.
_SHOWN_FORMATS = ("%a, %b %d, %Y", "%A, %B %d, %Y", "%b %d, %Y", "%B %d, %Y")
# Names the arrows either side of that date might carry.
_NEXT_WORDS = ("next day", "next date", "forward one day", "following day")
_PREV_WORDS = ("previous day", "previous date", "back one day", "prior day")
# Stepping day by day beats reopening the calendar, but only for a short walk.
_MAX_STEPS = 7


def _parse_shown_date(value: str) -> date | None:
    """Return the date a day-bar label names, or None if it names no date."""
    text = value.strip().rstrip("\u25be\u25bc").strip()
    for fmt in _SHOWN_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def shown_date(root: ET.Element) -> tuple[ET.Element, date] | None:
    """Return the day bar and the date it names, if it is on screen.

    The bar sits above the day list — "‹ Tue, Aug 11, 2026 ▾ ›" — and the date
    it carries is the one thing on the screen that says which day is open.
    """
    for node in root.iter("node"):
        for value in (node.get("text", ""), node.get("content-desc", "")):
            if not value:
                continue
            found = _parse_shown_date(value)
            if found is not None and _bounds_rect(node.get("bounds", "")):
                return node, found
    return None


def _step_arrow(root: ET.Element, bar: ET.Element, forward: bool) -> ET.Element | None:
    """Return the arrow that steps one day from the day bar, or None.

    A named arrow wins. Otherwise it is the node furthest along the same row
    as the date, on the side the step goes: the arrows sit either end of that
    row and nothing else shares it.
    """
    words = _NEXT_WORDS if forward else _PREV_WORDS
    for node in root.iter("node"):
        haystack = f"{node.get('text', '')} {node.get('content-desc', '')}".lower()
        if any(word in haystack for word in words) and _bounds_rect(node.get("bounds", "")):
            logger.debug("Step arrow found by name: %r", haystack.strip())
            return node

    rect = _bounds_rect(bar.get("bounds", ""))
    if rect is None:
        return None
    left, top, right, bottom = rect
    middle = (top + bottom) // 2
    height = bottom - top

    best: tuple[int, ET.Element] | None = None
    for node in root.iter("node"):
        other = _bounds_rect(node.get("bounds", ""))
        if other is None or other == rect:
            continue
        if abs((other[1] + other[3]) // 2 - middle) > height:
            continue          # not on the day bar's row
        if forward and other[0] < right:
            continue          # not clear of the date, so not the right arrow
        if not forward and other[2] > left:
            continue
        centre = (other[0] + other[2]) // 2
        rank = centre if forward else -centre
        if best is None or rank > best[0]:
            best = (rank, node)

    return best[1] if best else None


def _step_days(
    target: date,
    bar: ET.Element,
    current: date,
    root: ET.Element,
    serial: str | None = None,
) -> bool:
    """Walk the day bar's arrows from the open day to the target.

    Returns False as soon as a tap fails to move the day, so the caller can
    fall back to the calendar rather than collect whatever is on screen.
    """
    forward = target > current
    steps = abs((target - current).days)
    logger.info(
        "Stepping %d day(s) %s from %s with the day bar's arrow",
        steps,
        "forward" if forward else "back",
        current.isoformat(),
    )

    for _ in range(steps):
        arrow = _step_arrow(root, bar, forward)
        if arrow is None:
            logger.warning("No %s arrow beside the date", "next-day" if forward else "previous-day")
            return False
        tap_element(arrow, serial=serial)
        time.sleep(_TAP_WAIT_S)

        root = dump_ui(serial=serial)
        found = shown_date(root)
        if found is None:
            logger.warning("The day bar is gone after tapping the arrow")
            return False
        bar, moved = found
        expected = current + timedelta(days=1 if forward else -1)
        if moved != expected:
            logger.warning(
                "The arrow moved the day to %s, not %s", moved.isoformat(), expected.isoformat()
            )
            return False
        current = moved
        logger.info("Day bar now reads %s", current.isoformat())

    return current == target


def _confirm_day(target: date, serial: str | None = None) -> bool:
    """Return True if the screen names the day that was asked for.

    The trips of a wrong day must never be filed under the date that was
    requested, so what the screen says is read back and logged either way.
    """
    root = dump_ui(serial=serial)
    found = shown_date(root)
    if found is not None:
        _, current = found
        if current == target:
            logger.info("Day bar reads %s", target.isoformat())
            return True
        logger.warning(
            "Day bar reads %s, not %s", current.isoformat(), target.isoformat()
        )
        return False

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


def _pick_from_calendar(
    target: date,
    serial: str | None = None,
    dump_dir: Path | None = None,
) -> None:
    """Open the month calendar and tap the target's day cell."""
    root = open_calendar(target, serial=serial, dump_dir=dump_dir)
    label = _accessible_date_label(target)
    day_node = find_element_by_text(root, label)
    if day_node is None:
        path = _save_dump(
            ET.tostring(root, encoding="unicode"), dump_dir, "day-cell-not-found", target
        )
        raise RuntimeError(
            f"Calendar day cell not found for {label!r}. The calendar does not "
            "page across months yet, so the date must be in the month it opens to."
            + (f" The screen is saved as {path}." if path else "")
        )
    logger.info("Tapping calendar day: %r", label)
    tap_element(day_node, serial=serial)
    time.sleep(_TAP_WAIT_S)


def go_to_date(
    target: date,
    serial: str | None = None,
    dump_dir: Path | None = None,
) -> bool:
    """Put the Timeline on a given day and say whether the screen confirms it.

    The day bar above the list carries the open date between two arrows, so a
    day next to the one already open is one tap away. The calendar is for the
    first day of a run and for anything the arrows cannot reach: it is the
    slower path and the one that can miss.

    Raises:
        RuntimeError: If the calendar cannot be opened or the day cell is missing.
    """
    scroll_to_top(serial=serial)
    root = dump_ui(serial=serial)
    found = shown_date(root)

    if found is not None:
        bar, current = found
        if current == target:
            logger.info("Day bar already reads %s", target.isoformat())
            return True
        if abs((target - current).days) <= _MAX_STEPS:
            if _step_days(target, bar, current, root, serial=serial):
                return _confirm_day(target, serial=serial)
            logger.warning("Stepping failed; falling back to the calendar")

    _pick_from_calendar(target, serial=serial, dump_dir=dump_dir)
    return _confirm_day(target, serial=serial)
