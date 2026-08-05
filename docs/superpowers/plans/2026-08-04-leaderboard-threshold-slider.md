# Leaderboard Threshold Slider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the leaderboard rank tickers at ±5% / ±10% / ±15% / ±20%, switchable via a slider, instead of a single hard-coded ±10%.

**Architecture:** Python (`main.py leaderboard`) precomputes and writes one ranked JSON per configured threshold plus a small manifest; the Python ranking engine (`reliability.py` / `report.py`) is untouched and stays the single source of truth. The frontend (`bullish-screen.js`) fetches the manifest, then fetches and caches per-threshold JSON on demand as the user drags a range slider on `index.astro`, re-rendering the existing scatter/table/meta components — none of which need internal changes since they already read `threshold_pct` / `universe_size` from the fetched payload.

**Tech Stack:** Python 3.13 (pandas, PyYAML) for the pipeline; vanilla JS + Plotly + Tabulator for the frontend; Astro static site; `uv` for Python execution, `npm` for the site build.

## Global Constraints

- Threshold stops: **5 / 10 / 15 / 20%**, default **10%** (matches today's behavior on first load).
- The Python ranking engine (`reliability.py`, `report.py`) must not change — this is a data-pipeline and frontend change only.
- `public/data/bullish_screen.json` must keep existing at the default threshold's content — `generate_data.py` reads it, and it may be bookmarked.
- Run Python via `uv run ...` (never bare `python`/`pip`), matching this repo's CI (`.github/workflows/`) and existing convention.
- Follow existing code conventions: inline imports inside `main.py` functions (not top-level), `f"{n:g}"` for trimming trailing `.0` in filenames (matches `events_{n:g}pct.csv` in `cmd_analyze`).

---

### Task 1: Precompute one leaderboard JSON per configured threshold

**Files:**
- Modify: `config.yaml:16-18` (analyzer thresholds)
- Modify: `main.py:137-178` (`cmd_leaderboard`), add two new helpers above it
- Test: `test_analyzer.py` (append at end of file)

**Interfaces:**
- Produces: `_screen_filename(threshold_pct: float) -> str` — e.g. `_screen_filename(5.0) == "bullish_screen_5pct.json"`.
- Produces: `_leaderboard_payloads(prices: dict[str, pd.DataFrame], categories: dict[str, str], as_of, thresholds: list[float], years: int, a: dict, universe_size: int, generated_at: str) -> dict[float, dict]` — maps each threshold to the full leaderboard payload dict (same shape `build_leaderboard` already returns).
- Consumes: `compute_leaderboard_rows` / `build_leaderboard` from `report.py` (unchanged signatures).

- [ ] **Step 1: Write the failing tests**

Append to `test_analyzer.py`:

```python
def test_screen_filename_matches_threshold():
    from main import _screen_filename
    assert _screen_filename(5.0) == "bullish_screen_5pct.json"
    assert _screen_filename(10.0) == "bullish_screen_10pct.json"
    assert _screen_filename(12.5) == "bullish_screen_12.5pct.json"


def test_leaderboard_payloads_one_per_threshold():
    from main import _leaderboard_payloads

    prices = {
        "OSC": sine_prices(),
        "DEC": declining_prices(),
    }
    as_of = max(p["date"].iloc[-1] for p in prices.values())
    a = {
        "recent_window_days": 30,
        "parabolic_window_days": 365,
        "parabolic_max_run_up_pct": 200.0,
        "parabolic_recency_days": 730,
        "chained_max_down_streak": 5,
        "chained_deep_run_len": 4,
        "chained_deep_run_count": 2,
        "min_events": 10,
    }
    payloads = _leaderboard_payloads(
        prices, {"OSC": "test"}, as_of, [5.0, 10.0], years=5, a=a,
        universe_size=2, generated_at="2026-08-04T00:00:00")

    assert set(payloads) == {5.0, 10.0}
    assert payloads[5.0]["threshold_pct"] == 5.0
    assert payloads[10.0]["threshold_pct"] == 10.0
    assert payloads[5.0]["universe_size"] == 2
    # A tighter threshold never prints fewer events than a looser one for
    # the same sine wave.
    osc_5 = next(r for r in payloads[5.0]["results"] if r["ticker"] == "OSC")
    osc_10 = next(r for r in payloads[10.0]["results"] if r["ticker"] == "OSC")
    assert (osc_5["n_up"] + osc_5["n_down"]) >= (osc_10["n_up"] + osc_10["n_down"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest test_analyzer.py -k "screen_filename or leaderboard_payloads" -v`
Expected: FAIL — `ImportError: cannot import name '_screen_filename' from 'main'` (and same for `_leaderboard_payloads`).

- [ ] **Step 3: Update `config.yaml`**

Replace `config.yaml:17` (`thresholds_pct: [10.0]        # ±N% leg sizes analyzed / reported`) with:

```yaml
  thresholds_pct: [5.0, 10.0, 15.0, 20.0]  # ±N% leg sizes precomputed for the leaderboard slider
  default_threshold_pct: 10.0   # slider's initial position; also the bullish_screen.json alias
```

- [ ] **Step 4: Implement the two helpers and rewrite `cmd_leaderboard` in `main.py`**

Insert above `def cmd_leaderboard(args, cfg) -> int:` (replacing the current lines 137-178 entirely):

```python
def _screen_filename(threshold_pct: float) -> str:
    return f"bullish_screen_{threshold_pct:g}pct.json"


def _leaderboard_payloads(prices: dict[str, pd.DataFrame], categories: dict[str, str],
                          as_of, thresholds: list[float], years: int, a: dict,
                          universe_size: int, generated_at: str) -> dict[float, dict]:
    """threshold_pct -> full leaderboard payload, one per configured threshold."""
    from report import build_leaderboard, compute_leaderboard_rows
    out = {}
    for n in thresholds:
        rows = compute_leaderboard_rows(
            prices, categories, as_of, n, a["recent_window_days"],
            a["parabolic_window_days"], a["parabolic_max_run_up_pct"],
            a["parabolic_recency_days"], a["chained_max_down_streak"],
            a["chained_deep_run_len"], a["chained_deep_run_count"],
            a["min_events"])
        out[n] = build_leaderboard(rows, n, years, universe_size=universe_size,
                                   generated_at=generated_at)
    return out


def cmd_leaderboard(args, cfg) -> int:
    a = cfg["analyzer"]
    tickers, categories = _universe(cfg, args.tickers)
    prices = _load_prices(tickers, args.years, args.max_age_days)
    as_of = _as_of(prices)

    thresholds = [args.threshold] if args.threshold else a["thresholds_pct"]
    default_n = args.threshold or a["default_threshold_pct"]
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    payloads = _leaderboard_payloads(prices, categories, as_of, thresholds,
                                     args.years, a, len(tickers), generated_at)
    if default_n not in payloads:
        raise SystemExit(
            f"default_threshold_pct {default_n:g} is not in thresholds {thresholds}")
    default_payload = payloads[default_n]

    hdr = (f"{'#':>3} {'ticker':<7}{'price':>9}{'action':<14}{'need%':>7}{'netlegs':>8}{'netdips':>8}{'P(rec)':>7}"
           f"{'n▲':>5}{'n▼':>5}"
           f"{'cagr%':>8}{'maxDD%':>8}  trend")
    print("\n" + hdr + "\n" + "-" * len(hdr))
    for r in default_payload["results"][:25]:
        trend = ("DOWN" if not r["trend_positive"]
                 else "PARA" if r["parabolic"]
                 else "CHAIN" if r["chained_dips"]
                 else "THIN" if r["thin_history"] else "up")
        rec = (f"{r['recovery_rate']:>7.2f}" if r["recovery_rate"] is not None
               else f"{'—':>7}")
        action = (f"{r['action_side']} @ {r['action_price']:.2f}"
                  if r["action_side"] else "—")
        need = (f"{r['pct_to_action']:>+7.1f}" if r["pct_to_action"] is not None
                else f"{'—':>7}")
        print(f"{r['rank']:>3} {r['ticker']:<7}{r['current_price']:>9.2f}{action:<14}{need}"
              f"{r['net_legs_per_year']:>8.1f}{r['net_dips_per_year']:>8.1f}{rec}"
              f"{r['n_up']:>5}{r['n_down']:>5}"
              f"{r['cagr_pct']:>8.1f}{r['max_drawdown_pct']:>8.1f}  {trend}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    for n, payload in payloads.items():
        _write_json(SITE_DATA_DIR / _screen_filename(n), payload)
    _write_json(SITE_DATA_DIR / "bullish_screen.json", default_payload)
    _write_json(OUTPUT_DIR / "leaderboard.json", default_payload)
    _write_json(SITE_DATA_DIR / "screen_manifest.json",
               {"thresholds": thresholds, "default": default_n})
    return 0
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest test_analyzer.py -v`
Expected: PASS (all tests, including the two new ones and every pre-existing test — `cmd_leaderboard`'s public signature and CLI flags are unchanged).

- [ ] **Step 6: Commit**

```bash
git add config.yaml main.py test_analyzer.py
git commit -m "feat: precompute leaderboard at multiple ±N% thresholds"
```

---

### Task 2: Add the threshold slider control to the leaderboard page

**Files:**
- Modify: `src/pages/index.astro:10-33` (insert control block after the intro paragraph, before the meta line)

**Interfaces:**
- Produces: DOM elements `#lb-threshold` (range input, `min=5 max=20 step=5 value=10`) and `#lb-threshold-label` (value-pill span) — consumed by Task 3's `bullish-screen.js`.
- Reuses: `.sma-controls` / `.value-pill` CSS classes already defined in `src/styles/global.css:253-301` (no new CSS needed).

- [ ] **Step 1: Insert the control markup**

In `src/pages/index.astro`, immediately after the closing `</p>` of the intro paragraph (the one ending `...Investigate any ticker in the chart explorer.</p>`) and before `<p id="bullish-meta">`, insert:

```astro
  <div class="sma-controls">
    <div>
      <label for="lb-threshold">
        Threshold <span id="lb-threshold-label" class="value-pill">10%</span>
      </label>
      <input id="lb-threshold" type="range" min="5" max="20" step="5" value="10" />
    </div>
  </div>

```

- [ ] **Step 2: Build and verify the control renders**

Run: `npm run build && grep -c 'id="lb-threshold"' dist/index.html && grep -c 'id="lb-threshold-label"' dist/index.html`
Expected: both greps print `1` (the element appears exactly once in the built HTML).

- [ ] **Step 3: Commit**

```bash
git add src/pages/index.astro
git commit -m "feat: add threshold slider control to leaderboard page"
```

---

### Task 3: Wire the slider to fetch, cache, and re-render per-threshold data

**Files:**
- Modify: `public/js/bullish-screen.js` (replace `render()` bootstrap with manifest-driven `init()`)

**Interfaces:**
- Consumes: `#lb-threshold` / `#lb-threshold-label` from Task 2; `renderScatter(el, results)`, `buildTable(el, results)`, `wireFilters()` (all unchanged, defined earlier in this same file).
- Consumes: `public/data/screen_manifest.json` (`{ thresholds: number[], default: number }`) and `public/data/bullish_screen_{n}pct.json` from Task 1.

- [ ] **Step 1: Replace the bootstrap section of `public/js/bullish-screen.js`**

Replace everything from `// ---- Bootstrap ----` (the `function render() {`) through the end of the file with:

```javascript
  // ---- Bootstrap ----
  let lastResults = [];
  let defaultThreshold = 10;
  const screenCache = new Map(); // thresholdPct -> payload

  async function loadManifest() {
    const url = `${dataBase()}/screen_manifest.json`;
    const resp = await fetch(url, { cache: "no-cache" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} loading ${url}`);
    return await resp.json();
  }

  async function loadScreen(thresholdPct) {
    if (screenCache.has(thresholdPct)) return screenCache.get(thresholdPct);
    const url = `${dataBase()}/bullish_screen_${thresholdPct}pct.json`;
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status} loading ${url}`);
    const data = await resp.json();
    screenCache.set(thresholdPct, data);
    return data;
  }

  function renderMeta(metaEl, data) {
    const results = data.results || [];
    const nPos = results.filter((r) => r.trend_positive && !r.parabolic && !r.chained_dips && !r.thin_history).length;
    const nPara = results.filter((r) => r.trend_positive && r.parabolic).length;
    const nChain = results.filter((r) => r.trend_positive && !r.parabolic && r.chained_dips).length;
    const nThin = results.filter((r) => r.trend_positive && !r.parabolic && !r.chained_dips && r.thin_history).length;
    metaEl.innerHTML =
      `Screened <b>${data.universe_size}</b> tickers @ ±${data.threshold_pct}% ` +
      `over ${data.lookback_years}y — <b>${nPos}</b> steady trend-positive candidates, ` +
      `${nThin} thin histories (🌱, ranked down), ` +
      `${nChain} dip-chainers (⛓️, ranked down), ` +
      `${nPara} parabolic runners (🚀, ranked down), ` +
      `${results.filter((r) => !r.trend_positive).length} downtrenders (greyed). ` +
      `<small>Generated ${new Date(data.generated_at).toLocaleString()}.</small>`;
  }

  async function loadAndRender(thresholdPct, isFallback) {
    const scatterEl = document.getElementById("bullish-scatter");
    const tableEl = document.getElementById("bullish-table");
    const metaEl = document.getElementById("bullish-meta");
    if (!scatterEl || typeof Plotly === "undefined" || typeof Tabulator === "undefined") return;

    try {
      const data = await loadScreen(thresholdPct);
      lastResults = data.results || [];
      if (metaEl) renderMeta(metaEl, data);
      renderScatter(scatterEl, lastResults);
      buildTable(tableEl, lastResults);
    } catch (err) {
      if (!isFallback && thresholdPct !== defaultThreshold) {
        const thresholdInput = document.getElementById("lb-threshold");
        const thresholdLabel = document.getElementById("lb-threshold-label");
        if (thresholdInput) thresholdInput.value = defaultThreshold;
        if (thresholdLabel) thresholdLabel.textContent = `${defaultThreshold}%`;
        return loadAndRender(defaultThreshold, true);
      }
      if (metaEl) metaEl.innerHTML =
        `<span style="color:var(--down,#c2410c);">Could not load bullish_screen_${thresholdPct}pct.json (${err.message || err}). ` +
        "Run <code>python3 main.py leaderboard</code> to generate it.</span>";
    }
  }

  async function init() {
    const scatterEl = document.getElementById("bullish-scatter");
    if (!scatterEl) return;

    const thresholdInput = document.getElementById("lb-threshold");
    const thresholdLabel = document.getElementById("lb-threshold-label");

    if (thresholdInput) {
      try {
        const manifest = await loadManifest();
        if (typeof manifest.default === "number") defaultThreshold = manifest.default;
        if (Array.isArray(manifest.thresholds) && manifest.thresholds.length) {
          thresholdInput.min = Math.min(...manifest.thresholds);
          thresholdInput.max = Math.max(...manifest.thresholds);
        }
      } catch (e) {
        // Manifest missing: fall back to the slider's markup defaults (5-20, default 10).
      }
      thresholdInput.value = defaultThreshold;
      if (thresholdLabel) thresholdLabel.textContent = `${defaultThreshold}%`;

      thresholdInput.addEventListener("input", () => {
        const n = parseFloat(thresholdInput.value);
        if (thresholdLabel) thresholdLabel.textContent = `${n}%`;
        loadAndRender(n, false);
      });
    }

    await loadAndRender(defaultThreshold, false);
    wireFilters();

    const rerenderScatter = () => renderScatter(scatterEl, lastResults);
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", rerenderScatter);
    window.addEventListener("themechange", rerenderScatter);
  }

  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", init);
  else init();
})();
```

Note: `wireFilters()` now runs once in `init()` (after the first table build) instead of once per render — calling it on every threshold change would stack duplicate `input` listeners on the filter bar (those DOM elements survive across re-renders; only `#bullish-table`'s contents are rebuilt), so it must run exactly once.

- [ ] **Step 2: Syntax-check the script**

Run: `node --check public/js/bullish-screen.js`
Expected: no output, exit code 0 (this repo ships the file to `public/` unbundled, so `npm run build` doesn't parse it — `node --check` is the fast syntax gate).

- [ ] **Step 3: Commit**

```bash
git add public/js/bullish-screen.js
git commit -m "feat: fetch and cache per-threshold leaderboard data on slider input"
```

---

### Task 4: End-to-end verification with real data

**Files:** none (verification only)

**Interfaces:** none — this task exercises Tasks 1-3 together.

- [ ] **Step 1: Generate real per-threshold leaderboard data for a small ticker subset**

Run: `uv run python main.py leaderboard --tickers AAPL,MSFT,SPY,QQQ,TQQQ`

Expected: prints the ranked table (as before), and the command exits 0.

- [ ] **Step 2: Verify the expected files were written with correct contents**

Run:
```bash
ls public/data/bullish_screen_5pct.json public/data/bullish_screen_10pct.json \
   public/data/bullish_screen_15pct.json public/data/bullish_screen_20pct.json \
   public/data/screen_manifest.json public/data/bullish_screen.json
python3 -c "
import json
for n in (5, 10, 15, 20):
    d = json.load(open(f'public/data/bullish_screen_{n}pct.json'))
    assert d['threshold_pct'] == float(n), (n, d['threshold_pct'])
m = json.load(open('public/data/screen_manifest.json'))
assert m == {'thresholds': [5.0, 10.0, 15.0, 20.0], 'default': 10.0}, m
default = json.load(open('public/data/bullish_screen.json'))
assert default['threshold_pct'] == 10.0
print('OK')
"
```
Expected: all six files listed exist, and the Python snippet prints `OK`.

- [ ] **Step 3: Verify `--threshold` still produces a single ad-hoc run**

Run: `uv run python main.py leaderboard --threshold 7.5 --tickers AAPL,MSFT`

```bash
python3 -c "
import json
d = json.load(open('public/data/bullish_screen_7.5pct.json'))
assert d['threshold_pct'] == 7.5, d['threshold_pct']
m = json.load(open('public/data/screen_manifest.json'))
assert m == {'thresholds': [7.5], 'default': 7.5}, m
print('OK')
"
```
Expected: prints `OK` — confirms the `--threshold` override still writes exactly one dataset (mirroring pre-slider behavior) rather than the full four-stop sweep.

- [ ] **Step 4: Full Python test suite**

Run: `uv run pytest -v`
Expected: PASS, no regressions in `test_analyzer.py`, `test_engine.py`.

- [ ] **Step 5: Manual browser verification**

Run: `npm run build && npm run preview` (or `npm run dev`), then open the leaderboard page in a browser.

Check:
- The threshold slider shows `10%` initially and the meta line reads `... @ ±10% ...`.
- Dragging the slider to `5%`, `15%`, and `20%` updates the meta line's `±N%` text, the scatter plot, and the table without a page reload; rank order visibly changes between stops (e.g. `net legs/yr` values differ) since it's a different precomputed dataset per stop.
- The ticker filter bar (`#tb-filters`) still filters correctly after moving the slider more than once (regression check for the `wireFilters()` single-registration fix in Task 3).
- No console errors on load or on slider `input` events.

- [ ] **Step 6: Regenerate the full-universe leaderboard and commit the refreshed data**

Run: `uv run python main.py leaderboard` (full universe, no `--tickers` override — this restores `public/data/*.json` to real production data instead of the 5-ticker subset used for verification)

```bash
git add public/data/bullish_screen*.json public/data/screen_manifest.json output/leaderboard.json
git commit -m "chore: regenerate leaderboard data for the multi-threshold slider"
```
