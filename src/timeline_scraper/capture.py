"""Second pass over a scraped day: open each driving trip and save its map.

The list pass and this pass are kept apart on purpose. Opening a row replaces
the screen, which would break the scroll-and-merge loop that builds the day.

Rows are reached with D-pad focus, not with taps at reported coordinates —
see focus.py for why coordinates cannot be trusted here.
"""

import logging
import re
import time
from pathlib import Path

from . import adb, focus
from .extract import descriptions, flatten
from .model import Day, Trip

logger = logging.getLogger(__name__)

_ACTIVATE_KEYS = (focus.CENTER, focus.ENTER)
_AFTER_ACTIVATE_S = 0.9
_MIN_SETTLE_S = 1.2
_POLL_S = 0.4
_MAX_SETTLE_S = 8.0
_MAX_STEPS_PER_SWEEP = 400
_MAX_SWEEPS = 6


def _visible_descriptions(serial: str | None) -> list[str]:
    """Return the accessibility descriptions currently on screen."""
    return descriptions(flatten(adb.dump_ui(serial=serial)))


def _on_day_list(day_rows: set[str], serial: str | None) -> bool:
    """Return True if the day list is the screen in front of us.

    Judged from the day's own rows: several of them share the screen on the
    day list, and none of them survives on a trip screen.
    """
    return len(set(_visible_descriptions(serial)) & day_rows) >= 2


def _opened(target: str, day_rows: set[str], serial: str | None) -> bool:
    """Return True if the trip detail screen appears to be open."""
    on_screen = set(_visible_descriptions(serial))
    return len((on_screen & day_rows) - {target}) < 2


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


def _open_focused(target: str, day_rows: set[str], serial: str | None) -> bool:
    """Activate the focused row and confirm the trip screen replaced the list."""
    for key in _ACTIVATE_KEYS:
        focus.press(key, serial=serial, settle_s=_AFTER_ACTIVATE_S)
        if _opened(target, day_rows, serial=serial):
            return True
        logger.debug("%s did not open the trip screen", key)
    return False


def _return_to_list(day_rows: set[str], serial: str | None) -> bool:
    """Press Back until the day list is on screen again."""
    for _ in range(3):
        focus.back(serial=serial)
        if _on_day_list(day_rows, serial=serial):
            return True
    return False


def _capture_focused(
    trip: Trip, day_rows: set[str], out_dir: Path, serial: str | None
) -> bool:
    """Open the currently focused trip row, save its map, and come back."""
    target = trip.raw_text
    if not _open_focused(target, day_rows, serial=serial):
        logger.warning("Row would not open: %r", target)
        return False

    png, waited_ms, settled = _wait_for_map(serial=serial)
    path = out_dir / _file_name(trip)
    path.write_bytes(png)
    trip.screenshot = f"{out_dir.name}/{path.name}"
    logger.info(
        "Saved %s (%d ms%s)", trip.screenshot, waited_ms, "" if settled else ", still changing"
    )

    if not _return_to_list(day_rows, serial=serial):
        raise RuntimeError("Back did not return to the Timeline day list")
    return True


def capture_trip_maps(
    day: Day,
    out_dir: Path,
    serial: str | None = None,
    modes: tuple[str, ...] = ("Driving",),
) -> int:
    """Save a map screenshot for every trip of the given modes. Returns the count.

    Walks the list with D-pad focus. Every row is identified from the dump
    while it holds focus, so the row about to be opened is known by name and
    no coordinate is ever used.
    """
    targets = {t.raw_text: t for t in day.trips if t.mode in modes}
    if not targets:
        logger.info("No trips to screenshot")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    day_rows = {s.raw_text for s in day.segments if s.raw_text}
    pending = dict(targets)
    done: set[str] = set()

    logger.info("Capturing maps for %d trip(s) by focus navigation", len(targets))

    for sweep in range(1, _MAX_SWEEPS + 1):
        if not pending:
            break
        focus.to_start(serial=serial)
        node = focus.establish(serial=serial)
        if node is None:
            logger.error(
                "This screen does not take D-pad focus — no node reports focused=true "
                "after %s. Run 'scrape --probe-focus' and inspect the saved dumps.",
                focus.DOWN,
            )
            return len(done)

        logger.info("Sweep %d — focus starts on %s", sweep, focus.label(node))
        captured_here = 0
        for _ in range(_MAX_STEPS_PER_SWEEP):
            if not pending:
                break
            desc = node.content_desc
            if desc in pending:
                trip = pending.pop(desc)
                logger.info("Opening focused row: %r", desc)
                if _capture_focused(trip, day_rows, out_dir, serial=serial):
                    done.add(desc)
                captured_here += 1
                # Back may have dropped or moved the highlight; only keep
                # stepping while focus is still on the row we just left.
                node = focus.focused_node(serial=serial)
                if node is None or node.content_desc != desc:
                    logger.debug("Focus did not survive Back; restarting the sweep")
                    break
            node, moved = focus.step(focus.DOWN, serial=serial)
            if not moved or node is None:
                break

        if captured_here == 0:
            logger.warning("Sweep %d reached the end without finding a pending row", sweep)
            break

    missed = len(targets) - len(done)
    if missed:
        logger.warning("%d trip(s) without a screenshot", missed)
    return len(done)
