"""CLI entrypoint — scrape and flatten commands."""

import argparse
import logging
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from .adb import ADBError, devices, is_locked, wake_screen
from .extract import collect_day
from .model import (
    STATUS_FAILED,
    DayResult,
    Run,
    day_result,
    read_run_json,
    write_run_json,
)
from .naming import draft_stem, range_stem
from .nav import go_to_date, launch_maps, reach_timeline
from .parse import build_day
from .report import render_run

logger = logging.getLogger(__name__)

# M3 test range (spec: dates are hardcoded through M1-M5); the seven days
# ending Thursday, Aug 20 2026.
_M3_TEST_END = date(2026, 8, 20)
_M3_DAYS = 7
_DEFAULT_OUT_DIR = Path("exports")
# Let the day's list finish drawing after the calendar closes.
_DAY_SETTLE_S = 1.5


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

def _parse_date(value: str, flag: str) -> date:
    """Return an ISO date from the command line, or say which flag was wrong."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"--{flag} must be a date as YYYY-MM-DD, got {value!r}") from None


def _resolve_range(args: argparse.Namespace) -> tuple[date, date]:
    """Return the first and last day to scrape, oldest first."""
    end = _parse_date(args.end, "end") if args.end else _M3_TEST_END
    if args.start:
        start = _parse_date(args.start, "start")
    else:
        start = end - timedelta(days=_M3_DAYS - 1)
    if start > end:
        raise ValueError(f"--start ({start.isoformat()}) is after --end ({end.isoformat()})")
    return start, end


def _days_in(start: date, end: date) -> list[date]:
    """Return every day of the range, oldest first."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def _device_present(serial: str) -> bool:
    """Return True if the phone is still attached."""
    try:
        return serial in devices()
    except ADBError:
        return False


def _pick_device() -> str | None:
    """Return the serial to drive, or None with the reason already logged."""
    try:
        found = devices()
    except ADBError as exc:
        logger.error("ADB error: %s", exc)
        return None

    if not found:
        logger.error(
            "No device detected. Connect your Pixel via USB, enable USB debugging, "
            "and authorize this computer on the phone."
        )
        return None

    serial = found[0]
    if len(found) > 1:
        logger.warning("Multiple devices found; using %s", serial)
    else:
        logger.info("Device: %s", serial)
    return serial


def _load_run(partial_path: Path, start: date, end: date, total: int) -> Run:
    """Return the run in progress for this range, or a fresh one.

    A partial file left by a different range is not this run's business and is
    ignored — it stays on disk, since the range that wrote it may still be
    resumed later.
    """
    run = read_run_json(partial_path)
    if run is None:
        return Run(first_date=start.isoformat(), last_date=end.isoformat())
    if (run.first_date, run.last_date) != (start.isoformat(), end.isoformat()):
        logger.warning(
            "Partial file %s covers %s - %s, not this range; starting fresh",
            partial_path,
            run.first_date,
            run.last_date,
        )
        return Run(first_date=start.isoformat(), last_date=end.isoformat())
    retry = [d.date for d in run.days if d.status == STATUS_FAILED]
    logger.info(
        "Resuming %s: %d of %d day(s) already collected",
        partial_path,
        len(run.collected_dates),
        total,
    )
    if retry:
        logger.info("Retrying the day(s) that failed last time: %s", ", ".join(retry))
    return run


def _scrape_day(target: date, serial: str, dump_dir: Path) -> DayResult:
    """Open one day on the phone and reduce it to the trips that get exported.

    Maps is relaunched for every day rather than driven from the day already
    on screen. The Timeline screen Maps opens with is the one measured to
    carry the "Today" control; what the screen reads once a day is showing is
    not known, and a run that guesses at it loses every day after the first.
    """
    launch_maps(serial=serial)
    reach_timeline(serial=serial)
    confirmed = go_to_date(target, serial=serial, dump_dir=dump_dir)
    time.sleep(_DAY_SETTLE_S)
    day = build_day(target.isoformat(), collect_day(serial=serial))
    return day_result(day, confirmed=confirmed)


def cmd_scrape(args: argparse.Namespace) -> int:
    """Capture a range of Timeline days: driving and missing travel, to JSON and a report."""
    _setup_logging(args.verbose)

    try:
        start, end = _resolve_range(args)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    days = _days_in(start, end)
    out_dir = Path(args.out).expanduser() if args.out else _DEFAULT_OUT_DIR
    # The partial is named for the range, never for the collection time: a
    # resumed run has to find the file the interrupted one left behind.
    partial_path = out_dir / f"{range_stem(start, end)}.partial.json"
    stem = draft_stem(start, datetime.now()) if start == end else range_stem(start, end)
    json_path = out_dir / f"{stem}.json"
    report_path = out_dir / f"{stem}.txt"

    logger.info(
        "Scraping %d day(s): %s to %s",
        len(days),
        start.isoformat(),
        end.isoformat(),
    )
    run = _load_run(partial_path, start, end, len(days))
    done = run.collected_dates
    pending = [d for d in days if d.isoformat() not in done]
    # A day that failed earlier is retried, so its old entry has to go.
    run.forget({d.isoformat() for d in pending})

    if pending:
        logger.info("ADB preflight check")
        serial = _pick_device()
        if serial is None:
            return 1

        try:
            wake_screen(serial=serial)
            if is_locked(serial=serial):
                input("  Phone is locked. Unlock it and press Enter to continue...")
        except ADBError as exc:
            logger.error("ADB error: %s", exc)
            return 1

        for position, target in enumerate(pending, start=1):
            logger.info(
                "Day %s (%d of %d to go)", target.isoformat(), position, len(pending)
            )
            try:
                result = _scrape_day(target, serial, out_dir)
            except (ADBError, RuntimeError) as exc:
                logger.error("Day %s not captured: %s", target.isoformat(), exc)
                result = DayResult(
                    date=target.isoformat(), status=STATUS_FAILED, error=str(exc)
                )
                run.days.append(result)
                run.sort_days()
                write_run_json(run, partial_path)
                if not _device_present(serial):
                    logger.error(
                        "Device %s is gone. Progress is kept in %s — re-run the same "
                        "command to continue from here.",
                        serial,
                        partial_path,
                    )
                    return 1
                continue

            run.days.append(result)
            run.sort_days()
            write_run_json(run, partial_path)
            logger.info(
                "Day %s: %d trip(s)%s; progress saved to %s",
                target.isoformat(),
                len(result.trips),
                "" if result.confirmed else " (date never confirmed on screen)",
                partial_path,
            )
    else:
        logger.info("Every day of this range was already collected; writing the export")

    run.sort_days()
    written = write_run_json(run, json_path)
    report = render_run(run)
    report_path.write_text(report, encoding="utf-8")
    partial_path.unlink(missing_ok=True)

    failed = [d.date for d in run.days if d.status == STATUS_FAILED]
    logger.info("Wrote %s (%d day(s), %d trip(s))", json_path, len(run.days), written)
    logger.info("Wrote %s", report_path)
    if failed:
        logger.warning("%d day(s) not captured: %s", len(failed), ", ".join(failed))
    unconfirmed = [d.date for d in run.days if d.status != STATUS_FAILED and not d.confirmed]
    if unconfirmed:
        logger.warning(
            "%d day(s) the phone never showed the date for: %s — check them by hand",
            len(unconfirmed),
            ", ".join(unconfirmed),
        )
    print()
    print(report)

    return 1 if len(failed) == len(run.days) else 0


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
    p_scrape = sub.add_parser(
        "scrape", help="Drive the phone and capture a range of Timeline days to JSON"
    )
    p_scrape.add_argument(
        "--start",
        metavar="YYYY-MM-DD",
        help="First day to scrape (default: six days before --end)",
    )
    p_scrape.add_argument(
        "--end",
        metavar="YYYY-MM-DD",
        help="Last day to scrape (default: the M3 test day, 2026-08-20)",
    )
    p_scrape.add_argument(
        "--out",
        metavar="PATH",
        help="Output directory (default: exports/)",
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
