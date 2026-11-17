"""Model v2: momentum leaders, leader-dip signal, backtest, market overview, sectors."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C


def _rsi(c: pd.DataFrame, n: int) -> pd.DataFrame:
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    r = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return r.where(dn > 0, 100.0)


def _z(x: pd.DataFrame) -> pd.DataFrame:
    return x.sub(x.mean(axis=1), axis=0).div(x.std(axis=1), axis=0)


@dataclass
class Panel:
    O: pd.DataFrame
    H: pd.DataFrame
    L: pd.DataFrame
    C: pd.DataFrame
    V: pd.DataFrame
    idx: pd.Series | None
    f: dict = field(default_factory=dict)   # derived frames

    @property
    def dates(self):
        return self.C.index

    @property
    def symbols(self):
        return self.C.columns


def build(raw: dict[str, pd.DataFrame], index_df: pd.DataFrame | None) -> Panel:
    cols = {k: pd.DataFrame({s: df[k] for s, df in raw.items()}).sort_index() for k in
            ("Open", "High", "Low", "Close", "Volume")}
    Cl = cols["Close"]
    idx = None
    if index_df is not None:
        idx = index_df["Close"].reindex(Cl.index).ffill()
    p = Panel(cols["Open"], cols["High"], cols["Low"], Cl, cols["Volume"], idx)
    f = p.f
    O, H, L, V = p.O, p.H, p.L, p.V
    for n in (5, 20, 50, 200):
        f[f"sma{n}"] = Cl.rolling(n).mean()
    f["rsi2"] = _rsi(Cl, 2)
    f["rsi14"] = _rsi(Cl, 14)
    pc = Cl.shift(1)
    tr = np.maximum(H - L, np.maximum((H - pc).abs(), (L - pc).abs()))
    f["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    f["turn"] = (Cl * V).rolling(20).mean()
    f["vol20"] = V.rolling(20).mean().shift(1)
    for n, k in ((1, "r1"), (5, "r5"), (21, "r21"), (63, "r63"), (126, "r126"), (252, "r252")):
        f[k] = Cl / Cl.shift(n) - 1
    dvol = Cl.pct_change().rolling(252, min_periods=120).std()
    # NSE-momentum-index style score: 6m and 12m returns divided by volatility, z-scored, averaged
    f["mom"] = (_z(f["r126"] / dvol) + _z(f["r252"] / dvol)) / 2
    f["mom_pct"] = f["mom"].rank(axis=1, pct=True)
    f["hi252"] = H.rolling(252, min_periods=120).max()
    f["liquid"] = f["turn"] > C.MIN_TURNOVER_CR * 1e7
    valid = Cl.notna().sum(axis=1)
    f["breadth50"] = (Cl > f["sma50"]).sum(axis=1) / valid
    f["breadth200"] = (Cl > f["sma200"]).sum(axis=1) / valid
    if idx is not None:
        f["reg_up"] = (idx > idx.rolling(200).mean()).fillna(True)
    else:
        f["reg_up"] = pd.Series(True, index=Cl.index)
    leader = (f["mom_pct"] >= C.LEADER_PCT) & (Cl > f["sma200"]) & f["liquid"]
    f["leader"] = leader
    calm = V < C.MAX_VOL_MULT * f["vol20"]
    reg = f["reg_up"].values[:, None]
    f["signal"] = (leader & (f["rsi2"] < C.DIP_RSI2) & calm & reg).fillna(False)
    f["watch"] = (leader & (f["rsi2"] < C.WATCH_RSI2) & ~f["signal"]).fillna(False)
    return p


# --------------------------------------------------------------------------- trade simulation

def simulate(o, h, l, c, s5, t: int, hold: int = C.MAX_HOLD) -> dict:
    """Signal at close t -> buy next open -> sell at first close above 5-day avg, else after `hold` days."""
    n = len(c)
    if t + 1 >= n or not np.isfinite(o[t + 1]):
        return {"status": "PENDING"}
    e = float(o[t + 1])
    end = min(t + hold, n - 1)
    for k in range(t + 1, end + 1):
        if np.isfinite(c[k]) and np.isfinite(s5[k]) and c[k] > s5[k]:
            return _done(e, c[k], k, t, "Closed above 5-day avg")
    if t + hold <= n - 1:
        return _done(e, c[t + hold], t + hold, t, f"{hold}-day time exit")
    last = float(c[n - 1])
    return {"status": "OPEN", "entry": e, "price": last, "ret": last / e - 1 - C.COST_ROUNDTRIP,
            "days": n - 1 - t, "exit_idx": None}


def _done(e, x, k, t, why):
    return {"status": "DONE", "entry": e, "price": float(x), "ret": float(x) / e - 1 - C.COST_ROUNDTRIP,
            "days": k - t, "exit_idx": k, "why": why}


@dataclass
class Bucket:
    n: int = 0
    wins: int = 0
    s: float = 0.0

    def add(self, r):
        self.n += 1
        self.wins += int(r > 0)
        self.s += r

    def js(self):
        return {"n": self.n, "win": round(self.wins / self.n, 4) if self.n else None,
                "avg": round(self.s / self.n, 5) if self.n else None}


def backtest(p: Panel):
    o, h, l, c, s5 = (x.values for x in (p.O, p.H, p.L, p.C, p.f[f"sma{C.EXIT_SMA}"]))
    S = p.f["signal"].values
    trades = []
    for j, sym in enumerate(p.symbols):
        last = -1
        for t in np.flatnonzero(S[:, j]):
            if t <= last:
                continue
            r = simulate(o[:, j], h[:, j], l[:, j], c[:, j], s5[:, j], t)
            if r["status"] != "DONE":
                continue
            trades.append({"date": p.dates[t], "symbol": sym, "ret": r["ret"], "days": r["days"],
                           "entry": r["entry"], "exit": r["price"], "t": t, "exit_idx": r["exit_idx"]})
            last = r["exit_idx"]
    tdf = pd.DataFrame(trades)
    stats = {"all": Bucket(), "train": Bucket(), "test": Bucket(), "years": {}, "stock": {}}
    split = pd.Timestamp(C.TEST_SPLIT)
    for tr in trades:
        stats["all"].add(tr["ret"])
        stats["train" if tr["date"] < split else "test"].add(tr["ret"])
        stats["years"].setdefault(tr["date"].year, Bucket()).add(tr["ret"])
        stats["stock"].setdefault(tr["symbol"], Bucket()).add(tr["ret"])
    return tdf, stats


def score(stats, sym: str) -> dict:
    base, own = stats["all"], stats["stock"].get(sym, Bucket())
    K = C.SHRINK_K
    p0 = base.wins / base.n if base.n else 0.5
    a0 = base.s / base.n if base.n else 0.0
    return {"prob": (own.wins + K * p0) / (own.n + K), "ev": (own.s + K * a0) / (own.n + K),
            "own_n": own.n, "own_wins": own.wins, "base_n": base.n}


# --------------------------------------------------------------------------- views for the app

def _f(x, d=4):
    try:
        x = float(x)
        return None if not np.isfinite(x) else round(x, d)
    except Exception:
        return None


def stock_row(p: Panel, sym: str, t: int, universe: dict) -> dict:
    f = p.f
    g = lambda k: _f(f[k][sym].iloc[t])
    close = _f(p.C[sym].iloc[t], 2)
    hi = g("hi252")
    sma20 = g("sma20")
    rsi2 = g("rsi2")
    state = "Trending"
    if bool(f["signal"][sym].iloc[t]):
        state = "Dip setup"
    elif rsi2 is not None and rsi2 < C.WATCH_RSI2:
        state = "Pulling back"
    elif hi and close and close / hi >= 0.97:
        state = "Near 52-week high"
    elif sma20 and close and close > 1.12 * sma20:
        state = "Stretched"
    return {
        "symbol": sym, "name": universe.get(sym, {}).get("name", sym),
        "industry": universe.get(sym, {}).get("industry", ""),
        "close": close, "r1": g("r1"), "r5": g("r5"), "r21": g("r21"), "r63": g("r63"), "r126": g("r126"),
        "mom_pct": g("mom_pct"), "rsi2": _f(rsi2, 1), "rsi14": g("rsi14") and round(g("rsi14"), 1),
        "from_high": (close / hi - 1) if (hi and close) else None,
        "above50": bool(p.C[sym].iloc[t] > f["sma50"][sym].iloc[t]),
        "above200": bool(p.C[sym].iloc[t] > f["sma200"][sym].iloc[t]),
        "vol_ratio": _f(p.V[sym].iloc[t] / f["vol20"][sym].iloc[t], 2),
        "atr": g("atr") and round(g("atr"), 2),
        "sma5": g("sma5") and round(g("sma5"), 2),
        "state": state,
        "spark": [_f(x, 2) for x in p.C[sym].iloc[max(0, t - C.SPARK_BARS + 1): t + 1].values],
    }


def chart(p: Panel, sym: str) -> dict:
    d = p.C[sym].dropna().index[-C.CHART_BARS:]
    r = lambda s: [_f(x, 2) for x in s.reindex(d).values]
    return {"t": d.strftime("%Y-%m-%d").tolist(), "o": r(p.O[sym]), "h": r(p.H[sym]), "l": r(p.L[sym]),
            "c": r(p.C[sym]), "v": [int(x) if np.isfinite(x) else 0 for x in p.V[sym].reindex(d).values],
            "sma5": r(p.f["sma5"][sym]), "sma50": r(p.f["sma50"][sym]), "sma200": r(p.f["sma200"][sym])}


def market(p: Panel) -> dict:
    f, t = p.f, len(p.dates) - 1
    d = p.dates[-C.MARKET_BARS:]
    out = {"dates": d.strftime("%Y-%m-%d").tolist(),
           "breadth50": [_f(x, 3) for x in f["breadth50"].reindex(d).values],
           "breadth200": [_f(x, 3) for x in f["breadth200"].reindex(d).values]}
    r1 = f["r1"].iloc[t]
    out["adv"] = int((r1 > 0).sum())
    out["dec"] = int((r1 < 0).sum())
    out["b50"] = _f(f["breadth50"].iloc[t], 3)
    out["b200"] = _f(f["breadth200"].iloc[t], 3)
    out["b50_prev"] = _f(f["breadth50"].iloc[t - 5], 3) if t >= 5 else None
    out["regime"] = "up" if bool(f["reg_up"].iloc[t]) else "down"
    out["leaders"] = int(f["leader"].iloc[t].sum())
    if p.idx is not None:
        ic = p.idx
        out["nifty"] = [_f(x, 1) for x in ic.reindex(d).values]
        out["nifty_sma200"] = [_f(x, 1) for x in ic.rolling(200).mean().reindex(d).values]
        out["nifty_close"] = _f(ic.iloc[t], 2)
        out["nifty_r1"] = _f(ic.iloc[t] / ic.iloc[t - 1] - 1)
        out["nifty_r21"] = _f(ic.iloc[t] / ic.iloc[t - 21] - 1)
    return out


def sectors(p: Panel, universe: dict) -> list[dict]:
    f, t = p.f, len(p.dates) - 1
    by = {}
    for s in p.symbols:
        ind = universe.get(s, {}).get("industry") or "Other"
        by.setdefault(ind, []).append(s)
    out = []
    for ind, syms in by.items():
        if len(syms) < 3:
            continue
        col = lambda k: f[k][syms].iloc[t]
        lead = f["leader"][syms].iloc[t]
        top = f["mom"][syms].iloc[t].sort_values(ascending=False).dropna().index[:3].tolist()
        out.append({"name": ind, "n": len(syms), "r1": _f(col("r1").median()), "r5": _f(col("r5").median()),
                    "r21": _f(col("r21").median()), "r63": _f(col("r63").median()),
                    "above50": _f((p.C[syms].iloc[t] > f["sma50"][syms].iloc[t]).mean(), 3),
                    "leaders": int(lead.sum()), "top": top})
    out.sort(key=lambda x: (x["r21"] if x["r21"] is not None else -9), reverse=True)
    return out
