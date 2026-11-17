"""Universe (which stocks to scan) and price history download."""
from __future__ import annotations

import csv
import io
import os
import time

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WATCHLIST_FILE = os.path.join(ROOT, "watchlist.txt")
UNIVERSE_CACHE = os.path.join(ROOT, "data", "nifty500_cache.csv")
NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def read_watchlist() -> dict[str, dict]:
    """watchlist.txt: one NSE symbol per line, optional ', Company Name'. # = comment."""
    out = {}
    if not os.path.exists(WATCHLIST_FILE):
        return out
    with open(WATCHLIST_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split(",", 1)]
            sym = parts[0].upper()
            out[sym] = {"name": parts[1] if len(parts) > 1 else sym, "industry": ""}
    return out


def _parse_nifty_csv(text: str) -> dict[str, dict]:
    out = {}
    for row in csv.DictReader(io.StringIO(text)):
        sym = (row.get("Symbol") or "").strip().upper()
        if sym:
            out[sym] = {"name": (row.get("Company Name") or sym).strip(),
                        "industry": (row.get("Industry") or "").strip()}
    return out


def nifty500() -> dict[str, dict]:
    try:
        r = requests.get(NIFTY500_URL, headers=UA, timeout=20)
        r.raise_for_status()
        uni = _parse_nifty_csv(r.text)
        if len(uni) > 400:
            os.makedirs(os.path.dirname(UNIVERSE_CACHE), exist_ok=True)
            with open(UNIVERSE_CACHE, "w", encoding="utf-8") as f:
                f.write(r.text)
            return uni
    except Exception as e:  # NSE sometimes blocks cloud IPs
        print(f"[universe] NSE download failed ({e}); trying cache")
    if os.path.exists(UNIVERSE_CACHE):
        with open(UNIVERSE_CACHE, encoding="utf-8") as f:
            return _parse_nifty_csv(f.read())
    print("[universe] no Nifty 500 list available; using watchlist only")
    return {}


def load_universe(mode: str) -> tuple[dict[str, dict], set[str]]:
    """Returns ({symbol: info}, watchlist_symbols)."""
    wl = read_watchlist()
    uni = {} if mode == "watchlist" else nifty500()
    for s, info in wl.items():
        if s not in uni:
            uni[s] = info
        elif info["name"] != s:
            uni[s]["name"] = info["name"]
    return uni, set(wl)


def _clean(df: pd.DataFrame) -> pd.DataFrame | None:
    cols = ["Open", "High", "Low", "Close", "Volume"]
    if df is None or df.empty or not set(cols).issubset(df.columns):
        return None
    df = df[cols].dropna()
    df = df[(df["Close"] > 0) & (df["High"] >= df["Low"])]
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[~df.index.duplicated(keep="last")]
    return df if len(df) >= 230 else None


def fetch_history(symbols: list[str], years: int, batch: int = 80) -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        tickers = [s + ".NS" for s in chunk]
        for attempt in range(3):
            try:
                raw = yf.download(tickers, period=f"{years}y", interval="1d", group_by="ticker",
                                  auto_adjust=False, threads=True, progress=False)
                break
            except Exception as e:
                print(f"[data] batch {i} attempt {attempt + 1} failed: {e}")
                time.sleep(5)
        else:
            continue
        for s, t in zip(chunk, tickers):
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            df = _clean(df)
            if df is not None:
                out[s] = df
        print(f"[data] {min(i + batch, len(symbols))}/{len(symbols)} requested, {len(out)} usable")
    return out


def fetch_index(years: int) -> pd.DataFrame | None:
    import yfinance as yf
    try:
        raw = yf.download("^NSEI", period=f"{years}y", interval="1d", auto_adjust=False, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        return _clean(raw)
    except Exception as e:
        print(f"[data] Nifty index download failed: {e}")
        return None


# --------------------------------------------------------------------------- NSE official daily files
# Yahoo often posts the newest day late (e.g. still missing at 2 AM IST). NSE publishes its own
# end-of-day file around 6 PM IST; we use it to fill in missing recent days and to get delivery %.

NSE_FULL = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
NSE_INDEX = "https://nsearchives.nseindia.com/content/indices/ind_close_all_{d}.csv"


def _nse_session():
    s = requests.Session()
    s.headers.update({**UA, "Accept": "text/csv,text/plain,*/*", "Referer": "https://www.nseindia.com/"})
    try:
        s.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass
    return s


def _get_csv(s, url):
    try:
        r = s.get(url, timeout=20)
        if r.status_code != 200 or len(r.content) < 60 or b"<html" in r.content[:200].lower():
            return None
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception as e:
        print(f"[nse] {url.rsplit('/', 1)[-1]}: {e}")
        return None


def patch_with_nse(raw: dict, index_df, now_ist) -> dict:
    """Append missing recent days from NSE files; return info incl. delivery % for the latest day."""
    info = {"patched_days": [], "nse_ok": False, "delivery": {}, "delivery_date": None}
    if not raw:
        return info
    last = max(df.index[-1] for df in raw.values())
    end = pd.Timestamp(now_ist.date())
    if now_ist.hour < 18 or (now_ist.hour == 18 and now_ist.minute < 30):
        end -= pd.Timedelta(days=1)
    days = [last] + [d for d in pd.bdate_range(last + pd.Timedelta(days=1), end)]
    s = _nse_session()
    for d in days[-6:]:
        tag = d.strftime("%d%m%Y")
        bhav = _get_csv(s, NSE_FULL.format(d=tag))
        time.sleep(1)
        if bhav is None:
            continue
        info["nse_ok"] = True
        bhav = bhav[bhav["SERIES"].astype(str).str.strip().isin(["EQ", "BE"])]
        bhav["SYMBOL"] = bhav["SYMBOL"].astype(str).str.strip()
        num = lambda c: pd.to_numeric(bhav[c].astype(str).str.strip(), errors="coerce")
        rows = pd.DataFrame({"Open": num("OPEN_PRICE"), "High": num("HIGH_PRICE"), "Low": num("LOW_PRICE"),
                             "Close": num("CLOSE_PRICE"), "Volume": num("TTL_TRD_QNTY"),
                             "deliv": num("DELIV_PER")})
        rows.index = bhav["SYMBOL"].values
        info["delivery"] = {k: float(v) for k, v in rows["deliv"].dropna().items() if k in raw}
        info["delivery_date"] = d.strftime("%Y-%m-%d")
        if d <= last:
            continue
        added = 0
        for sym, df in raw.items():
            if sym in rows.index and d not in df.index:
                r = rows.loc[sym]
                if isinstance(r, pd.DataFrame):
                    r = r.iloc[0]
                if pd.notna(r["Close"]) and r["Close"] > 0:
                    raw[sym] = pd.concat([df, pd.DataFrame([r[["Open", "High", "Low", "Close", "Volume"]].values],
                                                           columns=df.columns, index=[d])])
                    added += 1
        if added:
            info["patched_days"].append(d.strftime("%Y-%m-%d"))
            if index_df is not None and d not in index_df.index:
                ic = _get_csv(s, NSE_INDEX.format(d=tag))
                time.sleep(1)
                if ic is not None:
                    row = ic[ic["Index Name"].astype(str).str.strip().str.lower() == "nifty 50"]
                    if len(row):
                        g = lambda c: float(str(row.iloc[0][c]).strip())
                        index_df.loc[d] = [g("Open Index Value"), g("High Index Value"), g("Low Index Value"),
                                           g("Closing Index Value"), 0]
        print(f"[nse] {d.date()}: +{added} stocks")
    return info


def load_csv(path: str):
    """Offline mode: read an exported prices.csv.gz (from the research-data branch)."""
    px = pd.read_csv(path, parse_dates=["date"])
    out, idx = {}, None
    for sym, g in px.groupby("symbol"):
        df = g.set_index("date")[["open", "high", "low", "close", "volume"]]
        df.columns = ["Open", "High", "Low", "Close", "Volume"]
        if sym == "^NSEI":
            idx = df
        elif len(df) >= 230:
            out[sym] = df
    return out, idx
