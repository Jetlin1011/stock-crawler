"""AI news check on today's buy picks (added in 2.3.0).

The trading rule still finds every pick and sets every price. The AI only reads the week's headlines for each
pick and answers one question: "Did this stock fall because of real bad news about the company?"

Three roles:
  1. News analyst  - Claude, through the Claude Code CLI on your Claude Pro plan (CLAUDE_CODE_OAUTH_TOKEN).
  2. Second opinion - Google Gemini, free tier (GEMINI_API_KEY). Optional.
  3. Judge          - plain Python below (judge()), never an AI. It decides GO / CAUTION / SKIP.

Safety rails:
  - An AI's "bad news" call only counts if it quotes a headline word for word. Made-up quotes are thrown out.
  - The AI never sees or changes prices, targets or sizes, and it can never add a pick.
  - Skipped picks stay in the track record, so the app can show whether skipping them actually helped.
  - If neither AI is set up or both fail, picks go through unchanged (verdict "unchecked").
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import requests

from . import config as C

NOTES: list[str] = []          # problems during today's check, shown on the AI desk


def _note(msg: str) -> None:
    print("[agents] " + msg)
    NOTES.append(msg)


CAUSES = ["company_bad_news", "market_or_sector", "no_clear_news", "good_news"]

SCHEMA = {
    "type": "object",
    "properties": {
        "picks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "cause": {"type": "string", "enum": CAUSES},
                    "severity": {"type": "string", "enum": ["none", "low", "high"]},
                    "evidence": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["symbol", "cause", "severity", "evidence", "reason"],
            },
        }
    },
    "required": ["picks"],
}

INSTRUCTIONS = """You are the news analyst for a swing-trading tool on Indian (NSE) stocks.
A fixed price rule has picked the stocks below to buy tomorrow because each one had a sharp 2-3 day dip.
The rule works when the dip is temporary. It fails when the stock fell because of real, lasting bad news
about the company itself.

For EACH stock, read only the headlines given and decide why it fell:
- "company_bad_news": a headline reports a real problem for this company: fraud, raid or probe, regulator
  action or ban, bad results or a profit fall, guidance or target cut, downgrade, top management or auditor
  resignation, default, promoter selling or pledging, plant shutdown, US FDA warning, big order loss, lawsuit.
- "market_or_sector": headlines blame the whole market, the sector, FII selling, global news or policy, not
  this company.
- "no_clear_news": nothing in the headlines explains the fall (routine coverage, price-move reports, no news).
- "good_news": the headlines are clearly positive.

Severity: "high" if the bad news could keep the stock falling for weeks (fraud, regulator action, results
miss, downgrade, default, management exit). "low" if it is minor or old. "none" if not company_bad_news.

Rules:
- "evidence" MUST be one headline copied exactly, character for character, from that stock's list.
  Use "" when the cause is no_clear_news.
- "reason" is one short plain-English sentence for a retail trader. No jargon.
- Judge only what the headlines say. Do not use anything you remember about these companies.
- Do not comment on price, value or whether to buy. Only the cause of the fall.
- Return one entry per stock, using the exact symbol given."""


def _brief(setups: list[dict]) -> list[dict]:
    out = []
    for r in setups:
        out.append({
            "symbol": r["symbol"], "company": r.get("name"), "industry": r.get("industry"),
            "fell_last_5_days_pct": round((r.get("r5") or 0) * 100, 1),
            "volume_vs_usual": round(r["vol_ratio"], 1) if r.get("vol_ratio") is not None else None,
            "headlines": [{"date": n.get("date"), "source": n.get("source"), "title": n.get("title")}
                          for n in (r.get("news") or [])],
        })
    return out


def _prompt(setups: list[dict]) -> str:
    return (INSTRUCTIONS + "\n\nStocks (JSON):\n" + json.dumps(_brief(setups), ensure_ascii=False, indent=1)
            + "\n\nAnswer with JSON only, matching: " + json.dumps(SCHEMA))


# --------------------------------------------------------------------------- analysts

def ask_claude(setups: list[dict]) -> dict | None:
    """Claude through the Claude Code CLI. Uses CLAUDE_CODE_OAUTH_TOKEN (your Pro plan), no API key needed."""
    exe = shutil.which("claude")
    if not exe or not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        print("[agents] Claude not set up (needs the claude CLI and CLAUDE_CODE_OAUTH_TOKEN) — skipping")
        return None
    cmd = [exe, "-p", "--output-format", "json", "--json-schema", json.dumps(SCHEMA),
           "--model", C.AGENT_CLAUDE_MODEL, "--tools", "", "--max-turns", "3"]
    # never --bare: it ignores the subscription login
    try:
        res = subprocess.run(cmd, input=_prompt(setups), capture_output=True, text=True,
                             timeout=C.AGENT_TIMEOUT_S)
    except Exception as e:
        _note(f"Claude didn't answer ({str(e)[:120]})")
        return None
    try:
        out = json.loads(res.stdout)
    except Exception:
        print(f"[agents] Claude gave no JSON (exit {res.returncode}): {(res.stderr or res.stdout)[:300]}")
        _note("Claude didn't answer (no usable reply)")
        return None
    data = out.get("structured_output")
    if data is None and isinstance(out.get("result"), str):
        data = _loose_json(out["result"])
    if not data:
        print(f"[agents] Claude answer missing ({out.get('subtype') or out.get('is_error')})")
        _note("Claude didn't answer (empty reply; usage limit or login problem?)")
        return None
    return {"by": f"Claude ({C.AGENT_CLAUDE_MODEL})", "picks": data.get("picks", [])}


def ask_gemini(setups: list[dict]) -> dict | None:
    """Google Gemini free tier, used as a second opinion."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("[agents] Gemini not set up (GEMINI_API_KEY) — skipping")
        return None
    body = {"contents": [{"role": "user", "parts": [{"text": _prompt(setups)}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    text = model = None
    for model in C.AGENT_GEMINI_MODELS:     # fast free model first, then the next one
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        try:
            r = requests.post(url, params={"key": key}, json=body, timeout=C.AGENT_GEMINI_TIMEOUT_S)
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            break
        except Exception as e:
            print(f"[agents] Gemini {model} failed: {str(e)[:200]}")
            _note(f"Gemini {model} didn't answer" + (" (timed out)" if "timed out" in str(e).lower() else ""))
    if text is None:
        return None
    data = _loose_json(text)
    if not data:
        print("[agents] Gemini answer wasn't valid JSON")
        return None
    return {"by": f"Gemini ({model})", "picks": data.get("picks", [])}


def _loose_json(s: str):
    s = s.strip()
    m = re.search(r"\{.*\}", s, re.S)
    try:
        return json.loads(m.group(0) if m else s)
    except Exception:
        return None


# --------------------------------------------------------------------------- checks + judge

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def clean_opinion(op: dict, row: dict) -> dict:
    """Keep an analyst's call only if it's well-formed and its quoted headline really exists."""
    cause = op.get("cause") if op.get("cause") in CAUSES else "no_clear_news"
    sev = op.get("severity") if op.get("severity") in ("none", "low", "high") else "none"
    ev = (op.get("evidence") or "").strip()
    titles = [_norm(n.get("title")) for n in (row.get("news") or [])]
    quote_ok = bool(ev) and any(_norm(ev) in t or (t and t in _norm(ev)) for t in titles)
    if cause in ("company_bad_news", "good_news", "market_or_sector") and not quote_ok:
        # no real headline behind it: treat as "no clear news"
        return {"cause": "no_clear_news", "severity": "none", "evidence": "",
                "reason": "Answer ignored: the quoted headline wasn't in the news.", "rejected": True}
    if cause != "company_bad_news":
        sev = "none"
    return {"cause": cause, "severity": sev, "evidence": ev if quote_ok else "",
            "reason": str(op.get("reason") or "")[:240]}


def judge(opinions: list[dict]) -> str:
    """Plain rules, no AI. GO = buy as normal, CAUTION = your call, SKIP = don't buy."""
    if not opinions:
        return "unchecked"
    bad = [o for o in opinions if o["cause"] == "company_bad_news"]
    high = [o for o in bad if o["severity"] == "high"]
    if len(opinions) == 1:
        return "SKIP" if high else "CAUTION" if bad else "GO"
    if len(high) == len(opinions) or (high and len(bad) == len(opinions)):
        return "SKIP"          # both analysts found real bad news, at least one says serious
    if bad:
        return "CAUTION"       # they disagree, or it's minor
    return "GO"


def review(setups: list[dict], as_of: str) -> dict:
    """Adds r['agent'] to each setup in place. Returns run info for the app."""
    NOTES.clear()
    info = {"date": as_of, "prompt_version": C.AGENT_PROMPT_VERSION, "analysts": [], "checked": 0, "notes": NOTES}
    if not setups:
        return info
    # a stock with no headlines at all can't have bad news: GO without spending AI calls
    need = [r for r in setups if r.get("news")]
    configured = bool((shutil.which("claude") and os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
                      or os.environ.get("GEMINI_API_KEY"))
    if not configured:
        print("[agents] no AI set up — picks go through unchecked")
        return info
    answers = []
    if need:
        for fn in (ask_claude, ask_gemini):
            a = fn(need)
            if a:
                answers.append(a)
                info["analysts"].append(a["by"])
    for r in setups:
        if not r.get("news"):
            if answers or not need:     # same verdict whether or not the AIs answered today
                r["agent"] = {"verdict": "GO", "summary": "No company headlines this week. The fall looks price-driven.",
                              "opinions": [], "v": C.AGENT_PROMPT_VERSION}
            continue
        ops = []
        for a in answers:
            raw = next((p for p in a["picks"] if str(p.get("symbol", "")).upper() == r["symbol"].upper()), None)
            if raw is not None:
                o = clean_opinion(raw, r)
                o["by"] = a["by"]
                ops.append(o)
        v = judge(ops)
        lead = next((o for o in ops if o["cause"] == "company_bad_news"), ops[0] if ops else None)
        r["agent"] = {"verdict": v, "summary": lead["reason"] if lead else "AI check unavailable today.",
                      "evidence": lead.get("evidence") if lead else "", "opinions": ops,
                      "v": C.AGENT_PROMPT_VERSION}
    info["checked"] = sum(1 for r in setups if r.get("agent", {}).get("verdict") not in (None, "unchecked"))
    print(f"[agents] {info['checked']}/{len(setups)} picks checked by {info['analysts'] or 'no AI'}: "
          + ", ".join(f"{r['symbol']}={r.get('agent', {}).get('verdict')}" for r in setups))
    return info


def session(setups: list[dict], info: dict | None, as_of: str, label: str, regime: str, n_watch: int) -> dict:
    """One evening at the AI desk, in a form the app can show step by step."""
    keep = ("symbol", "name", "industry", "prob", "ev", "base_n", "own_n", "own_wins", "r5", "close", "sma5",
            "vol_ratio", "delivery")
    picks = []
    for r in setups:
        a = r.get("agent") or {}
        picks.append({**{k: r.get(k) for k in keep}, "id": f"{as_of}:{r['symbol']}",
                      "headlines": [{k: n.get(k) for k in ("title", "source", "date", "link")}
                                    for n in (r.get("news") or [])],
                      "opinions": a.get("opinions", []), "verdict": a.get("verdict", "unchecked"),
                      "summary": a.get("summary")})
    return {"date": as_of, "label": label, "regime": regime, "watch": n_watch,
            "analysts": (info or {}).get("analysts", []), "notes": list((info or {}).get("notes", [])),
            "ai_on": info is not None and bool((info or {}).get("analysts")), "picks": picks}
