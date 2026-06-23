# Autonomous Stock Screener Agent

This plan outlines the architecture and implementation steps to build an Autonomous Machine Learning Research tool capable of screening thousands of stocks for specific mean-reverting/oscillating patterns using natural language queries.

## User Review Required

> [!IMPORTANT]
> The plan has been updated to integrate directly into your `stock-threshold-analyzer` repo, outputting results to the GitHub Pages frontend, and using a vendor-agnostic LLM setup powered by Anthropic. Please review the updated steps below and give the green light to begin execution!

## Proposed Architecture

Based on your choices, we will repurpose the existing repo to run an LLM agent that outputs research reports directly to the static GitHub Pages site.

### 1. Vendor-Agnostic LLM Core (`agent/`)
- We will use **LangChain** and **LiteLLM** (or standard LangChain Chat models) to ensure the agent is completely vendor-agnostic. You can swap Anthropic for OpenAI or Gemini by just changing an environment variable.
- **Anthropic (Claude)** will be our starting model.
- The agent will use a ReAct pattern to reason through the user's query and trigger the right analytical tools.

### 2. Strategy / Math Engine (`strategy.py`)
- We will use `pandas-ta` to compute the required technical indicators (SMA, Bollinger Bands, Z-scores).
- We will build a screener function that filters stocks that have repeatedly hit upper/lower bounds.
- *Integration*: We will use the existing `analyze.py` logic (the ±N% threshold trigger) as one of the core tools the LLM can use to evaluate a ticker's historical oscillation.

### 3. Backtesting Engine (`backtest.py`)
- We will integrate `Backtesting.py` to programmatically validate the P&L of trading the identified oscillation bounds, ensuring the pattern was actually profitable.

### 4. GitHub Pages Frontend Integration (`sma/`)
- Currently, `generate_data.py` builds the JSON data for the `sma/` GitHub Pages site.
- We will update the agent to output its findings (e.g., a "Top 10 Reliable Stocks" JSON report containing the LLM's reasoning, the backtest results, and the ticker list) into the `sma/data/` directory.
- We will update the MkDocs/GitHub Pages frontend to display these agent-generated research reports alongside the interactive charts.

### 5. Data Ingestion Layer
- We will continue using `yfinance` to pull 5-10 years of OHLCV data. 

## Implementation Steps (MVP)

1. **Setup Dependencies**: Add `langchain`, `langchain-anthropic`, `pandas-ta`, `Backtesting` to `requirements.txt`.
2. **Build the Agent Core**: Create `research_agent.py` which initializes the Anthropic model and the ReAct orchestration loop.
3. **Build the Tools**: 
   - `screener_tool`: Scans a universe of tickers (e.g., S&P 500) against a specific technical condition.
   - `backtest_tool`: Validates a single ticker's oscillation strategy profitability.
4. **Bridge to Frontend**: Modify the agent to generate a `research_report.json` in the `sma/data/` folder instead of just printing to the console.
5. **Update UI**: Modify the `sma/` docs (e.g., `index.md` or a new `reports.md`) to fetch and display the latest autonomous research report.

## Verification Plan

### Automated Tests
- Unit tests to ensure the agent correctly parses parameters from natural language (e.g., "10%" and "200-day SMA").

### Manual Verification
- Run `python research_agent.py "Find me 10 stocks that reliably bounce 10% off their 200-day SMA over the last 5 years."`
- Verify that `research_report.json` is generated.
- Run `mkdocs serve` and verify the frontend beautifully displays the agent's reasoning and the resulting top 10 stocks.
