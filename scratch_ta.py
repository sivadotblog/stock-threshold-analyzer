import yfinance as yf
import pandas as pd
import pandas_ta as ta

df = yf.download("TQQQ", period="5y")
# Flatten multi-index columns if yfinance returns them
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)

df.ta.sma(length=200, append=True)
df.ta.bbands(length=200, std=2.0, append=True)
df.ta.stdev(length=200, append=True)

print(df.tail())
