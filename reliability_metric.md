# Oscillation Reliability Metric — Design & Decisions

This document specifies how the autonomous screener scores a ticker's
**oscillation reliability** ("stable, periodically moves ±N% up and down over
many years"). It records the **chosen** formulas and the **alternatives** that
were considered, so the choices can be revisited later without re-deriving them.

All scores are normalized to `[0, 1]` (1 = best) and combined into a single
`reliability` score used to rank the universe.

> Status: design locked for Phase A implementation. Constants below are starting
> values to be **calibrated empirically** on the small handful (see
> [Calibration](#calibration)) before scaling to the S&P 500.

---

## 1. Inputs

Computed from the existing moving-anchor event detector
`find_threshold_events(df, threshold_pct)` in `analyze.py`, which returns an
events table with `date`, `price`, `direction` (`up` / `down` / `start`),
`pct_from_anchor`. From it we derive:

- **intervals** `Δt_i` — days between consecutive events
- **amplitudes** `a_i` = `|pct_from_anchor|` for each triggered event (always ≥ threshold)
- the raw **close** series (for drift / trend)
- `n_up`, `n_down` — event counts by direction

---

## 2. Sub-metrics

### 2.1 Regularity — is the oscillation *periodic*?
Measures evenness of time spacing between events via the scale-invariant
coefficient of variation, so different natural cycle lengths are judged fairly.

```
CV_t       = std(Δt) / mean(Δt)
regularity = exp(-k_reg · CV_t)          # CHOSEN, k_reg = 1.0
```

**Alternatives (documented for future):**
- `1 / (1 + CV_t)` — gentler, bounded, never reaches 0. Less discriminating.
- `max(0, 1 - CV_t)` — linear, hits 0 at `CV_t = 1`, clips below.
- **FFT / autocorrelation** on the detrended close series: peak spectral power ÷
  total power gives a true periodicity score *and* the dominant cycle length.
  Stronger but heavier; adopt if interval-CV rankings prove too coarse.

### 2.2 Amplitude consistency — do swings land *near* ±N%?
Tightly clustered trigger magnitudes = clean, repeatable swings.

```
CV_a                  = std(a) / mean(a)
amplitude_consistency = exp(-k_amp · CV_a)   # CHOSEN, k_amp = 1.0
```
Diagnostic (not scored): `mean_overshoot = mean(a) - threshold` (small = clean triggers).

**Alternatives:**
- `1 / (1 + CV_a)` mapping (same trade-off as 2.1).
- **Peak-to-trough swing** amplitude between an up-reversal and the next
  down-reversal, instead of per-trigger magnitude. Richer (captures realized
  round-trip size) but heavier; defer to a refinement pass.

### 2.3 Drift — is it *stable* or actually trending?
Two complementary pieces.

**(a) Net drift**, normalized by swing size (the key trick — drift is only
meaningful relative to how big the oscillations are):
```
net_return  = (close[-1] - close[0]) / close[0]
drift_ratio = |net_return| / (mean(a) / 100)   # drift in units of one swing
drift_score = 1 / (1 + drift_ratio)            # CHOSEN
```

**(b) Trend strength** via OLS `close ~ time`:
```
trend_strength = R²(close vs time)
mean_revert    = 1 - trend_strength            # DIAGNOSTIC ONLY (dropped from score, see §6)
```
> Computed and reported, but **not** a scored axis. Calibration showed it rewards
> noise — a wildly volatile trender has low R² → high `mean_revert` — propping up
> chaotic names that `drift_score` already (correctly) penalizes.

**Alternatives:**
- Annualized slope magnitude instead of R² for trend strength.
- Use log-price for the regression (geometric drift) — preferable if we later
  span very long horizons; revisit at 10y+.

### 2.4 Direction balance / alternation — does it actually go *both* ways?
```
balance     = 1 - |n_up - n_down| / (n_up + n_down)     # CHOSEN (scored)
alternation = fraction of adjacent event pairs whose direction flips  # diagnostic
```
`alternation` starts as a diagnostic; promote to a scored axis if trending names
slip through `balance` alone.

---

## 3. Combination

### Eligibility gate (applied first)
If any of these fail, `reliability = 0` (too little signal to call "reliable"):
- `n_up + n_down ≥ 6`
- both directions present (`n_up ≥ 1` and `n_down ≥ 1`)
- events span ≥ 60% of the requested window (not all clustered in one stretch)

### Score — weighted geometric mean (CHOSEN)
```
reliability = ( regularity^w1
              · amplitude_consistency^w2
              · drift_score^w3
              · mean_revert^w4
              · balance^w5 ) ^ (1 / Σw)
```
| axis | weight | why |
|---|---|---|
| regularity            | 0.30 | "periodic" is half the goal |
| drift_score           | 0.30 | "stable" is the other half |
| amplitude_consistency | 0.25 | clean, repeatable ±N% swings |
| balance               | 0.15 | symmetric up/down legs |

> Weights revised during calibration (§6): `mean_revert` removed, its weight
> redistributed to `regularity`/`drift_score`/`amplitude_consistency`. Original
> 5-axis weights were 0.25 / 0.25 / 0.20 / 0.15(mean_revert) / 0.15.

**Why geometric, not arithmetic:** a stock must be good on *every* axis; the
geometric mean lets one terrible axis veto the score, which arithmetic averaging
would mask.

**Alternatives:**
- **Arithmetic (weighted) mean** — more forgiving; a strong axis can compensate
  a weak one. Use if geometric proves too punishing and drops good candidates.
- **Min-of-axes** (`min(scores)`) — hardest gate; ranks by weakest link. Too
  brittle for a first pass but useful as a tie-breaker / sanity filter.
- **Learned weights** — fit weights (e.g., logistic regression) against a small
  hand-labeled set of "clearly stable / clearly not." Deferred: we chose
  *autonomous quant research*, not a trained model, but this is the upgrade path
  if hand-tuned weights underperform.

---

## 4. Decisions locked

| # | Decision | Chosen | Default constant |
|---|---|---|---|
| 1 | CV → score mapping | `exp(-k · CV)` | `k_reg = k_amp = 1.0` |
| 2 | Axis combination | weighted **geometric** mean + hard gate | weights in §3 |

Both were delegated to implementer discretion; alternatives above are the record
for future revisiting.

---

## 5. Calibration

All constants (`k_reg`, `k_amp`, the five weights, gate thresholds) live as
**named constants in one place** so they are trivially tunable.

Procedure before scaling to 500:
1. Run the metric on the existing handful
   (`AAPL, MSFT, SPY, QQQ, TQQQ, ZETA, NVDA, TSLA, META, AMZN`) plus a few
   steady names (`KO, PG, JNJ`).
2. **Expected ordering** (falsifiable sanity check): steady names + `SPY` score
   high; `TQQQ / TSLA / ZETA` crater on `drift_score` / `mean_revert`.
3. If the ordering is wrong, retune `k` and weights here — never at 500 scale.

---

## 6. Calibration findings (2026-06-19, 5y window)

First calibration run on the set above. Outcomes:

- **Trend penalty works:** NVDA (net +1047%) ranked last; `drift_score` produced a
  clean inverse gradient vs. net return (PG +28% near top → NVDA +1047% bottom).
- **Dropped `mean_revert` from the score** (the only metric change): as a scored
  axis it rewarded volatility and propped up TSLA (5th). Removing it moved TSLA
  to 8th (below SPY) and lifted steady names (PG/MSFT/JNJ/KO) into the top 5.
  Kept as a diagnostic.
- **Honest caveat — bull-market regime:** over 2021–2026 every large cap drifted
  up strongly (SPY +90%), so there are *no* truly range-bound oscillators in this
  universe/window. Scores are compressed (~0.18–0.47) and the ranking is
  *relative* ("least-trending oscillators"), not absolute. This is correct
  behaviour, not a defect.

### Open product decision (surfaced by calibration) — RESOLVED
Do we want **(a) strictly range-bound** stocks (penalize all net drift, matches
"stable… moves 10% up and down"), or **(b) oscillates ±N% *around* an upward
trend** (reward up-trend, penalize down)? Option (b) surfaces stocks that reliably
swing ±10% *while drifting upward* ("like ZETA").

**Resolution (user picked (b)):** implemented as a **separate** metric,
`compute_bullish_oscillation` in `reliability.py`, so `compute_reliability` (the
range-bound view (a)) is left intact for the existing site/agent. The new metric
is deliberately lean — two scored axes combined as a plain product:

```
bullish_score = activity * trend
activity      = min(n_up,n_down) / (min(n_up,n_down) + ACTIVITY_HALF)   # two-sided swings
trend_units   = net_return / (mean_a/100)                              # SIGNED
trend         = 1 / (1 + exp(-K_TREND * trend_units))                  # up→1, flat→0.5, down→0
```

`regularity` and `amplitude_consistency` are **demoted to diagnostics** here (the
user judged them academic for this goal). The shared eligibility gate is factored
into `_oscillation_gate`. Tunables `ACTIVITY_HALF=8.0`, `K_TREND=0.5`. Validated
on the cohort: ZETA ≈ 0.88 (archetype tops it), AMPL/BRZE/DV ≈ 0.03–0.06,
flat KO/PG land middling. Screen the universe with `screen_bullish.py`; sanity-
check with `calibrate_bullish.py`.
