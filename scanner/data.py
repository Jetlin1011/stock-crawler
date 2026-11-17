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
                                  auto_adjust=True, threads=True, progress=False)
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
        raw = yf.download("^NSEI", period=f"{years}y", interval="1d", auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        return _clean(raw)
    except Exception as e:
        print(f"[data] Nifty index download failed: {e}")
        return None
