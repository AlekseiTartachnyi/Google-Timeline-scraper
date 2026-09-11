"""Names for the files a scrape writes.

Months and weekdays come from a table, not from `strftime('%b')`: the exported
names are English only, and the C library's month name follows whatever
regional setting the laptop happens to carry.
"""

from calendar import monthrange
from datetime import date as date_type
from datetime import datetime

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
# date.weekday() is 0 for Monday.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_PREFIX = "timeline_"
# Screenshots are a different kind of thing from an export and are kept apart
# by name: one folder of pictures, never mixed in with the files that carry
# numbers.
_SHOTS_PREFIX = "screens_"


def month(day: date_type) -> str:
    """Return the three-letter English month, e.g. 'Aug'."""
    return _MONTHS[day.month - 1]


def weekday(day: date_type) -> str:
    """Return the three-letter English weekday, e.g. 'Thu'."""
    return _WEEKDAYS[day.weekday()]


def stamp_date(day: date_type) -> str:
    """Return a date as '2026-Aug-20'."""
    return f"{day.year}-{month(day)}-{day.day:02d}"


def sheet_date(day: date_type) -> str:
    """Return a date as the mileage sheet writes it: '2026, Aug 28'.

    The year first and the month by name: the sheet is read by a person and
    filed by year, and 07/08 says nothing about which of the two is the month
    to a reader on the wrong side of the Atlantic. The day is padded so the
    column stays a column.
    """
    return f"{day.year}, {month(day)} {day.day:02d}"


def header_date(day: date_type) -> str:
    """Return a date as the report's header reads it: '2026, Aug, 20, Thu'."""
    return f"{day.year}, {month(day)}, {day.day:02d}, {weekday(day)}"


def draft_stem(day: date_type, collected_at: datetime) -> str:
    """Return the file stem for one scraped day, e.g.
    'timeline_2026-Aug-20_15-30'.

    The collection time is part of the name because a day is scraped more than
    once — Google keeps revising a day for a while after it happens — and an
    earlier draft must not be overwritten by a later one.
    """
    return f"{_PREFIX}{stamp_date(day)}_{collected_at:%H-%M}"


def is_whole_month(first: date_type, last: date_type) -> bool:
    """Return True if the range is exactly one calendar month, end to end."""
    if (first.year, first.month) != (last.year, last.month):
        return False
    return first.day == 1 and last.day == monthrange(first.year, first.month)[1]


def range_name(first: date_type, last: date_type) -> str:
    """Return the bare name of a range, with no prefix on it.

    A whole calendar month is named for the month; anything else spells both
    ends out. The shape is decided here once, so every kind of output built
    from a range — an export, a report, a folder of screenshots — calls the
    same days by the same name.
    """
    if is_whole_month(first, last):
        return f"{first.year}-{month(first)}"
    return f"{stamp_date(first)} - {stamp_date(last)}"


def run_stem(first: date_type, last: date_type) -> str:
    """Return the settled file stem for a scraped range, whatever its shape.

    The name is a function of the range alone, so the same days asked for twice
    — `--month 2026-07` and the two dates spelled out — resume the same partial
    file and replace the same export.
    """
    return f"{_PREFIX}{range_name(first, last)}"


def shots_dir_name(first: date_type, last: date_type) -> str:
    """Return the folder name holding a range of day screenshots, e.g.
    'screens_2026-Aug-30 - 2026-Sep-05'.

    The same range names the same folder every time, so a second run of the
    same days fills the folder the first one started rather than making a new
    one beside it.
    """
    return f"{_SHOTS_PREFIX}{range_name(first, last)}"


def shot_name(day: date_type, index: int, confirmed: bool = True) -> str:
    """Return one screenshot's file name, e.g. '2026-Aug-30_Sun_01.png'.

    The date chip scrolls away with the list, so only the first screenful of a
    day carries the date on it. The file name carries it for the rest — with
    the weekday, because a lost week of work is argued about in weekdays — and
    the number is padded so the screens of a day stay in screen order in a
    folder listing.

    A day the phone never confirmed the date of is named as such. A screenshot
    filed under the wrong date is worse than one that is missing, and this
    ends up in front of an insurer.
    """
    stem = f"{stamp_date(day)}_{weekday(day)}_{index:02d}"
    if not confirmed:
        stem += "_unconfirmed"
    return f"{stem}.png"
