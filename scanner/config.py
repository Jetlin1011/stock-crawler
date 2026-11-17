"""All tunable settings in one place."""

# How long a swing trade is given to work (trading days after entry)
HORIZON_DAYS = 7

# Target / stop distance, in multiples of the stock's ATR(14) (its normal daily range).
# 1.5 : 1.0 means a win pays 1.5x what a loss costs, so the break-even hit rate is 40%.
TARGET_ATR = 1.5
STOP_ATR = 1.0

# Years of daily history used for backtesting each setup
HISTORY_YEARS = 4

# Skip illiquid stocks: minimum average daily traded value (in ₹ crore)
MIN_TURNOVER_CR = 5

# How many ideas to show / track each day
TOP_BUY = 30
TOP_EXIT = 15

# How many of the top buy ideas get the Telegram message
TOP_ALERT = 10

# Bayesian shrinkage: how many "virtual" market-wide cases a stock's own history is blended with
SHRINK_K = 20

# Minimum past cases before a setup's hit rate is trusted for a given market regime
MIN_REGIME_CASES = 40

# News
NEWS_FOR_TOP = 45          # fetch headlines for this many top candidates
NEWS_LOOKBACK_DAYS = 7
NEWS_RISK_PENALTY = 0.10   # ranking penalty (not shown as probability) when red-flag news is found

# On the very first run, replay this many past trading days so the track record isn't empty
BACKFILL_DAYS = 60

# Days of candles to send to the dashboard chart
CHART_BARS = 180
