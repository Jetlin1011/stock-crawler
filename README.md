# Stock Crawler — NSE "temporary dip" watcher

Every weekday evening (6 PM IST) this:

1. Downloads daily prices for the **Nifty 500 + your watchlist** (free, via Yahoo Finance).
2. Looks for **dip patterns in healthy stocks** (pullback in an uptrend, sharp 2–3 day selloff, gap-down bought back,
   heavy-volume flush) and **exit warnings** (breakdown on volume, overextended rally).
3. Gives each idea a **probability**: how often that same pattern hit its target before its stop within 7 trading days,
   replayed over the last 4 years on every stock, split by market regime and blended with that stock's own record.
4. Checks **Google News headlines** for the top ideas and flags real bad news (fraud, raids, downgrades, results misses…).
5. Sends you a **phone notification** (app push and/or Telegram) and updates the **Stock Crawler app**: an installable
   PWA for iPhone and Android with charts, levels, news and a **track record** showing whether past ideas actually worked.

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
1. Read the alert / dashboard in the evening.
2. Next morning, if the stock opens near the signal close (not a big gap up), buy in **CNC (delivery)**.
3. Immediately place a **GTT OCO**: target and stop recalculated from your actual fill
   (target ≈ fill + 1.5 × ATR, stop ≈ fill − 1 × ATR; ATR is shown on each idea).
4. If neither hits in 7 trading days, exit anyway.
5. Size each trade so hitting the stop loses only 1–2% of your trading capital.

Read the **Track record** tab regularly. The "Live" number (ideas made after launch, not replayed) is the real test.
If after ~2 months the live hit rate is under the 40% break-even, don't trade it.

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
