"""Second pass over a scraped day: open each driving trip and save its map.

The list pass and this pass are kept apart on purpose. Tapping a row replaces
the screen, which would break the scroll-and-merge loop that builds the day.
"""

import logging
import re
import time
from pathlib import Path

from . import adb
from .extract import flatten, parse_bounds_center, scroll_to_top
from .model import Day, Trip

logger = logging.getLogger(__name__)

_MAX_TAPS = 3
_AFTER_TAP_S = 0.8
_AFTER_BACK_S = 1.0
_MIN_SETTLE_S = 1.2
_POLL_S = 0.4
_MAX_SETTLE_S = 8.0
_MAX_SCROLL_PASSES = 40


def _visible_descriptions(serial: str | None) -> list[str]:
    """Return the accessibility descriptions currently on screen."""
    return [n.content_desc for n in flatten(adb.dump_ui(serial=serial)) if n.content_desc]


def _find_tappable(descriptions_on_screen: list[str], target: str) -> bool:
    """Return True if the target row is currently on screen."""
    return target in descriptions_on_screen


def _tap_target(target: str, serial: str | None) -> bool:
    """Tap the row with this description. Returns False if it is not on screen."""
    for node in flatten(adb.dump_ui(serial=serial)):
        if node.content_desc != target:
            continue
        point = parse_bounds_center(node.bounds)
        if point is None:
            return False
        adb.tap(*point, serial=serial)
        return True
    return False


def _opened(target: str, day_rows: set[str], serial: str | None) -> bool:
    """Return True if the trip detail screen appears to be open.

    Judged from the day's own rows rather than from any assumed label: on the
    day list many of them are on screen at once, on a trip screen they are gone.
    """
    on_screen = set(_visible_descriptions(serial))
    remaining = (on_screen & day_rows) - {target}
    return len(remaining) < 2


def _wait_for_map(serial: str | None) -> tuple[bytes, int, bool]:
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


def _go_back(day_rows: set[str], serial: str | None) -> bool:
    """Press Back and confirm the day list is on screen again."""
    for _ in range(2):
        adb.shell("input keyevent KEYCODE_BACK", serial=serial)
        time.sleep(_AFTER_BACK_S)
        if len(set(_visible_descriptions(serial)) & day_rows) >= 2:
            return True
    return False


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


def _file_name(trip: Trip) -> str:
    """Return a stable file name built from the trip's own times and mode."""
    mode = trip.mode.lower().replace(" ", "_")
    return f"{_hhmm(trip.start_time)}-{_hhmm(trip.end_time)}_{mode}.png"


def _capture_one(trip: Trip, day_rows: set[str], out_dir: Path, serial: str | None) -> bool:
    """Open one trip, save its map screenshot, and return to the day list."""
    target = trip.raw_text
    for attempt in range(1, _MAX_TAPS + 1):
        if not _tap_target(target, serial=serial):
            logger.debug("Row not tappable on screen: %r", target)
            return False
        time.sleep(_AFTER_TAP_S)
        if _opened(target, day_rows, serial=serial):
            break
        logger.info("Trip did not open on tap %d/%d, retrying", attempt, _MAX_TAPS)
    else:
        logger.warning("Could not open trip after %d taps: %r", _MAX_TAPS, target)
        return False

    png, waited_ms, settled = _wait_for_map(serial=serial)
    path = out_dir / _file_name(trip)
    path.write_bytes(png)
    trip.screenshot = f"{out_dir.name}/{path.name}"
    logger.info(
        "Saved %s (%d ms%s)", trip.screenshot, waited_ms, "" if settled else ", still changing"
    )

    if not _go_back(day_rows, serial=serial):
        raise RuntimeError("Back did not return to the Timeline day list")
    return True


def capture_trip_maps(
    day: Day,
    out_dir: Path,
    serial: str | None = None,
    modes: tuple[str, ...] = ("Driving",),
) -> int:
    """Save a map screenshot for every trip of the given modes. Returns the count.

    Rows are located by their accessibility description on each pass, never by
    remembered coordinates: both scrolling and Back move them.
    """
    targets = {t.raw_text: t for t in day.trips if t.mode in modes}
    if not targets:
        logger.info("No trips to screenshot")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    day_rows = {s.raw_text for s in day.segments if s.raw_text}
    width, height = adb.screen_size(serial=serial)
    x = width // 2

    logger.info("Capturing maps for %d trips", len(targets))
    scroll_to_top(serial=serial)

    done: set[str] = set()
    failed: set[str] = set()
    for _ in range(_MAX_SCROLL_PASSES):
        if len(done | failed) == len(targets):
            break
        on_screen = _visible_descriptions(serial)
        progressed = False
        for target, trip in targets.items():
            if target in done or target in failed:
                continue
            if not _find_tappable(on_screen, target):
                continue
            if _capture_one(trip, day_rows, out_dir, serial=serial):
                done.add(target)
            else:
                failed.add(target)
            progressed = True
            break  # the screen moved; re-read it before the next target
        if progressed:
            continue
        adb.swipe(x, int(height * 0.80), x, int(height * 0.35), 400, serial=serial)
        time.sleep(0.6)

    missed = len(targets) - len(done)
    if missed:
        logger.warning("%d trip(s) without a screenshot", missed)
    return len(done)
