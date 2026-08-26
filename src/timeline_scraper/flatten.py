"""Flatten a scraped run to the CSV that carries the mileage record.

One row per driving trip, in the order the phone showed it: the day, where the
drive started and when, where it ended and when, and the miles Google reported.

A field the scrape could not fill is written empty. This sheet ends up in a tax
record, so a blank cell that says "check this one by hand" is worth more than a
plausible guess, and nothing here invents a time or an address.
"""

import csv
import logging
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path

from .model import Run, Trip

logger = logging.getLogger(__name__)

# The columns of the mileage sheet, in order.
HEADER = (
    "date",
    "from_address",
    "departure_time",
    "to_address",
    "arrival_time",
    "miles",
)

# The mode that reaches the sheet: a drive with miles to claim.
DRIVING = "Driving"
# A gap Google flagged as travel it could not describe. Kept in the JSON and in
# the report, left out of the sheet unless it is asked for: it is a hole in the
# record, not a drive.
MISSING_TRAVEL = "Missing travel"

# What the report calls an endpoint Google recorded but could not name.
_MISSING_VISIT = "Missing visit"


def endpoint(place: str | None, address: str | None, missing: bool) -> str:
    """Return one end of a trip as the sheet reads it.

    Place and address are both written when both are known — "Home" alone does
    not identify a location on a tax form, and a bare street number does not say
    what was there. Neither known leaves the cell empty.
    """
    if missing:
        return _MISSING_VISIT
    return ", ".join(part for part in (place, address) if part)


def row(day_date: str, trip: Trip) -> list[str]:
    """Return one trip as its row of the sheet."""
    return [
        day_date,
        endpoint(trip.from_place, trip.from_address, trip.from_missing),
        trip.start_time or "",
        endpoint(trip.to_place, trip.to_address, trip.to_missing),
        trip.end_time or "",
        "" if trip.distance_mi is None else f"{trip.distance_mi}",
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


def collect(
    run: Run, include_missing: bool = False
) -> tuple[list[tuple[str, Trip]], list[tuple[str, Trip]]]:
    """Return the run's trips as (date, trip) pairs: the ones kept, and the
    duplicate halves of a midnight crossing that were dropped.

    The drive is kept on the day it started, which is the day it was driven on.
    """
    modes = (DRIVING, MISSING_TRAVEL) if include_missing else (DRIVING,)
    kept: list[tuple[str, Trip]] = []
    dropped: list[tuple[str, Trip]] = []
    previous_date: str | None = None
    previous_trips: list[Trip] = []

    for day in sorted(run.days, key=lambda d: d.date):
        trips = [t for t in day.trips if t.mode in modes]
        if not include_missing:
            for gap in day.trips:
                if gap.mode == MISSING_TRAVEL and gap.distance_mi is not None:
                    logger.warning(
                        "%s: a Missing travel row reports %s mi and is not in the "
                        "sheet; re-run with --include-missing to keep it",
                        day.date,
                        gap.distance_mi,
                    )
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
    run: Run, path: Path, include_missing: bool = False
) -> tuple[list[tuple[str, Trip]], list[tuple[str, Trip]]]:
    """Write the run as the mileage sheet. Returns the rows kept and dropped.

    The file is written with a BOM: Excel opens a plain UTF-8 CSV in the
    laptop's own code page and mangles anything outside it.
    """
    kept, dropped = collect(run, include_missing=include_missing)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(row(day_date, trip) for day_date, trip in kept)
    return kept, dropped
