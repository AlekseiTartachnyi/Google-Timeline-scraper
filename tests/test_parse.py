"""Parser tests against an anonymized day of Timeline rows."""

from timeline_scraper.extract import parse_bounds_center
from timeline_scraper.parse import build_day

# Anonymized: same shapes as a real dump, invented places and addresses.
ROWS = [
    "Sample Apartments, Left at 7:19 AM, 1 Example Dr, Sampleton, TX 70000",
    "Driving, 27 min, 12 mi, 7:19 AM – 7:47 AM",
    "Visited Sample School?, 7:47 AM – 7:48 AM, 2 Example Rd, Sampleton, TX 70001",
    "Yes, Sample School, 7:47 AM – 7:48 AM, 2 Example Rd, Sampleton, TX 70001",
    "Edit, Sample School, 7:47 AM – 7:48 AM, 2 Example Rd, Sampleton, TX 70001",
    "Missing travel, 35 min, 19 mi, 7:48 AM – 8:24 AM",
    "Add travel, 35 min, 19 mi",
    "Sample Store, 8:24 AM – 8:42 AM, 3 Example Blvd, Sampleton, TX 70002",
    "Driving, 1 hr 5 min, 41 mi, 8:42 AM – 9:47 AM",
    "Missing visit, 9:47 AM – 10:43 AM",
    "Add visit, 9:47 AM – 10:43 AM",
    "Driving, 28 min, 500 ft, 10:43 AM – 11:11 AM",
    "Sample Apartments, Arrived at 11:11 AM, 1 Example Dr, Sampleton, TX 70000",
]


def test_action_rows_are_dropped():
    day = build_day("2026-08-20", ROWS)
    assert [s.raw_text.split(",")[0] for s in day.segments] == [
        "Sample Apartments",
        "Driving",
        "Visited Sample School?",
        "Missing travel",
        "Sample Store",
        "Driving",
        "Missing visit",
        "Driving",
        "Sample Apartments",
    ]


def test_endpoints_come_from_neighbouring_visits():
    trips = build_day("2026-08-20", ROWS).trips
    assert trips[0].from_place == "Sample Apartments"
    assert trips[0].from_address == "1 Example Dr, Sampleton, TX 70000"
    assert trips[0].to_place == "Sample School"
    assert trips[0].to_address == "2 Example Rd, Sampleton, TX 70001"


def test_missing_travel_still_gets_endpoints():
    missing = build_day("2026-08-20", ROWS).trips[1]
    assert missing.mode == "Missing travel"
    assert missing.from_place == "Sample School"
    assert missing.to_place == "Sample Store"


def test_endpoint_left_empty_when_the_visit_has_no_place():
    trips = build_day("2026-08-20", ROWS).trips
    assert trips[2].to_place is None  # trip into the missing visit
    assert trips[3].from_place is None  # trip out of the missing visit
    assert trips[3].to_place == "Sample Apartments"


def test_distance_and_duration():
    trips = build_day("2026-08-20", ROWS).trips
    assert (trips[0].duration_min, trips[0].distance_mi) == (27, 12.0)
    assert trips[2].duration_min == 65
    assert trips[3].distance_mi == 0.09  # 500 ft


def test_unconfirmed_visit_keeps_its_place():
    school = build_day("2026-08-20", ROWS).segments[2]
    assert school.place == "Sample School"
    assert school.unconfirmed is True


def test_bounds_off_screen_rows_are_not_tappable():
    assert parse_bounds_center("[0,0][0,0]") is None
    assert parse_bounds_center("[149,1735][937,1905]") == (543, 1820)
