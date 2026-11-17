"""Export raw daily history for offline research:  python -m scanner.export_data OUT_DIR

Writes prices.csv.gz (date,symbol,open,high,low,close,volume), universe.csv and a small report on data freshness.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

from . import data

YEARS = 6


def main(out):
    os.makedirs(out, exist_ok=True)
    universe, watch = data.load_universe("nifty500")
    raw = data.fetch_history(sorted(universe), YEARS)
    idx = data.fetch_index(YEARS)
    frames = []
    for s, df in raw.items():
        d = df.reset_index().rename(columns={"index": "date", "Date": "date"})
        d.columns = [str(c).lower() for c in d.columns]
        d.insert(1, "symbol", s)
        frames.append(d)
    if idx is not None:
        d = idx.reset_index().rename(columns={"index": "date", "Date": "date"})
        d.columns = [str(c).lower() for c in d.columns]
        d.insert(1, "symbol", "^NSEI")
        frames.append(d)
    allp = pd.concat(frames)
    allp["date"] = pd.to_datetime(allp["date"]).dt.strftime("%Y-%m-%d")
    allp = allp.round({"open": 2, "high": 2, "low": 2, "close": 2})
    allp.to_csv(os.path.join(out, "prices.csv.gz"), index=False, compression="gzip")
    pd.DataFrame([{"symbol": s, **v} for s, v in universe.items()]).to_csv(
        os.path.join(out, "universe.csv"), index=False)
    last = allp.groupby("symbol")["date"].max().value_counts().head(5).to_dict()
    ist = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d %H:%M IST")
    rep = {"generated": ist, "symbols": int(allp["symbol"].nunique()), "rows": int(len(allp)),
           "last_date_counts": last}
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(rep, f, indent=1)
    print(rep)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "export")
