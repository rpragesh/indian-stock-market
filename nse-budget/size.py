#!/usr/bin/env python3
"""nse-budget: how many shares, from your capital and your max loss, after charges.

Reads nse/plan.json (nse-exit) and nse/config.json, writes ONE proposed order
to nse/order.json with --write. The stop decides the size: the loss at the
stop, charges included, must fit inside max_loss_per_trade_inr.

    python3 size.py
    python3 size.py --write
    python3 size.py --capital 50000 --max-loss 300 --json

Analysis only: nothing here places an order.
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import nselib  # noqa: E402
from nselib import charges, market  # noqa: E402


class Refused(Exception):
    pass


def costs(cfg, plan, qty):
    """Net loss at the stop and net P&L at the target for `qty` shares, charges included."""
    b, ex, pr = cfg["broker"], plan["exchange"], plan["product"]
    at_stop = charges.trade_charges(b, plan["entry"], plan["stop"], qty, pr, ex)
    at_target = charges.trade_charges(b, plan["entry"], plan["target"], qty, pr, ex)
    return at_stop, at_target


def size(cfg, plan, journal, now=None):
    now = now or market.now_ist()
    if plan.get("date") != now.strftime("%Y-%m-%d"):
        raise Refused("the plan is for %s, not today: make a new one with nse-exit" % plan.get("date"))
    if plan.get("side") != "BUY":
        raise Refused("Phase 1 sizes longs only")
    entry, risk = plan["entry"], plan["risk_per_share"]
    max_loss = float(cfg["max_loss_per_trade_inr"])
    equity = nselib.equity(cfg, journal)
    cash = nselib.cash(cfg, journal)

    caps = {}
    caps["max loss per trade"] = int(math.floor(max_loss / risk))
    caps["max position"] = int(math.floor(equity * float(cfg["max_position_pct"]) / 100.0 / entry))
    spendable = cash - equity * float(cfg.get("cash_buffer_pct", 0)) / 100.0
    caps["cash after buffer"] = int(math.floor(max(spendable, 0) / entry))

    qty = min(caps.values())
    decided = min(caps, key=lambda k: caps[k])
    # charges push the loss at the stop up: step down until it fits
    while qty > 0 and -costs(cfg, plan, qty)[0]["net_pnl"] > max_loss:
        qty -= 1
        decided = "max loss per trade (after charges)"
    if qty < 1:
        if caps["max loss per trade"] < 1 or decided.startswith("max loss"):
            raise Refused("even 1 share loses more than your %s max loss at this stop (risk %.2f a share plus "
                          "charges). Use a closer stop from nse-exit, or skip the trade."
                          % (nselib.inr(max_loss), risk))
        raise Refused("not enough room for 1 share: limited by %s" % decided)

    at_stop, at_target = costs(cfg, plan, qty)
    loss = -at_stop["net_pnl"]
    gain = at_target["net_pnl"]
    order = {
        "date": plan["date"],
        "written_at": now.strftime("%Y-%m-%d %H:%M"),
        "symbol": plan["symbol"],
        "exchange": plan["exchange"],
        "product": plan["product"],
        "side": "BUY",
        "order_type": "LIMIT",
        "qty": qty,
        "entry": plan["entry"],
        "stop": plan["stop"],
        "target": plan["target"],
        "flat_by": plan["flat_by"],
        "setup": plan.get("setup"),
        "value": round(qty * entry, 2),
        "max_loss_net": round(loss, 2),
        "charges_at_stop": at_stop["total_charges"],
        "net_pnl_at_target": round(gain, 2),
        "charges_at_target": at_target["total_charges"],
        "reward_risk_net": round(gain / loss, 2) if loss > 0 else None,
        "breakeven_exit": charges.breakeven_exit(cfg["broker"], entry, qty, "long", plan["product"], plan["exchange"]),
        "decided_by": decided,
        "caps": caps,
        "broker": cfg["broker"],
        "paper": bool(cfg.get("paper", True)),
    }
    order["fingerprint"] = nselib.fingerprint(order)
    return order


def describe(o, cfg):
    return "\n".join([
        "Size: %s %d shares of %s on %s at %.2f (%s), %s" % (
            "PAPER" if o["paper"] else "LIVE TICKET", o["qty"], o["symbol"], o["exchange"], o["entry"],
            o["product"], nselib.inr(o["value"])),
        "  Decided by     %s (caps: %s)" % (o["decided_by"], ", ".join("%s %d" % kv for kv in o["caps"].items())),
        "  At the stop    %.2f: lose %s net, of which %s is charges (limit %s)" % (
            o["stop"], nselib.inr(o["max_loss_net"]), nselib.inr(o["charges_at_stop"]),
            nselib.inr(float(cfg["max_loss_per_trade_inr"]))),
        "  At the target  %.2f: make %s net after %s of charges" % (
            o["target"], nselib.inr(o["net_pnl_at_target"]), nselib.inr(o["charges_at_target"])),
        "  Reward:risk    %.2f after charges" % o["reward_risk_net"],
        "  Breakeven      %.2f (the exit that nets zero)" % o["breakeven_exit"],
        "  Flat by        %s IST" % o["flat_by"],
        "Proposal only. nse-risk checks it next; nothing is placed.",
    ])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Size the plan in nse/plan.json to your limits, after charges.")
    ap.add_argument("--capital", type=float, help="override paper_capital_inr for this run")
    ap.add_argument("--max-loss", type=float, help="override max_loss_per_trade_inr for this run")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--write", action="store_true", help="write nse/order.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    cfg = nselib.config()
    if a.capital is not None:
        cfg["paper_capital_inr"] = a.capital
    if a.max_loss is not None:
        cfg["max_loss_per_trade_inr"] = a.max_loss
    plan = nselib.read_json(nselib.path("plan.json"))
    if not plan:
        print("No nse/plan.json: run nse-exit first.")
        return 1
    try:
        o = size(cfg, plan, nselib.journal(), market.now_ist(a.now))
    except Refused as e:
        print("REFUSED: %s" % e)
        return 2
    if a.write:
        nselib.write_json(nselib.path("order.json"), o)
    print(json.dumps(o, indent=2) if a.json else describe(o, cfg))
    return 0


if __name__ == "__main__":
    sys.exit(main())
