# Google Maps Timeline Scraper

![Status](https://img.shields.io/badge/status-in%20development-orange)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Drives a Pixel phone over **ADB** to read **Google Maps Timeline** day by day and export
**everything visible on screen** to JSON, then flatten it to a CSV table for mileage
labeling (business vs. personal).

> **Status: early development.** The interface and roadmap below are the target design;
> milestones are being implemented incrementally (see [Roadmap](#roadmap)).

---

## Why

Google's official Timeline export is raw and incomplete: it omits a lot of what you actually
see in the app — place guesses ("Is this where you were?"), suggested locations, and
**"Missing"** gaps where Google couldn't reconstruct a trip or stop. This tool reads the
Timeline UI directly, so **nothing visible is lost**: every text element is captured first,
and structured fields (time, distance, address) are parsed on top.

## How it works

Two deterministic commands — no autonomous agents:

| Command   | Direction   | What it does                                         |
|-----------|-------------|------------------------------------------------------|
| `scrape`  | phone → JSON | Drives the phone, walks the date range, captures every visible block losslessly |
| `flatten` | JSON → CSV   | Flattens the JSON into a labeling-ready table         |

Capture is **lossless first**: the accessibility tree (`uiautomator dump`) is the primary
source, with an **OCR fallback** (Tesseract) for any text the tree doesn't expose. Long days
are handled by scrolling to the end and de-duplicating.

## Requirements

- A computer with `adb` (Android platform-tools) on `PATH`
- A Pixel (or similar) phone with the Google Maps app, **English UI**
- USB cable; **USB debugging** enabled on the phone
- Python 3.11+
- Tesseract (optional — only used as an OCR fallback)

## Setup

1. Install Android platform-tools and confirm `adb` works:
   ```bash
   adb version
   ```
2. On the phone: enable **Developer Options → USB debugging**, connect by cable, and
   authorize the computer when prompted.
3. Confirm the device is visible:
   ```bash
   adb devices    # should list your device as "device"
   ```
4. Install Python dependencies:
   ```bash
   pip install -e .
   ```

## Usage

```bash
# Scrape a date range from the phone into JSON
python -m timeline_scraper scrape --start 2026-05-01 --end 2026-06-07 --out ~/timeline-exports/

# Flatten the JSON into a CSV table
python -m timeline_scraper flatten --in timeline.json --out timeline.csv

# Or, with no arguments: take the newest export and write the CSV beside it
python -m timeline_scraper flatten
```

If `--start`, `--end`, or `--out` are omitted, the script prompts for them. The end date
defaults to **yesterday** (the current day is excluded). Output is saved **outside the repo**
(default `~/timeline-exports/`) with a timestamped filename, and the run is **crash-safe**:
progress is flushed after each day and can be resumed if interrupted.

## Output

**JSON** keeps the full structure — each day holds an ordered list of trips/visits, and every
segment keeps its complete `raw_text` alongside best-effort fields:

```json
{
  "date": "2026-05-01",
  "segments": [
    {
      "type": "trip",
      "start_time": "08:12",
      "end_time": "08:34",
      "distance_mi": 7.4,
      "from": "Home",
      "to": "456 Sample Ave",
      "raw_text": ["8:12 AM - 8:34 AM", "Driving 7.4 mi"]
    }
  ]
}
```

**CSV** is the mileage sheet: one row per trip, nine columns, nothing to skip over, and a
blank line between days.

```
date, from_address, departure_time, to_address, arrival_time,
miles, route_mi_with_tolls, route_mi_no_tolls, mode
```

`mode` sits past the miles and reads `Driving`, or `Missing travel` where Maps recorded
travel it could not describe — those rows stay in, so a hole in the record is visible in the
day it belongs to. A field the scrape could not fill says `missing information` rather than
being guessed or left blank, and a drive that crossed midnight is written once, on the day it
started, so its distance is not claimed on both days.

`miles` is what Timeline showed: the length of the *recorded GPS track*, which wanders where
the signal is poor. The two `route_mi_*` columns are what the road network says about the
same two addresses — one allowing tolls, one avoiding them — and they are filled only when
`flatten --routes` is given a Google Maps Platform API key:

```
python -m timeline_scraper flatten --routes
```

The first run without a key creates `api-keys.txt` in the project folder and stops. Paste
the key after `routes_api_key =`, save, run again. The file is gitignored and never leaves
the machine; a `GOOGLE_MAPS_API_KEY` environment variable is read second if it is set.

Neither number is corrected into the other: a detour is legitimate, so a track longer than
the route is a row to look at, not an error to fix. Answers are cached per address pair in
`exports/route-cache.json`, so a repeated commute is a billed lookup once and a re-run of
`flatten` costs nothing.

## Project structure

```
timeline-scraper/
  src/timeline_scraper/
    cli.py        # entrypoint: scrape / flatten
    adb.py        # adb wrappers (shell, tap, swipe, dump, screencap)
    nav.py        # open Maps, reach Timeline, set/advance date
    extract.py    # UI dump -> ordered text blocks (scroll + dedupe)
    parse.py      # best-effort structured fields
    ocr.py        # screenshot -> Tesseract fallback
    model.py      # data model + JSON (de)serialization
    flatten.py    # JSON -> CSV
    routes.py     # routed miles from the Google Routes API
  tests/          # unit tests on parse/flatten against fixture dumps
  docs/           # spec
```

The parsing and flattening logic is unit-tested against fixture UI dumps, so it can be
developed and verified **without a phone attached**.

## Roadmap

- [ ] **M1** — Launch Maps and reach the Timeline screen
- [ ] **M2** — Capture one day losslessly to JSON (+ save location & conflict handling)
- [ ] **M3** — Scrape the previous 7 days with crash-safe incremental saving
- [ ] **M4** — Flatten 7 days to CSV
- [ ] **M5** — Export a full previous month to JSON and CSV
- [ ] **M6** — Polish: interactive prompts, logging, tests, docs

## Privacy & data handling

This tool reads **your own** Timeline from **your own** device. No location data is committed
to the repository — exports are written outside the repo and ignored via `.gitignore`, and
all test fixtures are anonymized.

## Limitations

- Depends on the Google Maps UI; a major app redesign may require updating the navigation.
- Assumes an **English** interface throughout.
- Some fields may rely on the OCR fallback when the accessibility tree doesn't expose them.

## License

MIT
