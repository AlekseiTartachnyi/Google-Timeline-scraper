"""Turn Timeline accessibility descriptions into visits and trips.

A trip row never carries an address of its own. The addresses live in the
visit rows above and below it, and the timestamps line up exactly:
a visit that ends at 1:21 PM is followed by a trip that starts at 1:21 PM.
That is how `from` and `to` are recovered.
"""

import logging
import re

from .model import Day, Trip, Visit

logger = logging.getLogger(__name__)

# Heads of movement rows. "Missing travel" is a movement Google failed to record
# but still reports a duration and a distance for.
_MOVEMENT_HEADS = (
    "Driving",
    "Walking",
    "Running",
    "Cycling",
    "Motorcycling",
    "Flying",
    "In transit",
    "By bus",
    "By train",
    "By subway",
    "By tram",
    "By ferry",
    "Missing travel",
)

# Rows that duplicate the row above them as action buttons.
_ACTION_HEADS = ("Yes", "No", "Edit", "Add travel", "Add visit", "Delete")

_TIME = r"\d{1,2}:\d{2}\s*[AP]M"
_RANGE_RE = re.compile(rf"({_TIME})\s*[–—-]\s*({_TIME})")
_SINGLE_RE = re.compile(rf"(Left|Arrived)\s+at\s+({_TIME})")
_DURATION_RE = re.compile(r"^(?:(\d+)\s*hr)?\s*(?:(\d+)\s*min)?$")
_DISTANCE_RE = re.compile(r"^([\d.,]+)\s*(mi|ft|km|m)$")


def _norm_time(value: str) -> str:
    """Normalize a clock string to a single-space form, e.g. '1:21 PM'."""
    return re.sub(r"\s+", " ", value).strip().upper()


def _parse_duration(part: str) -> int | None:
    """Return minutes from a duration fragment such as '27 min' or '1 hr 5 min'."""
    match = _DURATION_RE.match(part.strip())
    if not match or not any(match.groups()):
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours * 60 + minutes


def _parse_distance(part: str) -> float | None:
    """Return miles from a distance fragment such as '4.0 mi', '500 ft' or '3 km'."""
    match = _DISTANCE_RE.match(part.strip())
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = match.group(2)
    if unit == "mi":
        return value
    if unit == "ft":
        return round(value / 5280, 2)
    if unit == "km":
        return round(value * 0.621371, 2)
    return round(value * 0.000621371, 2)


def _parse_movement(desc: str, head: str, parts: list[str]) -> Trip:
    """Build a Trip from a movement row description."""
    times = _RANGE_RE.search(desc)
    duration = next((d for d in (_parse_duration(p) for p in parts[1:]) if d), None)
    distance = next((d for d in (_parse_distance(p) for p in parts[1:]) if d is not None), None)
    return Trip(
        mode=head,
        start_time=_norm_time(times.group(1)) if times else None,
        end_time=_norm_time(times.group(2)) if times else None,
        duration_min=duration,
        distance_mi=distance,
        raw_text=desc,
    )


def _parse_visit(desc: str, head: str) -> Visit:
    """Build a Visit from a place row description."""
    place: str | None = head
    unconfirmed = False
    if place.startswith("Visited ") and place.endswith("?"):
        place = place[len("Visited "):-1]
        unconfirmed = True

    missing = place.startswith("Missing visit")
    if missing:
        place = None

    start: str | None = None
    end: str | None = None
    address: str | None = None

    times = _RANGE_RE.search(desc)
    if times:
        start = _norm_time(times.group(1))
        end = _norm_time(times.group(2))
        address = desc[times.end():].strip(" ,") or None
    else:
        single = _SINGLE_RE.search(desc)
        if single:
            if single.group(1) == "Left":
                end = _norm_time(single.group(2))
            else:
                start = _norm_time(single.group(2))
            address = desc[single.end():].strip(" ,") or None

    return Visit(
        place=place,
        address=address,
        start_time=start,
        end_time=end,
        unconfirmed=unconfirmed,
        missing=missing,
        raw_text=desc,
    )


def parse_segments(descriptions: list[str]) -> list[Visit | Trip]:
    """Parse ordered accessibility descriptions into visits and trips.

    Action rows ("Yes", "Edit", "Add travel") repeat the row above them and are
    dropped. Rows that carry no recognisable time at all are dropped as chrome.
    """
    segments: list[Visit | Trip] = []
    for desc in descriptions:
        parts = [p.strip() for p in desc.split(",")]
        head = parts[0]
        if head in _ACTION_HEADS:
            continue
        if head.startswith(_MOVEMENT_HEADS):
            segments.append(_parse_movement(desc, head, parts))
            continue
        if _RANGE_RE.search(desc) or _SINGLE_RE.search(desc):
            segments.append(_parse_visit(desc, head))
    return segments


def link_endpoints(segments: list[Visit | Trip]) -> None:
    """Fill each trip's from/to from the neighbouring visits, in place.

    A neighbour is only accepted when the clock strings match exactly: the
    visit before must end when the trip starts, the visit after must start when
    the trip ends. Anything else leaves the endpoint empty rather than guessed.
    """
    for i, segment in enumerate(segments):
        if not isinstance(segment, Trip):
            continue

        before = next(
            (s for s in reversed(segments[:i]) if isinstance(s, Visit)),
            None,
        )
        if before is not None and before.end_time == segment.start_time:
            segment.from_place = before.place
            segment.from_address = before.address

        after = next(
            (s for s in segments[i + 1:] if isinstance(s, Visit)),
            None,
        )
        if after is not None and after.start_time == segment.end_time:
            segment.to_place = after.place
            segment.to_address = after.address


def build_day(date: str, descriptions: list[str]) -> Day:
    """Parse descriptions into a Day with trip endpoints already linked."""
    segments = parse_segments(descriptions)
    link_endpoints(segments)
    day = Day(date=date, segments=segments)
    logger.info(
        "Parsed %s: %d segments (%d trips)",
        date,
        len(day.segments),
        len(day.trips),
    )
    return day
