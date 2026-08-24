"""Data model for a scraped Timeline day and its JSON serialization."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Visit:
    """A stop shown on the Timeline: a named place, or a gap Google could not name."""

    place: str | None
    address: str | None
    start_time: str | None
    end_time: str | None
    unconfirmed: bool = False
    missing: bool = False
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the visit as a JSON-serializable dict."""
        return {
            "type": "visit",
            "place": self.place,
            "address": self.address,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "unconfirmed": self.unconfirmed,
            "missing": self.missing,
            "raw_text": self.raw_text,
        }


@dataclass
class Trip:
    """A movement segment: driving, walking, or a gap Google flagged as missing travel."""

    mode: str
    start_time: str | None
    end_time: str | None
    duration_min: int | None = None
    distance_mi: float | None = None
    from_place: str | None = None
    from_address: str | None = None
    to_place: str | None = None
    to_address: str | None = None
    from_missing: bool = False
    to_missing: bool = False
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return the trip as a JSON-serializable dict."""
        return {
            "type": "trip",
            "mode": self.mode,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_min": self.duration_min,
            "distance_mi": self.distance_mi,
            "from_place": self.from_place,
            "from_address": self.from_address,
            "to_place": self.to_place,
            "to_address": self.to_address,
            "from_missing": self.from_missing,
            "to_missing": self.to_missing,
            "raw_text": self.raw_text,
        }


@dataclass
class Day:
    """One scraped Timeline day, in the order the segments appear on screen."""

    date: str
    segments: list[Visit | Trip] = field(default_factory=list)

    @property
    def trips(self) -> list[Trip]:
        """Return only the movement segments, in screen order."""
        return [s for s in self.segments if isinstance(s, Trip)]

    def trips_of(self, modes: tuple[str, ...]) -> list[Trip]:
        """Return the movement segments of the given modes, in screen order."""
        return [t for t in self.trips if t.mode in modes]

    def to_dict(self) -> dict[str, Any]:
        """Return the day as a JSON-serializable dict."""
        return {"date": self.date, "segments": [s.to_dict() for s in self.segments]}


# The only movement modes that carry mileage worth labelling. Walking and the
# transit modes are dropped: they are not driven, so they never reach the
# mileage record.
REPORTED_MODES = ("Driving", "Missing travel")


def write_trips_json(day: Day, path: Path, modes: tuple[str, ...] = REPORTED_MODES) -> int:
    """Write the day's reportable trips as JSON. Returns how many were written.

    Endpoints are already resolved against every visit of the day, including
    the ones sitting between a walk and a drive, so filtering here cannot cost
    an address.
    """
    trips = day.trips_of(modes)
    payload = {
        "date": day.date,
        "trips": [
            {"index": i, **trip.to_dict()} for i, trip in enumerate(trips, start=1)
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return len(trips)
