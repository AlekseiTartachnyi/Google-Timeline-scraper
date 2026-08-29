"""CLI entrypoint — the scrape, flatten and routes commands."""

import argparse
import logging
import sys
import time
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from glob import glob
from pathlib import Path

from .adb import ADBError, devices, is_locked, wake_screen
from .extract import collect_day
from .flatten import MISSING_INFO, fill_sheet_routes, row, total_miles, write_run_csv
from .model import (
    STATUS_FAILED,
    DayResult,
    Run,
    day_result,
    merge_runs,
    read_run_json,
    write_run_json,
)
from .naming import draft_stem, month_chunks, run_stem
from .nav import go_to_date, launch_maps, reach_timeline
from .parse import build_day
from .routes import CACHE_NAME, KEY_ENV, RouteLookup, open_lookup
from .report import render_index, render_run

logger = logging.getLogger(__name__)

# M3 test range (spec: dates are hardcoded through M1-M5); the seven days
# ending Thursday, Aug 20 2026.
_M3_TEST_END = date(2026, 8, 20)
_M3_DAYS = 7
_DEFAULT_OUT_DIR = Path("exports")
# Let the day's list finish drawing after the calendar closes.
_DAY_SETTLE_S = 1.5
# How many days may fail back to back before Maps is restarted. One failure is
# a day the phone was slow on; two in a row is a screen the run is lost on, and
# a month has too many days left to spend them all failing the same way.
_FAILURES_BEFORE_RESTART = 2


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


def _parse_month(value: str) -> tuple[date, date]:
    """Return the first and last day of a month written as YYYY-MM.

    The last day comes from the calendar, not from a table of 30s and 31s:
    February decides its own length and a month export must not stop a day
    short of one.
    """
    try:
        first = datetime.strptime(value, "%Y-%m").date()
    except ValueError:
        raise ValueError(f"--month must be a month as YYYY-MM, got {value!r}") from None
    return first, first.replace(day=monthrange(first.year, first.month)[1])


def _resolve_range(args: argparse.Namespace) -> tuple[date, date]:
    """Return the first and last day to scrape, oldest first."""
    if args.month:
        if args.start or args.end:
            raise ValueError(
                "--month already names both ends of the range; drop --start and --end"
            )
        return _parse_month(args.month)

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


def _listed(dates: list[str], most: int = 12) -> str:
    """Return dates as one line, cut short when there are too many to read.

    A day or two is what a run leaves behind; a hundred is what a run that went
    wrong leaves behind, and printing all of them buries the line that says so.
    """
    if len(dates) <= most:
        return ", ".join(dates)
    return f"{', '.join(dates[:most])} and {len(dates) - most} more"


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


@dataclass
class Chunk:
    """One calendar month of a range: the days it covers and the files it lives in.

    A range is scraped day by day from end to end, but stored a month at a
    time. The chunk is what says which file the day just read off the screen
    belongs in, and it carries that month's run so an interrupted year keeps
    every month it already finished.
    """

    first: date
    last: date
    json_path: Path
    report_path: Path
    partial_path: Path
    run: Run = field(default_factory=lambda: Run(first_date="", last_date=""))

    @property
    def days(self) -> list[date]:
        """Return every day this month of the range covers, oldest first."""
        return _days_in(self.first, self.last)


def _stored_run(path: Path, first: date, last: date) -> Run | None:
    """Return the run stored at `path`, if what is in it covers this range.

    A file left by a different range is not this run's business and is left
    alone: the range that wrote it may still be resumed later.
    """
    run = read_run_json(path)
    if run is None:
        return None
    if (run.first_date, run.last_date) != (first.isoformat(), last.isoformat()):
        logger.warning(
            "%s covers %s - %s, not %s - %s; ignoring it",
            path,
            run.first_date,
            run.last_date,
            first.isoformat(),
            last.isoformat(),
        )
        return None
    return run


def _load_chunk_run(chunk: Chunk, reuse_finished: bool) -> Run:
    """Return the month's run in progress, the month already exported, or a fresh one.

    A partial file comes first: it is the run that was interrupted. A finished
    export counts as collected only when the command covers more than one month
    — a year re-run after a crash must not walk January again — while a single
    month asked for on its own is collected again, because that is what asking
    for it means. `--refresh` says the same thing about every month of a range.
    """
    total = len(chunk.days)
    run = _stored_run(chunk.partial_path, chunk.first, chunk.last)
    if run is not None:
        logger.info(
            "Resuming %s: %d of %d day(s) already collected",
            chunk.partial_path,
            len(run.collected_dates),
            total,
        )
        retry = [d.date for d in run.days if d.status == STATUS_FAILED]
        if retry:
            logger.info("Retrying the day(s) that failed last time: %s", ", ".join(retry))
        return run

    if reuse_finished:
        run = _stored_run(chunk.json_path, chunk.first, chunk.last)
        if run is not None:
            logger.info(
                "%s is already exported: %d of %d day(s) kept as they are "
                "(delete the file or pass --refresh to collect them again)",
                chunk.json_path,
                len(run.collected_dates),
                total,
            )
            return run

    return Run(first_date=chunk.first.isoformat(), last_date=chunk.last.isoformat())


def _plan_chunks(
    start: date, end: date, out_dir: Path, collected_at: datetime, refresh: bool
) -> list[Chunk]:
    """Return the range split into months, each carrying whatever is already on disk.

    The file names are the ones the range would have had if each month had been
    asked for on its own — a whole month is `timeline_2026-Jul`, a month cut
    short by the ends of the range spells its days out — so a month scraped
    inside a year and the same month scraped alone are the same file.
    """
    pieces = month_chunks(start, end)
    one_day = start == end
    chunks = []
    for first, last in pieces:
        # A single day keeps the collection time in its name: Google revises a
        # day for a while afterwards, so a second reading of it must not
        # overwrite the first.
        stem = draft_stem(first, collected_at) if one_day else run_stem(first, last)
        chunk = Chunk(
            first=first,
            last=last,
            json_path=out_dir / f"{stem}.json",
            report_path=out_dir / f"{stem}.txt",
            # The partial is named for the days, never for the collection time:
            # a resumed run has to find the file the interrupted one left.
            partial_path=out_dir / f"{run_stem(first, last)}.partial.json",
        )
        chunk.run = _load_chunk_run(chunk, reuse_finished=len(pieces) > 1 and not refresh)
        chunks.append(chunk)
    return chunks


def _pending_days(chunks: list[Chunk]) -> list[tuple[date, Chunk]]:
    """Return the days still to scrape, oldest first, each with the month it belongs to.

    A day that failed earlier is retried, so its old entry is dropped from the
    month first — otherwise the retry would be recorded beside the failure.
    """
    pending: list[tuple[date, Chunk]] = []
    for chunk in chunks:
        done = chunk.run.collected_dates
        todo = [d for d in chunk.days if d.isoformat() not in done]
        chunk.run.forget({d.isoformat() for d in todo})
        pending.extend((day, chunk) for day in todo)
    return pending


def _scrape_day(target: date, serial: str, dump_dir: Path) -> DayResult:
    """Open one day on the phone and reduce it to the trips that get exported.

    Maps stays where it is between days: the day already on screen is the
    Timeline screen, and the calendar reopens from it.
    """
    confirmed = go_to_date(target, serial=serial, dump_dir=dump_dir)
    time.sleep(_DAY_SETTLE_S)
    day = build_day(target.isoformat(), collect_day(serial=serial))
    return day_result(day, confirmed=confirmed)


def _restart_maps(serial: str) -> bool:
    """Put Maps back on the Timeline screen after a run loses it.

    Returns False with the reason logged: the caller keeps going either way,
    since the days left may still open, and a day that cannot be reached is
    recorded as a failure rather than ending the run.
    """
    logger.warning("Restarting Google Maps to get back to a known screen")
    try:
        launch_maps(serial=serial)
        reach_timeline(serial=serial)
    except (ADBError, RuntimeError) as exc:
        logger.error("Could not get back to the Timeline screen: %s", exc)
        return False
    return True


def _is_complete(chunk: Chunk) -> bool:
    """Return True if every day of this month has been through the phone.

    A day that failed counts: it was attempted, its failure is recorded, and
    the export says so. A day that was never reached does not — the run stopped
    before it, and a month missing a day it never tried is not a month anyone
    should file.
    """
    return {d.isoformat() for d in chunk.days} <= {d.date for d in chunk.run.days}


def _write_chunk(chunk: Chunk) -> tuple[str, Run] | None:
    """Write one finished month's export and report; return its name and run.

    A month the run never got to the end of is not written as an export: a file
    named for the month reads as the settled month, and one silently missing
    the days the run never reached is the kind of hole a mileage record cannot
    carry. It stays a `.partial.json` instead, which is what the next run
    resumes from.
    """
    chunk.run.sort_days()
    if not _is_complete(chunk):
        if chunk.run.days:
            write_run_json(chunk.run, chunk.partial_path)
            logger.warning(
                "%s to %s is unfinished: %d of %d day(s) collected, kept in %s",
                chunk.first.isoformat(),
                chunk.last.isoformat(),
                len(chunk.run.days),
                len(chunk.days),
                chunk.partial_path,
            )
        else:
            logger.warning(
                "%s to %s was never reached; nothing written for it",
                chunk.first.isoformat(),
                chunk.last.isoformat(),
            )
        return None

    written = write_run_json(chunk.run, chunk.json_path)
    chunk.report_path.write_text(render_run(chunk.run), encoding="utf-8")
    chunk.partial_path.unlink(missing_ok=True)
    logger.info(
        "Wrote %s (%d day(s), %d trip(s)) and %s",
        chunk.json_path,
        len(chunk.run.days),
        written,
        chunk.report_path,
    )
    return chunk.json_path.name, chunk.run


def _walk_days(
    pending: list[tuple[date, Chunk]], serial: str, out_dir: Path
) -> bool:
    """Scrape every day still outstanding, saving after each one.

    Returns False when the phone went away mid-run: what was read off the
    screen is already on disk by then, so the caller stops rather than spending
    the rest of the range failing.
    """
    in_a_row = 0
    for position, (target, chunk) in enumerate(pending, start=1):
        logger.info("Day %s (%d of %d)", target.isoformat(), position, len(pending))
        try:
            result = _scrape_day(target, serial, out_dir)
        except (ADBError, RuntimeError) as exc:
            logger.error("Day %s not captured: %s", target.isoformat(), exc)
            result = DayResult(
                date=target.isoformat(), status=STATUS_FAILED, error=str(exc)
            )
            chunk.run.days.append(result)
            chunk.run.sort_days()
            write_run_json(chunk.run, chunk.partial_path)
            if not _device_present(serial):
                logger.error(
                    "Device %s is gone. Progress is kept in the .partial.json files "
                    "beside the exports — re-run the same command to continue from here.",
                    serial,
                )
                return False
            in_a_row += 1
            if in_a_row >= _FAILURES_BEFORE_RESTART and position < len(pending):
                _restart_maps(serial)
                in_a_row = 0
            continue

        in_a_row = 0
        chunk.run.days.append(result)
        chunk.run.sort_days()
        write_run_json(chunk.run, chunk.partial_path)
        logger.info(
            "Day %s: %d trip(s)%s; progress saved to %s",
            target.isoformat(),
            len(result.trips),
            "" if result.confirmed else " (date never confirmed on screen)",
            chunk.partial_path,
        )
    return True


def cmd_scrape(args: argparse.Namespace) -> int:
    """Capture a range of Timeline days: driving and missing travel, to JSON and a report.

    However long the range, the days come off the phone one at a time and are
    stored one month per JSON file. The mileage sheet is written once, from all
    of those months at once, so a range asked for in a single command comes out
    as a single sheet.
    """
    _setup_logging(args.verbose)

    try:
        start, end = _resolve_range(args)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1

    days = _days_in(start, end)
    out_dir = Path(args.out).expanduser() if args.out else _DEFAULT_OUT_DIR

    # The key is checked before the phone is touched. Finding out that the
    # Routes API has nothing to authenticate with is worth two seconds at the
    # start of a month-long run and worthless at the end of one.
    lookup = None
    if args.routes:
        lookup = _open_routes(out_dir)
        if lookup is None:
            return 1

    logger.info(
        "Scraping %d day(s): %s to %s, one JSON per calendar month",
        len(days),
        start.isoformat(),
        end.isoformat(),
    )
    chunks = _plan_chunks(start, end, out_dir, datetime.now(), args.refresh)
    pending = _pending_days(chunks)
    logger.info(
        "%d month file(s); %d day(s) still to collect", len(chunks), len(pending)
    )

    lost_device = False
    if pending:
        logger.info("ADB preflight check")
        serial = _pick_device()
        if serial is None:
            return 1

        try:
            wake_screen(serial=serial)
            if is_locked(serial=serial):
                input("  Phone is locked. Unlock it and press Enter to continue...")
            launch_maps(serial=serial)
            reach_timeline(serial=serial)
        except ADBError as exc:
            logger.error("ADB error: %s", exc)
            return 1
        except RuntimeError as exc:
            logger.error("%s", exc)
            return 1

        lost_device = not _walk_days(pending, serial, out_dir)
    else:
        logger.info("Every day of this range was already collected; writing the export")

    # Every month that made it to the end of its days becomes an export; the
    # one the run stopped inside keeps its partial file and is scraped again
    # next time.
    parts = [_write_chunk(chunk) for chunk in chunks]
    finished = [part for part in parts if part is not None]
    missing = sorted({d.isoformat() for d in days} - {
        day.date for chunk in chunks for day in chunk.run.days
    })

    if len(finished) != len(chunks):
        # The sheet is the thing the mileage is claimed off, so it is never
        # written from half a range: a sheet that stops in October reads
        # exactly like a year with no driving after October.
        logger.error(
            "The range stopped early: %d of %d month(s) finished, %d day(s) never "
            "reached. The sheet was not written — re-run the same command to "
            "carry on from here.",
            len(finished),
            len(chunks),
            len(missing),
        )
        if missing:
            logger.error("Never reached: %s", _listed(missing))
        return 1

    run = merge_runs([chunk.run for chunk in chunks])

    if len(chunks) == 1:
        csv_path = chunks[0].json_path.with_suffix(".csv")
        report = render_run(run)
    else:
        # The range gets a name of its own for the sheet and a short index
        # beside it; the day-by-day reading stays in the month files.
        stem = run_stem(start, end)
        csv_path = out_dir / f"{stem}.csv"
        index_path = out_dir / f"{stem}.txt"
        report = render_index(run, finished)
        index_path.write_text(report, encoding="utf-8")
        logger.info("Wrote %s", index_path)

    # The sheet is written from the same days that are already in memory: the
    # scrape is not finished until the thing the mileage is claimed off exists.
    _write_sheet(run, csv_path, lookup)

    failed = [d.date for d in run.days if d.status == STATUS_FAILED]
    if failed:
        logger.warning("%d day(s) not captured: %s", len(failed), _listed(failed))
    unconfirmed = [d.date for d in run.days if d.status != STATUS_FAILED and not d.confirmed]
    if unconfirmed:
        logger.warning(
            "%d day(s) the phone never showed the date for: %s — check them by hand",
            len(unconfirmed),
            _listed(unconfirmed),
        )
    print()
    print(report)

    if lost_device:
        return 1
    return 1 if len(failed) == len(run.days) else 0


# ---------------------------------------------------------------------------
# The mileage sheet — written by scrape, and again by flatten on demand
# ---------------------------------------------------------------------------

def _write_sheet(run: Run, csv_path: Path, lookup: RouteLookup | None) -> int:
    """Write the mileage sheet and say what in it still needs a person. Returns rows.

    Shared by both commands that produce a sheet, so a scrape and a later
    flatten of the same export write the same file and warn about the same
    rows.
    """
    kept, dropped = write_run_csv(run, csv_path, lookup)

    for day_date, trip in dropped:
        logger.warning(
            "%s: dropped a %s mi %s row that is the same drive as the one on the "
            "day before, shown twice because it crossed midnight",
            day_date,
            trip.distance_mi,
            trip.mode,
        )
    incomplete = sum(1 for day_date, trip in kept if MISSING_INFO in row(day_date, trip))
    if incomplete:
        logger.warning(
            "%d row(s) say '%s' in at least one cell and have to be completed by hand",
            incomplete,
            MISSING_INFO,
        )
    if lookup is not None:
        logger.info("Routes API: %s", lookup.summary())

    logger.info(
        "Wrote %s (%d row(s), %s mi total)", csv_path, len(kept), total_miles(kept)
    )
    return len(kept)


def _open_routes(out_dir: Path) -> RouteLookup | None:
    """Return the Routes API lookup, or None with the reason already logged.

    The cache lives beside the exports, never in the repo: it is keyed by the
    addresses that were driven between, and those are personal.
    """
    return open_lookup(out_dir / CACHE_NAME)


# ---------------------------------------------------------------------------
# flatten
# ---------------------------------------------------------------------------

def _finished_exports(out_dir: Path) -> list[Path]:
    """Return the finished exports in `out_dir`, oldest written first.

    A partial file is skipped: it belongs to a run that has not finished, and
    flattening it would produce a sheet with days missing from the middle.
    """
    finished = [
        path
        for path in out_dir.glob("timeline_*.json")
        if not path.name.endswith(".partial.json")
    ]
    return sorted(finished, key=lambda path: (path.stat().st_mtime, path.name))


def _newest_export(out_dir: Path) -> Path | None:
    """Return the most recently written finished export in `out_dir`."""
    finished = _finished_exports(out_dir)
    return finished[-1] if finished else None


def _expand_inputs(patterns: list[str]) -> list[Path]:
    """Return the export files named on the command line, oldest written first.

    A pattern is expanded here rather than left to the shell: on Windows the
    program is handed the star as typed, and a year stored a month at a time is
    not a list anybody should have to type out. A directory means every
    finished export in it.

    The order is the order they are merged in, and the last reading of a day
    wins, so the newest file is the one that decides a day two files both
    carry.
    """
    found: list[Path] = []
    for pattern in patterns:
        path = Path(pattern).expanduser()
        if path.is_dir():
            matches = _finished_exports(path)
            if not matches:
                raise ValueError(f"No finished export in {path}")
        elif any(ch in pattern for ch in "*?["):
            matches = sorted(
                (
                    found_path
                    for found_path in (Path(m) for m in glob(str(path)))
                    if not found_path.name.endswith(".partial.json")
                ),
                key=lambda found_path: (found_path.stat().st_mtime, found_path.name),
            )
            if not matches:
                raise ValueError(f"{pattern} matched no finished export")
        elif path.exists():
            matches = [path]
        else:
            raise ValueError(f"No such file: {path}")
        found.extend(matches)
    # The same file named twice — a folder and one of the files in it — is read
    # once, keeping the position it first appeared in.
    return list(dict.fromkeys(found))


def _sheet_path_for(run: Run, sources: list[Path]) -> Path:
    """Return where the sheet for these exports goes when --out did not say.

    One export keeps its own name. Several are one sheet spanning all of them,
    so it is named for the range they cover and written beside the first of
    them.
    """
    if len(sources) == 1:
        return sources[0].with_suffix(".csv")
    try:
        first = date.fromisoformat(run.first_date)
        last = date.fromisoformat(run.last_date)
    except ValueError:
        return sources[0].parent / "timeline_merged.csv"
    return sources[0].parent / f"{run_stem(first, last)}.csv"


def cmd_flatten(args: argparse.Namespace) -> int:
    """Flatten one or more scraped runs to a single CSV mileage sheet."""
    _setup_logging(args.verbose)

    if args.input:
        try:
            sources = _expand_inputs(args.input)
        except ValueError as exc:
            logger.error("%s", exc)
            return 1
    else:
        found = _newest_export(_DEFAULT_OUT_DIR)
        if found is None:
            logger.error(
                "Nothing to flatten: no finished export in %s/. Scrape a range "
                "first, or name the file with --in.",
                _DEFAULT_OUT_DIR,
            )
            return 1
        sources = [found]
        logger.info("Flattening the newest export: %s", found)

    runs = []
    for path in sources:
        run = read_run_json(path)
        if run is None:
            logger.error("%s is not a scrape file this version can read", path)
            return 1
        runs.append(run)
    if len(runs) > 1:
        logger.info(
            "Merging %d export(s) into one sheet: %s",
            len(runs),
            ", ".join(path.name for path in sources),
        )
    # Merged before anything is written, never pasted together afterwards: a
    # drive that crossed from the last night of one month into the next is one
    # drive, and the sheet has to see both days to recognise it as one.
    run = merge_runs(runs)

    csv_path = Path(args.out).expanduser() if args.out else _sheet_path_for(run, sources)

    lookup = None
    if args.routes:
        lookup = _open_routes(csv_path.parent)
        if lookup is None:
            return 1

    failed = [d.date for d in run.days if d.status == STATUS_FAILED]
    if failed:
        logger.warning(
            "%d day(s) were never captured and have no rows: %s",
            len(failed),
            ", ".join(failed),
        )
    unconfirmed = [d.date for d in run.days if d.status != STATUS_FAILED and not d.confirmed]
    if unconfirmed:
        logger.warning(
            "%d day(s) the phone never showed the date for: %s — check them by hand",
            len(unconfirmed),
            ", ".join(unconfirmed),
        )

    _write_sheet(run, csv_path, lookup)
    return 0



# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------

def _newest_sheet(out_dir: Path) -> Path | None:
    """Return the most recently written mileage sheet in `out_dir`."""
    sheets = list(out_dir.glob("timeline_*.csv"))
    if not sheets:
        return None
    return max(sheets, key=lambda path: path.stat().st_mtime)


def cmd_routes(args: argparse.Namespace) -> int:
    """Fill the two route columns of a sheet that already exists.

    The same lookups `flatten --routes` does, run over a written CSV instead of
    the JSON, so a sheet whose addresses have been corrected or thinned out by
    hand can be priced again without scraping or flattening anything.
    """
    _setup_logging(args.verbose)

    if args.input:
        csv_path = Path(args.input).expanduser()
        if not csv_path.exists():
            logger.error("No such file: %s", csv_path)
            return 1
    else:
        found = _newest_sheet(_DEFAULT_OUT_DIR)
        if found is None:
            logger.error(
                "No sheet found in %s/. Name the file with --in, or run flatten first.",
                _DEFAULT_OUT_DIR,
            )
            return 1
        csv_path = found
        logger.info("Using the newest sheet: %s", csv_path)

    out_path = Path(args.out).expanduser() if args.out else None
    lookup = open_lookup(csv_path.parent / CACHE_NAME)
    if lookup is None:
        return 1

    try:
        filled, skipped = fill_sheet_routes(csv_path, lookup, out_path)
    except ValueError as exc:
        logger.error("%s", exc)
        return 1
    except OSError as exc:
        logger.error("Could not write the sheet: %s", exc)
        return 1

    logger.info("Routes API: %s", lookup.summary())
    logger.info(
        "Wrote %s (%d row(s) with routed miles, %d without an address to route from)",
        out_path or csv_path,
        filled,
        skipped,
    )
    return 0


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
        "scrape",
        help=(
            "Drive the phone and capture a range of Timeline days: one JSON per "
            "calendar month, and one mileage sheet for the whole range"
        ),
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
        "--month",
        metavar="YYYY-MM",
        help="Scrape a whole calendar month, e.g. 2026-07 (instead of --start/--end)",
    )
    p_scrape.add_argument(
        "--out",
        metavar="PATH",
        help="Output directory (default: exports/)",
    )
    p_scrape.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "Collect every day of the range again, even the months already "
            "exported. Without it a range covering more than one month keeps the "
            "months whose export is already on disk, so an interrupted year "
            "resumes at the month it stopped in"
        ),
    )
    p_scrape.add_argument(
        "--routes",
        action="store_true",
        help=(
            "Also fill the sheet's two route columns from the Google Routes API: "
            "the miles the road network gives with tolls and without. The key is "
            f"read from api-keys.txt (or {KEY_ENV}) and checked before the phone "
            "is driven, so a missing one costs nothing"
        ),
    )
    p_scrape.add_argument(
        "--tz",
        metavar="TZ",
        default="America/Chicago",
        help="Timezone for date math (default: America/Chicago)",
    )
    p_scrape.set_defaults(func=cmd_scrape)

    # -- flatten --------------------------------------------------------------
    p_flatten = sub.add_parser(
        "flatten", help="Flatten one or more JSON exports into a single CSV"
    )
    p_flatten.add_argument(
        "--in",
        dest="input",
        metavar="PATH",
        nargs="+",
        help=(
            "The export(s) to flatten, merged into one sheet in the order given "
            "(default: the newest finished export in exports/). A name may be a "
            "pattern — \"exports/timeline_2026-*.json\" — or a folder, meaning "
            "every finished export in it"
        ),
    )
    p_flatten.add_argument(
        "--out",
        metavar="PATH",
        help=(
            "Output CSV file (default: the input file's name with .csv, or the "
            "range the merged exports cover when there is more than one)"
        ),
    )
    p_flatten.add_argument(
        "--routes",
        action="store_true",
        help=(
            "Fill the two route columns from the Google Routes API: the miles the "
            f"road network gives with tolls and without. Needs {KEY_ENV} set, and "
            "each new pair of addresses is a billed lookup — answers are cached in "
            f"exports/{CACHE_NAME} and never asked for twice"
        ),
    )
    p_flatten.set_defaults(func=cmd_flatten)

    # -- routes ---------------------------------------------------------------
    p_routes = sub.add_parser(
        "routes",
        help=(
            "Fill the Tolls / No tolls columns of a sheet that already exists, "
            "reading the addresses out of the CSV"
        ),
    )
    p_routes.add_argument(
        "--in",
        dest="input",
        metavar="PATH",
        help="The sheet to fill (default: the newest CSV in exports/)",
    )
    p_routes.add_argument(
        "--out",
        metavar="PATH",
        help="Write the result here instead of back into the same file",
    )
    p_routes.set_defaults(func=cmd_routes)

    return parser


def main() -> None:
    """Parse arguments and dispatch to the appropriate command."""
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))
