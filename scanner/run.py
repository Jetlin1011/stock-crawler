"""Daily pipeline (model v2).

    python -m scanner.run                      # live: Yahoo + NSE official files, news, alerts
    python -m scanner.run --csv prices.csv.gz  # offline on exported data (no news / alerts)
    python -m scanner.run --demo               # synthetic prices, for layout testing only
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import config as C
from . import agents, data, model, news, notify

ROOT = data.ROOT
OUT = os.path.join(ROOT, "docs", "data")
IST = timezone(timedelta(hours=5, minutes=30))


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else round(float(o), 5)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    return o


def _write(name, obj):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        json.dump(_clean(obj), f, ensure_ascii=False, separators=(",", ":"))


def _read(name, default):
    p = os.path.join(OUT, name)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default


# --------------------------------------------------------------------------- track record

def _pick(p, sym, t, universe, sc, replay):
    return {"id": f"{p.dates[t]:%Y-%m-%d}:{sym}", "date": p.dates[t].strftime("%Y-%m-%d"), "symbol": sym,
            "name": universe.get(sym, {}).get("name", sym), "prob": round(sc["prob"], 4),
            "ev": round(sc["ev"], 5), "signal_close": round(float(p.C[sym].iloc[t]), 2),
            "replay": replay, "status": "PENDING"}


def replay_history(p, stats, universe):
    S = p.f["signal"].values
    start = max(0, len(p.dates) - C.BACKFILL_DAYS)
    o, h, l, c, s5 = (x.values for x in (p.O, p.H, p.L, p.C, p.f[f"sma{C.EXIT_SMA}"]))
    picks = []
    for j, sym in enumerate(p.symbols):
        last = -1
        for t in np.flatnonzero(S[:, j]):
            if t < start or t <= last:
                continue
            r = model.simulate(o[:, j], h[:, j], l[:, j], c[:, j], s5[:, j], t)
            picks.append(_pick(p, sym, t, universe, model.score(stats, sym), True))
            last = r["exit_idx"] if r.get("exit_idx") is not None else (t if r["status"] == "DONE" else len(p.dates))
    return picks


def update_history(history, p):
    pos = {d: i for i, d in enumerate(p.dates.strftime("%Y-%m-%d"))}
    O, Cl = p.O.values, p.C.values
    for k in history:
        if k["symbol"] not in p.C.columns or k["date"] not in pos:
            continue
        j, t = p.C.columns.get_loc(k["symbol"]), pos[k["date"]]
        # what actually happened on the next trading day (for the prediction-vs-reality view)
        if "d1_close" not in k and t + 1 < len(p.dates) and np.isfinite(Cl[t + 1, j]) and np.isfinite(O[t + 1, j]):
            base = k.get("signal_close") or float(Cl[t, j])
            k.update({"d1_date": p.dates[t + 1].strftime("%Y-%m-%d"), "d1_open": round(float(O[t + 1, j]), 2),
                      "d1_close": round(float(Cl[t + 1, j]), 2), "d1_gap": round(float(O[t + 1, j]) / base - 1, 5),
                      "d1_ret": round(float(Cl[t + 1, j]) / base - 1, 5)})
        if k["status"] == "DONE":
            continue
        r = model.simulate(p.O.values[:, j], p.H.values[:, j], p.L.values[:, j], p.C.values[:, j],
                           p.f[f"sma{C.EXIT_SMA}"].values[:, j], t)
        k["status"] = r["status"]
        if "entry" in r:
            k.update({"entry": round(r["entry"], 2), "price": round(r["price"], 2), "ret": round(r["ret"], 5),
                      "days": int(r["days"]), "why": r.get("why"),
                      "exit_date": p.dates[r["exit_idx"]].strftime("%Y-%m-%d") if r.get("exit_idx") else None})


def _paper(rows):
    """Virtual account: C.PAPER_PER_TRADE rupees into each pick, from C.PAPER_START."""
    live = [k for k in rows if k["status"] in ("DONE", "OPEN") and k.get("ret") is not None]
    done = [k for k in live if k["status"] == "DONE"]
    pnl = sum(C.PAPER_PER_TRADE * k["ret"] for k in live)
    return {"start": C.PAPER_START, "per_trade": C.PAPER_PER_TRADE, "trades": len(live), "closed": len(done),
            "pnl": round(pnl, 2), "value": round(C.PAPER_START + pnl, 2),
            "open_pnl": round(sum(C.PAPER_PER_TRADE * k["ret"] for k in live if k["status"] == "OPEN"), 2)}


def summarize(history):
    def s(rows):
        done = [k for k in rows if k["status"] == "DONE"]
        out = {"done": len(done), "open": sum(k["status"] in ("OPEN", "PENDING") for k in rows)}
        if done:
            rets = [k["ret"] for k in done]
            out.update({"win": sum(r > 0 for r in rets) / len(rets), "avg": float(np.mean(rets)),
                        "best": max(rets), "worst": min(rets),
                        "days": float(np.mean([k["days"] for k in done]))})
        return out
    out = s(history)
    out["live"] = s([k for k in history if not k.get("replay")])
    months = {}
    for k in history:
        if k["status"] == "DONE":
            months.setdefault(k["date"][:7], []).append(k["ret"])
    # AI check vs plain rule, on live picks the AI looked at (same picks, same exits: a fair comparison)
    checked = [k for k in history if not k.get("replay") and k.get("agent")]
    if checked:
        v = lambda k: k["agent"]["verdict"]
        out["agent"] = {"since": min(k["date"] for k in checked), "all": s(checked),
                        "go": s([k for k in checked if v(k) == "GO"]),
                        "caution": s([k for k in checked if v(k) == "CAUTION"]),
                        "skip": s([k for k in checked if v(k) == "SKIP"]),
                        "paper": {"every": _paper(checked), "ai": _paper([k for k in checked if v(k) != "SKIP"])}}
    out["months"] = [{"m": m, "n": len(v), "avg": float(np.mean(v)), "win": sum(r > 0 for r in v) / len(v)}
                     for m, v in sorted(months.items())][-12:]
    return out


# --------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", default=os.environ.get("UNIVERSE", "nifty500"), choices=["nifty500", "watchlist"])
    ap.add_argument("--csv", help="offline: exported prices.csv.gz")
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--no-agents", action="store_true", help="skip the AI news check")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()
    now = datetime.now(IST)
    dinfo = {"source": "Yahoo Finance", "patched_days": [], "nse_ok": None, "delivery": {}}

    if a.demo:
        from . import demo
        universe, watch, raw, index_df = demo.make()
        a.no_news = a.no_notify = True
        dinfo["source"] = "demo"
    elif a.csv:
        raw, index_df = data.load_csv(a.csv)
        universe, watch = {}, set(data.read_watchlist())
        ucsv = os.path.join(os.path.dirname(os.path.abspath(a.csv)), "universe.csv")
        if os.path.exists(ucsv):
            u = pd.read_csv(ucsv).fillna("")
            universe = {r["symbol"]: {"name": r["name"], "industry": r["industry"]} for _, r in u.iterrows()}
        a.no_news = a.no_notify = True
        dinfo["source"] = "exported file"
    else:
        universe, watch = data.load_universe(a.universe)
        symbols = sorted(universe)
        print(f"[run] downloading {len(symbols)} symbols")
        raw = data.fetch_history(symbols, C.HISTORY_YEARS)
        index_df = data.fetch_index(C.HISTORY_YEARS)
        # Never use a half-finished day: before 6 PM IST, drop any bar dated today (market still open / settling).
        if now.hour < 18:
            today = pd.Timestamp(now.date())
            raw = {s: df[df.index < today] for s, df in raw.items()}
            if index_df is not None:
                index_df = index_df[index_df.index < today]
            print(f"[run] before 6 PM IST: ignoring any {today.date()} bars")
        try:
            dinfo.update(data.patch_with_nse(raw, index_df, now))
            if dinfo["patched_days"]:
                dinfo["source"] = "Yahoo Finance + NSE official file"
        except Exception as e:
            print(f"[nse] patch failed: {e}")
    if not raw:
        raise SystemExit("No price data — aborting so the last dashboard stays intact.")

    p = model.build(raw, index_df)
    t = len(p.dates) - 1
    as_of = p.dates[t]
    print(f"[run] {len(p.symbols)} stocks, latest bar {as_of.date()}")

    trades, stats = model.backtest(p)
    bt = {k: stats[k].js() for k in ("all", "train", "test")}
    bt["years"] = {str(y): b.js() for y, b in sorted(stats["years"].items())}
    print(f"[run] backtest all={bt['all']} test={bt['test']}")

    # ---- today's lists
    sig = p.f["signal"].iloc[t]
    setups = []
    for sym in sig[sig].index:
        row = model.stock_row(p, sym, t, universe)
        sc = model.score(stats, sym)
        row.update({k: (round(v, 5) if isinstance(v, float) else v) for k, v in sc.items()})
        setups.append(row)
    setups.sort(key=lambda r: (r["prob"], r["ev"]), reverse=True)

    w = p.f["watch"].iloc[t]
    watchl = [model.stock_row(p, s, t, universe) for s in w[w].index]
    watchl.sort(key=lambda r: r["rsi2"] if r["rsi2"] is not None else 99)
    watchl = watchl[:20]

    m = p.f["mom"].iloc[t].where(p.f["liquid"].iloc[t] & (p.C.iloc[t] > p.f["sma200"].iloc[t]))
    leaders = [model.stock_row(p, s, t, universe) for s in m.dropna().sort_values(ascending=False).index[:C.TOP_LEADERS]]
    for i, r in enumerate(leaders, 1):
        r["rank"] = i

    mine = []
    for s in sorted(watch):
        if s in p.C.columns and np.isfinite(p.C[s].iloc[t]):
            r = model.stock_row(p, s, t, universe)
            mp = r["mom_pct"] or 0
            r["health"] = ("Strong" if (mp >= 0.6 and r["above50"]) else
                           "Weak" if (not r["above200"] or mp < 0.3) else "Mixed")
            mine.append(r)

    for r in setups + watchl + leaders + mine:
        r["delivery"] = dinfo["delivery"].get(r["symbol"])
        r["watchlist"] = r["symbol"] in watch

    if not a.no_news:
        seen, todo = set(), []
        for r in setups + watchl[:10] + leaders[:15] + mine:
            if r["symbol"] not in seen:
                seen.add(r["symbol"])
                todo.append(r)
        todo = todo[:C.NEWS_MAX_STOCKS]
        print(f"[run] news for {len(todo)} stocks")
        news.enrich(todo)
        bysym = {r["symbol"]: r for r in todo}
        for r in setups + watchl + leaders + mine:
            src = bysym.get(r["symbol"])
            if src is not None and r is not src:
                r["news"], r["news_flag"] = src.get("news"), src.get("news_flag")

    # ---- AI news check on today's buy picks (never adds a pick or changes a price)
    agent_info = None
    if C.AGENTS_ON and not a.no_news and not a.no_agents:
        try:
            agent_info = agents.review(setups, as_of.strftime("%Y-%m-%d"))
        except Exception as e:
            print(f"[agents] check failed, picks go through unchecked: {e}")

    # ---- track record
    prev_meta = _read("latest.json", {}).get("meta", {})
    history = _read("history.json", [])
    if a.rebuild or prev_meta.get("model") != C.MODEL_VERSION or not history:
        print("[run] new model version: replaying track record")
        history = replay_history(p, stats, universe)
    history = [k for k in history if k["date"] <= as_of.strftime("%Y-%m-%d")]   # drop picks from partial-day runs
    known = {k["id"] for k in history}
    open_syms = {k["symbol"] for k in history if k["status"] in ("OPEN", "PENDING")}
    byid = {k["id"]: k for k in history}
    for r in setups:
        pk = _pick(p, r["symbol"], t, universe, r, False)
        ag = r.get("agent")
        if ag and ag.get("verdict") != "unchecked":
            pk["agent"] = {"verdict": ag["verdict"], "summary": ag.get("summary"), "evidence": ag.get("evidence"),
                           "by": [o["by"] for o in ag.get("opinions", [])], "v": ag.get("v")}
        if pk["id"] not in known and r["symbol"] not in open_syms:
            history.append(pk)
        elif pk["id"] in byid and "agent" in pk and "agent" not in byid[pk["id"]]:
            byid[pk["id"]]["agent"] = pk["agent"]      # same-day re-run after the AI was set up
    update_history(history, p)
    history.sort(key=lambda k: (k["date"], k["prob"]), reverse=True)
    track = summarize(history)

    # ---- trades to act on: exit signals today and open holdings
    as_of_s = as_of.strftime("%Y-%m-%d")
    sells, holding = [], []
    for k in history:
        sym = k["symbol"]
        if sym not in p.C.columns or not np.isfinite(p.C[sym].iloc[t]):
            continue
        if k["status"] == "DONE" and k.get("exit_date") == as_of_s:
            dest = sells
        elif k["status"] == "OPEN":
            dest = holding
        else:
            continue
        row = model.stock_row(p, sym, t, universe)
        row["pick"] = {x: k.get(x) for x in ("date", "entry", "price", "ret", "days", "why", "prob", "replay")}
        row["max_hold"] = C.MAX_HOLD
        dest.append(row)
    holding.sort(key=lambda r: r["pick"]["date"])
    for r in sells + holding:
        r["delivery"] = dinfo["delivery"].get(r["symbol"])
        r["watchlist"] = r["symbol"] in watch

    # ---- charts (loaded lazily by the app)
    charts = {}
    for r in setups + watchl + leaders + mine + sells + holding:
        if r["symbol"] not in charts:
            charts[r["symbol"]] = model.chart(p, r["symbol"])

    expected = pd.Timestamp(now.date()) if now.hour >= 19 else pd.Timestamp(now.date()) - pd.Timedelta(days=1)
    while expected.weekday() >= 5:
        expected -= pd.Timedelta(days=1)
    dinfo_out = {"source": dinfo["source"], "patched_days": dinfo["patched_days"], "nse_ok": dinfo["nse_ok"],
                 "delivery_date": dinfo.get("delivery_date"),
                 "stale": bool(as_of < expected and not a.csv and not a.demo),
                 "expected": expected.strftime("%Y-%m-%d")}

    mk = model.market(p)
    secs = model.sectors(p, universe)
    meta = {"model": C.MODEL_VERSION, "app_version": C.APP_VERSION, "as_of": as_of.strftime("%Y-%m-%d"), "as_of_label": as_of.strftime("%a %d %b %Y"),
            "generated": now.strftime("%Y-%m-%d %H:%M IST"), "scanned": len(p.symbols),
            "universe": "demo" if a.demo else a.universe, "demo": a.demo, "news": not a.no_news, "data": dinfo_out,
            "vapid_public": os.environ.get("VAPID_PUBLIC_KEY") or None, "agents": agent_info,
            "rules": {"leader_pct": C.LEADER_PCT, "dip_rsi2": C.DIP_RSI2, "watch_rsi2": C.WATCH_RSI2,
                      "max_vol": C.MAX_VOL_MULT, "max_hold": C.MAX_HOLD, "exit_sma": C.EXIT_SMA,
                      "cost": C.COST_ROUNDTRIP, "min_turnover_cr": C.MIN_TURNOVER_CR,
                      "test_split": C.TEST_SPLIT, "years": C.HISTORY_YEARS},
            "backtest": bt}

    _write("latest.json", {"meta": meta, "market": mk, "setups": setups, "watch": watchl,
                           "sells": sells, "holding": holding,
                           "leaders": leaders, "sectors": secs, "mine": mine, "track": track})
    _write("history.json", history[:1500])
    _write("charts.json", charts)
    print(f"[run] setups={len(setups)} watch={len(watchl)} leaders={len(leaders)} history={len(history)}")

    if a.no_notify:
        return
    if prev_meta.get("as_of") == meta["as_of"] and prev_meta.get("model") == C.MODEL_VERSION:
        print("[run] no new trading day — no alert")
        return
    held = {r["symbol"] for r in holding}
    payload = {"meta": meta, "setups": [r for r in setups if r["symbol"] not in held], "watch": watchl, "mine": mine, "track": track, "sells": sells,
               "market": mk, "sectors": secs}
    notify.send(notify.build_message(payload))
    notify.send_push(notify.push_payload(payload))


if __name__ == "__main__":
    main()
