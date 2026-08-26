# Timeline Scraper — Spec v0.3

ADB-driven scraper that reads Google Maps Timeline from a Pixel (English UI) and exports
**everything visible on screen** to structured data for business-vs-personal mileage
labeling and taxes.

> Two deterministic commands in one repo (no autonomous agents):
> - `scrape`  — drives the phone, UI → JSON (lossless capture)
> - `flatten` — JSON → CSV (adds an empty `category` column for labeling)

---

## 1. Goal

For a chosen date range, walk Google Maps Timeline day by day and record **every text
element shown** — trips, visits, distances, times, addresses, Google's place guesses,
"Missing"/skipped markers, suggestions — losslessly to JSON. A second command flattens to CSV.

The built-in Google export is **not** sufficient: it omits on-screen info (place guesses,
"Missing" gaps, suggestions). That is exactly why we scrape the UI.

## 2. Model & environment

- **Driver:** Python on the **laptop**, controlling the Pixel via **ADB over USB cable**.
- **Cross-platform:** runs on the Mac Mini (home) and the Windows laptop (field).
- **Phone:** Pixel, English UI everywhere, Developer Options + USB debugging enabled.
- **Connection:** USB cable only.
- **Timezone:** `America/Chicago` (Austin) for date math. Configurable.

## 3. Repository & code standards (PUBLIC repo — portfolio quality)

This repo is public and serves as a portfolio piece. It must read well to a hiring manager.

- **English only.** No Russian anywhere — code, comments, docstrings, commit messages,
  README, issues.
- **No personal data committed.** Exports live outside the repo; `.gitignore` excludes
  `exports/`, `*.json`, `*.csv` data, screenshots, and UI dumps. Test fixtures are
  synthetic/anonymized.
- **Python style:** 3.11+, type hints everywhere, docstrings (Google style), `logging`
  (not `print`), `argparse` for the CLI, explicit error handling, no bare `except`.
- **Tested logic:** pure functions (`parse`, `flatten`) are unit-tested against fixture
  UI dumps, so parsing can be developed and verified without a phone attached.
- **Conventional, English commit messages.** Small, reviewable commits.

### Suggested layout

```
timeline-scraper/
  README.md                 # overview, setup, usage, limitations, license
  LICENSE
  pyproject.toml            # or requirements.txt
  .gitignore                # excludes exports/, *.json, *.csv, *.png, *.xml dumps
  src/timeline_scraper/
    __init__.py
    cli.py                  # entrypoint: `scrape` / `flatten`
    adb.py                  # devices/shell/tap/swipe/dump_ui/screencap wrappers
    nav.py                  # open Maps, reach Timeline, set/advance date
    extract.py              # XML -> ordered text blocks; scroll-to-end + dedupe
    parse.py                # best-effort structured fields + flag detection
    ocr.py                  # screenshot -> Tesseract fallback
    model.py                # dataclasses + JSON (de)serialization
    flatten.py              # JSON -> CSV
  tests/
    test_parse.py
    test_flatten.py
    fixtures/               # anonymized uiautomator XML dumps
  docs/
    timeline-scraper-spec.md
```

## 4. CLI

```
# scrape: phone -> JSON
python -m timeline_scraper scrape [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--out PATH] [--tz TZ]

# flatten: JSON -> CSV
python -m timeline_scraper flatten --in timeline.json [--out timeline.csv]
```

Interactive (final form, wired up at M6): if `--start` / `--end` / `--out` are omitted,
the script prompts for them.
- start date (required)
- end date — **default = yesterday** (today excluded). E.g. today 2026-06-08 → end 2026-06-07.
- output path — **default outside the repo**, e.g. `~/timeline-exports/`.

## 5. Output & persistence

- **Location:** prompted; default `~/timeline-exports/`. Never the repo root.
- **Filename:** `timeline_<start>_<end>_<YYYYMMDD-HHMM>.json` (timestamp avoids collisions).
- **Conflict (exact path exists):** prompt — overwrite / rename / cancel.
- **Incremental + crash-safe:** after each day, flush accumulated data to `*.partial.json`;
  on success, rename to the final filename.
- **Resume:** if a matching `*.partial.json` exists, offer to resume from the last
  completed day instead of restarting.

## 6. Extraction strategy — LOSSLESS FIRST

**Rule: never drop anything visible.** Record every text block in order; structure is
best-effort on top.

1. **Primary — accessibility tree.** `uiautomator dump` → pull → parse XML (`text`,
   `content-desc`, `bounds`). Keep all of it.
2. **Scroll loop.** Dump, swipe up, dump again, merge unique blocks; stop when consecutive
   dumps are identical.
3. **OCR fallback.** When the tree is incomplete (custom-drawn views), `adb exec-out
   screencap` → Tesseract. Optional dependency; invoked only to fill gaps.
4. **Flags (DEFERRED).** Normalize known English markers (place guesses, "Missing", skipped,
   low-confidence). Phrase list TBD — provided later. Until then, all such text is kept raw.

## 7. Data model

### JSON (scrape output)

```json
{
  "export_meta": {
    "device": "pixel",
    "scraped_at": "2026-06-08T14:03:00-05:00",
    "start_date": "2026-05-01",
    "end_date": "2026-06-07",
    "tz": "America/Chicago",
    "source": "maps_timeline_ui"
  },
  "days": [
    {
      "date": "2026-05-01",
      "raw_text": ["day-level banners/headers"],
      "segments": [
        {
          "type": "trip",
          "start_time": "08:12",
          "end_time": "08:34",
          "duration_min": 22,
          "mode": "driving",
          "distance_mi": 7.4,
          "from": "Home, 123 Example St",
          "to": "Job site, 456 Sample Ave",
          "place": null,
          "address": null,
          "note": null,
          "flags": [],
          "suggestions": [],
          "raw_text": ["8:12 AM – 8:34 AM", "Driving 7.4 mi", "Home -> 456 Sample Ave"]
        }
      ]
    }
  ]
}
```

`raw_text` is mandatory and complete; structured fields are derived and may be partial.

### CSV (flatten output)

```
date, segment_type, start_time, end_time, duration_min, mode, distance_mi,
from, to, place, address, note, flags, suggestions, raw_text, category
```

`category` is left blank for business/personal labeling (free text; README suggests
`business` / `personal`). `raw_text` is preserved so nothing is lost in the flatten step.

## 8. Development roadmap (M1 -> M6)

Dates are **hardcoded during M1–M5 for testing**; interactive prompts are wired up at M6.

### M1 — Launch & reach Timeline
- Preflight `adb devices`; launch Google Maps; navigate to Timeline (by element text).
- **Done when:** running the script reliably lands on the Timeline screen.

### M2 — One day -> JSON (+ save/conflict design)
- Open a fixed day (e.g. yesterday), capture ALL on-screen data, scroll-to-end, write JSON.
- Implement output location prompt, timestamped filename, and conflict handling
  (overwrite / rename / cancel).
- Introduce OCR fallback here if M2 shows the tree misses fields.
- **M2.2 — trip endpoints.** A trip row carries no address of its own; the endpoints live in
  the neighbouring visit rows and are recovered by matching timestamps exactly. Record where
  each endpoint came from instead of guessing when the chain breaks.
- **M2.2 — map screenshots.** Second pass over the day: open each motion segment, wait for the
  map to settle, save the screenshot next to the JSON. This is the manual-review channel for
  trips the accessibility tree cannot explain.
- **Done when:** one full day is captured losslessly to a JSON file in the chosen location.

### M3 — Previous 7 days (+ crash-safe incremental save)
- Loop over the last 7 days; advance one day at a time.
- Flush to `*.partial.json` after each day; resume support if a partial exists.
- **Done when:** 7 days scrape end-to-end and survive an interruption mid-run.

### M4 — 7 days -> CSV
- `flatten` command turns the 7-day JSON into the CSV schema above.
- Unit-tested against fixture dumps.
- **Done when:** a clean CSV with the `category` column is produced from the JSON.

### M5 — Previous month -> CSV
- Scrape a full previous month and flatten to CSV.
- Validate scroll/dedupe and date navigation at scale; tune throttling.
- **Done when:** a full month exports correctly to JSON and CSV.

### M6 — Polish
- Replace hardcoded test dates with interactive prompts (start, end=yesterday, output path).
- Logging, error messages, README, tests, `.gitignore`, final cleanup for the public repo.
- **Done when:** the repo is portfolio-ready and runs from prompts alone.

## 9. Open items

1. **Flag phrases (deferred):** exact English markers to normalize (e.g. "Missing visit",
   "Is this where you were?") — to be provided.
2. Tesseract OCR: treated as an optional fallback dependency; confirm it is acceptable.
3. CSV `category`: free text by default (suggested values `business` / `personal`).
4. **A trip across midnight is recorded on both days (deferred, seen in M3).** A drive that
   left late on Sat 2026-Aug-15 and arrived at 00:17 on Sun 2026-Aug-16 came out as a trip on
   each of the two days: same distance (31.0 mi), no times parsed, and no endpoints on either
   copy. Google shows the segment on both days, and it reads differently from a trip inside a
   day — the clock strings the parser expects were not there, which is why the times and the
   endpoints came out empty. What settles it is the `raw_text` of those two rows in the export;
   the fix decides which day owns the trip (the day it started, most likely) and drops the copy
   on the other. Left alone for now — it inflates the mileage of a day it did not happen on,
   so it must be settled before the CSV is used for anything.
5. **Route distance cross-check (deferred, post-M4).** Timeline reports the length of the
   *recorded GPS track*, which inflates where the signal is poor — a 1.5 mi downtown drive can
   be reported as 4.0 mi. Once trip endpoints are derived (M2.2), the routed distance between
   them can be looked up through a directions API. Keep **both** numbers, never replace one
   with the other: `distance_mi_recorded` (what the UI showed) and `distance_mi_route` (what
   the road network says). Detours are legitimate — accidents, closures, road works — so a
   track longer than the route is not automatically an error. A large gap between the two is a
   review signal, not a correction. Open questions: which provider, cost and quota per lookup,
   whether results are cached per endpoint pair, and whether the API is worth the dependency at
   all versus reviewing flagged trips by hand.
