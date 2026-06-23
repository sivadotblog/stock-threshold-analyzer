import pandas as pd
from backtesting import Backtest, Strategy
from strategy import add_indicators

class MeanReversionOscillation(Strategy):
    """
    Backtesting strategy for trading the +/- N% bounds around the SMA.
    """
    sma_length = 200
    threshold_pct = 10.0
    
    def init(self):
        # We assume indicators are pre-calculated and present in self.data
        pass
        
    def next(self):
        # Skip if SMA is not yet available
        sma_col = f"SMA_{self.sma_length}"
        try:
            sma = self.data[sma_col][-1]
        except KeyError:
            return
            
        if pd.isna(sma):
            return

        close = self.data.Close[-1]
        
        # Calculate thresholds dynamically
        upper_threshold = sma * (1 + (self.threshold_pct / 100.0))
        lower_threshold = sma * (1 - (self.threshold_pct / 100.0))
        
        # Mean reversion logic
        if not self.position:
            # If price drops below the lower threshold, we expect it to bounce back up to the SMA.
            if close <= lower_threshold:
                self.buy()
            # Alternatively, if price rises above upper threshold, short it to bounce down
            elif close >= upper_threshold:
                self.sell()
        else:
            # We are in a position. Close it if we hit the SMA.
            if self.position.is_long and close >= sma:
                self.position.close()
            elif self.position.is_short and close <= sma:
                self.position.close()

def run_backtest(df: pd.DataFrame, sma_length: int = 200, threshold_pct: float = 10.0) -> dict:
    """
    Runs the mean reversion strategy backtest on the given DataFrame.
    """
    # Pre-calculate indicators
    df_with_inds = add_indicators(df, sma_length=sma_length)
    
    # Drop rows without SMA
    sma_col = f"SMA_{sma_length}"
    if sma_col not in df_with_inds.columns:
         return {"Return [%]": 0.0, "Win Rate [%]": 0.0, "Trades": 0}
         
    df_clean = df_with_inds.dropna(subset=[sma_col])
    if df_clean.empty:
        return {"Return [%]": 0.0, "Win Rate [%]": 0.0, "Trades": 0}
        
    # Backtest expects columns: Open, High, Low, Close, Volume
    bt = Backtest(df_clean, MeanReversionOscillation, cash=10000, commission=.002, exclusive_orders=True)
    
    # Override strategy parameters
    stats = bt.run(sma_length=sma_length, threshold_pct=threshold_pct)
    
    return {
        "Return [%]": round(stats.get("Return [%]", 0.0), 2),
        "Win Rate [%]": round(stats.get("Win Rate [%]", 0.0), 2),
        "Trades": int(stats.get("# Trades", 0)),
        "Max Drawdown [%]": round(stats.get("Max. Drawdown [%]", 0.0), 2)
    }
