"""Alerts: Telegram (optional) and Web Push to the installed app."""
from __future__ import annotations

import html
import json
import os

import requests

from . import config as C


def _inr(x) -> str:
    if x is None:
        return "–"
    return f"₹{x:,.2f}" if x < 1000 else f"₹{x:,.0f}"


def _mood(mk: dict) -> str:
    if mk.get("regime") == "up":
        return "Uptrend (Nifty above its 200-day average)"
    return "Downtrend: no dip buys until Nifty is back above its 200-day average"


def build_message(d: dict) -> str:
    e = html.escape
    meta, mk, setups, watch, mine = d["meta"], d["market"], d["setups"], d["watch"], d["mine"]
    lines = [f"<b>📊 Stock Crawler — {e(meta['as_of_label'])}</b>",
             f"Market: {e(_mood(mk))}",
             f"Breadth: {round((mk.get('b50') or 0) * 100)}% of stocks above 50-day avg", ""]
    skipped = [x for x in setups if (x.get("agent") or {}).get("verdict") == "SKIP"]
    setups = [x for x in setups if x not in skipped]
    if setups:
        lines.append(f"<b>Buy at tomorrow's open</b> (leader dips, sell at first close above 5-day avg, max {C.MAX_HOLD} days):")
        for i, s in enumerate(setups[:C.TOP_ALERT], 1):
            v = (s.get("agent") or {}).get("verdict")
            flag = (" ✅AI: no bad news" if v == "GO" else " ⚠️AI: check the news first" if v == "CAUTION"
                    else " ⚠️news" if s.get("news_flag") == "risk" else "")
            lines.append(f"{i}. <b>{e(s['symbol'])}</b> {_inr(s['close'])} · {s['prob']*100:.0f}% past win rate, "
                         f"avg {s['ev']*100:+.1f}%{flag}")
    elif not skipped:
        lines.append("No leader-dip setups today. Nothing to buy — that's normal on most days.")
    if skipped:
        lines += ["", "<b>🚫 Skipped by the AI news check</b> (still tracked, so you can see if skipping was right):"]
        for x in skipped[:C.TOP_ALERT]:
            lines.append(f"• <b>{e(x['symbol'])}</b>: {e(x['agent'].get('summary') or '')}")
    if d.get("sells"):
        lines += ["", "<b>Sell at tomorrow's open</b> (closed above 5-day avg): " + ", ".join(
            f"{e(x['symbol'])} {x['pick']['ret']*100:+.1f}%" for x in d["sells"][:8])]
    if watch:
        lines += ["", "<b>Watch (could set up soon):</b> " + ", ".join(e(w["symbol"]) for w in watch[:8])]
    weak = [m for m in mine if m.get("health") == "Weak"]
    if weak:
        lines += ["", "<b>⚠️ Your watchlist turning weak:</b> " + ", ".join(e(m["symbol"]) for m in weak[:8])]
    secs = d.get("sectors") or []
    if secs:
        lines += ["", "<b>Hottest sectors (1 month):</b> " + ", ".join(
            f"{e(s['name'])} {s['r21']*100:+.1f}%" for s in secs[:3] if s.get("r21") is not None)]
    url = os.environ.get("DASHBOARD_URL")
    if url:
        lines += ["", f'<a href="{e(url)}">Open Stock Crawler →</a>']
    lines += ["", "<i>Past-pattern statistics, not advice.</i>"]
    return "\n".join(lines)


def send(text: str) -> bool:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("[notify] Telegram not configured — skipping")
        return False
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=20)
    if not r.ok:
        print(f"[notify] Telegram error {r.status_code}: {r.text[:300]}")
    return r.ok


# --------------------------------------------------------------------------- web push (PWA)

def push_payload(d: dict) -> dict:
    meta, watch, mine = d["meta"], d["watch"], d["mine"]
    skip = [s["symbol"] for s in d["setups"] if (s.get("agent") or {}).get("verdict") == "SKIP"]
    setups = [s for s in d["setups"] if s["symbol"] not in skip]
    mark = {"GO": " ✓", "CAUTION": " ⚠"}
    if setups:
        top = ", ".join(f"{s['symbol']} {s['prob']*100:.0f}%{mark.get((s.get('agent') or {}).get('verdict'), '')}"
                        for s in setups[:4])
        body = f"Buy at open: {top}"
    else:
        body = "No setups today."
    if skip:
        body += " · AI skipped: " + ", ".join(skip[:3])
    if d.get("sells"):
        body += " · Sell: " + ", ".join(x["symbol"] for x in d["sells"][:3])
    if watch:
        body += f" · Watching {len(watch)}"
    weak = [m["symbol"] for m in mine if m.get("health") == "Weak"]
    if weak:
        body += " · Weak: " + ", ".join(weak[:3])
    return {"title": f"Stock Crawler — {meta['as_of_label']}", "body": body,
            "url": os.environ.get("DASHBOARD_URL") or "./", "tag": "scan-" + meta["as_of"]}


def _subscriptions() -> list[dict]:
    raw = (os.environ.get("PUSH_SUBSCRIPTIONS") or "").strip()
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else [v]
    except json.JSONDecodeError:
        out = []
        for line in raw.splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    print("[push] skipping a line in PUSH_SUBSCRIPTIONS that isn't valid JSON")
        return out


def send_push(payload: dict) -> int:
    subs, key = _subscriptions(), os.environ.get("VAPID_PRIVATE_KEY")
    if not subs or not key:
        print("[push] web push not configured — skipping")
        return 0
    from pywebpush import WebPushException, webpush
    claims = {"sub": os.environ.get("VAPID_SUBJECT") or "mailto:stock-crawler@example.com"}
    sent = 0
    for i, sub in enumerate(subs, 1):
        try:
            webpush(subscription_info=sub, data=json.dumps(payload), vapid_private_key=key,
                    vapid_claims=dict(claims), ttl=12 * 3600)
            sent += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            hint = " (device unsubscribed — remove line %d from PUSH_SUBSCRIPTIONS)" % i if code in (404, 410) else ""
            print(f"[push] device {i} failed: {code}{hint}")
        except Exception as e:
            print(f"[push] device {i} failed: {e}")
    print(f"[push] sent to {sent}/{len(subs)} device(s)")
    return sent
