"""Free headline check via Google News RSS — flags 'real bad news' vs 'just a dip'."""
from __future__ import annotations

import email.utils
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from . import config as C

UA = {"User-Agent": "Mozilla/5.0 (StockCrawler; personal use)"}

NEG = [
    r"fraud", r"\braid", r"probe", r"investigat", r"sebi (order|ban|bars|penalt|notice)", r"default",
    r"downgrad", r"resign", r"auditor", r"pledge", r"insolvenc", r"\bnclt\b", r"\bed\b (search|raid)",
    r"income tax (search|raid)", r"loss widen", r"(profit|net profit|earnings|revenue) (falls|fell|drops|dropped|"
    r"declines|plunges|slumps|tanks|down)", r"miss(es)? estimate", r"weak (guidance|outlook|q[1-4])",
    r"\bcuts? (guidance|target|forecast)", r"target (cut|lowered)", r"recall", r"penalt", r"lawsuit",
    r"\bfire\b", r"(workers|labou?r|employees)'? strike", r"shut ?down", r"warning letter", r"import alert", r"usfda (observation|warning)",
    r"block deal.*(promoter|exit)", r"promoter.*(sell|stake sale)", r"\bban\b",
]
POS = [
    r"order (win|inflow)", r"bags? .*order", r"wins? .*(order|contract)", r"upgrad", r"beats? estimate",
    r"(profit|earnings|revenue) (rises|rose|jumps|jumped|surges|soars|up)", r"buyback", r"dividend",
    r"target (raised|hike)", r"approval", r"record high", r"expansion", r"acquires?|acquisition",
]
NEG_RE = re.compile("|".join(NEG), re.I)
POS_RE = re.compile("|".join(POS), re.I)


def classify(title: str) -> str:
    if NEG_RE.search(title):
        return "neg"
    if POS_RE.search(title):
        return "pos"
    return "neutral"


def headlines(name: str, symbol: str, limit: int = 6) -> list[dict]:
    clean = re.sub(r"\b(Ltd|Limited|Ltd\.)\b\.?", "", name).strip()
    q = f'"{clean}" (share OR stock OR shares) when:{C.NEWS_LOOKBACK_DAYS}d'
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q) +
           "&hl=en-IN&gl=IN&ceid=IN:en")
    try:
        r = requests.get(url, headers=UA, timeout=12)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"[news] {symbol}: {e}")
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=C.NEWS_LOOKBACK_DAYS)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        src = (it.findtext("source") or "").strip()
        try:
            dt = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "")
        except Exception:
            dt = None
        if dt and dt < cutoff:
            continue
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        items.append({"title": title, "link": link, "source": src,
                      "date": dt.strftime("%Y-%m-%d") if dt else "", "tone": classify(title)})
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:limit]


def enrich(cands: list[dict]) -> None:
    """Adds news + news_flag ('risk' | 'positive' | 'none' | 'quiet') to each candidate in place."""
    for c in cands:
        items = headlines(c["name"], c["symbol"])
        c["news"] = items
        tones = {i["tone"] for i in items}
        c["news_flag"] = ("risk" if "neg" in tones else "positive" if "pos" in tones
                          else "none" if items else "quiet")
        time.sleep(0.6)
