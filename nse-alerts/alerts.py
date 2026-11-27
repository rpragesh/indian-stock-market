#!/usr/bin/env python3
"""nse-alerts: price, stop, target and square-off reminders.

Claude fetches live prices with the broker connector (Groww: get_ltp) and
passes them in; this says what rings. Run it on a schedule (for example
every 5 minutes while the market is open) to get reminders.

    python3 alerts.py check --ltp INFY=1171.5 --ltp SBIN=811.2
    python3 alerts.py check                          # clock reminders, plus nse/prices.json if fresh
    python3 alerts.py add --symbol SBIN --above 815 --note "day high"
    python3 alerts.py list
    python3 alerts.py remove --id 2

It checks open trades in the journal (stop, target, flat-by), today's plan
(entry reached, or ran away), your own price alerts, and the clock (opening
bell, end of the entry window, flat-by, square-off). Analysis only: an alert
is a reminder, and nothing here places, modifies or cancels an order.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import nselib  # noqa: E402
from nselib import market  # noqa: E402

NEAR_PCT = 0.15        # "close to" means within this % of the price
FLAT_WARN_MIN = 15     # start warning this many minutes before flat-by
PRICE_MAX_AGE_MIN = 10


def _mins(hm):
    h, m = map(int, hm.split(":"))
    return h * 60 + m


def load_alerts():
    return nselib.read_json(nselib.path("alerts.json"), {"alerts": []})


def save_alerts(a):
    nselib.write_json(nselib.path("alerts.json"), a)


def fresh_prices(now):
    p = nselib.read_json(nselib.path("prices.json"))
    if not p:
        return {}, None
    try:
        t = dt.datetime.strptime(p["as_of"], "%Y-%m-%d %H:%M").replace(tzinfo=now.tzinfo)
    except (KeyError, ValueError):
        return {}, "nse/prices.json has no as_of time"
    age = (now - t).total_seconds() / 60
    if age > PRICE_MAX_AGE_MIN:
        return {}, "prices in nse/prices.json are %d minutes old: fetch fresh ones" % age
    return p.get("ltp", {}), None


def check(cfg, now, ltp, journal, plan, alerts):
    rings, notes = [], []
    clock = market.status(now, cfg)
    t = _mins(now.strftime("%H:%M"))
    today = now.strftime("%Y-%m-%d")
    near = lambda a, b: abs(a - b) / b * 100 <= NEAR_PCT  # noqa: E731

    # ---- the clock ----
    if clock["trading_day"]:
        if _mins(cfg["market_open"]) <= t < _mins(cfg["market_open"]) + 5:
            rings.append(("bell", "Market open (09:15 IST). No entries before %s." % cfg["no_entries_before"]))
        if _mins(cfg["no_entries_after"]) <= t < _mins(cfg["no_entries_after"]) + 5:
            rings.append(("window", "Entry window closed at %s: no new trades today." % cfg["no_entries_after"]))
    opens = [x for x in nselib.open_trades(journal)]
    fb, so = _mins(clock["flat_by"]), _mins(clock["square_off"])
    if opens and clock["trading_day"]:
        names = ", ".join("%s (%d)" % (x["symbol"], x["qty"]) for x in opens)
        if t >= so:
            rings.append(("square-off", "Past the broker's %s square-off with %s still open in the journal. Check your positions and close it in the journal." % (clock["square_off"], names)))
        elif t >= fb:
            rings.append(("flat-by", "EXIT NOW: past flat-by %s. Cancel the stop and sell %s." % (clock["flat_by"], names)))
        elif t >= fb - FLAT_WARN_MIN:
            rings.append(("flat-by", "%d minutes to flat-by %s: plan the exit for %s." % (fb - t, clock["flat_by"], names)))

    # ---- open trades ----
    for x in opens:
        px = ltp.get(x["symbol"])
        if px is None:
            notes.append("no price for open trade %s" % x["symbol"])
            continue
        if px <= x["stop"]:
            rings.append(("stop", "%s %.2f is at or under the stop %.2f. If your SL-M filled, close it: ticket.py close --symbol %s --exit PRICE --reason stop." % (x["symbol"], px, x["stop"], x["symbol"])))
        elif px >= x["target"]:
            rings.append(("target", "%s %.2f reached the target %.2f: cancel the stop, then sell %d." % (x["symbol"], px, x["target"], x["qty"])))
        elif near(px, x["stop"]):
            rings.append(("near-stop", "%s %.2f is close to the stop %.2f." % (x["symbol"], px, x["stop"])))
        elif near(px, x["target"]):
            rings.append(("near-target", "%s %.2f is close to the target %.2f." % (x["symbol"], px, x["target"])))

    # ---- today's plan, not yet taken ----
    if plan and plan.get("date") == today and not any(x["symbol"] == plan["symbol"] for x in opens):
        px = ltp.get(plan["symbol"])
        if px is not None:
            risk = plan["risk_per_share"]
            if px <= plan["stop"]:
                rings.append(("plan", "%s %.2f is under the planned stop %.2f: the setup has failed, skip it." % (plan["symbol"], px, plan["stop"])))
            elif px > plan["entry"] + 0.5 * risk:
                rings.append(("plan", "%s %.2f ran more than half the risk past the planned entry %.2f: don't chase. Re-plan or skip." % (plan["symbol"], px, plan["entry"])))
            elif px >= plan["entry"]:
                rings.append(("plan", "%s %.2f is at the planned entry %.2f. If it is still within your rules: nse-budget, nse-risk, then nse-ticket." % (plan["symbol"], px, plan["entry"])))

    # ---- the user's own alerts ----
    for a in alerts["alerts"]:
        if a.get("fired"):
            continue
        px = ltp.get(a["symbol"])
        if px is None:
            continue
        hit = (a.get("above") is not None and px >= a["above"]) or (a.get("below") is not None and px <= a["below"])
        if hit:
            a["fired"] = now.strftime("%Y-%m-%d %H:%M")
            lvl = "above %.2f" % a["above"] if a.get("above") is not None else "below %.2f" % a["below"]
            rings.append(("alert", "#%d %s %.2f is %s%s." % (a["id"], a["symbol"], px, lvl, (": " + a["note"]) if a.get("note") else "")))
    return rings, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description="Price, stop, target and square-off reminders.")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check")
    ck.add_argument("--ltp", action="append", default=[], help="SYMBOL=PRICE, repeatable")
    ck.add_argument("--json", action="store_true")
    ad = sub.add_parser("add")
    ad.add_argument("--symbol", required=True)
    g = ad.add_mutually_exclusive_group(required=True)
    g.add_argument("--above", type=float)
    g.add_argument("--below", type=float)
    ad.add_argument("--note", default="")
    sub.add_parser("list")
    rm = sub.add_parser("remove")
    rm.add_argument("--id", type=int, required=True)
    a = ap.parse_args(argv)
    cfg = nselib.config()
    now = market.now_ist(a.now)
    alerts = load_alerts()

    if a.cmd == "add":
        nid = max([x["id"] for x in alerts["alerts"]] + [0]) + 1
        alerts["alerts"].append({"id": nid, "symbol": a.symbol.upper(), "above": a.above, "below": a.below,
                                 "note": a.note, "created": now.strftime("%Y-%m-%d %H:%M"), "fired": None})
        save_alerts(alerts)
        print("Alert #%d: %s %s %.2f." % (nid, a.symbol.upper(), "above" if a.above is not None else "below",
                                          a.above if a.above is not None else a.below))
        return 0
    if a.cmd == "list":
        if not alerts["alerts"]:
            print("No price alerts.")
        for x in alerts["alerts"]:
            print("#%d %s %s %.2f%s%s" % (x["id"], x["symbol"], "above" if x["above"] is not None else "below",
                                          x["above"] if x["above"] is not None else x["below"],
                                          (" (" + x["note"] + ")") if x["note"] else "",
                                          "  fired %s" % x["fired"] if x["fired"] else ""))
        return 0
    if a.cmd == "remove":
        before = len(alerts["alerts"])
        alerts["alerts"] = [x for x in alerts["alerts"] if x["id"] != a.id]
        save_alerts(alerts)
        print("Removed #%d." % a.id if len(alerts["alerts"]) < before else "No alert #%d." % a.id)
        return 0

    ltp, stale = {}, None
    if a.ltp:
        for kv in a.ltp:
            k, v = kv.split("=", 1)
            ltp[k.strip().upper()] = float(v)
        nselib.write_json(nselib.path("prices.json"), {"as_of": now.strftime("%Y-%m-%d %H:%M"), "ltp": ltp})
    else:
        ltp, stale = fresh_prices(now)
    rings, notes = check(cfg, now, ltp, nselib.journal(), nselib.read_json(nselib.path("plan.json")), alerts)
    save_alerts(alerts)
    if stale:
        notes.append(stale)
    if a.json:
        print(json.dumps({"as_of": now.strftime("%Y-%m-%d %H:%M"), "rings": [{"kind": k, "text": t} for k, t in rings],
                          "notes": notes}, indent=2))
        return 0
    print("%s IST: %s" % (now.strftime("%Y-%m-%d %H:%M"), "%d alert(s)" % len(rings) if rings else "nothing to report"))
    for k, t in rings:
        print("  [%s] %s" % (k, t))
    for n in notes:
        print("  note: %s" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
