"""Synthetic market for offline testing (python -m scanner.run --demo). Prices are FAKE."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

NAMES = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "SBIN", "BHARTIARTL", "ITC", "LT", "AXISBANK",
         "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA", "TITAN", "ASIANPAINT", "WIPRO",
         "HCLTECH", "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC", "TATASTEEL", "JSWSTEEL", "ADANIPORTS",
         "COALINDIA", "M&M", "NESTLEIND", "TECHM", "DRREDDY", "CIPLA", "GRASIM", "HINDALCO", "EICHERMOT",
         "BRITANNIA", "DIVISLAB", "APOLLOHOSP", "HEROMOTOCO", "BAJAJ-AUTO", "TATACONSUM", "SBILIFE",
         "HDFCLIFE", "BPCL", "INDUSINDBK", "DABUR", "PIDILITIND", "HAVELLS", "SIEMENS", "DLF", "GODREJCP",
         "TRENT", "LUPIN", "BEL", "HAL", "IRCTC", "PNB", "BANKBARODA", "CANBK", "TVSMOTOR", "VOLTAS",
         "AUROPHARMA", "BIOCON", "MUTHOOTFIN", "PAGEIND", "COLPAL", "MARICO", "BERGEPAINT", "AMBUJACEM",
         "ACC", "SHREECEM", "INDIGO", "ZYDUSLIFE", "TORNTPHARM", "MPHASIS", "PERSISTENT", "COFORGE",
         "LTIM", "POLYCAB", "DIXON", "CUMMINSIND", "ABB", "BHEL", "GAIL", "IOC", "TATAPOWER", "ADANIENT",
         "JINDALSTEL", "SAIL", "NMDC", "VEDL", "ASHOKLEY", "ESCORTS", "MRF", "BALKRISIND", "APOLLOTYRE",
         "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "CHOLAFIN"]


def make():
    rng = np.random.default_rng(7)
    days = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=252 * C.HISTORY_YEARS)
    n = len(days)
    market = np.cumsum(rng.normal(0.0004, 0.009, n))
    raw = {}
    for i, sym in enumerate(NAMES):
        drift = rng.uniform(-0.0002, 0.0011)
        vol = rng.uniform(0.012, 0.024)
        beta = rng.uniform(0.6, 1.3)
        eps = rng.normal(drift, vol, n)
        # occasional temporary shocks that partly mean-revert
        shocks = rng.random(n) < 0.012
        eps[shocks] -= rng.uniform(0.03, 0.08, shocks.sum())
        for j in np.flatnonzero(shocks):
            k = min(n, j + 6)
            eps[j + 1:k] += rng.uniform(0.002, 0.009)
        logp = np.log(rng.uniform(150, 4000)) + np.cumsum(eps) + beta * market
        close = np.exp(logp)
        prev = np.r_[close[0], close[:-1]]
        gap = rng.normal(0, vol * 0.4, n)
        gap[shocks] = (close[shocks] / prev[shocks] - 1) * rng.uniform(0.5, 1.1, shocks.sum())
        open_ = prev * (1 + gap)
        hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol * 0.5, n)))
        lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol * 0.5, n)))
        volu = rng.lognormal(13.5, 0.4, n) * (1 + 2 * shocks)
        raw[sym] = pd.DataFrame({"Open": open_, "High": hi, "Low": lo, "Close": close, "Volume": volu},
                                index=days)
    idx_close = np.exp(np.log(22000) + market)
    index_df = pd.DataFrame({"Open": idx_close, "High": idx_close, "Low": idx_close, "Close": idx_close,
                             "Volume": 0}, index=days)
    universe = {s: {"name": s.title() + " Ltd (demo)", "industry": "Demo"} for s in NAMES}
    watch = {"RELIANCE", "TCS", "INFY", "HDFCBANK", "ITC"}
    return universe, watch, raw, index_df
