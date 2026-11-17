"""Indicators, dip / exit setups, trade simulation, backtest stats and scoring."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import config as C

# --------------------------------------------------------------------------- indicators


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    r = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return r.where(dn > 0, 100.0)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    c, h, l, o, v = df["Close"], df["High"], df["Low"], df["Open"], df["Volume"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["sma20"] = c.rolling(20).mean()
    df["sma50"] = c.rolling(50).mean()
    df["sma200"] = c.rolling(200).mean()
    df["std20"] = c.rolling(20).std()
    df["bb_low"] = df["sma20"] - 2 * df["std20"]
    df["rsi14"] = rsi(c, 14)
    df["rsi2"] = rsi(c, 2)
    df["vol20"] = v.rolling(20).mean().shift(1)            # average of the *previous* 20 days
    df["turnover20"] = (c * v).rolling(20).mean()
    df["high20"] = h.rolling(20).max()
    df["low20_prev"] = l.rolling(20).min().shift(1)
    df["gap"] = o / pc - 1
    df["from_high20"] = c / df["high20"] - 1
    return df


# --------------------------------------------------------------------------- setups
# direction +1 = "buy the dip" idea, -1 = "sell / exit warning" (price expected to fall)

@dataclass(frozen=True)
class Setup:
    id: str
    name: str
    direction: int
    explain: str


SETUPS = [
    Setup("pullback", "Pullback in uptrend", 1,
          "A healthy stock (above its 200-day and with the 50-day above the 200-day average) has "
          "dropped 7–20% from its 20-day high and is oversold. Dips like this in strong stocks often bounce."),
    Setup("rsi2", "Sharp 2–3 day selloff", 1,
          "A long-term uptrend stock just had a very sharp short selloff (2-day RSI under 5). "
          "These short panics frequently snap back within a week."),
    Setup("gap_recovery", "Gap-down bought back", 1,
          "Opened at least 2.5% below yesterday's close, but buyers pushed it up through the day "
          "and it stays above its 200-day average — the drop may be temporary."),
    Setup("capitulation", "Heavy-volume flush", 1,
          "Closed below its lower Bollinger band on 1.5x+ normal volume while still in a long-term "
          "uptrend — often a short-term capitulation low."),
    Setup("breakdown", "Breakdown on volume", -1,
          "Closed below its 20-day low on heavy volume and is under its 50-day average. "
          "If you hold it, the trend says consider exiting."),
    Setup("overextended", "Overextended rally", -1,
          "Ran up too far too fast (14-day RSI above 78 and 12%+ above its 20-day average). "
          "Pullback risk is high — a good time to book some profit if you hold it."),
]
SETUP_BY_ID = {s.id: s for s in SETUPS}


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    c = df["Close"]
    up = (c > df["sma200"]) & (df["sma50"] > df["sma200"])
    above200 = c > df["sma200"]
    heavy = df["Volume"] > 1.5 * df["vol20"]
    df["sig_pullback"] = up & df["from_high20"].between(-0.20, -0.07) & (df["rsi14"] < 40)
    df["sig_rsi2"] = up & (df["rsi2"] < 5)
    df["sig_gap_recovery"] = above200 & (df["gap"] <= -0.025) & (c > df["Open"])
    df["sig_capitulation"] = above200 & (c < df["bb_low"]) & heavy
    df["sig_breakdown"] = (c < df["low20_prev"]) & (c < df["sma50"]) & heavy
    df["sig_overextended"] = (df["rsi14"] > 78) & (c > 1.12 * df["sma20"])
    sig_cols = [f"sig_{s.id}" for s in SETUPS]
    df[sig_cols] = df[sig_cols].fillna(False).astype(bool)
    return df


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    return add_signals(add_indicators(df))


# --------------------------------------------------------------------------- trade simulation

def simulate(o, h, l, c, t: int, atr: float, direction: int,
             horizon: int = C.HORIZON_DAYS) -> dict:
    """Signal on bar t (seen after close) -> enter at next open, exit on target / stop / horizon.

    ret is the move in the predicted direction (positive = the alert was right).
    For exit warnings, "TARGET" means the stock fell as warned.
    """
    n = len(c)
    if t + 1 >= n or not np.isfinite(atr) or atr <= 0:
        return {"status": "OPEN"}
    entry = float(o[t + 1])
    tgt = entry + direction * C.TARGET_ATR * atr
    stp = entry - direction * C.STOP_ATR * atr
    last = min(t + horizon, n - 1)
    for j in range(t + 1, last + 1):
        if direction == 1:
            if l[j] <= stp:                                   # stop checked first (conservative)
                px = min(o[j], stp) if j > t + 1 else stp
                return _res("STOP", entry, tgt, stp, px, direction, j)
            if h[j] >= tgt:
                return _res("TARGET", entry, tgt, stp, tgt, direction, j)
        else:
            if h[j] >= stp:
                px = max(o[j], stp) if j > t + 1 else stp
                return _res("STOP", entry, tgt, stp, px, direction, j)
            if l[j] <= tgt:
                return _res("TARGET", entry, tgt, stp, tgt, direction, j)
    if t + horizon <= n - 1:
        return _res("EXPIRED", entry, tgt, stp, float(c[t + horizon]), direction, t + horizon)
    r = _res("OPEN", entry, tgt, stp, float(c[-1]), direction, n - 1)
    r["exit_idx"] = None
    return r


def _res(status, entry, tgt, stp, px, direction, j):
    return {"status": status, "entry": entry, "target": tgt, "stop": stp,
            "exit_price": float(px), "ret": direction * (float(px) / entry - 1), "exit_idx": j}


# --------------------------------------------------------------------------- backtest

def regime_series(index_df: pd.DataFrame | None, dates: pd.DatetimeIndex) -> np.ndarray:
    """'up' when Nifty closes above its 200-day average, else 'down'."""
    if index_df is None:
        return np.array(["all"] * len(dates), dtype=object)
    up = (index_df["Close"] > index_df["Close"].rolling(200).mean())
    up = up.reindex(dates, method="ffill")
    return np.where(up.fillna(True).values, "up", "down").astype(object)


@dataclass
class Bucket:
    n: int = 0
    wins: int = 0
    ret_sum: float = 0.0

    def add(self, win: bool, ret: float):
        self.n += 1
        self.wins += int(win)
        self.ret_sum += ret

    @property
    def rate(self):
        return self.wins / self.n if self.n else None

    @property
    def avg_ret(self):
        return self.ret_sum / self.n if self.n else None


class Stats:
    def __init__(self):
        self.setup = defaultdict(Bucket)       # (setup, regime|'all')
        self.stock = defaultdict(Bucket)       # (symbol, setup)

    def to_json(self):
        out = {}
        for s in SETUPS:
            row = {}
            for reg in ("all", "up", "down"):
                b = self.setup.get((s.id, reg))
                if b and b.n:
                    row[reg] = {"n": b.n, "rate": round(b.rate, 4), "avg_ret": round(b.avg_ret, 5)}
            out[s.id] = row
        return out


def backtest(prepared: dict[str, pd.DataFrame], index_df) -> Stats:
    st = Stats()
    H = C.HORIZON_DAYS
    for sym, df in prepared.items():
        o, h, l, c, a = (df[k].values for k in ("Open", "High", "Low", "Close", "atr"))
        reg = regime_series(index_df, df.index)
        for s in SETUPS:
            idx = np.flatnonzero(df[f"sig_{s.id}"].values)
            last_taken = -10 ** 9
            for t in idx:
                if t - last_taken < H or t + H >= len(c):   # no overlapping trades, only finished ones
                    continue
                r = simulate(o, h, l, c, t, a[t], s.direction)
                if r["status"] == "OPEN":
                    continue
                last_taken = t
                win = r["status"] == "TARGET"
                st.setup[(s.id, "all")].add(win, r["ret"])
                st.setup[(s.id, reg[t])].add(win, r["ret"])
                st.stock[(sym, s.id)].add(win, r["ret"])
    return st


# --------------------------------------------------------------------------- scoring

def probability(st: Stats, setup_id: str, regime: str, sym: str) -> dict | None:
    base = st.setup.get((setup_id, regime))
    if base is None or base.n < C.MIN_REGIME_CASES:
        base = st.setup.get((setup_id, "all"))
    if base is None or base.n < 30:
        return None
    own = st.stock.get((sym, setup_id), Bucket())
    K = C.SHRINK_K
    p = (own.wins + K * base.rate) / (own.n + K)
    ev = ((own.ret_sum + K * base.avg_ret) / (own.n + K))
    return {"prob": p, "ev": ev, "base_rate": base.rate, "base_n": base.n,
            "own_n": own.n, "own_wins": own.wins}


def candidates_at(prepared, st: Stats, index_df, date: pd.Timestamp, universe: dict) -> list[dict]:
    """All setups that fired on `date`, scored. One entry per (stock, direction) — best setup wins."""
    out = []
    min_turn = C.MIN_TURNOVER_CR * 1e7
    reg = regime_series(index_df, pd.DatetimeIndex([date]))[0]     # same for every stock on a date
    for sym, df in prepared.items():
        if date not in df.index:
            continue
        t = df.index.get_loc(date)
        row = df.iloc[t]
        if not np.isfinite(row["turnover20"]) or row["turnover20"] < min_turn:
            continue
        best = {}
        for s in SETUPS:
            if not row[f"sig_{s.id}"]:
                continue
            sc = probability(st, s.id, reg, sym)
            if sc is None:
                continue
            cur = best.get(s.direction)
            if cur is None or sc["prob"] > cur["prob"]:
                fired = (cur["also"] + [cur["setup"]]) if cur else []
                best[s.direction] = {**sc, "setup": s.id, "also": fired}
            else:
                cur["also"].append(s.id)
        for d, sc in best.items():
            atr = float(row["atr"])
            close = float(row["Close"])
            out.append({
                "symbol": sym,
                "name": universe.get(sym, {}).get("name", sym),
                "industry": universe.get(sym, {}).get("industry", ""),
                "date": date.strftime("%Y-%m-%d"),
                "direction": d,
                "setup": sc["setup"],
                "also": sc["also"],
                "prob": round(sc["prob"], 4),
                "ev": round(sc["ev"], 5),
                "base_rate": round(sc["base_rate"], 4),
                "base_n": sc["base_n"],
                "own_n": sc["own_n"],
                "own_wins": sc["own_wins"],
                "regime": reg,
                "close": round(close, 2),
                "atr": round(atr, 2),
                # indicative levels from today's close; real levels are set from tomorrow's open
                "target": round(close + d * C.TARGET_ATR * atr, 2),
                "stop": round(close - d * C.STOP_ATR * atr, 2),
                "rsi14": round(float(row["rsi14"]), 1),
                "from_high20": round(float(row["from_high20"]), 4),
            })
    return out


def rank(cands: list[dict], direction: int, top: int, watch: set[str] | None = None) -> list[dict]:
    pool = [c for c in cands if c["direction"] == direction]
    def key(c):
        pen = C.NEWS_RISK_PENALTY if c.get("news_flag") == "risk" else 0.0
        wl = 1 if (watch and direction == -1 and c["symbol"] in watch) else 0  # your holdings first
        return (wl, c["prob"] - pen, c["ev"])
    return sorted(pool, key=key, reverse=True)[:top]
