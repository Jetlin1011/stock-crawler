"""Daily pipeline:  python -m scanner.run [--universe nifty500|watchlist] [--demo] [--no-news] [--no-notify]"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import config as C
from . import data, engine, news, notify
from .engine import SETUP_BY_ID, SETUPS

ROOT = data.ROOT
OUT = os.path.join(ROOT, "docs", "data")
IST = timezone(timedelta(hours=5, minutes=30))


# --------------------------------------------------------------------------- helpers

def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else round(float(o), 5)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def _write(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(_clean(obj), f, ensure_ascii=False, separators=(",", ":"))


def _read(name, default):
    p = os.path.join(OUT, name)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return default


def chart_data(df: pd.DataFrame) -> dict:
    d = df.tail(C.CHART_BARS)
    t = d.index.strftime("%Y-%m-%d").tolist()
    r = lambda s: [None if not np.isfinite(x) else round(float(x), 2) for x in s.values]
    return {"t": t, "o": r(d["Open"]), "h": r(d["High"]), "l": r(d["Low"]), "c": r(d["Close"]),
            "v": [int(x) for x in d["Volume"].values], "sma50": r(d["sma50"]), "sma200": r(d["sma200"])}


# --------------------------------------------------------------------------- track record

def pick_record(c: dict, backfilled: bool) -> dict:
    return {"id": f"{c['date']}:{c['symbol']}:{c['setup']}", "date": c["date"], "symbol": c["symbol"],
            "name": c["name"], "setup": c["setup"], "direction": c["direction"], "prob": c["prob"],
            "base_n": c["base_n"], "atr": c["atr"], "signal_close": c["close"],
            "news_flag": c.get("news_flag"), "backfilled": backfilled, "status": "OPEN"}


def update_history(history: list[dict], prepared: dict[str, pd.DataFrame]) -> None:
    for p in history:
        if p["status"] not in ("OPEN", "PENDING"):
            continue
        df = prepared.get(p["symbol"])
        if df is None:
            continue
        d = pd.Timestamp(p["date"])
        if d not in df.index:
            continue
        t = df.index.get_loc(d)
        r = engine.simulate(df["Open"].values, df["High"].values, df["Low"].values, df["Close"].values,
                            t, p["atr"], p["direction"])
        if "entry" not in r:                      # entry day hasn't happened yet
            p["status"] = "PENDING"
            continue
        p.update({"status": r["status"], "entry": round(r["entry"], 2), "target": round(r["target"], 2),
                  "stop": round(r["stop"], 2), "ret": round(r["ret"], 5),
                  "last_price": round(r["exit_price"], 2),
                  "days": (int(r["exit_idx"]) - t) if r.get("exit_idx") is not None else len(df) - 1 - t,
                  "exit_date": df.index[r["exit_idx"]].strftime("%Y-%m-%d")
                  if r.get("exit_idx") is not None else None})


def track_summary(history: list[dict]) -> dict:
    def summ(rows):
        done = [p for p in rows if p["status"] in ("TARGET", "STOP", "EXPIRED")]
        if not done:
            return {"resolved": 0, "open": sum(p["status"] in ("OPEN", "PENDING") for p in rows)}
        wins = sum(p["status"] == "TARGET" for p in done)
        pos = sum((p.get("ret") or 0) > 0 for p in done)
        return {"resolved": len(done), "wins": wins, "win_rate": wins / len(done),
                "positive_rate": pos / len(done),
                "avg_ret": float(np.mean([p.get("ret") or 0 for p in done])),
                "open": sum(p["status"] in ("OPEN", "PENDING") for p in rows),
                "avg_prob": float(np.mean([p["prob"] for p in done]))}
    buys = [p for p in history if p["direction"] == 1]
    out = summ(buys)
    out["live_only"] = summ([p for p in buys if not p.get("backfilled")])
    out["exits"] = summ([p for p in history if p["direction"] == -1])
    out["by_setup"] = {s.id: summ([p for p in history if p["setup"] == s.id]) for s in SETUPS}
    # calibration: does a higher probability actually hit more often?
    bands = []
    for lo, hi in ((0, .45), (.45, .55), (.55, .65), (.65, 1.01)):
        b = summ([p for p in buys if lo <= p["prob"] < hi])
        if b.get("resolved"):
            bands.append({"band": f"{int(lo*100)}–{min(int(hi*100), 100)}%", **b})
    out["calibration"] = bands
    return out


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=os.environ.get("UNIVERSE", "nifty500"),
                    choices=["nifty500", "watchlist"])
    ap.add_argument("--demo", action="store_true", help="synthetic prices, no network (for testing)")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--rebuild", action="store_true", help="wipe track record and backfill again")
    a = ap.parse_args()

    # 1. universe + prices
    if a.demo:
        from . import demo
        universe, watch, raw, index_df = demo.make()
        a.no_news = True
    else:
        universe, watch = data.load_universe(a.universe)
        hist_syms = {p["symbol"] for p in _read("history.json", []) if p["status"] in ("OPEN", "PENDING")}
        symbols = sorted(set(universe) | hist_syms)
        print(f"[run] scanning {len(symbols)} symbols")
        raw = data.fetch_history(symbols, C.HISTORY_YEARS)
        index_df = data.fetch_index(C.HISTORY_YEARS)
    if not raw:
        raise SystemExit("No price data downloaded — aborting so yesterday's dashboard stays intact.")

    # 2. indicators + signals
    prepared = {s: engine.prepare(df) for s, df in raw.items()}
    as_of = max(df.index[-1] for df in prepared.values())
    print(f"[run] {len(prepared)} stocks with data, latest bar {as_of.date()}")

    # 3. backtest every setup on every stock -> base rates
    st = engine.backtest(prepared, index_df)
    for s in SETUPS:
        b = st.setup.get((s.id, "all"))
        if b and b.n:
            print(f"  {s.id:<14} n={b.n:<5} hit={b.rate*100:5.1f}%  avg={b.avg_ret*100:+.2f}%")

    # 4. track record (backfill on first run)
    history = [] if a.rebuild else _read("history.json", [])
    known = {p["id"] for p in history}
    if not history:
        dates = sorted({d for df in prepared.values() for d in df.index if d < as_of})[-C.BACKFILL_DAYS:]
        print(f"[run] first run: backfilling {len(dates)} days of picks")
        for d in dates:
            cands = engine.candidates_at(prepared, st, index_df, d, universe)
            for c in engine.rank(cands, 1, C.TOP_BUY) + engine.rank(cands, -1, C.TOP_EXIT, watch):
                rec = pick_record(c, backfilled=True)
                if rec["id"] not in known:
                    history.append(rec)
                    known.add(rec["id"])

    # 5. today's candidates
    cands = engine.candidates_at(prepared, st, index_df, as_of, universe)
    pre_buy = engine.rank(cands, 1, C.NEWS_FOR_TOP)
    pre_exit = engine.rank(cands, -1, C.TOP_EXIT, watch)
    if not a.no_news:
        print(f"[run] checking news for {len(pre_buy) + len(pre_exit)} stocks")
        news.enrich(pre_buy + pre_exit)
    buys = engine.rank(pre_buy, 1, C.TOP_BUY)
    exits = engine.rank(pre_exit, -1, C.TOP_EXIT, watch)
    for c in buys + exits:
        c["watchlist"] = c["symbol"] in watch
        c["chart"] = chart_data(prepared[c["symbol"]])
        rec = pick_record(c, backfilled=False)
        if rec["id"] not in known:
            history.append(rec)
            known.add(rec["id"])

    update_history(history, prepared)
    history.sort(key=lambda p: (p["date"], -p["prob"]), reverse=True)
    track = track_summary(history)

    # 6. regime
    regime = engine.regime_series(index_df, pd.DatetimeIndex([as_of]))[0]
    nifty = None
    if index_df is not None and len(index_df) > 200:
        ic = index_df["Close"]
        nifty = {"close": float(ic.iloc[-1]), "sma200": float(ic.rolling(200).mean().iloc[-1]),
                 "chg": float(ic.iloc[-1] / ic.iloc[-2] - 1)}

    now = datetime.now(IST)
    meta = {"as_of": as_of.strftime("%Y-%m-%d"), "as_of_label": as_of.strftime("%a %d %b %Y"),
            "generated": now.strftime("%Y-%m-%d %H:%M IST"), "regime": regime, "nifty": nifty,
            "universe": "demo" if a.demo else a.universe, "scanned": len(prepared),
            "demo": bool(a.demo), "news": not a.no_news,
            "vapid_public": os.environ.get("VAPID_PUBLIC_KEY") or None,
            "config": {"horizon": C.HORIZON_DAYS, "target_atr": C.TARGET_ATR, "stop_atr": C.STOP_ATR,
                       "years": C.HISTORY_YEARS, "min_turnover_cr": C.MIN_TURNOVER_CR,
                       "breakeven": C.STOP_ATR / (C.STOP_ATR + C.TARGET_ATR)},
            "setups": [{"id": s.id, "name": s.name, "direction": s.direction, "explain": s.explain}
                       for s in SETUPS],
            "setup_stats": st.to_json()}

    prev = _read("latest.json", {}).get("meta", {}).get("as_of")
    _write("latest.json", {"meta": meta, "buys": buys, "exits": exits, "track": track})
    _write("history.json", history)
    print(f"[run] wrote {len(buys)} buy ideas, {len(exits)} exit warnings, history={len(history)}")

    if a.no_notify:
        return
    if prev == meta["as_of"]:
        print("[run] no new trading day since last run — not sending alert")
        return
    notify.send(notify.build_message(meta, buys, exits, track, watch))
    notify.send_push(notify.push_payload(meta, buys, exits, watch))


if __name__ == "__main__":
    main()
