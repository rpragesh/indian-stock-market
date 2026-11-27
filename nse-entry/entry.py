#!/usr/bin/env python3
"""nse-entry: watch one setup bar by bar and say the moment it triggers.

Reads the stock's saved candles (nse/candles/SYMBOL.json or .csv, refreshed
from the broker connector before each check) and only bars that have closed.

    python3 entry.py watch --symbol INFY --setup orb              # now
    python3 entry.py watch --symbol INFY --setup orb --at 14:10 --write
    python3 entry.py watch --symbol SBIN --setup level --level 812 --stop 805
    python3 entry.py replay --symbol INFY --setup orb --date 2026-11-26   # every bar of a day

On a trigger, --write saves nse/entry.json, and `exit.py plan --from-entry`
picks it up. Analysis only: nothing here places an order.
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

SETUPS = ("orb", "flag", "bounce", "level")


def candle_file(symbol, folder=None):
    folder = folder or nselib.path("candles")
    for pat in ("%s.json", "%s.csv", "%s-5m.json", "%s-5m.csv"):
        for f in glob.glob(os.path.join(folder, pat % symbol.upper())):
            return f
    return None


def level_setup(today, level, stop, tick):
    for b in today:
        if stop is not None and b["c"] < stop:
            return {"setup": "level", "state": "failed", "trigger": level, "entry": None, "stop": stop,
                    "stop_rule": "your price", "bar": b["hm"], "why": "closed under your stop %.2f at %s" % (stop, b["hm"])}
        if b["c"] > level:
            return {"setup": "level", "state": "triggered", "trigger": level, "entry": nselib.to_tick(b["c"], tick),
                    "stop": stop, "stop_rule": "your price", "bar": b["hm"],
                    "why": "closed %.2f above your level %.2f at %s" % (b["c"], level, b["hm"])}
    return {"setup": "level", "state": "forming", "trigger": level, "entry": None, "stop": stop,
            "stop_rule": "your price", "bar": today[-1]["hm"] if today else None,
            "why": "waiting for a close above %.2f" % level}


def check(cfg, symbol, setup, bars_, date, at, level=None, stop=None):
    tick = nselib.tick(cfg)
    days = B.sessions(bars_)
    if date not in days:
        return {"symbol": symbol, "state": "no-data", "why": "no candles for %s: refresh them from the connector" % date}
    today = B.until(days[date], at) if at else days[date]
    if not today:
        return {"symbol": symbol, "state": "no-data", "why": "no closed bars yet at %s" % at}
    history = [b for d in list(days)[:-1] if d < date for b in days[d]][-80:]
    if setup == "level":
        if level is None:
            raise ValueError("a level setup needs --level")
        r = level_setup(today, level, stop, tick)
    else:
        r = S.DETECTORS[setup](today, S.params(cfg), tick, history)
        if r is None:
            r = {"setup": setup, "state": "none", "why": "no %s setup in the bars so far" % setup}
    r = dict(r, symbol=symbol.upper(), date=date, last=today[-1]["c"], last_bar=today[-1]["hm"])
    if at:
        clock = market.status(market.now_ist("%s %s" % (date, at)), cfg)
        if r["state"] in ("forming", "triggered") and not clock["can_enter"]:
            r["late"] = clock["reason"]
    return r


def describe(r):
    if r["state"] == "triggered":
        s = "TRIGGERED  %s %s at %s: %s.\n  Entry %.2f, stop %s." % (
            r["symbol"], r["setup"], r["bar"], r["why"], r["entry"],
            "%.2f (%s)" % (r["stop"], r.get("stop_rule")) if r.get("stop") is not None else "not set: name one")
        if r.get("volume_ok") is False:
            s += " Volume was weak."
    elif r["state"] == "forming":
        s = "WAITING    %s %s, last %.2f at %s: %s." % (r["symbol"], r["setup"], r["last"], r["last_bar"], r["why"])
    else:
        s = "%-10s %s %s: %s." % (r["state"].upper(), r["symbol"], r.get("setup", ""), r["why"])
    if r.get("late"):
        s += "\n  Too late to enter: %s." % r["late"]
    return s


def main(argv=None):
    ap = argparse.ArgumentParser(description="Watch a setup bar by bar.")
    ap.add_argument("cmd", choices=("watch", "replay"))
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--setup", choices=SETUPS, default="orb")
    ap.add_argument("--level", type=float)
    ap.add_argument("--stop", type=float)
    ap.add_argument("--date")
    ap.add_argument("--at", help="HH:MM IST: bars closed by then")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--file", help="candle file (default nse/candles/SYMBOL.json|csv)")
    ap.add_argument("--write", action="store_true", help="on a trigger, write nse/entry.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    f = a.file or candle_file(a.symbol)
    if not f:
        print("No candles for %s in %s: fetch its 5-minute candles with the connector and save them there."
              % (a.symbol.upper(), nselib.path("candles")))
        return 1
    bars_ = B.load(f)
    now = market.now_ist(a.now)
    date = a.date or (now.strftime("%Y-%m-%d") if any(b["d"] == now.strftime("%Y-%m-%d") for b in bars_) else bars_[-1]["d"])

    if a.cmd == "replay":
        day = B.sessions(bars_).get(date, [])
        step = B.interval_minutes(day) if len(day) > 1 else 5
        last_state = None
        for b in day:
            h, m = map(int, b["hm"].split(":"))
            at = "%02d:%02d" % divmod(h * 60 + m + step, 60)
            r = check(cfg, a.symbol, a.setup, bars_, date, at, a.level, a.stop)
            key = (r["state"], r.get("bar") if r["state"] == "triggered" else None)
            if key != last_state:
                print("%s  %s" % (at, describe(r).replace("\n", "\n       ")))
                last_state = key
        return 0

    at = a.at
    if not at and date == now.strftime("%Y-%m-%d") and market.status(now, cfg)["phase"] == "open":
        at = now.strftime("%H:%M")
    try:
        r = check(cfg, a.symbol, a.setup, bars_, date, at, a.level, a.stop)
    except ValueError as e:
        print("REFUSED: %s" % e)
        return 2
    if a.write and r["state"] == "triggered":
        nselib.write_json(nselib.path("entry.json"), dict(r, written_at=now.strftime("%Y-%m-%d %H:%M")))
    print(json.dumps(r, indent=2) if a.json else describe(r))
    if r["state"] == "triggered" and not a.json:
        print("  Next: exit.py plan --from-entry%s" % ("" if a.write else " (run again with --write first)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
