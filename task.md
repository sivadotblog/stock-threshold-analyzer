# Autonomous Stock Screener Agent - Tasks

This document breaks down the implementation plan into actionable tasks. This can be used to coordinate work across multiple agents.

- [x] **Phase 1: Foundation & Dependencies**
    - [x] Update `requirements.txt` with `langchain`, `langchain-anthropic`, `pandas-ta`, and `Backtesting`.
    - [x] Install the new dependencies in the local environment to ensure everything resolves.
- [x] **Phase 2: Strategy & Backtesting Engine**
    - [x] Create `strategy.py` with a function to calculate technical indicators (SMA, Bollinger Bands, Z-scores) using `pandas-ta`.
    - [x] Create `backtest.py` integrating `Backtesting.py` to validate strategy profitability on historical data.
    - [x] Create unit tests for strategy calculations and backtesting logic to ensure correctness.
- [x] **Phase 3: Agent Core Construction**
    - [x] Create `research_agent.py` to initialize the Anthropic model via LangChain.
    - [x] Implement the `screener_tool` in the agent to allow it to dynamically query and filter stocks based on technical conditions.
    - [x] Implement the `backtest_tool` in the agent to validate the screened stocks.
    - [x] Set up the ReAct orchestration loop so the agent can reason through natural language queries.
- [x] **Phase 4: Frontend & Data Integration**
    - [x] Modify the agent to output its final analysis as a structured JSON report (`research_report.json`) into the `sma/data/` directory.
    - [x] Update the GitHub Pages frontend (`sma/`) to read and display the agent-generated research reports.
    - [x] Ensure the UI provides a beautiful, modern presentation of the top 10 stocks and the agent's reasoning.
- [x] **Phase 5: End-to-End Testing & Verification** (small-scale)
    - [x] Run a full test query end-to-end (verified with a top-3 query). Required fixes:
        - `research_agent.py`: `create_react_agent(state_modifier=...)` -> `prompt=...` (removed in langgraph_prebuilt >=1.0).
        - `research_agent.py`: model `claude-3-5-sonnet-latest` (404 / retired) -> `claude-sonnet-4-6`, env-overridable via `RESEARCH_AGENT_MODEL`.
        - `requirements.txt`: added missing `langgraph` (imported but unlisted).
        - `sma/.pages`: added `reports.md` to nav so the report page renders on the site.
        - Env note: venv is `uv`-managed (Python 3.13, no pip). Run with `source .venv/bin/activate && python3 ...`.
    - [x] Validate the resulting `research_report.json` structure (valid JSON: query/generated_at/analysis).
    - [ ] Serve the `sma/` frontend locally and verify the report is displayed correctly.
    - [ ] OPEN ISSUES before opening it up (not blockers, but affect result quality):
        - [x] ~~Screener ranks by raw bounce count~~ -> **Phase A done**: replaced with an
          oscillation `reliability` score (regularity + amplitude consistency + drift +
          balance, geometric mean + eligibility gate). Reuses `analyze.py` moving-anchor
          events. See `reliability.py`, `reliability_metric.md`, `test_reliability.py`,
          `calibrate_reliability.py`. Calibrated on the handful: steady names (PG/BMY/XYL)
          now outrank volatile trenders (NVDA/TQQQ), and the agent autonomously surfaces
          genuinely range-bound names scoring 0.74-0.77.
        - [x] **Phase B done:** real universe + data engineering. `universe.py` (603
          tickers: S&P 500 + mid/small-cap growth supplement where ZETA-like behavior
          lives) screened via `price_cache.py` (on-disk CSV cache around `load_prices`,
          parameterized lookback 5/10y) + `screen_bullish.py`.
        - [ ] **Phase C:** backtest still shorts volatile/leveraged names all-in (-100% ruin).
          Needs position sizing / stop-loss; align backtest with the moving-anchor signal.
        - [x] **Phase D done (for the bullish screen):** `screen_bullish.py` emits a
          *structured* ranked report (`sma/data/bullish_screen.json`, per-stock metrics
          array). The LLM agent's freeform `research_report.json` path is untouched.
        - [x] **Open product decision RESOLVED** (reliability_metric.md §6): user chose
          "oscillates around an *upward* trend" → new `compute_bullish_oscillation` metric
          (rewards up-trend + two-sided swings, "like ZETA"). Range-bound `compute_reliability`
          left intact.
