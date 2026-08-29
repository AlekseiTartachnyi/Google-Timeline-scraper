"""Names for the files a scrape writes.

Months and weekdays come from a table, not from `strftime('%b')`: the exported
names are English only, and the C library's month name follows whatever
regional setting the laptop happens to carry.
"""

from calendar import monthrange
from datetime import date as date_type
from datetime import datetime, timedelta

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
# date.weekday() is 0 for Monday.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

_PREFIX = "timeline_"


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


def range_stem(first: date_type, last: date_type) -> str:
    """Return the file stem for a finished range, e.g.
    'timeline_2026-Aug-20 - 2026-Aug-24'.

    No collection time here: a range file is the settled result, one per range,
    and a second run of the same range replaces it rather than piling up.
    """
    return f"{_PREFIX}{stamp_date(first)} - {stamp_date(last)}"


def month_stem(day: date_type) -> str:
    """Return the file stem for a whole calendar month, e.g. 'timeline_2026-Jul'.

    A month is named for the month and nothing else. The days it covers are the
    whole of it, so spelling both ends out only makes the name longer than the
    thing it names.
    """
    return f"{_PREFIX}{day.year}-{month(day)}"


def is_whole_month(first: date_type, last: date_type) -> bool:
    """Return True if the range is exactly one calendar month, end to end."""
    if (first.year, first.month) != (last.year, last.month):
        return False
    return first.day == 1 and last.day == monthrange(first.year, first.month)[1]


def run_stem(first: date_type, last: date_type) -> str:
    """Return the settled file stem for a scraped range, whatever its shape.

    The name is a function of the range alone, so the same days asked for twice
    — `--month 2026-07` and the two dates spelled out — resume the same partial
    file and replace the same export.
    """
    if is_whole_month(first, last):
        return month_stem(first)
    return range_stem(first, last)


def month_chunks(first: date_type, last: date_type) -> list[tuple[date_type, date_type]]:
    """Split a range into one piece per calendar month, oldest first.

    A year asked for in one command is still stored a month at a time: a month
    is the unit the mileage is filed in, it is small enough to open and check by
    eye, and a run that dies in June does not take the months before it down.
    The first and last pieces are as short as the range makes them — a range
    starting on the 6th begins with a 25-day September, not a whole one.
    """
    if first > last:
        return []
    chunks: list[tuple[date_type, date_type]] = []
    cursor = first
    while cursor <= last:
        month_end = cursor.replace(day=monthrange(cursor.year, cursor.month)[1])
        chunks.append((cursor, min(month_end, last)))
        cursor = month_end + timedelta(days=1)
    return chunks
