#!/usr/bin/env python3
"""nse-scanner: scan saved NSE candles for opening-range breakouts, bull flags and oversold bounces.

Claude saves each candidate's intraday candles (from the broker connector)
to nse/candles/SYMBOL.json or SYMBOL.csv; this reads them all.

    python3 scan.py                         # today, bars closed by now (IST)
    python3 scan.py --at 10:30              # replay today as of 10:30
    python3 scan.py --date 2026-11-26 --at 11:00 --setups orb,flag
    python3 scan.py --write --json          # also write nse/scan.json

Analysis only. A hit is a pattern match, not a recommendation, and nothing here places an order.
"""

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import bars as B  # noqa: E402
import nselib  # noqa: E402
import setups as S  # noqa: E402
from nselib import market  # noqa: E402

RANK = {"triggered": 0, "forming": 1, "stale": 2, "failed": 3}
SETUP_RANK = {"orb": 0, "flag": 1, "bounce": 2}


def symbol_of(path):
    name = os.path.splitext(os.path.basename(path))[0].upper()
    for suffix in ("-5M", "-1M", "-15M", "_5M", "_1M", "_15M"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name


def scan_symbol(symbol, bars_, cfg, date, at, which=None):
    p = S.params(cfg)
    tick = nselib.tick(cfg)
    days = B.sessions(bars_)
    if date not in days:
        return {"symbol": symbol, "skipped": "no candles for %s" % date}
    prior = [d for d in days if d < date]
    turnover = [sum(b["c"] * b["v"] for b in days[d]) for d in prior[-5:]]
    avg_turn = sum(turnover) / len(turnover) if turnover else None
    min_turn = float(cfg.get("min_day_turnover_inr", 1e8))
    if avg_turn is not None and avg_turn < min_turn:
        return {"symbol": symbol, "skipped": "thin: %s a day traded, under %s" % (nselib.inr(avg_turn), nselib.inr(min_turn))}
    today = B.until(days[date], at) if at else days[date]
    if not today:
        return {"symbol": symbol, "skipped": "no closed bars yet at %s" % at}
    history = [b for d in prior[-2:] for b in days[d]]
    hits = S.detect(today, p, tick, history, which)
    last = today[-1]
    return {"symbol": symbol, "last": last["c"], "last_bar": last["hm"], "vwap": round(B.vwap(today), 2),
            "day_change_pct": round((last["c"] / days[prior[-1]][-1]["c"] - 1) * 100, 2) if prior else None,
            "avg_day_turnover": round(avg_turn, 0) if avg_turn else None, "hits": hits}


def next_step(sym, h):
    if h["state"] in ("stale", "failed"):
        return "skip: the setup is %s" % h["state"]
    if h["state"] != "triggered":
        return "wait for a close above %.2f (nse-entry can watch it)" % h["trigger"]
    if h["setup"] == "orb":
        return "exit.py plan --symbol %s --entry %.2f --or-high %.2f --or-low %.2f" % (
            sym, h["entry"], h["or_high"], h["or_low"])
    return "exit.py plan --symbol %s --entry %.2f --stop price:%.2f --setup %s" % (sym, h["entry"], h["stop"], h["setup"])


def run(cfg, files, date, at, which=None):
    blocked = set(x.upper() for x in cfg.get("blocked", []))
    rows, skipped = [], []
    for f in files:
        sym = symbol_of(f)
        if sym in blocked:
            skipped.append({"symbol": sym, "skipped": "on your blocked list"})
            continue
        try:
            r = scan_symbol(sym, B.load(f), cfg, date, at, which)
        except (ValueError, KeyError, IndexError) as e:
            skipped.append({"symbol": sym, "skipped": "could not read %s: %s" % (os.path.basename(f), e)})
            continue
        if "skipped" in r:
            skipped.append(r)
            continue
        for h in r["hits"]:
            rows.append(dict(h, symbol=sym, last=r["last"], vwap=r["vwap"], day_change_pct=r["day_change_pct"],
                             next=next_step(sym, h)))
    rows.sort(key=lambda h: (RANK[h["state"]], not h.get("volume_ok", True), SETUP_RANK[h["setup"]], h["symbol"]))
    return {"date": date, "as_of": at, "scanned": len(files), "hits": rows, "skipped": skipped}


def describe(res):
    out = ["Scan %s as of %s IST: %d stocks, %d hits" % (res["date"], res["as_of"] or "close", res["scanned"], len(res["hits"]))]
    for h in res["hits"]:
        if h["state"] in ("stale", "failed"):
            continue
        out.append("  %-10s %-6s %-9s last %.2f  %s" % (h["symbol"], h["setup"], h["state"].upper(), h["last"], h["why"]))
        stop = "stop %.2f (%s)" % (h["stop"], h["stop_rule"]) if h.get("stop") else ""
        out.append("  %10s entry %s, %s -> %s" % ("", "%.2f" % h["entry"] if h["entry"] else "on a close above %.2f" % h["trigger"], stop, h["next"]))
    quiet = [h for h in res["hits"] if h["state"] in ("stale", "failed")]
    if quiet:
        out.append("  Also: " + "; ".join("%s %s %s" % (h["symbol"], h["setup"], h["state"]) for h in quiet))
    for s in res["skipped"]:
        out.append("  skipped %s: %s" % (s["symbol"], s["skipped"]))
    out.append("Pattern matches, not recommendations. Plan any of them with nse-exit, then size and check.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scan saved candles for ORB, flag and oversold-bounce setups.")
    ap.add_argument("--dir", default=None, help="candle folder (default nse/candles)")
    ap.add_argument("--date", help="YYYY-MM-DD (default: today IST, or the latest date in the files)")
    ap.add_argument("--at", help="HH:MM: only bars closed by then (default: now while the market is open)")
    ap.add_argument("--setups", help="comma list of orb,flag,bounce (default all)")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    folder = a.dir or nselib.path("candles")
    files = sorted(glob.glob(os.path.join(folder, "*.json")) + glob.glob(os.path.join(folder, "*.csv")))
    if not files:
        print("No candles in %s. Fetch each stock's 5-minute candles with the broker connector and save them there." % folder)
        return 1
    now = market.now_ist(a.now)
    date, at = a.date, a.at
    if not date:
        latest = max(B.load(f)[-1]["d"] for f in files if B.load(f))
        date = now.strftime("%Y-%m-%d") if now.strftime("%Y-%m-%d") <= latest else latest
    if not at and date == now.strftime("%Y-%m-%d") and market.status(now, cfg)["phase"] == "open":
        at = now.strftime("%H:%M")
    which = a.setups.split(",") if a.setups else None
    res = run(cfg, files, date, at, which)
    if a.write:
        nselib.write_json(nselib.path("scan.json"), res)
    print(json.dumps(res, indent=2) if a.json else describe(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
