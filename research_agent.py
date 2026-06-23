import os
import json
import pandas as pd
from typing import List, Optional
import yfinance as yf

from langchain_anthropic import ChatAnthropic
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from reliability import compute_reliability
from backtest import run_backtest

# Define a default universe for the MVP
DEFAULT_UNIVERSE = ["AAPL", "MSFT", "SPY", "QQQ", "TQQQ", "ZETA", "NVDA", "TSLA", "META", "AMZN"]


def load_prices(ticker: str, years: int = 5) -> Optional[pd.DataFrame]:
    """Fetch split/dividend-adjusted daily closes as a ['date','close'] frame."""
    df = yf.download(ticker, period=f"{years}y", auto_adjust=True, progress=False)
    if df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    out = df[["Close"]].reset_index()
    out.columns = ["date", "close"]
    out["date"] = pd.to_datetime(out["date"])
    return out.sort_values("date").reset_index(drop=True)


@tool
def screen_stocks(threshold_pct: float = 10.0, years: int = 5, min_reliability: float = 0.0,
                  tickers: Optional[List[str]] = None) -> str:
    """
    Screens a universe of stocks for those that STABLY and PERIODICALLY oscillate
    +/- threshold_pct up and down over the lookback window.

    Ranks candidates by an oscillation `reliability` score in [0, 1] (1 = best),
    a composite of: regularity (even spacing), amplitude_consistency (swings land
    near +/-N%), drift_score (price is stable, not trending away), mean_revert,
    and balance (symmetric up/down). Names with too few events, only one
    direction, or poor window coverage are gated to reliability 0.

    Use this FIRST to find candidates. Returns tickers sorted by reliability,
    each with its full sub-score breakdown.
    """
    target_tickers = tickers if tickers else DEFAULT_UNIVERSE
    results = []

    for ticker in target_tickers:
        try:
            prices = load_prices(ticker, years=years)
            if prices is None or len(prices) < 50:
                continue
            rel = compute_reliability(prices, threshold_pct=threshold_pct)
            if rel["reliability"] >= min_reliability:
                results.append({"ticker": ticker, **rel})
        except Exception:
            pass

    results = sorted(results, key=lambda x: x["reliability"], reverse=True)
    return json.dumps(results)

@tool
def backtest_strategy(ticker: str, threshold_pct: float, sma_length: int) -> str:
    """
    Runs a backtest for a specific ticker to validate if trading the +/- threshold_pct bounds is profitable.
    Returns the profitability metrics like Return [%], Win Rate [%], Trades, and Max Drawdown [%].
    """
    try:
        df = yf.download(ticker, period="5y", progress=False)
        if df.empty:
            return json.dumps({"error": f"No data found for {ticker}"})
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
            
        stats = run_backtest(df, sma_length=sma_length, threshold_pct=threshold_pct)
        return json.dumps(stats)
    except Exception as e:
        return json.dumps({"error": str(e)})

def run_agent(query: str):
    # Initialize the LLM
    # Assumes ANTHROPIC_API_KEY is available in the environment.
    # Model is overridable via env var to keep the core vendor/model-agnostic.
    model = os.environ.get("RESEARCH_AGENT_MODEL", "claude-sonnet-4-6")
    llm = ChatAnthropic(model=model, temperature=0)
    
    tools = [screen_stocks, backtest_strategy]
    
    system_prompt = (
        "You are an Autonomous Quantitative Research agent for stock analysis. "
        "Your goal is to find stocks that STABLY and PERIODICALLY oscillate +/-N% up and down over many years. "
        "Workflow: "
        "1. Use screen_stocks to rank candidates by their oscillation `reliability` score (0-1), "
        "which already accounts for regularity, amplitude consistency, low drift, and up/down balance. "
        "Trust this score for ranking 'stability' and 'reliability' -- a high raw event count alone does NOT mean reliable. "
        "2. Use backtest_strategy on the top candidates to check tradeability. "
        "3. Treat a backtest with a ~-100% return or near-total drawdown as RUIN: such a stock is NOT reliable, "
        "so exclude it or clearly flag it rather than presenting it as a top pick. "
        "Finally, present a ranked list of the most reliable oscillators with their reliability sub-scores and backtest results. "
        "Do not ask for follow-ups, just execute the analysis and present the final results."
    )
    
    # NOTE: langgraph_prebuilt >=1.0 renamed `state_modifier` to `prompt`.
    agent_executor = create_react_agent(llm, tools, prompt=system_prompt)
    
    # LangGraph's invoke expects a messages array
    response = agent_executor.invoke({"messages": [("user", query)]})
    
    # Extract the final message content from the response
    output = response["messages"][-1].content
    
    # Save the output to JSON for the frontend
    output_dir = os.path.join(os.path.dirname(__file__), "sma", "data")
    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, "research_report.json")
    
    report_data = {
        "query": query,
        "generated_at": pd.Timestamp.now(tz='UTC').isoformat(),
        "analysis": output
    }
    
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2)
        
    return output

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
    else:
        query = "Find me 2 stocks that reliably bounce 10% off their 200-day SMA over the last 5 years."
    
    print(f"Running query: {query}")
    try:
        output = run_agent(query)
        print("\n=== AGENT RESPONSE ===\n")
        print(output)
    except Exception as e:
        print(f"Agent failed: {e}")
