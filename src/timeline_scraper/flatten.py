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
from datetime import date as date_type
from datetime import timedelta
from itertools import groupby
from pathlib import Path

from .model import Run, Trip

logger = logging.getLogger(__name__)

# The columns of the mileage sheet, in order. `mode` sits last, past the miles:
# the four columns before it are what a mileage claim is read off, and the mode
# is what to check when one of them looks wrong.
HEADER = (
    "date",
    "from_address",
    "departure_time",
    "to_address",
    "arrival_time",
    "miles",
    "mode",
)

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


def row(day_date: str, trip: Trip) -> list[str]:
    """Return one trip as its row of the sheet.

    The miles cell stays empty when no distance was reported, rather than
    carrying the words: a spreadsheet has to be able to add that column up, and
    the mode beside it already says why the number is not there.
    """
    return [
        day_date,
        endpoint(trip.from_place, trip.from_address, trip.from_missing),
        trip.start_time or MISSING_INFO,
        endpoint(trip.to_place, trip.to_address, trip.to_missing),
        trip.end_time or MISSING_INFO,
        "" if trip.distance_mi is None else f"{trip.distance_mi}",
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
    run: Run, path: Path
) -> tuple[list[tuple[str, Trip]], list[tuple[str, Trip]]]:
    """Write the run as the mileage sheet. Returns the rows kept and dropped.

    Each day is followed by a blank line, so the days stay apart when the sheet
    is read down the screen. The file is written with a BOM: Excel opens a plain
    UTF-8 CSV in the laptop's own code page and mangles anything outside it.
    """
    kept, dropped = collect(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        for _, day_rows in groupby(kept, key=lambda pair: pair[0]):
            writer.writerows(row(day_date, trip) for day_date, trip in day_rows)
            writer.writerow([])
    return kept, dropped
