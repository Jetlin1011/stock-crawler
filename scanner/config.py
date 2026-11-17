"""All tunable settings in one place.

Model v2 ("momentum leader dip"), chosen by testing on real NSE data 2021-2026:
buy a short, sharp dip in a stock that is among the strongest 20% over 6-12 months,
only while Nifty is in an uptrend; sell at the first close above the 5-day average (max 10 days).
"""

MODEL_VERSION = 2

# Rule parameters
LEADER_PCT = 0.80          # momentum percentile rank (0-1) to count as a "leader"
DIP_RSI2 = 5               # 2-day RSI below this = sharp short dip
WATCH_RSI2 = 20            # leaders with RSI2 below this (but not a setup) go on the watch list
MAX_VOL_MULT = 1.5         # skip dips on volume above 1.5x the 20-day average (panic / news selling)
MAX_HOLD = 10              # trading days
EXIT_SMA = 5               # exit at first close above this moving average

# Costs: Zerodha delivery round trip ~0.25% (STT both sides, stamp, exchange, DP) + ~0.1% slippage
COST_ROUNDTRIP = 0.0035

# History used for testing each day
HISTORY_YEARS = 6
TEST_SPLIT = "2024-07-01"  # results before = tuning period, after = unseen check period

# Liquidity: minimum average daily traded value (₹ crore)
MIN_TURNOVER_CR = 5

# Bayesian shrinkage: a stock's own record is blended with this many market-wide cases
SHRINK_K = 20

# Lists
TOP_LEADERS = 40
TOP_ALERT = 8

# News
NEWS_LOOKBACK_DAYS = 7
NEWS_MAX_STOCKS = 40

# Track record replay on first run of a model version (trading days)
BACKFILL_DAYS = 250

# Charts
CHART_BARS = 160
SPARK_BARS = 60
MARKET_BARS = 260
