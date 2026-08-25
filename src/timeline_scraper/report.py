"""Render a scraped day as the numbered list used to check it by eye.

The JSON is what the next milestone consumes; this is what a person reads to
decide whether Google's mileage for a trip is believable. So every line answers
one question and says plainly when the answer is missing — a trip whose
endpoint Google could not name must look different from a trip whose endpoint
simply did not line up.
"""

from datetime import date as date_type

from .model import REPORTED_MODES, Day, Trip
from .naming import header_date

# Google recorded a stop there but not where it was.
_MISSING = "Missing visit"
# No visit lined up with this end of the trip at all.
_NO_MATCH = "no matching visit"
_NO_TIME = "no time reported"
_NO_DISTANCE = "no distance reported"


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


def render_day(day: Day, modes: tuple[str, ...] = REPORTED_MODES) -> str:
    """Return the whole day as the numbered report."""
    trips = day.trips_of(modes)
    lines = [f"Date - {_header_date(day.date)}", ""]
    if not trips:
        lines.append("No driving or missing travel recorded for this day.")
        return "\n".join(lines) + "\n"

    for index, trip in enumerate(trips, start=1):
        lines.extend(_trip_lines(index, trip))
        lines.append("")

    total = sum(t.distance_mi for t in trips if t.distance_mi is not None)
    unreported = sum(1 for t in trips if t.distance_mi is None)
    summary = f"{len(trips)} trip(s), {round(total, 1)} mi total"
    if unreported:
        summary += f" ({unreported} without a reported distance)"
    lines.append(summary)
    return "\n".join(lines) + "\n"
