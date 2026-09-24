"""Photograph whole Timeline days — the screen itself, nothing parsed.

The mileage sheet is the argument; these are the picture of Google's own screen
it was read off. Nothing here taps into a row: the day is walked with the same
swipe `extract.collect_day` walks it with, and every screenful is written out
exactly as the phone drew it. The bytes are never edited — a screenshot that
has been drawn on is not evidence of anything.

A day does not fit on one screen, so a day is a numbered series of screens. The
tree is still read on every pass, but only to answer one question: did the page
move? When a pass shows nothing that was not already seen, the bottom of the
day is on screen and the day is done.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Any

from .adb import dump_ui, screencap
from .extract import flatten, list_band, list_rows, scroll_step, scroll_to_top
from .model import STATUS_EMPTY, STATUS_FAILED, STATUS_OK
from .naming import day_dir_name, header_date, shot_name

logger = logging.getLogger(__name__)

# The same ceiling `collect_day` scrolls under. A day that has not reached its
# bottom in forty screenfuls is a screen that is not behaving, not a long day.
_MAX_SCREENS = 40

# What the run writes beside the pictures: one for the next run to resume from,
# one for the person who opens the folder.
INDEX_JSON = "index.json"
INDEX_TXT = "index.txt"


@dataclass
class DayShots:
    """The screens of one day, or the reason there are none."""

    date: str
    status: str = STATUS_OK
    screens: list[str] = field(default_factory=list)
    error: str | None = None
    # Screens that share no row with the screen before them: the list moved
    # further than one swipe should move it, so something may be missing
    # between the two. Named here and in index.txt rather than left to be
    # noticed by whoever reads the folder.
    gaps: list[int] = field(default_factory=list)
    # Whether the phone showed the date that was asked for. A day the screen
    # never named keeps its pictures, but they are named as unconfirmed: a
    # screenshot filed under the wrong date is worse than a missing one.
    confirmed: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return the day as a JSON-serializable dict."""
        return {
            "date": self.date,
            "status": self.status,
            "error": self.error,
            "confirmed": self.confirmed,
            "screens": list(self.screens),
            "gaps": list(self.gaps),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DayShots":
        """Rebuild a day from a dict written by `to_dict`."""
        return cls(
            date=payload["date"],
            status=payload.get("status", STATUS_OK),
            screens=list(payload.get("screens", [])),
            error=payload.get("error"),
            gaps=list(payload.get("gaps", [])),
            confirmed=payload.get("confirmed", True),
        )


@dataclass
class ShotRun:
    """A range of days photographed in one go, in date order."""

    first_date: str
    last_date: str
    days: list[DayShots] = field(default_factory=list)

    @property
    def collected_dates(self) -> set[str]:
        """Return the dates that came off the phone; a failed day is not one."""
        return {d.date for d in self.days if d.status != STATUS_FAILED}

    def forget(self, dates: set[str]) -> None:
        """Drop the days about to be photographed again."""
        self.days = [d for d in self.days if d.date not in dates]

    def sort_days(self) -> None:
        """Put the days back in date order."""
        self.days.sort(key=lambda d: d.date)

    def to_dict(self) -> dict[str, Any]:
        """Return the run as a JSON-serializable dict."""
        return {
            "first_date": self.first_date,
            "last_date": self.last_date,
            "days": [d.to_dict() for d in self.days],
        }


def capture_day(
    target: date_type,
    out_dir: Path,
    serial: str | None = None,
    confirmed: bool = True,
    max_screens: int = _MAX_SCREENS,
) -> tuple[list[str], list[int]]:
    """Photograph one open day, top to bottom.

    Returns the file names written, and the numbers of any screens that may not
    meet the screen before them.

    The day must already be on screen — `nav.go_to_date` puts it there. The list
    is wound back to its first row first, because collecting or photographing a
    day leaves it at the bottom.

    Only the rows inside the scrolling strip count. The header, the tabs, the
    map and the day bar are on every screenful of every day, so a walk that
    counted them would never see a screen as new.

    The loop takes the picture before it reads the tree, so the screenshot and
    the rows it is judged by are one moment. A pass that adds no row it has not
    already seen is the bottom of the day: that screen is kept, and the walk
    stops there.
    """
    scroll_to_top(serial=serial)
    day_dir = out_dir / day_dir_name(target)
    day_dir.mkdir(parents=True, exist_ok=True)
    _, top, _ = list_band(serial=serial)

    names: list[str] = []
    gaps: list[int] = []
    seen: set[str] = set()
    previous_shot: bytes | None = None
    previous_rows: list[str] = []

    for index in range(1, max_screens + 1):
        shot = screencap(serial=serial)
        rows = list_rows(flatten(dump_ui(serial=serial)), top)
        fresh = [row for row in rows if row not in seen]
        seen.update(rows)

        if previous_shot is not None and shot == previous_shot and not fresh:
            logger.debug("Screen %d is the one before it; the day is already at its end", index)
            break

        # The swipe is meant to leave about two fifths of the screenful on
        # screen. If a screen has nothing at all in common with the one before
        # it, the list moved further than that and something fell between the
        # two — say so rather than handing over a folder with a hole in it.
        if previous_rows and rows and not set(rows) & set(previous_rows):
            logger.warning(
                "%s: screen %d has no row in common with screen %d — the list "
                "moved further than one swipe should move it, and a row may "
                "have been skipped between them",
                target.isoformat(),
                index,
                index - 1,
            )
            gaps.append(index)

        name = shot_name(target, index, confirmed)
        (day_dir / name).write_bytes(shot)
        names.append(name)
        previous_shot = shot
        previous_rows = rows
        logger.debug(
            "Screen %d of %s: %d row(s) in the list, %d of them new",
            index,
            target.isoformat(),
            len(rows),
            len(fresh),
        )

        if not fresh:
            break
        scroll_step(serial=serial)
    else:
        logger.warning(
            "%s was still showing new rows after %d screens; it may be cut short",
            target.isoformat(),
            max_screens,
        )

    logger.info("Day %s: %d screen(s), %d row(s) seen", target.isoformat(), len(names), len(seen))
    return names, gaps


def discard_day(target: date_type, out_dir: Path) -> int:
    """Delete the day's folder if an earlier try left one. Returns screens removed.

    A day that failed part-way leaves the screens it did reach. Those are the
    top of a day whose bottom is unknown, and a partial day that reads as a
    whole one is exactly the gap this tool exists to make visible, so they go
    before the day is tried again.
    """
    day_dir = out_dir / day_dir_name(target)
    if not day_dir.is_dir():
        return 0
    stale = sorted(day_dir.glob("*.png"))
    for path in stale:
        path.unlink(missing_ok=True)
    # Anything else in there was not put there by this run; the folder only
    # goes if emptying it emptied it.
    try:
        day_dir.rmdir()
    except OSError:
        logger.warning("%s still holds files this run did not write; left in place", day_dir)
    if stale:
        logger.info(
            "Cleared %d screen(s) left by an earlier try at %s", len(stale), target.isoformat()
        )
    return len(stale)


def read_index(path: Path) -> ShotRun | None:
    """Return the run recorded in an index file, or None if there is none to read."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        run = ShotRun(
            first_date=payload["first_date"],
            last_date=payload["last_date"],
            days=[DayShots.from_dict(d) for d in payload.get("days", [])],
        )
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("Could not read %s (%s); starting the range fresh", path, exc)
        return None
    return run


def write_index(run: ShotRun, path: Path) -> None:
    """Write the index the next run resumes from, after every day."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")


def render_index(run: ShotRun) -> str:
    """Return the folder's contents as a page a person can read.

    Whoever opens this folder is looking for one day. The list says what each
    day holds before they open a single picture, and says plainly which days
    hold nothing — an empty day is the finding, not a defect.
    """
    lines = [
        f"Timeline screens, {run.first_date} to {run.last_date}",
        "",
        "One folder per day, and inside it every screenful of that day in the",
        "order it appears on the phone.",
        "The day bar reading the date sits above the part that scrolls, so it",
        "is on every screen of a day, not only the first. The file name carries",
        "the date as well, so a screen that gets separated from the folder can",
        "still be placed.",
        "",
    ]
    for day in run.days:
        when = date_type.fromisoformat(day.date)
        head = header_date(when)
        if day.status == STATUS_FAILED:
            lines.append(f"{head}  —  not captured: {day.error}")
        elif day.status == STATUS_EMPTY:
            lines.append(f"{head}  —  nothing on the screen for this day")
        else:
            count = len(day.screens)
            note = "" if day.confirmed else "  (the phone never confirmed this date)"
            lines.append(f"{head}  —  {count} screen(s){note}")
            lines.append(f"    {day_dir_name(when)}/")
            for position, name in enumerate(day.screens, start=1):
                mark = "   <- may not meet the screen above" if position in day.gaps else ""
                lines.append(f"        {name}{mark}")
        lines.append("")

    captured = [d for d in run.days if d.status != STATUS_FAILED]
    total = sum(len(d.screens) for d in run.days)
    lines.append(f"{len(captured)} of {len(run.days)} day(s) captured, {total} screen(s) in all.")
    failed = [d.date for d in run.days if d.status == STATUS_FAILED]
    if failed:
        lines.append(f"Not captured: {', '.join(failed)}")
    unconfirmed = [d.date for d in run.days if d.status != STATUS_FAILED and not d.confirmed]
    if unconfirmed:
        lines.append(f"Date never confirmed on screen: {', '.join(unconfirmed)}")
    gapped = [d.date for d in run.days if d.gaps]
    if gapped:
        lines.append(f"Screens that may not meet, so a row could be missing: {', '.join(gapped)}")
    return "\n".join(lines) + "\n"
