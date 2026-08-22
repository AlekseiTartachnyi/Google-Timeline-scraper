"""CLI entrypoint — scrape and flatten commands."""

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .adb import ADBError, devices, is_locked, wake_screen
from .extract import capture_day_rows
from .nav import go_to_date, launch_maps, reach_timeline

logger = logging.getLogger(__name__)

# M2 test date (spec: dates are hardcoded through M1-M5); Thursday, Aug 20 2026.
_M2_TEST_DATE = date(2026, 8, 20)


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# scrape
# ---------------------------------------------------------------------------

def cmd_scrape(args: argparse.Namespace) -> int:
    """Preflight, reach Timeline, capture one hardcoded day to a draft JSON (M2.2).

    Multi-day looping and crash-safe incremental save are added in M3.
    """
    _setup_logging(args.verbose)

    logger.info("ADB preflight check")
    try:
        found = devices()
    except ADBError as exc:
        logger.error("ADB error: %s", exc)
        return 1

    if not found:
        logger.error(
            "No device detected. Connect your Pixel via USB, enable USB debugging, "
            "and authorize this computer on the phone."
        )
        return 1

    serial = found[0]
    if len(found) > 1:
        logger.warning("Multiple devices found; using %s", serial)
    else:
        logger.info("Device: %s", serial)

    try:
        wake_screen(serial=serial)
        if is_locked(serial=serial):
            input("  Phone is locked. Unlock it and press Enter to continue...")
        launch_maps(serial=serial)
        reach_timeline(serial=serial)

        logger.info("M2.1 — opening calendar and selecting %s", _M2_TEST_DATE.isoformat())
        go_to_date(_M2_TEST_DATE, serial=serial)

        logger.info("M2.2 — capturing %s, scrolling to the end of the day", _M2_TEST_DATE.isoformat())
        rows = capture_day_rows(serial=serial)
        logger.info("M2.2 — captured %d rows", len(rows))
        for i, row in enumerate(rows):
            preview = " | ".join(n.text or n.content_desc for n in row if n.text or n.content_desc)
            logger.info("  row %3d: %s", i, preview)

        out_dir = Path("exports")
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / f"timeline_{_M2_TEST_DATE.isoformat()}.draft.json"
        draft = {
            "date": _M2_TEST_DATE.isoformat(),
            "rows": [
                {"row_index": i, "nodes": [asdict(n) for n in row]}
                for i, row in enumerate(rows)
            ],
        }
        out_path.write_text(json.dumps(draft, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("M2.2 — wrote draft JSON to %s", out_path)
    except ADBError as exc:
        logger.error("ADB error: %s", exc)
        return 1
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("M2.2 draft complete — %d rows written to %s", len(rows), out_path)
    return 0


# ---------------------------------------------------------------------------
# flatten
# ---------------------------------------------------------------------------

def cmd_flatten(args: argparse.Namespace) -> int:
    """Flatten a JSON scrape file to CSV (not yet implemented — target: M4)."""
    _setup_logging(args.verbose)
    logger.error("flatten is not yet implemented (target: M4)")
    return 1


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="python -m timeline_scraper",
        description="Scrape Google Maps Timeline from a Pixel phone via ADB.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # -- scrape ---------------------------------------------------------------
    p_scrape = sub.add_parser("scrape", help="Drive the phone and capture Timeline to JSON")
    p_scrape.add_argument("--start", metavar="YYYY-MM-DD", help="First day to scrape")
    p_scrape.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        help="Last day to scrape (default: yesterday)",
    )
    p_scrape.add_argument(
        "--out",
        metavar="PATH",
        help="Output directory (default: ~/timeline-exports/)",
    )
    p_scrape.add_argument(
        "--tz",
        metavar="TZ",
        default="America/Chicago",
        help="Timezone for date math (default: America/Chicago)",
    )
    p_scrape.set_defaults(func=cmd_scrape)

    # -- flatten --------------------------------------------------------------
    p_flatten = sub.add_parser("flatten", help="Flatten a JSON export to CSV")
    p_flatten.add_argument(
        "--in",
        dest="input",
        metavar="PATH",
        help="Input JSON file",
    )
    p_flatten.add_argument("--out", metavar="PATH", help="Output CSV file")
    p_flatten.set_defaults(func=cmd_flatten)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate command."""
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
