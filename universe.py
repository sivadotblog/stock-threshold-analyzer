"""
Screening universe for the bullish-oscillator search (`screen_bullish.py`).

A *static* list keeps the screen deterministic and reviewable and avoids a runtime
index-scrape dependency. Two parts:

  * ``SP500``      — S&P 500 constituents (large-cap baseline; generated once from
                     Wikipedia, symbols Yahoo-normalized: '.' -> '-').
  * ``SUPPLEMENT`` — liquid MID/SMALL-CAP volatile growth names (ad-tech, SaaS,
                     fintech, EV, crypto-miners, space/defense, meme/consumer).
                     This is where "oscillates like ZETA" actually lives — ZETA
                     itself is NOT in the S&P 500, so the baseline alone misses
                     the target class.

``UNIVERSE`` is the de-duplicated union. To refresh SP500, re-run the one-off
``pd.read_html`` of the Wikipedia list (needs a browser User-Agent + lxml) and
paste the result below.
"""

from __future__ import annotations

SP500: list[str] = [
    'A', 'AAPL', 'ABBV', 'ABNB', 'ABT', 'ACGL', 'ACN', 'ADBE', 'ADI', 'ADM',
    'ADP', 'ADSK', 'AEE', 'AEP', 'AES', 'AFL', 'AIG', 'AIZ', 'AJG', 'AKAM',
    'ALB', 'ALGN', 'ALL', 'ALLE', 'AMAT', 'AMCR', 'AMD', 'AME', 'AMGN', 'AMP',
    'AMT', 'AMZN', 'ANET', 'AON', 'AOS', 'APA', 'APD', 'APH', 'APO', 'APP',
    'APTV', 'ARE', 'ARES', 'ATO', 'AVB', 'AVGO', 'AVY', 'AWK', 'AXON', 'AXP',
    'AZO', 'BA', 'BAC', 'BALL', 'BAX', 'BBY', 'BDX', 'BEN', 'BF-B', 'BG',
    'BIIB', 'BKNG', 'BKR', 'BLDR', 'BLK', 'BMY', 'BNY', 'BR', 'BRK-B', 'BRO',
    'BSX', 'BX', 'BXP', 'C', 'CAG', 'CAH', 'CARR', 'CASY', 'CAT', 'CB',
    'CBOE', 'CBRE', 'CCI', 'CCL', 'CDNS', 'CDW', 'CEG', 'CF', 'CFG', 'CHD',
    'CHRW', 'CHTR', 'CI', 'CIEN', 'CINF', 'CL', 'CLX', 'CMCSA', 'CME', 'CMG',
    'CMI', 'CMS', 'CNC', 'CNP', 'COF', 'COHR', 'COIN', 'COO', 'COP', 'COR',
    'COST', 'CPAY', 'CPRT', 'CPT', 'CRH', 'CRL', 'CRM', 'CRWD', 'CSCO', 'CSGP',
    'CSX', 'CTAS', 'CTSH', 'CTVA', 'CVNA', 'CVS', 'CVX', 'D', 'DAL', 'DASH',
    'DD', 'DDOG', 'DE', 'DECK', 'DELL', 'DG', 'DGX', 'DHI', 'DHR', 'DIS',
    'DLR', 'DLTR', 'DOC', 'DOV', 'DOW', 'DPZ', 'DRI', 'DTE', 'DUK', 'DVA',
    'DVN', 'DXCM', 'EA', 'EBAY', 'ECL', 'ED', 'EFX', 'EG', 'EIX', 'EL',
    'ELV', 'EME', 'EMR', 'EOG', 'EQIX', 'EQR', 'EQT', 'ERIE', 'ES', 'ESS',
    'ETN', 'ETR', 'EVRG', 'EW', 'EXC', 'EXE', 'EXPD', 'EXPE', 'EXR', 'F',
    'FANG', 'FAST', 'FCX', 'FDS', 'FDX', 'FE', 'FFIV', 'FICO', 'FIS', 'FITB',
    'FIX', 'FLEX', 'FOX', 'FOXA', 'FRT', 'FSLR', 'FTNT', 'FTV', 'GD', 'GDDY',
    'GE', 'GEHC', 'GEN', 'GEV', 'GILD', 'GIS', 'GL', 'GLW', 'GM', 'GNRC',
    'GOOG', 'GOOGL', 'GPC', 'GPN', 'GRMN', 'GS', 'GWW', 'HAL', 'HAS', 'HBAN',
    'HCA', 'HD', 'HIG', 'HII', 'HLT', 'HON', 'HOOD', 'HPE', 'HPQ', 'HRL',
    'HSIC', 'HST', 'HSY', 'HUBB', 'HUM', 'HWM', 'IBKR', 'IBM', 'ICE', 'IDXX',
    'IEX', 'IFF', 'INCY', 'INTC', 'INTU', 'INVH', 'IP', 'IQV', 'IR', 'IRM',
    'ISRG', 'IT', 'ITW', 'IVZ', 'J', 'JBHT', 'JBL', 'JCI', 'JKHY', 'JNJ',
    'JPM', 'KDP', 'KEY', 'KEYS', 'KHC', 'KIM', 'KKR', 'KLAC', 'KMB', 'KMI',
    'KO', 'KR', 'KVUE', 'L', 'LDOS', 'LEN', 'LH', 'LHX', 'LII', 'LIN',
    'LITE', 'LLY', 'LMT', 'LNT', 'LOW', 'LRCX', 'LULU', 'LUV', 'LVS', 'LYB',
    'LYV', 'MA', 'MAA', 'MAR', 'MAS', 'MCD', 'MCHP', 'MCK', 'MCO', 'MDLZ',
    'MDT', 'MET', 'META', 'MGM', 'MKC', 'MLM', 'MMM', 'MNST', 'MO', 'MOS',
    'MPC', 'MPWR', 'MRK', 'MRNA', 'MRVL', 'MS', 'MSCI', 'MSFT', 'MSI', 'MTB',
    'MTD', 'MU', 'NCLH', 'NDAQ', 'NDSN', 'NEE', 'NEM', 'NFLX', 'NI', 'NKE',
    'NOC', 'NOW', 'NRG', 'NSC', 'NTAP', 'NTRS', 'NUE', 'NVDA', 'NVR', 'NWS',
    'NWSA', 'NXPI', 'O', 'ODFL', 'OKE', 'OMC', 'ON', 'ORCL', 'ORLY', 'OTIS',
    'OXY', 'PANW', 'PAYX', 'PCAR', 'PCG', 'PEG', 'PEP', 'PFE', 'PFG', 'PG',
    'PGR', 'PH', 'PHM', 'PKG', 'PLD', 'PLTR', 'PM', 'PNC', 'PNR', 'PNW',
    'PODD', 'PPG', 'PPL', 'PRU', 'PSA', 'PSX', 'PTC', 'PWR', 'PYPL', 'QCOM',
    'RCL', 'REG', 'REGN', 'RF', 'RJF', 'RL', 'RMD', 'ROK', 'ROL', 'ROP',
    'ROST', 'RSG', 'RTX', 'RVTY', 'SBAC', 'SBUX', 'SCHW', 'SHW', 'SJM', 'SLB',
    'SMCI', 'SNA', 'SNPS', 'SO', 'SOLV', 'SPG', 'SPGI', 'SRE', 'STE', 'STLD',
    'STT', 'STX', 'STZ', 'SWK', 'SWKS', 'SYF', 'SYK', 'SYY', 'T', 'TAP',
    'TDG', 'TDY', 'TECH', 'TEL', 'TER', 'TFC', 'TGT', 'TJX', 'TKO', 'TMO',
    'TMUS', 'TPL', 'TPR', 'TRGP', 'TRMB', 'TROW', 'TRV', 'TSCO', 'TSLA', 'TSN',
    'TT', 'TTD', 'TTWO', 'TXN', 'TXT', 'TYL', 'UAL', 'UBER', 'UDR', 'UHS',
    'ULTA', 'UNH', 'UNP', 'UPS', 'URI', 'USB', 'V', 'VEEV', 'VICI', 'VLO',
    'VLTO', 'VMC', 'VRSK', 'VRSN', 'VRT', 'VRTX', 'VST', 'VTR', 'VTRS', 'VZ',
    'WAB', 'WAT', 'WBD', 'WDAY', 'WDC', 'WEC', 'WELL', 'WFC', 'WM', 'WMB',
    'WMT', 'WRB', 'WSM', 'WST', 'WTW', 'WY', 'WYNN', 'XEL', 'XOM', 'XYL',
    'XYZ', 'YUM', 'ZBH', 'ZBRA', 'ZTS',
]

# Liquid mid/small-cap volatile growth — the ZETA-like cohort. Hand-curated;
# many post-2020 IPOs that swing hard and trend in big multi-month arcs.
SUPPLEMENT: list[str] = [
    # ad-tech / martech / digital advertising (ZETA's actual neighbors)
    'ZETA', 'KVYO', 'MGNI', 'BRZE', 'DV', 'AMPL', 'PUBM', 'CRTO', 'PERI',
    'APPS', 'ZD', 'CART', 'YELP', 'TRUE',
    # application / infra / security SaaS
    'PATH', 'GTLB', 'S', 'DOCN', 'FROG', 'ESTC', 'BL', 'PCTY', 'ASAN',
    'MNDY', 'BIGC', 'FSLY', 'NET', 'CFLT', 'AI', 'BBAI', 'SOUN', 'PEGA',
    'PD', 'BOX', 'SMAR', 'GWRE', 'SPT', 'SEMR', 'DOCS', 'AMPX',
    # consumer internet / platforms
    'SNAP', 'PINS', 'RDDT', 'SPOT', 'ROKU', 'RBLX', 'U', 'DKNG', 'CHWY',
    'ETSY', 'W', 'WIX', 'SHOP', 'GRAB', 'SE', 'BMBL', 'LYFT',
    # fintech / crypto-adjacent
    'SOFI', 'AFRM', 'UPST', 'LC', 'BILL', 'TOST', 'NU', 'MARA', 'RIOT',
    'CLSK', 'BTBT', 'HUT', 'CIFR', 'MSTR', 'BTDR',
    # EV / clean energy (high-beta)
    'RIVN', 'LCID', 'CHPT', 'RUN', 'PLUG', 'FCEL', 'QS', 'NIO', 'XPEV',
    'LI', 'BLNK', 'ENPH', 'SEDG', 'FLNC',
    # space / defense / frontier
    'RKLB', 'ASTS', 'ACHR', 'JOBY', 'LUNR', 'PL', 'RDW',
    # biotech / genomics (volatile)
    'CRSP', 'NTLA', 'BEAM', 'DNA', 'RXRX', 'TWST', 'PACB', 'EXAS',
    # meme / high-volatility consumer
    'GME', 'AMC', 'CVNA', 'CELH', 'PTON', 'WBA', 'HIMS', 'OSCR',
]

# De-duplicated union, sorted for stable iteration order.
UNIVERSE: list[str] = sorted(set(SP500) | set(SUPPLEMENT))


if __name__ == "__main__":
    print(f"SP500:      {len(set(SP500))}")
    print(f"SUPPLEMENT: {len(set(SUPPLEMENT))}")
    print(f"UNIVERSE:   {len(UNIVERSE)} unique tickers")
