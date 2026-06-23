import pandas as pd
import pandas_ta as ta

def add_indicators(df: pd.DataFrame, sma_length: int = 200, bb_std: float = 2.0) -> pd.DataFrame:
    """
    Adds SMA, Bollinger Bands, and Z-Score to the OHLCV dataframe.
    """
    if df.empty or len(df) < sma_length:
        return df

    # We make a copy to avoid SettingWithCopyWarning
    df = df.copy()

    # Calculate SMA
    df.ta.sma(length=sma_length, append=True)
    
    # Calculate Bollinger Bands
    df.ta.bbands(length=sma_length, std=bb_std, append=True)
    
    # Calculate Rolling Standard Deviation
    df.ta.stdev(length=sma_length, append=True)
    
    # Determine the dynamic column names
    sma_col = f"SMA_{sma_length}"
    stdev_col = f"STDEV_{sma_length}"
    
    if sma_col in df.columns and stdev_col in df.columns:
        # Z-score measures how many standard deviations the close is from the SMA
        df["Z_SCORE"] = (df["Close"] - df[sma_col]) / df[stdev_col]
        
    return df

def count_oscillation_bounces(df: pd.DataFrame, threshold_pct: float = 10.0, sma_length: int = 200) -> dict:
    """
    Analyzes how many times the price bounces back to the SMA after diverging by +/- threshold_pct.
    Returns metrics on the oscillation.
    """
    sma_col = f"SMA_{sma_length}"
    
    if sma_col not in df.columns or "Close" not in df.columns:
        return {"total_bounces": 0, "up_bounces": 0, "down_bounces": 0}

    df = df.dropna(subset=[sma_col])
    
    # Identify moments when price deviates by +/- threshold_pct from SMA
    upper_threshold = df[sma_col] * (1 + (threshold_pct / 100.0))
    lower_threshold = df[sma_col] * (1 - (threshold_pct / 100.0))
    
    # Simplified tracking:
    # A "bounce" is counted when the price crosses the threshold and then eventually reverts to touch the SMA.
    state = "NEUTRAL"
    up_bounces = 0
    down_bounces = 0
    
    for _, row in df.iterrows():
        close = row["Close"]
        sma = row[sma_col]
        ut = upper_threshold.loc[_]
        lt = lower_threshold.loc[_]
        
        if state == "NEUTRAL":
            if close >= ut:
                state = "ABOVE_UPPER"
            elif close <= lt:
                state = "BELOW_LOWER"
                
        elif state == "ABOVE_UPPER":
            # Reverted back to SMA
            if close <= sma:
                up_bounces += 1
                state = "NEUTRAL"
                
        elif state == "BELOW_LOWER":
            # Reverted back to SMA
            if close >= sma:
                down_bounces += 1
                state = "NEUTRAL"
                
    return {
        "total_bounces": up_bounces + down_bounces,
        "up_bounces": up_bounces,
        "down_bounces": down_bounces
    }
