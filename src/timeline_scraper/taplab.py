"""Run every tap strategy against the same day and keep what each one produced.

Which strategy survives the phone cannot be reasoned out from here — the
WebView's virtual rectangles are the thing under test. So both are run, on the
same two driving trips, with the day reopened in between so neither inherits
the other's scroll position or a map the previous run panned away.

Everything lands under `exports/draft-screenshots/<variant>/<timestamp>/`:
the tree and the screen before the touch, the screen straight after it, the
settled map when the trip opened, and a `result.txt` naming what happened.
"""

import logging
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from . import adb, tap
from .extract import flatten
from .capture import file_name, opened_trip_screen, wait_for_map
from .model import Day, Trip

logger = logging.getLogger(__name__)

Locator = Callable[[str, set[str], str | None], tuple[int, int] | None]
Gesture = Callable[[tuple[int, int], str | None], None]

# Each entry is (folder name, how the row is found, how it is touched).
VARIANTS: tuple[tuple[str, Locator, Gesture], ...] = (
    ("variant-1-strict-bounds", tap.locate_strict, tap.tap_instant),
    ("variant-2-anchor-point", tap.locate_anchor, tap.tap_gesture),
)

_TRIPS_PER_VARIANT = 2
_AFTER_TAP_S = 1.2


def _stamp() -> str:
    """Return a folder-safe timestamp, e.g. '2026-Aug-24-1503'."""
    return datetime.now().strftime("%Y-%b-%d-%H%M")


def _save_screen(out_dir: Path, name: str, serial: str | None) -> None:
    """Write the tree and the screen to disk under one name."""
    root = adb.dump_ui(serial=serial)
    (out_dir / f"{name}.xml").write_bytes(ET.tostring(root, encoding="utf-8"))
    (out_dir / f"{name}.png").write_bytes(adb.screencap(serial=serial))


def _attempt(
    index: int,
    trip: Trip,
    day_rows: set[str],
    out_dir: Path,
    locate: Locator,
    gesture: Gesture,
    serial: str | None,
) -> str:
    """Try to open one trip and save its map. Returns a one-line result."""
    name = f"{index:02d}-{trip.start_time or 'unknown'}".replace(":", "").replace(" ", "")
    logger.info("--- trip %d: %r", index, trip.raw_text)
    _save_screen(out_dir, f"{name}-1-before", serial)

    before_png = adb.screencap(serial=serial)
    point = locate(trip.raw_text, day_rows, serial)
    if point is None:
        logger.warning("Could not locate the row — no touch sent")
        return f"{name}: NOT LOCATED — the row's rectangle never passed the check"

    under = tap.describe_node_at(point, serial=serial)
    logger.info("Touching (%d, %d); the tree says that point is %s", *point, under)
    (out_dir / f"{name}-2-target.txt").write_text(
        f"point={point}\nunder point={under}\nrow={trip.raw_text!r}\n", encoding="utf-8"
    )

    gesture(point, serial)
    time.sleep(_AFTER_TAP_S)
    _save_screen(out_dir, f"{name}-3-after-tap", serial)

    if adb.screencap(serial=serial) == before_png:
        logger.warning("The screen is byte-identical after the touch — nothing reacted")
        return f"{name}: NO REACTION at {point} (touched {under})"

    if not opened_trip_screen(trip.raw_text, day_rows, serial=serial):
        logger.warning("The screen changed but the trip did not open — the map most likely moved")
        return f"{name}: WRONG TARGET at {point} (touched {under})"

    png, waited_ms, settled = wait_for_map(serial=serial)
    map_path = out_dir / file_name(trip)
    map_path.write_bytes(png)
    logger.info("Saved %s (%d ms%s)", map_path.name, waited_ms, "" if settled else ", still moving")
    return f"{name}: OPENED at {point} -> {map_path.name} ({waited_ms} ms)"


def _back_to_list(day_rows: set[str], serial: str | None) -> bool:
    """Press Back until the day list is on screen again."""
    for _ in range(3):
        adb.keyevent("KEYCODE_BACK", serial=serial)
        time.sleep(1.0)
        on_screen = {n.content_desc for n in flatten(adb.dump_ui(serial=serial))}
        if len(on_screen & day_rows) >= 2:
            return True
    return False


def run_tap_lab(
    day: Day,
    base_dir: Path,
    reopen_day: Callable[[], None],
    serial: str | None = None,
    mode: str = "Driving",
) -> list[str]:
    """Run every variant over the same trips and return the result lines."""
    trips = [t for t in day.trips if t.mode == mode][:_TRIPS_PER_VARIANT]
    if not trips:
        logger.error("The day has no %s trip to test with", mode)
        return []

    day_rows = {s.raw_text for s in day.segments if s.raw_text}
    root = base_dir / "draft-screenshots"
    results: list[str] = []

    for variant_index, (name, locate, gesture) in enumerate(VARIANTS, start=1):
        out_dir = root / name / _stamp()
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info("=" * 70)
        logger.info("VARIANT %d — %s", variant_index, name)
        logger.info("Output: %s", out_dir)
        logger.info("=" * 70)

        if variant_index > 1:
            logger.info("Reopening the day so this variant starts from a clean screen")
            reopen_day()

        lines: list[str] = []
        for trip_index, trip in enumerate(trips, start=1):
            line = _attempt(trip_index, trip, day_rows, out_dir, locate, gesture, serial)
            logger.info("Result: %s", line)
            lines.append(line)
            if not _back_to_list(day_rows, serial=serial):
                logger.warning("Lost the day list — reopening it before the next trip")
                reopen_day()

        (out_dir / "result.txt").write_text(
            f"variant: {name}\n" + "\n".join(lines) + "\n", encoding="utf-8"
        )
        results.extend(f"{name}  {line}" for line in lines)

    logger.info("=" * 70)
    logger.info("Tap lab summary")
    for line in results:
        logger.info("  %s", line)
    logger.info("Files are under %s", root)
    return results
