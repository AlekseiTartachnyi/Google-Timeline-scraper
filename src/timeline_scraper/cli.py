"""CLI entrypoint — scrape and flatten commands."""

import argparse
import logging
import sys
from datetime import date

from .adb import ADBError, devices, dump_ui, is_locked, wake_screen
from .extract import flatten, log_nodes
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
    """Preflight check + reach the Timeline screen (M1).

    Date range capture and JSON output are added in M2–M3.
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

        logger.info("M2.1 — screen after selecting the date:")
        log_nodes(flatten(dump_ui(serial=serial)))
    except ADBError as exc:
        logger.error("ADB error: %s", exc)
        return 1
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("M1 complete — Timeline screen reached")
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
