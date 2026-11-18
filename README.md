# Stock Crawler — NSE "temporary dip" watcher

Every weekday evening (about 6:45 PM IST) this:

1. Downloads daily prices for the **Nifty 500 + your watchlist** from Yahoo Finance, and fills in any day Yahoo is
   late with **NSE's official end-of-day file** (which also gives delivery %).
2. Ranks every stock by **momentum** (6- and 12-month return divided by volatility, the way NSE's momentum indices do)
   and builds the **leaders list**: the top 20%, above their 200-day average and liquid.
3. Finds **leader dips**: a leader whose 2-day RSI drops below 5 on normal volume while Nifty is above its 200-day
   average. Plan: buy at the next open, sell at the first close above the 5-day average (max 10 trading days).
   This rule was chosen by testing on 6 years of real NSE prices: it was tuned on data before July 2024 and stayed
   profitable after ~0.35% costs on the unseen period after it. Older "any dip" rules lost money there.
4. Builds the app: market mood and breadth, buy list, watch list, your watchlist's trend health, momentum leaders map,
   sector heatmap, Nifty and breadth charts, and a track record of every pick.
5. Checks Google News headlines for the shortlisted stocks, then sends a **push notification** (and Telegram if set up).

It never places orders. You trade manually in Zerodha Kite.

Cost: **₹0**. GitHub Actions + GitHub Pages + web push / Telegram are free for a public repo.

---

## Setup (about 15 minutes, one time)

### 1. Put the code on GitHub
1. Create a new **public** repository on github.com (e.g. `stock-crawler`). Private works for the scanner, but free
   GitHub Pages needs public (or use Cloudflare Pages, see below).
2. Upload everything in this folder, including the hidden `.github` folder:
   ```bash
   cd stock-crawler
   git init && git add . && git commit -m "Stock Crawler"
   git branch -M main
   git remote add origin https://github.com/<you>/stock-crawler.git
   git push -u origin main
   ```

### 2. Turn on the dashboard (GitHub Pages)
Repo → **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main`, folder: **`/docs`** → Save.
Your dashboard will be at `https://<you>.github.io/stock-crawler/`.

### 3. (Optional) Telegram bot
Skip this if the app's own push notifications (step 7) are enough for you.
1. In Telegram, open **@BotFather** → `/newbot` → pick a name → copy the **token**.
2. Open your new bot and send it any message (e.g. "hi").
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and copy the number at `"chat":{"id": …}`.

### 4. Add the secrets
Repo → **Settings → Secrets and variables → Actions**:
- **Secrets** tab → New secret: `TELEGRAM_BOT_TOKEN` = the token, `TELEGRAM_CHAT_ID` = the chat id.
- **Variables** tab → New variable: `DASHBOARD_URL` = your Pages URL from step 2.
  Optional: `UNIVERSE` = `watchlist` to scan only your list instead of the Nifty 500.

### 5. First run
Repo → **Actions** → enable workflows if asked → **Daily scan** → **Run workflow**.
It takes ~5–10 minutes. The first run also replays the last 60 trading days so the track record isn't empty
(those rows are marked "replay"). After that it runs by itself every weekday at 6 PM IST.

### 6. Install the app on your phone
- **iPhone:** open your Pages URL in **Safari** → **Share** → **Add to Home Screen**. Open it from the new icon.
- **Android:** open it in Chrome → ⋮ → **Install app**.

The app refreshes by itself when you open it or switch back to it (and every 15 minutes while it's open), works
offline with the last scan, and has a ⟳ button.

### 7. Push notifications from the app (iOS 16.4+ and Android)
1. On your computer: `pip install cryptography` then `python -m scanner.vapid`. It prints two keys.
2. GitHub → Settings → Secrets and variables → Actions:
   - **Secret** `VAPID_PRIVATE_KEY` = the private key
   - **Variable** `VAPID_PUBLIC_KEY` = the public key
   - (optional) **Variable** `VAPID_SUBJECT` = `mailto:your@email.com`
3. Run the workflow once (Actions → Daily scan → Run workflow) so the app learns the public key.
4. Open the **installed** app → **App & alerts** tab → **Turn on notifications** → Allow → **Copy code**.
5. Add **Secret** `PUSH_SUBSCRIPTIONS` and paste the code. For a second phone, paste its code on a new line in the
   same secret.

From then on each evening's scan sends a notification such as
*"3 dip ideas above break-even: TCS 62%, LT 58%, … · ⚠ exit watch: INFY"*. Tapping it opens the app.

### 8. Your watchlist
Edit `watchlist.txt` on GitHub (pencil icon). Put stocks you're interested in **and stocks you hold**:
holdings get exit warnings listed first, marked ★.

---

## How to use the signals in Kite
1. Read the notification / Today tab in the evening.
2. Next morning, buy each setup in **CNC (delivery)** near the open. Skip it if it opens more than 2% above the signal close.
3. Each evening, check the stock's page: once it has closed above its 5-day average, sell the next morning.
   Sell anyway after 10 trading days.
4. Use the same amount on every trade, and keep any one stock to 5–10% of your trading money.

Read the **Record** tab regularly. The "Live since launch" number is the real test. If after a few months live
results are negative after costs, stop trading it.

## Research data
The **Export research data** workflow saves 6 years of prices to the `research-data` branch. Run the scanner offline on it:
`python -m scanner.run --csv prices.csv.gz` (needs `universe.csv` next to it).

## Updating the app later
If you change files in `docs/`, bump `VERSION` at the top of `docs/sw.js` (e.g. `sc-v2`) so phones pick up the new
version. They update on the next open after that.

## Tuning
All settings are in `scanner/config.py`: holding days, target/stop multiples, liquidity filter, how many ideas to show,
news penalty. Pattern rules are in `scanner/engine.py` → `add_signals`.

## Run on your own computer (optional)
```bash
pip install -r requirements.txt
python -m scanner.run --no-notify          # real data
python -m scanner.run --demo --no-notify   # fake data, no internet needed
cd docs && python -m http.server 8000      # open http://localhost:8000
```

## Private repo instead?
Actions stays free (2,000 min/month; this uses ~200). For the dashboard, connect the repo to
**Cloudflare Pages** (free) with build output directory `docs`, or keep alerts only.

## Limits, honestly
- Yahoo data is end-of-day and occasionally late or missing a stock. This is a swing tool, not intraday.
- Probabilities come from past behaviour. They're not guarantees, and in a falling market dip-buying works less often
  (the regime pill at the top tells you which market you're in).
- News tagging is keyword-based. Always open the headlines yourself.
- Not investment advice.

## Versions

Every release has a version number, a plain-language entry in [CHANGELOG.md](CHANGELOG.md) and a tag on GitHub.
Numbers use `MAJOR.MINOR.PATCH`: MAJOR when the trading rule changes, MINOR for new screens or features,
PATCH for fixes. The running version is shown at the bottom of the app's More tab.

To release a change:
1. Bump `APP_VERSION` in `scanner/config.py` and `VERSION` in `docs/sw.js` (so phones load the new app).
2. Add an entry at the top of `CHANGELOG.md`: what changed and why, in plain words.
3. Commit with a message like `v2.3.0: <short summary>`. Then add a line `v2.3.0|<commit>|<short title>` to
   `.github/releases.txt` and push: the "Tag releases" workflow creates the tag and a Releases page entry whose
   notes come from the CHANGELOG.
4. If the trading rule changes, also bump `MODEL_VERSION` (this rebuilds the track record) and the MAJOR number.
