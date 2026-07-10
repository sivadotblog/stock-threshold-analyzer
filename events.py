"""
Event stream: anchor-reset threshold events plus per-down-event outcome records.

Extends the existing detection in ``reliability.find_threshold_events`` (kept as
the single source of event truth — same anchor-reset walk, same field names:
``date``, ``price``, ``direction``, ``pct_from_anchor``). The spec calls the
date field ``event_date``; we keep the existing ``date`` name (see README for
the mapping).

For every *down* event this module adds an outcome record:

* ``resolved`` — ``bounce`` if the next event is an up-trigger, ``continuation``
  if it is another down-trigger, ``censored`` if no subsequent event exists in
  the price window. Censored events are kept and counted, never dropped.
* ``resolution_date`` / ``days_to_resolution`` — calendar days to the next event
  (NaT/NaN when censored).
* ``drawdown_beyond_trigger_pct`` — max adverse excursion: the worst additional
  close-to-close decline between the down event and its resolution (>= 0, in %).
  For censored events it is measured to the end of the available data.
* ``resolution_return_pct`` — signed return from trigger close to resolution
  close (NaN when censored).

LOOK-AHEAD WARNING: outcome fields describe the *future* of each event. Any
"as of T" consumer must re-censor internally (treat ``resolution_date > T`` as
censored and not read MAE/returns from it) — ``metrics.py`` does exactly that.

Pure functions on DataFrames; no I/O, no network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from reliability import find_threshold_events

OUTCOME_BOUNCE = "bounce"
OUTCOME_CONTINUATION = "continuation"
OUTCOME_CENSORED = "censored"


def build_events(prices: pd.DataFrame, threshold_pct: float) -> pd.DataFrame:
    """Detect +/-N% anchor-reset events and attach outcome records to down events.

    Parameters
    ----------
    prices : DataFrame with columns ['date', 'close'], ascending by date.
    threshold_pct : the N in "+/-N% from the current anchor".

    Returns the event frame (including the initial ``start`` row) with outcome
    columns populated on ``direction == 'down'`` rows and NaN/NaT elsewhere.
    """
    prices = prices.reset_index(drop=True).copy()
    prices["date"] = pd.to_datetime(prices["date"], format="mixed", dayfirst=False)

    events = find_threshold_events(prices, threshold_pct)
    events["date"] = pd.to_datetime(events["date"])

    events["resolved"] = pd.Series([None] * len(events), dtype="object")
    events["resolution_date"] = pd.NaT
    events["days_to_resolution"] = np.nan
    events["drawdown_beyond_trigger_pct"] = np.nan
    events["resolution_return_pct"] = np.nan

    if events.empty:
        return events

    # Map each event date to its positional row in `prices` for MAE slicing.
    pos_by_date = pd.Series(prices.index.values, index=prices["date"])
    close = prices["close"].to_numpy(dtype=float)

    for i in events.index:
        if events.at[i, "direction"] != "down":
            continue

        trigger_price = float(events.at[i, "price"])
        start_pos = int(pos_by_date[events.at[i, "date"]])

        nxt = i + 1  # events are chronological; next row is the resolving event
        if nxt < len(events):
            res_dir = events.at[nxt, "direction"]
            res_date = events.at[nxt, "date"]
            res_price = float(events.at[nxt, "price"])
            end_pos = int(pos_by_date[res_date])

            events.at[i, "resolved"] = (
                OUTCOME_BOUNCE if res_dir == "up" else OUTCOME_CONTINUATION
            )
            events.at[i, "resolution_date"] = res_date
            events.at[i, "days_to_resolution"] = float(
                (res_date - events.at[i, "date"]).days
            )
            events.at[i, "resolution_return_pct"] = round(
                (res_price - trigger_price) / trigger_price * 100.0, 4
            )
        else:
            events.at[i, "resolved"] = OUTCOME_CENSORED
            end_pos = len(close) - 1

        worst = float(close[start_pos:end_pos + 1].min())
        mae = max(0.0, (trigger_price - worst) / trigger_price * 100.0)
        events.at[i, "drawdown_beyond_trigger_pct"] = round(mae, 4)

    return events


def down_event_outcomes(events: pd.DataFrame) -> pd.DataFrame:
    """The outcome records alone: one row per down-trigger event."""
    if events.empty:
        return events
    return events[events["direction"] == "down"].reset_index(drop=True)
