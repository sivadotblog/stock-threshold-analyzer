"""
Out-of-sample validation harness (spec §3).

Answers one question: *does past bounce_rate predict future bounce_rate across
tickers?* If it doesn't, no ranking on this data supports the dip-buy strategy
and the tool must say so — the leaderboard and signals are gated on this
module's verdict.

Two tests, both cross-sectional:

1. **Split-half**: window W is cut at its midpoint; per-ticker ``bounce_rate``
   (and ``expectancy_per_trade_pct``) are computed independently in each half
   (events assigned by event date; an event unresolved at the cut is censored
   in H1 — nothing spans halves). Spearman rank correlation across tickers,
   with a seeded permutation p-value (one-sided: we only care about positive
   persistence). Plus a quintile-transition check.
2. **Rolling**: trailing 2.5y metrics vs the subsequent 1y realized
   bounce_rate, stepped quarterly — guards against the split-half result being
   an artifact of one particular split point.

Pure functions on ``{ticker: events_frame}`` dicts; I/O lives in the CLI.
Determinism: the only stochastic piece (permutation test) is seeded.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from metrics import DAYS_PER_YEAR, compute_bounce_metrics

PASS, WEAK, FAIL = "PASSED", "WEAK", "FAILED"


def spearman_rho(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman rank correlation (average ranks for ties)."""
    rx = pd.Series(x).rank().to_numpy(dtype=float)
    ry = pd.Series(y).rank().to_numpy(dtype=float)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def spearman_perm_pvalue(x: np.ndarray, y: np.ndarray,
                         permutations: int = 10000, seed: int = 42) -> tuple[float, float]:
    """(rho, one-sided p) via a seeded permutation test.

    p = P(rho_perm >= rho_observed) under the null of no association. One-sided
    because only *positive* persistence supports ranking on the metric.
    """
    rho = spearman_rho(x, y)
    rng = np.random.default_rng(seed)
    # Permuting y and re-ranking == permuting y's ranks, so rank once.
    rx = pd.Series(x).rank().to_numpy(dtype=float)
    ry = pd.Series(y).rank().to_numpy(dtype=float)
    hits = 0
    for _ in range(permutations):
        perm = rng.permutation(ry)
        if np.std(perm) > 0 and float(np.corrcoef(rx, perm)[0, 1]) >= rho:
            hits += 1
    p = (hits + 1) / (permutations + 1)
    return rho, float(p)


def _half_metrics(events: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
                  threshold_pct: float) -> dict:
    """§2 metrics restricted to events in (start, end], censored at ``end``."""
    window_years = (end - start).days / DAYS_PER_YEAR
    return compute_bounce_metrics(events, as_of=end, threshold_pct=threshold_pct,
                                  window_years=window_years)


def split_half_test(events_by_ticker: dict[str, pd.DataFrame],
                    window_start: pd.Timestamp, window_end: pd.Timestamp,
                    threshold_pct: float,
                    min_events_per_half: int = 5,
                    permutations: int = 10000, seed: int = 42) -> dict:
    """Cross-sectional H1-vs-H2 persistence of bounce_rate and expectancy."""
    window_start = pd.Timestamp(window_start)
    window_end = pd.Timestamp(window_end)
    mid = window_start + (window_end - window_start) / 2

    rows = []
    for ticker, events in events_by_ticker.items():
        h1 = _half_metrics(events, window_start, mid, threshold_pct)
        h2 = _half_metrics(events, mid, window_end, threshold_pct)
        if (h1["n_down_events"] >= min_events_per_half
                and h2["n_down_events"] >= min_events_per_half
                and h1["bounce_rate"] is not None
                and h2["bounce_rate"] is not None):
            rows.append({
                "ticker": ticker,
                "h1_bounce_rate": h1["bounce_rate"],
                "h2_bounce_rate": h2["bounce_rate"],
                "h1_expectancy": h1["expectancy_per_trade_pct"],
                "h2_expectancy": h2["expectancy_per_trade_pct"],
            })

    out = {
        "midpoint": str(mid.date()),
        "n_tickers": len(rows),
        "min_events_per_half": min_events_per_half,
        "bounce_rate_rho": None, "bounce_rate_p": None,
        "expectancy_rho": None, "expectancy_p": None,
        "quintile_top_to_top2_frac": None,
    }
    if len(rows) < 10:  # too few tickers for a meaningful cross-section
        return out

    df = pd.DataFrame(rows)
    rho, p = spearman_perm_pvalue(df["h1_bounce_rate"].to_numpy(),
                                  df["h2_bounce_rate"].to_numpy(),
                                  permutations, seed)
    out["bounce_rate_rho"], out["bounce_rate_p"] = round(rho, 4), round(p, 5)

    exp_ok = df.dropna(subset=["h1_expectancy", "h2_expectancy"])
    if len(exp_ok) >= 10:
        rho_e, p_e = spearman_perm_pvalue(exp_ok["h1_expectancy"].to_numpy(),
                                          exp_ok["h2_expectancy"].to_numpy(),
                                          permutations, seed)
        out["expectancy_rho"], out["expectancy_p"] = round(rho_e, 4), round(p_e, 5)

    # Quintile transition: of H1 top-quintile tickers, how many land in the
    # top two H2 quintiles? (Chance level = 0.4.)
    q1 = pd.qcut(df["h1_bounce_rate"].rank(method="first"), 5, labels=False)
    q2 = pd.qcut(df["h2_bounce_rate"].rank(method="first"), 5, labels=False)
    top1 = q1 == 4
    if top1.sum() > 0:
        out["quintile_top_to_top2_frac"] = round(
            float((q2[top1] >= 3).mean()), 4)
    return out


def rolling_test(events_by_ticker: dict[str, pd.DataFrame],
                 window_start: pd.Timestamp, window_end: pd.Timestamp,
                 threshold_pct: float,
                 train_years: float = 2.5, test_years: float = 1.0,
                 step_months: int = 3,
                 min_events_per_half: int = 5) -> dict:
    """Trailing ``train_years`` metrics vs subsequent ``test_years`` realized
    bounce_rate, stepped every ``step_months`` — the split-point robustness check.
    """
    window_start = pd.Timestamp(window_start)
    window_end = pd.Timestamp(window_end)

    steps = []
    t = window_start + pd.Timedelta(days=train_years * DAYS_PER_YEAR)
    while t + pd.Timedelta(days=test_years * DAYS_PER_YEAR) <= window_end:
        test_end = t + pd.Timedelta(days=test_years * DAYS_PER_YEAR)
        pairs = []
        for ticker, events in events_by_ticker.items():
            train = compute_bounce_metrics(events, as_of=t,
                                           threshold_pct=threshold_pct,
                                           window_years=train_years)
            test = _half_metrics(events, t, test_end, threshold_pct)
            if (train["n_down_events"] >= min_events_per_half
                    and test["n_down_events"] >= max(2, min_events_per_half // 2)
                    and train["bounce_rate"] is not None
                    and test["bounce_rate"] is not None):
                pairs.append((train["bounce_rate"], test["bounce_rate"]))
        if len(pairs) >= 10:
            arr = np.array(pairs, dtype=float)
            steps.append({
                "as_of": str(t.date()),
                "n_tickers": len(pairs),
                "rho": round(spearman_rho(arr[:, 0], arr[:, 1]), 4),
            })
        t += pd.Timedelta(days=step_months * 30.44)

    rhos = [s["rho"] for s in steps]
    return {
        "n_steps": len(steps),
        "steps": steps,
        "median_rho": round(float(np.median(rhos)), 4) if rhos else None,
        "frac_positive": round(float(np.mean([r > 0 for r in rhos])), 4) if rhos else None,
    }


def interpret(split: dict, rolling: dict,
              rho_pass: float = 0.30, p_pass: float = 0.05,
              rho_weak: float = 0.15, rolling_min_steps: int = 4) -> dict:
    """Turn the two test outputs into an explicit PASSED / WEAK / FAILED verdict
    plus human-readable interpretation lines (spec: printed, not just numbers).
    """
    rho, p = split.get("bounce_rate_rho"), split.get("bounce_rate_p")
    med_rho = rolling.get("median_rho")
    frac_pos = rolling.get("frac_positive")
    n_steps = rolling.get("n_steps") or 0

    lines: list[str] = []
    if rho is None:
        status = FAIL
        lines.append("Not enough tickers with sufficient down events in both "
                     "halves to measure cross-ticker persistence — treat the "
                     "ranking as unvalidated (FAILED).")
    else:
        split_ok = rho >= rho_pass and p is not None and p < p_pass
        rolling_ok = (n_steps >= rolling_min_steps
                      and med_rho is not None and med_rho > 0
                      and frac_pos is not None and frac_pos >= 0.6)
        lines.append(
            f"Split-half Spearman rho = {rho:.2f} (p = {p:.4f}, one-sided, "
            f"n = {split['n_tickers']} tickers): past bounce_rate "
            + ("does" if split_ok else "does NOT clearly")
            + " rank future bounce_rate across tickers at this threshold.")
        if n_steps:
            lines.append(
                f"Rolling 2.5y->1y check over {n_steps} quarterly steps: "
                f"median rho = {med_rho:.2f}, {frac_pos:.0%} of steps positive — "
                + ("stable across split points."
                   if rolling_ok else "NOT stable across split points; the "
                   "split-half number may be an artifact of one regime."))
        else:
            lines.append("Rolling check produced no usable steps — stability "
                         "across split points is unverified.")

        if split_ok and rolling_ok:
            status = PASS
            lines.append("Verdict: PASSED — cross-ticker persistence exists; "
                         "ranking on bounce_rate_wilson_low is meaningful.")
        elif rho >= rho_weak:
            status = WEAK
            lines.append("Verdict: WEAK — some persistence, but below the "
                         "pass bar or unstable. Signals are suppressed; treat "
                         "the leaderboard as descriptive only.")
        else:
            status = FAIL
            lines.append("Verdict: FAILED — the leaderboard has no predictive "
                         "content on this data. No ranking supports the "
                         "strategy; the honest output is 'no signal'.")

    lines.append("Regime caveat: persistence measured on one historical window "
                 "reflects that window's market regime; a structural break "
                 "(rates, liquidity, index composition) can invalidate it "
                 "going forward. Re-run validation as data accrues.")
    return {"status": status, "interpretation": lines}


def run_validation(events_by_ticker: dict[str, pd.DataFrame],
                   window_start, window_end, threshold_pct: float,
                   cfg: dict) -> dict:
    """Full §3 harness for one threshold. ``cfg`` is config.yaml's v2.validation."""
    split = split_half_test(
        events_by_ticker, window_start, window_end, threshold_pct,
        min_events_per_half=cfg["min_events_per_half"],
        permutations=cfg["permutations"], seed=cfg["seed"])
    rolling = rolling_test(
        events_by_ticker, window_start, window_end, threshold_pct,
        train_years=cfg["rolling_train_years"],
        test_years=cfg["rolling_test_years"],
        step_months=cfg["rolling_step_months"],
        min_events_per_half=cfg["min_events_per_half"])
    verdict = interpret(split, rolling,
                        rho_pass=cfg["rho_pass"], p_pass=cfg["p_pass"],
                        rho_weak=cfg["rho_weak"],
                        rolling_min_steps=cfg["rolling_min_steps"])
    return {
        "threshold_pct": threshold_pct,
        "window_start": str(pd.Timestamp(window_start).date()),
        "window_end": str(pd.Timestamp(window_end).date()),
        "split_half": split,
        "rolling": rolling,
        "status": verdict["status"],
        "interpretation": verdict["interpretation"],
    }
