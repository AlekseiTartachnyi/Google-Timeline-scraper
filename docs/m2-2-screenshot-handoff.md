# M2.2 — what the scraper produces

## Scope

One Timeline day in, two files out. Movement rows are kept only when they are `Driving` or
`Missing travel`; walking and the transit modes are parsed but never written, because they
are not driven and never reach a mileage record.

The per-trip map screenshot is **not** part of this milestone. See the last section.

## Output

```
exports/timeline_20260820.json
exports/timeline_20260820.txt
```

The report is printed to the console as well, so a run ends with the day on screen.

```
Date - 2026, Aug, 20, Thu

1. Driving
   1. Left 9:13 AM - Home, 123 Main St, Springfield
   2. Arrived 9:41 AM - Missing visit
   3. 12.4 mi

2. Missing travel
   1. Left 11:00 AM - Costco, 500 Oak Ave
   2. Arrived 11:20 AM - Gas Station, 77 Elm St
   3. no distance reported

4 trip(s), 39.7 mi total (1 without a reported distance)
```

## The three ways an endpoint can be empty, and why they read differently

A tax record cannot carry a guess, so the report never blurs "unknown" into one word:

| printed | meaning |
| --- | --- |
| `Home, 123 Main St` | a visit lined up exactly with this end of the trip |
| `Missing visit` | a visit lined up, and Google knows a stop happened there but not where |
| `no matching visit` | nothing lined up — no clock string matched this end of the trip |

In the JSON these are `from_place`/`from_address` filled, `from_missing: true`, and
everything null respectively — same for the `to_` side.

## How endpoints are recovered

A trip row never carries an address. The addresses live in the visit rows above and below
it, and the clocks line up exactly: a visit ending at 1:21 PM is followed by a trip
starting at 1:21 PM. Linking happens over the **full** segment list, before the walking
rows are filtered out, so a visit sitting between a walk and a drive still supplies its
address to the drive.

Matching is exact string equality on the clock. No tolerance window, no nearest neighbour.
No match leaves the endpoint empty.

## What each file does

- `extract.collect_day` — scrolls the day, merges the dumps, returns every accessibility
  description in screen order.
- `parse.build_day` — descriptions to `Visit` / `Trip`, action rows (`Yes`, `Edit`,
  `Add travel`) dropped, endpoints linked, missing visits flagged.
- `model.write_trips_json` — filters to the reported modes and writes the JSON.
- `report.render_day` — the numbered list above.

## The map screenshot, and why it is parked

Opening each driving trip to screenshot its map was the original M2.2 and does not work.
The Timeline day is one `android.webkit.WebView` covering the whole screen; a focus walk
leaves it on the first step, so nothing can be selected before it is activated, and the
touch computed from a row's reported rectangle lands on the map, which then pans away.

Two tap strategies were written and are preserved in commit `88e7956` — a row-first one
that refuses rectangles failing a stability and overlap check, and a point-first one that
scrolls until the tree agrees a fixed point is covered by the wanted row. Neither was run
to a conclusion. Until someone picks that up, the map is checked by hand against the
report, which is what the report's per-trip layout is for.
