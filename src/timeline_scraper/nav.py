"""Navigate Google Maps to the Timeline screen using the accessibility tree."""

import logging
import time
from datetime import date
from xml.etree import ElementTree as ET

from .adb import ADBError, dump_ui, shell, tap

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


def _parse_bounds_center(bounds: str) -> tuple[int, int]:
    """Return the center pixel (x, y) of a bounds string '[l,t][r,b]'."""
    coords = bounds.replace("][", ",").strip("[]").split(",")
    left, top, right, bottom = (int(c) for c in coords)
    return (left + right) // 2, (top + bottom) // 2


def tap_element(node: ET.Element, serial: str | None = None) -> None:
    """Tap the center of a UI node using its bounds attribute."""
    bounds = node.get("bounds", "")
    if not bounds:
        raise ADBError(f"Node has no bounds: {ET.tostring(node, encoding='unicode')}")
    x, y = _parse_bounds_center(bounds)
    tap(x, y, serial=serial)


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


def go_to_date(target: date, serial: str | None = None) -> None:
    """From the Timeline screen, open the calendar and select a specific date.

    Taps the "Today" control to open the month calendar, then taps the day
    cell whose content-desc matches the target date's accessible label.
    Does not page across months yet — the target date must fall within
    whatever month the calendar opens to.

    Raises:
        RuntimeError: If the "Today" control or the target day cell isn't found.
    """
    root = dump_ui(serial=serial)
    today_node = find_element_by_text(root, "Today")
    if today_node is None:
        raise RuntimeError("'Today' control not found on the Timeline screen")
    logger.info("Tapping 'Today' to open the calendar")
    tap_element(today_node, serial=serial)
    time.sleep(_TAP_WAIT_S)

    label = _accessible_date_label(target)
    root = dump_ui(serial=serial)
    day_node = find_element_by_text(root, label)
    if day_node is None:
        raise RuntimeError(f"Calendar day cell not found for {label!r}")
    logger.info("Tapping calendar day: %r", label)
    tap_element(day_node, serial=serial)
    time.sleep(_TAP_WAIT_S)
