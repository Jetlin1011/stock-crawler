"""Telegram alert (free). Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars."""
from __future__ import annotations

import html
import json
import os

import requests

from . import config as C
from .engine import SETUP_BY_ID


def _inr(x: float) -> str:
    return f"₹{x:,.2f}" if x < 1000 else f"₹{x:,.0f}"


def build_message(meta: dict, buys: list[dict], exits: list[dict], track: dict, watch: set[str]) -> str:
    e = html.escape
    reg = meta.get("regime")
    reg_txt = {"up": "Nifty above 200-day avg ✅ (dips usually get bought)",
               "down": "Nifty below 200-day avg ⚠️ (dip-buys work less often — be picky)"}.get(reg, "")
    lines = [f"<b>📊 Stock Crawler — {e(meta['as_of_label'])}</b>", reg_txt, ""]
    be = meta.get("config", {}).get("breakeven", 0.4)
    good = [c for c in buys if c["prob"] >= be]
    if good:
        lines.append(f"<b>Top dip ideas</b> (hold up to {C.HORIZON_DAYS} trading days):")
        for i, c in enumerate(good[:C.TOP_ALERT], 1):
            flag = " ⚠️news" if c.get("news_flag") == "risk" else ""
            star = " ⭐" if c["symbol"] in watch else ""
            lines.append(
                f"{i}. <b>{e(c['symbol'])}</b>{star} — {e(SETUP_BY_ID[c['setup']].name)} · "
                f"<b>{c['prob']*100:.0f}%</b> ({c['base_n']} past cases){flag}\n"
                f"    Close {_inr(c['close'])} · Target {_inr(c['target'])} · Stop {_inr(c['stop'])}")
    else:
        lines.append(f"No dip idea above the {be*100:.0f}% break-even today — sitting out is a fine trade.")
    held = [c for c in exits if c["symbol"] in watch]
    if held:
        lines += ["", "<b>⚠️ Exit warnings on your watchlist:</b>"]
        for c in held[:8]:
            lines.append(f"• <b>{e(c['symbol'])}</b> — {e(SETUP_BY_ID[c['setup']].name)} "
                         f"({c['prob']*100:.0f}% fell further historically)")
    if track.get("resolved"):
        lines += ["", f"Track record (buy ideas): {track['win_rate']*100:.0f}% hit target "
                      f"· {track['resolved']} closed · avg {track['avg_ret']*100:+.1f}%/idea"]
    url = os.environ.get("DASHBOARD_URL")
    if url:
        lines += ["", f'<a href="{e(url)}">Open dashboard →</a>']
    lines += ["", "<i>Signals from past price patterns, not advice. Always use the stop.</i>"]
    return "\n".join(lines)


def send(text: str) -> bool:
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        print("[notify] Telegram not configured — skipping. Message would be:\n" + text)
        return False
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=20)
    if not r.ok:
        print(f"[notify] Telegram error {r.status_code}: {r.text[:300]}")
    return r.ok


# --------------------------------------------------------------------------- web push (PWA)

def push_payload(meta: dict, buys: list[dict], exits: list[dict], watch: set[str]) -> dict:
    be = meta.get("config", {}).get("breakeven", 0.4)
    good = [c for c in buys if c["prob"] >= be]
    if good:
        top = ", ".join(f"{c['symbol']} {c['prob']*100:.0f}%" for c in good[:4])
        body = f"{len(good)} dip idea{'s' if len(good) != 1 else ''} above break-even: {top}"
    else:
        body = "No strong dip ideas today."
    held = [c["symbol"] for c in exits if c["symbol"] in watch]
    if held:
        body += " · ⚠ exit watch: " + ", ".join(held[:4])
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
