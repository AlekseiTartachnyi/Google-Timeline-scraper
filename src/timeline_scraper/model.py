"""Data model for a scraped Timeline day, a multi-day run, and their JSON."""

import json
import logging
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Trip":
        """Rebuild a trip from a dict written by `to_dict`.

        Keys the dataclass does not know ("type", "index") are dropped, so a
        partial file written by an older run still loads.
        """
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})


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


# A day either produced its trips, produced none, or was never captured.
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_FAILED = "failed"


@dataclass
class DayResult:
    """One day of a run: its reportable trips, or why it was not captured.

    A day that failed is kept in the run rather than dropped. A gap in a
    mileage record must be visible as a gap — silently missing days read as
    days without driving.
    """

    date: str
    status: str = STATUS_OK
    trips: list[Trip] = field(default_factory=list)
    error: str | None = None
    # Whether the phone showed the date that was asked for. A day the screen
    # never named is kept, but never quietly: these trips end up in a tax
    # record, and one filed under the wrong date is worse than a gap.
    confirmed: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return the day as a JSON-serializable dict, trips numbered from 1."""
        return {
            "date": self.date,
            "status": self.status,
            "error": self.error,
            "confirmed": self.confirmed,
            "trips": [
                {"index": i, **trip.to_dict()} for i, trip in enumerate(self.trips, start=1)
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DayResult":
        """Rebuild a day result from a dict written by `to_dict`."""
        return cls(
            date=payload["date"],
            status=payload.get("status", STATUS_OK),
            trips=[Trip.from_dict(t) for t in payload.get("trips", [])],
            error=payload.get("error"),
            confirmed=payload.get("confirmed", True),
        )


def day_result(
    day: Day,
    confirmed: bool = True,
    modes: tuple[str, ...] = REPORTED_MODES,
) -> DayResult:
    """Reduce a scraped day to the trips that reach the export.

    Endpoints are already resolved against every visit of the day, including
    the ones sitting between a walk and a drive, so filtering here cannot cost
    an address.
    """
    trips = day.trips_of(modes)
    return DayResult(
        date=day.date,
        status=STATUS_OK if trips else STATUS_EMPTY,
        trips=trips,
        confirmed=confirmed,
    )


@dataclass
class Run:
    """A range of days scraped in one go, in date order."""

    first_date: str
    last_date: str
    days: list[DayResult] = field(default_factory=list)

    @property
    def collected_dates(self) -> set[str]:
        """Return the dates that came off the phone; a failed day is not one.

        A day that failed is worth retrying on the next run — the phone may
        have been mid-animation, or the calendar may have opened on the wrong
        month — so it does not count as collected.
        """
        return {d.date for d in self.days if d.status != STATUS_FAILED}

    def forget(self, dates: set[str]) -> None:
        """Drop the days about to be scraped again, so they are not recorded twice."""
        self.days = [d for d in self.days if d.date not in dates]

    @property
    def trip_count(self) -> int:
        """Return how many trips the whole run carries."""
        return sum(len(d.trips) for d in self.days)

    def sort_days(self) -> None:
        """Put the days back in date order after a resume."""
        self.days.sort(key=lambda d: d.date)

    def to_dict(self) -> dict[str, Any]:
        """Return the run as a JSON-serializable dict."""
        return {
            "first_date": self.first_date,
            "last_date": self.last_date,
            "days": [d.to_dict() for d in self.days],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Run":
        """Rebuild a run from a dict written by `to_dict`."""
        return cls(
            first_date=payload["first_date"],
            last_date=payload["last_date"],
            days=[DayResult.from_dict(d) for d in payload.get("days", [])],
        )


def write_run_json(run: Run, path: Path) -> int:
    """Write the whole run as JSON. Returns how many trips were written.

    Called after every scraped day, not once at the end: the phone is driven
    for minutes per day and an interrupted run must not lose what it already
    read off the screen.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(run.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return run.trip_count


def read_run_json(path: Path) -> Run | None:
    """Return the run stored at `path`, or None if there is nothing usable.

    A partial file that cannot be read is not an error worth stopping for —
    the run simply starts over — but it is worth saying out loud, because the
    days in it are about to be scraped again.
    """
    if not path.exists():
        return None
    try:
        return Run.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Ignoring unreadable partial file %s: %s", path, exc)
        return None
