# Leaderboard threshold slider

## Problem

The oscillation leaderboard (`index.astro` / `bullish-screen.js`) ranks all
tickers at a single, hard-coded ±10% threshold. The threshold drives the
entire ranking — event detection, `net_legs_per_year`, and the four gates
(parabolic / chained-dips / thin-history / downtrend) — all computed
server-side in Python (`reliability.py` / `report.py`) and baked into
`public/data/bullish_screen.json`. There's no way to see how the board
reshuffles at a tighter or looser threshold without editing config and
rebuilding.

This is distinct from the Chart page, which already has a live 1–25%
slider: that page ships raw closes and recomputes ±N% events entirely in
the browser (`sma-chart.js: detectEvents`), because event detection alone
is cheap and stateless. The leaderboard's ranking is not cheap or
stateless — it's a multi-stage pipeline with recency windows, streak
detection, and categorical gates — so porting it to JS would mean a second
implementation of the ranking engine to keep in sync with Python. That's
out of scope here.

## Approach

Precompute the leaderboard at a small set of discrete thresholds and let
the UI switch between prebuilt datasets. The Python ranking engine stays
the single source of truth; the "slider" snaps to the precomputed stops.

**Stops: 5 / 10 / 15 / 20%**, evenly spaced so a native `<input type=range
min=5 max=20 step=5>` maps directly to them (matches the Chart page's
control style). Default stays 10%, matching today's behavior exactly when
the page first loads.

## Data pipeline

**`config.yaml`**
- `analyzer.thresholds_pct: [5.0, 10.0, 15.0, 20.0]` (already a list; the
  `analyze` subcommand already loops over it — this reuses existing infra).
- New key `analyzer.default_threshold_pct: 10.0` — the threshold used for
  the legacy `bullish_screen.json` alias and the slider's initial value.
  Needed because `thresholds_pct[0]` is now `5`, not `10`; a separate key
  keeps the default explicit rather than implicit in list order.

**`main.py cmd_leaderboard`**
- Loop over every threshold in `analyzer.thresholds_pct`, computing rows
  and writing `public/data/bullish_screen_{n:g}pct.json` for each (reusing
  `compute_leaderboard_rows` / `build_leaderboard`, unchanged).
- Also write `public/data/bullish_screen.json` as a copy of the
  `default_threshold_pct` result — `generate_data.py` reads this file to
  seed the Chart page's ticker list, and it's a plausible bookmark/deep
  link, so it must keep working unchanged.
- Write `public/data/screen_manifest.json`:
  ```json
  { "thresholds": [5, 10, 15, 20], "default": 10 }
  ```
  so the frontend doesn't hardcode the stops.
- `--threshold` CLI flag behavior is unchanged (still overrides to a single
  ad-hoc run, mirroring today).

## Frontend

**`index.astro`**
Add a threshold control above the table, styled like the Chart page's
controls:
```
Threshold  [ 10% ]
|——●———|      (range: min=5 max=20 step=5 value=10)
```

**`bullish-screen.js`**
- Refactor the current one-shot fetch-then-render into
  `loadAndRender(thresholdPct)`.
- Cache fetched datasets in a `Map<thresholdPct, payload>` so re-visiting a
  stop doesn't re-fetch.
- On slider `input`: load from cache or fetch
  `bullish_screen_{n}pct.json`, then re-run `renderScatter`, `buildTable`,
  and the meta-line update. Both already read `threshold_pct` and
  `universe_size` straight from the fetched JSON, so labels/counts update
  for free — no changes needed inside those functions.
- Fetch failure for a given stop: show the existing error banner pattern,
  fall back to the default (10%) dataset.

**Unchanged:** `reliability.py`, `report.py` (the ranking engine and its
gates), the Chart page and `sma-chart.js`, `generate_data.py`'s own logic
(it just keeps reading `bullish_screen.json`, which still exists).

## Testing

- Extend `test_analyzer.py` (or add a small pipeline test) asserting a
  leaderboard build emits one JSON file per configured threshold, and that
  each file's `threshold_pct` field matches the value implied by its
  filename.
- Manual verification: `npm run build` (or dev server), load the
  leaderboard, move the slider through all four stops, confirm the table,
  scatter plot, and meta line all update and that rank order visibly
  changes between stops.

## Cost / trade-offs

- Build time: the ranking engine now runs once per configured threshold
  (4×) instead of once. Each run is already fast enough for `analyze` to do
  this today across the universe.
- Storage/page weight: four leaderboard JSON files instead of one, each
  loaded lazily on demand — a given page view only ever fetches the
  datasets the user actually selects.
- The slider is discrete (four stops), not continuous. If continuous
  resolution is wanted later, it requires porting the ranking engine to JS
  and shipping raw closes for the full universe (~16 MB) — a materially
  larger, separate effort, deliberately deferred.
