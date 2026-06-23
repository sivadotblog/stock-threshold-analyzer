import yfinance as yf
import pandas as pd
from strategy import add_indicators, count_oscillation_bounces
from backtest import run_backtest

def test_engine():
    print("Fetching SPY data...")
    df = yf.download("SPY", period="5y")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
        
    print("Testing indicators...")
    df_inds = add_indicators(df, sma_length=200)
    assert "SMA_200" in df_inds.columns
    assert "STDEV_200" in df_inds.columns
    assert "Z_SCORE" in df_inds.columns
    
    print("Testing bounce counter...")
    bounces = count_oscillation_bounces(df_inds, threshold_pct=10.0, sma_length=200)
    assert "total_bounces" in bounces
    
    print("Testing backtest engine...")
    stats = run_backtest(df, sma_length=200, threshold_pct=10.0)
    assert "Return [%]" in stats
    assert "Trades" in stats
    
    print("All engine tests passed!")
    print(f"Bounces: {bounces}")
    print(f"Stats: {stats}")

if __name__ == "__main__":
    test_engine()
