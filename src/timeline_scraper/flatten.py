"""Flatten a scraped run to the CSV that carries the mileage record.

One row per trip, in the order the phone showed it: the day, where the drive
started and when, where it ended and when, the miles Google reported, and last
the mode — so a `Missing travel` row is recognisable at a glance, sitting in the
day where it happened.

A field the scrape could not fill says so in words. This sheet ends up in a tax
record, so a cell that asks to be checked by hand is worth more than a plausible
guess, and nothing here invents a time or an address.
"""

import csv
import logging
from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from itertools import groupby
from pathlib import Path
from typing import TYPE_CHECKING

from .model import Run, Trip

if TYPE_CHECKING:  # the sheet is written with or without the network module
    from .routes import RouteLookup

logger = logging.getLogger(__name__)

# What the road network says about one trip: (miles allowing tolls, miles
# avoiding tolls). Either is None when the answer is not known.
RouteMiles = tuple[float | None, float | None]

# The columns of the mileage sheet, in order. `mode` sits last, past the miles:
# the columns before it are what a mileage claim is read off, and the mode is
# what to check when one of them looks wrong.
#
# The two route columns sit next to the miles Timeline reported, never instead
# of them (spec §9.5). `miles` is the length of the recorded GPS track, which
# inflates where the signal is poor; the route columns are what the road network
# says about the same two addresses, with tolls allowed and with tolls avoided.
# Three numbers that disagree are three numbers to look at — the sheet keeps all
# of them and corrects none.
TOLLS = "Tolls"
NO_TOLLS = "No tolls"

HEADER = (
    "date",
    "from_address",
    "departure_time",
    "to_address",
    "arrival_time",
    "miles",
    TOLLS,
    NO_TOLLS,
    "mode",
)

# Header spellings recognised when an already-written sheet is read back, so a
# file produced by an earlier version is filled in place rather than gaining a
# second pair of columns.
_TOLLS_HEADERS = {TOLLS.lower(), "route_mi_with_tolls", "with tolls", "with_tolls"}
_NO_TOLLS_HEADERS = {NO_TOLLS.lower(), "route_mi_no_tolls", "no_tolls", "without tolls"}
_FROM_HEADERS = {"from_address", "from address", "from"}
_TO_HEADERS = {"to_address", "to address", "to"}
_MODE_HEADERS = {"mode"}

# What a trip's routed distance looks like before anything has been looked up:
# tolls allowed, tolls avoided, both unknown.
NO_ROUTE: RouteMiles = (None, None)

# A drive, with miles to claim.
DRIVING = "Driving"
# Travel Google recorded but could not describe. It reaches the sheet too: it is
# a hole in the record, and a hole that is visible in the day it belongs to is
# what catches a drive Maps failed to log properly.
MISSING_TRAVEL = "Missing travel"
# The modes the scrape keeps; anything else was dropped before the JSON.
SHEET_MODES = (DRIVING, MISSING_TRAVEL)

# What the report calls an endpoint Google recorded but could not name.
_MISSING_VISIT = "Missing visit"
# What a cell says when the scrape could not fill it — a time or an address that
# never came off the screen. Written in words rather than left blank so that a
# row needing hand work cannot be read as a row that is simply short.
MISSING_INFO = "missing information"


def endpoint(place: str | None, address: str | None, missing: bool) -> str:
    """Return one end of a trip as the sheet reads it.

    Place and address are both written when both are known — "Home" alone does
    not identify a location on a tax form, and a bare street number does not say
    what was there. `Missing visit` is Google saying it recorded a stop it could
    not name, which is information; neither known is not, and says so.
    """
    if missing:
        return _MISSING_VISIT
    return ", ".join(part for part in (place, address) if part) or MISSING_INFO


def row(day_date: str, trip: Trip, route: RouteMiles = NO_ROUTE) -> list[str]:
    """Return one trip as its row of the sheet.

    A miles cell stays empty when the number is not known, rather than carrying
    the words: a spreadsheet has to be able to add those columns up, and the
    mode beside them already says why a number is not there. That holds for the
    two route columns as well — empty means nothing was looked up, or the
    lookup had no address to work from.
    """
    with_tolls, no_tolls = route
    return [
        day_date,
        endpoint(trip.from_place, trip.from_address, trip.from_missing),
        trip.start_time or MISSING_INFO,
        endpoint(trip.to_place, trip.to_address, trip.to_missing),
        trip.end_time or MISSING_INFO,
        "" if trip.distance_mi is None else f"{trip.distance_mi}",
        "" if with_tolls is None else f"{with_tolls}",
        "" if no_tolls is None else f"{no_tolls}",
        trip.mode,
    ]


# ---------------------------------------------------------------------------
# The trip that crosses midnight
# ---------------------------------------------------------------------------

def _next_day(earlier: str, later: str) -> bool:
    """Return True if `later` is the day after `earlier`."""
    try:
        gap = date_type.fromisoformat(later) - date_type.fromisoformat(earlier)
    except ValueError:
        return False
    return gap == timedelta(days=1)


def _same_drive(first: Trip, second: Trip) -> bool:
    """Return True if these two rows are one drive shown on two days.

    Seen on 2026-Aug-15/16: a drive that left late on the Saturday and arrived at
    00:17 on the Sunday was listed on both days, 31.0 mi on each, with no clock
    strings and therefore no endpoints on either copy. Adding both to the sheet
    claims the miles twice.

    The signature is narrow on purpose — same mode, same reported distance, and
    neither copy carrying a single time. Two genuine drives on consecutive days
    both missing every time and matching to the tenth of a mile is not something
    this data has shown.
    """
    if first.mode != second.mode:
        return False
    if first.distance_mi is None or first.distance_mi != second.distance_mi:
        return False
    return not any(
        (first.start_time, first.end_time, second.start_time, second.end_time)
    )


def collect(run: Run) -> tuple[list[tuple[str, Trip]], list[tuple[str, Trip]]]:
    """Return the run's trips as (date, trip) pairs: the ones kept, and the
    duplicate halves of a midnight crossing that were dropped.

    The drive is kept on the day it started, which is the day it was driven on.
    """
    kept: list[tuple[str, Trip]] = []
    dropped: list[tuple[str, Trip]] = []
    previous_date: str | None = None
    previous_trips: list[Trip] = []

    for day in sorted(run.days, key=lambda d: d.date):
        trips = [t for t in day.trips if t.mode in SHEET_MODES]
        carried_over = previous_date is not None and _next_day(previous_date, day.date)
        for trip in trips:
            if carried_over and any(_same_drive(earlier, trip) for earlier in previous_trips):
                dropped.append((day.date, trip))
                continue
            kept.append((day.date, trip))
        previous_date = day.date
        previous_trips = trips

    return kept, dropped


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def total_miles(trips: list[tuple[str, Trip]]) -> float:
    """Return the miles the sheet claims, rounded the way the report rounds."""
    return round(sum(t.distance_mi for _, t in trips if t.distance_mi is not None), 1)


def write_run_csv(
    run: Run, path: Path, lookup: "RouteLookup | None" = None
) -> tuple[list[tuple[str, Trip]], list[tuple[str, Trip]]]:
    """Write the run as the mileage sheet. Returns the rows kept and dropped.

    Each day is followed by a blank line, so the days stay apart when the sheet
    is read down the screen. The file is written with a BOM: Excel opens a plain
    UTF-8 CSV in the laptop's own code page and mangles anything outside it.

    With no `lookup` the two route columns are written empty: the sheet keeps
    the same shape whether or not the road network was asked, so a spreadsheet
    built on top of it does not have to move its formulas between runs.

    The rows are looked up only after the midnight-crossing duplicates have been
    dropped, so a drive shown on two days is never paid for twice.
    """
    kept, dropped = collect(run)
    routed = [
        (day_date, trip, lookup.for_trip(trip) if lookup is not None else NO_ROUTE)
        for day_date, trip in kept
    ]
    if lookup is not None:
        lookup.save_cache()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        for _, day_rows in groupby(routed, key=lambda triple: triple[0]):
            writer.writerows(row(*triple) for triple in day_rows)
            writer.writerow([])
    return kept, dropped


# ---------------------------------------------------------------------------
# Filling the route columns of a sheet that already exists
# ---------------------------------------------------------------------------
#
# The sheet is not only this program's output, it is also the copy a person
# works on: rows get deleted, an address gets corrected, a place name gets
# trimmed off the front of a cell. Asking Google again after that editing is a
# second, separate job from building the sheet, so it is a command of its own
# and it reads addresses out of the file rather than out of the JSON.


@dataclass
class SheetLayout:
    """Where the columns this job cares about sit in a sheet that was read back."""

    header_row: int
    from_col: int
    to_col: int
    tolls_col: int
    no_tolls_col: int
    columns_added: bool


def _index_of(header: list[str], names: set[str]) -> int | None:
    """Return the column whose title is one of `names`, ignoring case and spacing."""
    for position, title in enumerate(header):
        if title.strip().lower() in names:
            return position
    return None


def read_layout(rows: list[list[str]]) -> SheetLayout | None:
    """Find the header row and the columns to work with, adding the two route
    columns to every row if the sheet does not carry them yet.

    The header is looked for rather than assumed to be the first line: a sheet
    that has been opened, annotated and saved again may well have a note above
    it. Without both address columns there is nothing to route between, and the
    caller is told so instead of a guess being made.
    """
    for number, row in enumerate(rows):
        from_col = _index_of(row, _FROM_HEADERS)
        to_col = _index_of(row, _TO_HEADERS)
        if from_col is None or to_col is None:
            continue

        tolls_col = _index_of(row, _TOLLS_HEADERS)
        no_tolls_col = _index_of(row, _NO_TOLLS_HEADERS)
        if tolls_col is not None and no_tolls_col is not None:
            return SheetLayout(number, from_col, to_col, tolls_col, no_tolls_col, False)

        # Not there yet: they go in front of `mode`, which stays last, or at the
        # end of the line when the sheet has no mode column at all.
        mode_col = _index_of(row, _MODE_HEADERS)
        at = len(row) if mode_col is None else mode_col
        for position, line in enumerate(rows):
            if not line:  # the blank line between days stays blank
                continue
            while len(line) < at:
                line.append("")
            titles = [TOLLS, NO_TOLLS] if position == number else ["", ""]
            line[at:at] = titles
        return SheetLayout(number, from_col, to_col, at, at + 1, True)

    return None


def fill_sheet_routes(
    path: Path, lookup: "RouteLookup", out_path: Path | None = None
) -> tuple[int, int]:
    """Fill the two route columns of an existing sheet. Returns (filled, skipped).

    Every routable row is asked about again, not only the empty ones: the reason
    to run this over an edited sheet is that the addresses changed, and a number
    left over from the address that used to be in that cell would be worse than
    no number at all. Repeats cost nothing — the cache answers them.

    The file is replaced only once the whole sheet has been built, so an
    interrupted run leaves the sheet it started with rather than half of one.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = [list(row) for row in csv.reader(handle)]

    layout = read_layout(rows)
    if layout is None:
        raise ValueError(
            f"{path} has no 'from_address' and 'to_address' columns, so there is "
            "nothing to route between"
        )
    if layout.columns_added:
        logger.info("Sheet had no route columns; adding '%s' and '%s'", TOLLS, NO_TOLLS)

    filled = skipped = 0
    for row in rows[layout.header_row + 1:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        while len(row) <= layout.no_tolls_col:
            row.append("")
        origin = row[layout.from_col] if layout.from_col < len(row) else ""
        destination = row[layout.to_col] if layout.to_col < len(row) else ""
        with_tolls, no_tolls = lookup.for_cells(origin, destination)
        row[layout.tolls_col] = "" if with_tolls is None else f"{with_tolls}"
        row[layout.no_tolls_col] = "" if no_tolls is None else f"{no_tolls}"
        if with_tolls is None and no_tolls is None:
            skipped += 1
        else:
            filled += 1

    target = out_path or path
    temporary = target.with_suffix(target.suffix + ".writing")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows(rows)
    temporary.replace(target)
    return filled, skipped
