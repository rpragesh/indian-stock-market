#!/usr/bin/env python3
"""nse-exit: decide how a trade ends before it starts. Writes nse/plan.json.

    python3 exit.py plan --symbol TATASTEEL --entry 152.40 --stop pct:1 --target 2R
    python3 exit.py plan --symbol INFY --entry 1612.50 --or-high 1610 --or-low 1596.20 --write
    python3 exit.py plan --symbol SBIN --entry 812.35 --stop price:805 --target price:828 --write
    python3 exit.py show

Long only in Phase 1. Analysis only: nothing here places an order.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import nselib  # noqa: E402
from nselib import market  # noqa: E402

MIN_RISK_PCT = 0.1   # a stop closer than 0.1% of the price is inside normal wiggle


class Refused(Exception):
    pass


def make_plan(cfg, symbol, entry, stop_rule="or-mid", target_rule="2R", or_high=None, or_low=None,
              now=None, setup=None):
    now = now or market.now_ist()
    t = nselib.tick(cfg)
    symbol = symbol.strip().upper()
    if not re.match(r"^[A-Z0-9&\-]{1,20}$", symbol):
        raise Refused("%r does not look like an NSE/BSE symbol" % symbol)
    if entry <= 0:
        raise Refused("entry must be positive")
    if symbol in [b.upper() for b in cfg.get("blocked", [])]:
        raise Refused("%s is on your blocked list" % symbol)

    clock = market.status(now, cfg)
    if cfg.get("product") == "intraday" and clock["phase"] == "open" and clock["must_exit_now"]:
        raise Refused("it is past the flat-by time (%s): no new intraday plans today" % clock["flat_by"])

    # ---- stop ----
    if stop_rule in ("or-mid", "or-low"):
        if or_high is None or or_low is None:
            raise Refused("an opening-range stop needs --or-high and --or-low (or name a stop: price:X or pct:X)")
        if or_low >= or_high:
            raise Refused("the opening-range low must be under the high")
        raw = (or_high + or_low) / 2.0 if stop_rule == "or-mid" else or_low
        why = ("opening-range midpoint (%.2f + %.2f) / 2" % (or_high, or_low)) if stop_rule == "or-mid" \
            else "opening-range low"
    elif stop_rule.startswith("price:"):
        raw, why = float(stop_rule[6:]), "your price"
    elif stop_rule.startswith("pct:"):
        pct = float(stop_rule[4:])
        if pct <= 0:
            raise Refused("pct stop must be above 0")
        raw, why = entry * (1 - pct / 100.0), "%g%% under the entry" % pct
    else:
        raise Refused("unknown stop rule %r (use or-mid, or-low, price:X or pct:X)" % stop_rule)
    stop = nselib.to_tick(raw, t, "down")   # away from the entry for a long
    if stop >= entry:
        raise Refused("the stop (%.2f) must be under the entry (%.2f) for a long" % (stop, entry))
    risk = round(entry - stop, 2)
    if risk / entry * 100 < MIN_RISK_PCT:
        raise Refused("the stop is only %.2f away (%.3f%% of the price): too tight to survive normal moves"
                      % (risk, risk / entry * 100))

    # ---- target ----
    m = re.match(r"^(\d+(?:\.\d+)?)R$", target_rule, re.I)
    if m:
        r = float(m.group(1))
        target = nselib.to_tick(entry + r * risk, t, "nearest")
        twhy = "%gR (%g times the risk)" % (r, r)
    elif target_rule.startswith("price:"):
        target = nselib.to_tick(float(target_rule[6:]), t, "nearest")
        twhy = "your price"
    else:
        raise Refused("unknown target rule %r (use 2R, 1.5R or price:X)" % target_rule)
    if target <= entry:
        raise Refused("the target (%.2f) must be above the entry (%.2f)" % (target, entry))

    return {
        "date": now.strftime("%Y-%m-%d"),
        "written_at": now.strftime("%Y-%m-%d %H:%M"),
        "symbol": symbol,
        "exchange": cfg.get("exchange", "NSE"),
        "product": cfg.get("product", "intraday"),
        "side": "BUY",
        "setup": setup or ("opening-range breakout" if stop_rule.startswith("or-") else "level"),
        "entry": round(entry, 2),
        "stop": stop,
        "stop_rule": why,
        "target": target,
        "target_rule": twhy,
        "risk_per_share": risk,
        "reward_per_share": round(target - entry, 2),
        "reward_risk_gross": round((target - entry) / risk, 2),
        "flat_by": clock["flat_by"],
        "square_off": clock["square_off"],
        "tick_size": t,
    }


def describe(p):
    lines = [
        "Exit plan: %s long on %s, %s (%s)" % (p["symbol"], p["exchange"], p["date"], p["setup"]),
        "  Entry          %.2f" % p["entry"],
        "  Stop           %.2f  %s, rounded down to the tick" % (p["stop"], p["stop_rule"]),
        "  Target         %.2f  %s" % (p["target"], p["target_rule"]),
        "  Risk a share   %.2f (%.2f%% of the entry)" % (p["risk_per_share"], p["risk_per_share"] / p["entry"] * 100),
        "  Reward:risk    %.2f before charges (nse-budget works it out after charges)" % p["reward_risk_gross"],
        "  Flat by        %s IST, win or lose (broker square-off %s)" % (p["flat_by"], p["square_off"]),
        "A stop is a plan, not a guarantee: a gap or a fast market can fill past it.",
    ]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Plan the stop, target and flat-by time for a long intraday trade.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("plan")
    pl.add_argument("--from-entry", action="store_true", help="take symbol, entry, range and stop from nse/entry.json")
    pl.add_argument("--symbol")
    pl.add_argument("--entry", type=float)
    pl.add_argument("--stop", default=None, help="or-mid (default), or-low, price:X or pct:X")
    pl.add_argument("--target", default="2R", help="2R, 1.5R, ... or price:X")
    pl.add_argument("--or-high", type=float)
    pl.add_argument("--or-low", type=float)
    pl.add_argument("--setup")
    pl.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    pl.add_argument("--write", action="store_true", help="write nse/plan.json")
    pl.add_argument("--json", action="store_true")
    sh = sub.add_parser("show")
    sh.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "show":
        p = nselib.read_json(nselib.path("plan.json"))
        if not p:
            print("No plan yet: run exit.py plan.")
            return 1
        print(json.dumps(p, indent=2) if a.json else describe(p))
        return 0

    cfg = nselib.config()
    if a.from_entry:
        e = nselib.read_json(nselib.path("entry.json"))
        if not e or e.get("state") != "triggered":
            print("REFUSED: no triggered setup in nse/entry.json: run nse-entry with --write first")
            return 2
        a.symbol = a.symbol or e["symbol"]
        a.entry = a.entry if a.entry is not None else e["entry"]
        a.setup = a.setup or e.get("setup")
        if e.get("or_high") is not None:
            a.or_high = a.or_high if a.or_high is not None else e["or_high"]
            a.or_low = a.or_low if a.or_low is not None else e["or_low"]
        if a.stop is None and e.get("stop_rule") not in ("or-mid", "or-low") and e.get("stop") is not None:
            a.stop = "price:%s" % e["stop"]
    if a.symbol is None or a.entry is None:
        print("REFUSED: give --symbol and --entry, or --from-entry")
        return 2
    a.stop = a.stop or "or-mid"
    try:
        p = make_plan(cfg, a.symbol, a.entry, a.stop, a.target, a.or_high, a.or_low,
                      market.now_ist(a.now), a.setup)
    except (Refused, ValueError) as e:
        print("REFUSED: %s" % e)
        return 2
    if a.write:
        nselib.write_json(nselib.path("plan.json"), p)
    print(json.dumps(p, indent=2) if a.json else describe(p))
    if a.write and not a.json:
        print("Wrote %s." % nselib.path("plan.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
