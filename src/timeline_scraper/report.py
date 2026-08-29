"""Render a scraped run as the numbered list used to check it by eye.

The JSON is what the next milestone consumes; this is what a person reads to
decide whether Google's mileage for a trip is believable. So every line answers
one question and says plainly when the answer is missing — a trip whose
endpoint Google could not name must look different from a trip whose endpoint
simply did not line up, and a day the phone never gave up must look different
from a day without driving.
"""

from datetime import date as date_type

from .model import STATUS_FAILED, DayResult, Run, Trip
from .naming import header_date

# Google recorded a stop there but not where it was.
_MISSING = "Missing visit"
# No visit lined up with this end of the trip at all.
_NO_MATCH = "no matching visit"
_NO_TIME = "no time reported"
_NO_DISTANCE = "no distance reported"

# Days run together on screen, so they are cut apart by a rule.
_SEPARATOR = "=" * 60


def _header_date(iso_date: str) -> str:
    """Return '2026-08-20' as '2026, Aug, 20, Thu'."""
    try:
        parsed = date_type.fromisoformat(iso_date)
    except ValueError:
        return iso_date
    return header_date(parsed)


def _place(name: str | None, address: str | None, missing: bool) -> str:
    """Return the readable endpoint for one end of a trip."""
    if missing:
        return _MISSING
    parts = [p for p in (name, address) if p]
    return ", ".join(parts) if parts else _NO_MATCH


def _trip_lines(index: int, trip: Trip) -> list[str]:
    """Return the numbered block for one trip."""
    departed = trip.start_time or _NO_TIME
    arrived = trip.end_time or _NO_TIME
    origin = _place(trip.from_place, trip.from_address, trip.from_missing)
    destination = _place(trip.to_place, trip.to_address, trip.to_missing)
    distance = f"{trip.distance_mi} mi" if trip.distance_mi is not None else _NO_DISTANCE
    return [
        f"{index}. {trip.mode}",
        f"   1. Left {departed} - {origin}",
        f"   2. Arrived {arrived} - {destination}",
        f"   3. {distance}",
    ]


def render_day(day: DayResult) -> str:
    """Return one day of a run as the numbered report."""
    lines = [f"Date - {_header_date(day.date)}"]
    if not day.confirmed:
        lines.append("   ! the phone never showed this date — check these trips by hand")
    lines.append("")

    if day.status == STATUS_FAILED:
        lines.append(f"Day not captured: {day.error or 'reason not recorded'}")
        return "\n".join(lines) + "\n"

    if not day.trips:
        lines.append("No driving or missing travel recorded for this day.")
        return "\n".join(lines) + "\n"

    for index, trip in enumerate(day.trips, start=1):
        lines.extend(_trip_lines(index, trip))
        lines.append("")

    total = sum(t.distance_mi for t in day.trips if t.distance_mi is not None)
    unreported = sum(1 for t in day.trips if t.distance_mi is None)
    summary = f"{len(day.trips)} trip(s), {round(total, 1)} mi total"
    if unreported:
        summary += f" ({unreported} without a reported distance)"
    lines.append(summary)
    return "\n".join(lines) + "\n"


def _range_length(run: Run) -> int:
    """Return how many days the range covers, or 0 if its ends do not parse."""
    try:
        first = date_type.fromisoformat(run.first_date)
        last = date_type.fromisoformat(run.last_date)
    except ValueError:
        return 0
    return (last - first).days + 1


def render_summary(run: Run) -> str:
    """Return what the whole run came to, read off the days it collected.

    A month is too long to add up by eye, and the two numbers that decide
    whether it can be filed — how much of it was captured and how many miles it
    claims — are the ones nobody should have to scroll for. Days that failed
    and days the phone never named are listed by date: they are the hand work
    the run leaves behind.
    """
    days = run.days
    failed = [d.date for d in days if d.status == STATUS_FAILED]
    captured = [d for d in days if d.status != STATUS_FAILED]
    driven = [d for d in captured if d.trips]
    unconfirmed = [d.date for d in captured if not d.confirmed]
    trips = [t for d in captured for t in d.trips]
    miles = round(sum(t.distance_mi for t in trips if t.distance_mi is not None), 1)
    unreported = sum(1 for t in trips if t.distance_mi is None)

    counted = f"{len(days)} day(s)"
    asked_for = _range_length(run)
    if asked_for and asked_for != len(days):
        counted += f" of the {asked_for} in the range"
    lines = [
        f"Range - {_header_date(run.first_date)} to {_header_date(run.last_date)}",
        "",
        f"{counted}: {len(driven)} with driving, "
        f"{len(captured) - len(driven)} without, {len(failed)} not captured",
    ]
    total = f"{len(trips)} trip(s), {miles} mi total"
    if unreported:
        total += f" ({unreported} without a reported distance)"
    lines.append(total)
    if failed:
        lines.append(f"Not captured, re-run to retry: {', '.join(failed)}")
    if unconfirmed:
        lines.append(f"The phone never showed the date for: {', '.join(unconfirmed)}")
    return "\n".join(lines) + "\n"


def render_run(run: Run) -> str:
    """Return every day of the run, oldest first, cut apart by a rule.

    A run of more than one day ends with what the whole of it came to.
    """
    if not run.days:
        return "Nothing was captured for this range.\n"
    blocks = [render_day(day) for day in run.days]
    if len(run.days) > 1:
        blocks.append(render_summary(run))
    return f"\n{_SEPARATOR}\n\n".join(blocks)


def render_index(run: Run, parts: list[tuple[str, Run]]) -> str:
    """Return what a range split across month files came to, and where the months are.

    A year of days is too long to print, and pasting twelve reports into one
    file only makes a file nobody opens. What the range needs is the two
    numbers that decide whether it can be filed and a list saying which file
    holds which month — the day-by-day reading is in those files.
    """
    lines = [render_summary(run).rstrip("\n"), "", "Months:"]
    for name, part in parts:
        captured = [d for d in part.days if d.status != STATUS_FAILED]
        failed = len(part.days) - len(captured)
        trips = [t for d in captured for t in d.trips]
        miles = round(sum(t.distance_mi for t in trips if t.distance_mi is not None), 1)
        line = f"   {name} - {len(captured)} day(s), {len(trips)} trip(s), {miles} mi"
        if failed:
            line += f", {failed} not captured"
        lines.append(line)
    return "\n".join(lines) + "\n"
