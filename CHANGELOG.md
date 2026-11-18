# Changelog

What changed in each version of Stock Crawler, in plain language. Newest first.

**Version numbers** use the form `MAJOR.MINOR.PATCH`:

- **MAJOR** (2.0.0): the trading rule changed, so picks and the track record are different.
- **MINOR** (2.2.0): new screens or features. The rule is unchanged.
- **PATCH** (2.2.1): fixes and small improvements. Nothing new to learn.

Each version has a matching tag on GitHub (`v2.2.1`, etc.), so you can see exactly what the code looked like.
Commits named `Scan …` are the automatic daily data updates, not code changes.

---

## 2.2.1 — 18 Nov 2026
**Readable versions**
- Added this changelog and version tags on GitHub.
- The app shows its version number at the bottom of the More tab, with a link to this page.

## 2.2.0 — 18 Nov 2026
**Accuracy tab: prediction vs what happened**
- The Record tab is now called **Accuracy**. At the top, each day's buy picks sit next to the real prices that followed:
  next day's open and close, and the final result.
- Each pick gets a verdict: **Right** (finished with a profit after costs), **Wrong** (finished with a loss),
  **In progress** or **Waiting**.
- Summary of the last 30 finished picks, a day-by-day bar chart, and an "Only live picks" switch that hides
  replayed (simulated) picks.
- The Today tab went back to the 2.0 layout, which the owner preferred over 2.1.

## 2.1.1 — 18 Nov 2026
**Data fixes**
- A scan run during market hours no longer uses today's half-finished prices. Before 6 PM IST, today's bar is ignored.
- When Yahoo is missing a recent day for some stocks, that day is now filled from NSE's official end-of-day file
  for those stocks too, not only when every stock is missing it.
- Picks dated after the latest price day are removed from the track record.
- A stock you're already holding no longer also shows as a new buy, in the app or in alerts.

## 2.1.0 — 18 Nov 2026 (Today layout replaced in 2.2.0)
- Tried a checklist layout for the Today tab: sell, buy, holding and watch cards with step-by-step plans.
  Replaced in 2.2.0 by the earlier layout at the owner's request.

## 2.0.0 — 17 Nov 2026
**New trading rule ("momentum leader dip") and redesigned app**
- The old rule bought dips in any stock and lost money after costs in the 2024–26 test, so it was replaced.
- The new rule only buys a sharp, quiet 2–3 day dip in one of the strongest 20% of stocks over 6–12 months,
  and only while Nifty is above its 200-day average. Sell at the first close above the 5-day average, or after
  10 trading days at the latest.
- Tested on 6 years of real NSE prices: tuned on data before July 2024, then checked on the period after it.
  1,423 trades, 64% made money, average +0.57% after about 0.35% costs per trade (+0.25% in the unseen period).
- Prices: Yahoo Finance, with missing days filled from NSE's official end-of-day file (which also gives delivery %).
- Redesigned app: market briefing, buy list, watch list, watchlist health, momentum leaders map, sector heatmap,
  Nifty and market-breadth charts, track record. Self-hosted fonts, works offline.
- Scans run at 6:45 PM IST on weekdays, and can be started early by changing `.github/run-now.txt`.

## 1.1.0 — 17 Nov 2026
**Tools**
- "Test notification" workflow to check that phone notifications arrive.
- "Export research data" workflow: saves 6 years of prices to the `research-data` branch for offline testing.

## 1.0.0 — 17 Nov 2026
**First version**
- Daily scan of the Nifty 500 for dip patterns, each with a probability from a 4-year backtest.
- News headline check, Telegram alerts, and an installable app (PWA) with charts, track record, offline mode
  and push notifications.
