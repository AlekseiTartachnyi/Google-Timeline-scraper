"""Second pass over a scraped day: open each driving trip and save its map.

The list pass and this pass are kept apart on purpose. Opening a row replaces
the screen, which would break the scroll-and-merge loop that builds the day.

Rows are reached by touch. The Timeline day is a full-screen WebView, so there
is no focusable row to select and no container to bound a rectangle against —
see tap.py for what that leaves and how each strategy guards the touch.
"""

import logging
import re
import time
from pathlib import Path

from . import adb, tap
from .extract import descriptions, flatten
from .model import Day, Trip

logger = logging.getLogger(__name__)

_AFTER_TAP_S = 1.2
_MIN_SETTLE_S = 1.2
_POLL_S = 0.4
_MAX_SETTLE_S = 8.0
_BACK_ATTEMPTS = 3
_AFTER_BACK_S = 1.0


def visible_descriptions(serial: str | None) -> list[str]:
    """Return the accessibility descriptions currently on screen."""
    return descriptions(flatten(adb.dump_ui(serial=serial)))


def on_day_list(day_rows: set[str], serial: str | None) -> bool:
    """Return True if the day list is the screen in front of us.

    Judged from the day's own rows: several of them share the screen on the day
    list, and none of them survives on a trip screen.
    """
    return len(set(visible_descriptions(serial)) & day_rows) >= 2


def opened_trip_screen(target: str, day_rows: set[str], serial: str | None) -> bool:
    """Return True if the trip detail screen appears to be open."""
    on_screen = set(visible_descriptions(serial))
    return len((on_screen & day_rows) - {target}) < 2


def wait_for_map(serial: str | None) -> tuple[bytes, int, bool]:
    """Wait until the screen stops changing, then return (png, waited_ms, settled).

    A short trip makes Maps zoom in and fetch new tiles, so the wait is driven
    by the picture itself: poll screenshots until two in a row are identical.
    """
    time.sleep(_MIN_SETTLE_S)
    waited = _MIN_SETTLE_S
    previous = adb.screencap(serial=serial)
    while waited < _MAX_SETTLE_S:
        time.sleep(_POLL_S)
        waited += _POLL_S
        current = adb.screencap(serial=serial)
        if current == previous:
            return current, int(waited * 1000), True
        previous = current
    return previous, int(waited * 1000), False


def _hhmm(clock: str | None) -> str:
    """Return '1:21 PM' as '1321' so file names sort in trip order."""
    if not clock:
        return "0000"
    match = re.match(r"(\d{1,2}):(\d{2})\s*([AP])M", clock.strip(), re.IGNORECASE)
    if not match:
        return "0000"
    hour = int(match.group(1)) % 12
    if match.group(3).upper() == "P":
        hour += 12
    return f"{hour:02d}{match.group(2)}"


def file_name(trip: Trip) -> str:
    """Return a stable file name built from the trip's own times and mode."""
    mode = trip.mode.lower().replace(" ", "_")
    return f"{_hhmm(trip.start_time)}-{_hhmm(trip.end_time)}_{mode}.png"


def return_to_list(day_rows: set[str], serial: str | None) -> bool:
    """Press Back until the day list is on screen again."""
    for _ in range(_BACK_ATTEMPTS):
        adb.keyevent("KEYCODE_BACK", serial=serial)
        time.sleep(_AFTER_BACK_S)
        if on_day_list(day_rows, serial=serial):
            return True
    return False


def capture_trip_maps(
    day: Day,
    out_dir: Path,
    serial: str | None = None,
    modes: tuple[str, ...] = ("Driving",),
    locate=tap.locate_strict,
    gesture=tap.tap_instant,
) -> int:
    """Save a map screenshot for every trip of the given modes. Returns the count.

    The locating strategy is a parameter because which one the phone accepts is
    still being measured — `scrape --tap-lab` runs them side by side.
    """
    targets = [t for t in day.trips if t.mode in modes]
    if not targets:
        logger.info("No trips to screenshot")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    day_rows = {s.raw_text for s in day.segments if s.raw_text}
    saved = 0

    logger.info("Capturing maps for %d trip(s)", len(targets))
    for trip in targets:
        point = locate(trip.raw_text, day_rows, serial)
        if point is None:
            logger.warning("Row could not be located: %r", trip.raw_text)
            continue

        logger.info("Touching (%d, %d) for %r", point[0], point[1], trip.raw_text)
        gesture(point, serial)
        time.sleep(_AFTER_TAP_S)

        if not opened_trip_screen(trip.raw_text, day_rows, serial=serial):
            logger.warning(
                "The trip did not open; the touch hit %s",
                tap.describe_node_at(point, serial=serial),
            )
            return_to_list(day_rows, serial=serial)
            continue

        png, waited_ms, settled = wait_for_map(serial=serial)
        path = out_dir / file_name(trip)
        path.write_bytes(png)
        trip.screenshot = f"{out_dir.name}/{path.name}"
        saved += 1
        logger.info(
            "Saved %s (%d ms%s)", trip.screenshot, waited_ms, "" if settled else ", still changing"
        )

        if not return_to_list(day_rows, serial=serial):
            raise RuntimeError("Back did not return to the Timeline day list")

    missed = len(targets) - saved
    if missed:
        logger.warning("%d trip(s) without a screenshot", missed)
    return saved
