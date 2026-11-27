#!/usr/bin/env python3
"""nse-risk: PASS or BLOCK the proposed order in nse/order.json against your limits.

Recomputes every number from the order, the config, the charge rates and
the paper journal; it never trusts the totals written in the order. Writes
the verdict with the order's fingerprint to nse/state/risk.json, which
nse-ticket requires.

    python3 check.py
    python3 check.py --json
    python3 check.py --no-write
    python3 check.py --now "2026-11-27 10:06"

Exit code 0 = PASS, 1 = BLOCK. Analysis only: nothing here places an order.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import nselib  # noqa: E402
from nselib import charges, market  # noqa: E402


def check(cfg, order, journal, now=None):
    now = now or market.now_ist()
    today = now.strftime("%Y-%m-%d")
    blocks, warns, facts = [], [], {}

    def block(name, why):
        blocks.append("%s: %s" % (name, why))

    # ---- format ----
    sym = str(order.get("symbol", "")).upper()
    qty, entry, stop, target = order.get("qty"), order.get("entry"), order.get("stop"), order.get("target")
    if not re.match(r"^[A-Z0-9&\-]{1,20}$", sym):
        block("format", "no valid symbol")
    if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
        block("format", "quantity must be a whole number of shares, 1 or more")
    if order.get("side") != "BUY":
        block("format", "Phase 1 checks long entries (BUY) only")
    if order.get("order_type") != "LIMIT":
        block("format", "entries must be LIMIT orders")
    if not all(isinstance(x, (int, float)) and x > 0 for x in (entry, stop or 1, target or 1)):
        block("format", "prices must be positive numbers")
    if order.get("date") != today:
        block("date", "the order is for %s, not today (%s): size it again" % (order.get("date"), today))
    if blocks:
        return {"verdict": "BLOCK", "blocks": blocks, "warnings": warns, "facts": facts}

    # ---- what is allowed to trade ----
    if order.get("product") not in ("intraday", "delivery"):
        block("product", "only cash equity (intraday or delivery) is allowed")
    if order.get("product") != cfg.get("product"):
        block("product", "order is %s but your config says %s" % (order.get("product"), cfg.get("product")))
    if order.get("exchange") not in ("NSE", "BSE"):
        block("exchange", "NSE or BSE only")
    if sym in [b.upper() for b in cfg.get("blocked", [])]:
        block("blocked", "%s is on your blocked list" % sym)

    # ---- stop and target ----
    if stop is None:
        if cfg.get("require_stop", True):
            block("stop", "no stop, and your rules require one")
        stop = entry
    elif stop >= entry:
        block("stop", "the stop %.2f is not under the entry %.2f" % (stop, entry))
    if target is None or target <= entry:
        block("target", "the target must be above the entry")
    if blocks:
        return {"verdict": "BLOCK", "blocks": blocks, "warnings": warns, "facts": facts}

    b, pr, ex = cfg["broker"], order["product"], order["exchange"]
    at_stop = charges.trade_charges(b, entry, stop, qty, pr, ex)
    at_target = charges.trade_charges(b, entry, target, qty, pr, ex)
    loss, gain = -at_stop["net_pnl"], at_target["net_pnl"]
    rr = gain / loss if loss > 0 else 0.0
    facts.update(max_loss_net=round(loss, 2), net_pnl_at_target=round(gain, 2), reward_risk_net=round(rr, 2),
                 charges_round_trip=at_stop["total_charges"])

    max_loss = float(cfg["max_loss_per_trade_inr"])
    if loss > max_loss:
        block("loss", "%s at the stop after charges, over your %s max loss per trade"
              % (nselib.inr(loss), nselib.inr(max_loss)))
    if gain <= 0:
        block("target", "the target nets %s after charges: it cannot make money" % nselib.inr(gain))
    elif rr < float(cfg.get("min_reward_risk", 0)):
        block("reward:risk", "%.2f after charges, under your minimum %.2f" % (rr, float(cfg["min_reward_risk"])))

    # ---- size and money ----
    equity, cash = nselib.equity(cfg, journal), nselib.cash(cfg, journal)
    value = qty * entry
    facts.update(value=round(value, 2), equity=equity, cash_before=cash)
    cap = equity * float(cfg["max_position_pct"]) / 100.0
    if value > cap:
        block("position", "%s is over %s%% of your %s account (%s)"
              % (nselib.inr(value), cfg["max_position_pct"], nselib.inr(equity), nselib.inr(cap)))
    floor = equity * float(cfg.get("cash_buffer_pct", 0)) / 100.0
    if cash - value < floor:
        block("cash", "it would leave %s in cash, under your %s buffer" % (nselib.inr(cash - value), nselib.inr(floor)))

    # ---- the day ----
    todays = nselib.trades_on(journal, today)
    opens = nselib.open_trades(journal)
    realized_losses = -sum(min(t.get("net_pnl", 0.0), 0.0) for t in todays if t.get("status") == "closed")
    open_risk = sum(t.get("max_loss_net", 0.0) for t in opens)
    day_total = realized_losses + open_risk + loss
    max_day = float(cfg["max_daily_loss_inr"])
    facts.update(trades_today=len(todays), open_positions=len(opens),
                 day_loss_if_stopped=round(day_total, 2), max_daily_loss=max_day)
    if day_total > max_day:
        block("daily loss", "today's losses so far %s, plus open risk %s, plus this %s = %s, over your %s"
              % (nselib.inr(realized_losses), nselib.inr(open_risk), nselib.inr(loss), nselib.inr(day_total),
                 nselib.inr(max_day)))
    if len(todays) >= int(cfg["max_trades_per_day"]):
        block("trades", "%d of %d trades already taken today" % (len(todays), int(cfg["max_trades_per_day"])))
    if len(opens) >= int(cfg.get("max_open_positions", 99)):
        block("positions", "%d open already (max %d)" % (len(opens), int(cfg["max_open_positions"])))
    if any(t["symbol"] == sym for t in opens):
        block("duplicate", "you already have an open %s trade" % sym)

    # ---- the clock ----
    clock = market.status(now, cfg)
    facts.update(flat_by=clock["flat_by"])
    if not clock["can_enter"]:
        block("window", clock["reason"])

    # ---- warnings ----
    if not cfg.get("paper", True):
        warns.append("LIVE mode: the ticket is for a real order that you place yourself")
    try:
        age = (now.date() - dt.date.fromisoformat(at_stop["rates_as_of"])).days
        if age > 90:
            warns.append("charge rates are %d days old: check the broker's pricing page" % age)
    except ValueError:
        pass
    if order.get("fingerprint") and order["fingerprint"] != nselib.fingerprint(order):
        warns.append("the order was edited after nse-budget sized it; the numbers above are recomputed")
    if not clock["holidays_loaded"]:
        warns.append("no exchange holidays for %d in your config" % now.year)

    return {"verdict": "BLOCK" if blocks else "PASS", "blocks": blocks, "warnings": warns, "facts": facts}


def describe(order, r, cfg):
    f = r["facts"]
    out = ["%s  %s %s x %s @ %.2f, stop %.2f, target %.2f (%s)" % (
        r["verdict"], order.get("side"), order.get("qty"), order.get("symbol"), order.get("entry") or 0,
        order.get("stop") or 0, order.get("target") or 0, "paper" if cfg.get("paper", True) else "LIVE")]
    if "max_loss_net" in f:
        out.append("      max loss %s after charges (limit %s), reward:risk %.2f after charges (min %s)" % (
            nselib.inr(f["max_loss_net"]), nselib.inr(float(cfg["max_loss_per_trade_inr"])),
            f["reward_risk_net"], cfg.get("min_reward_risk")))
    if "trades_today" in f:
        out.append("      today: %d of %d trades, %d open, worst case for the day %s of %s" % (
            f["trades_today"], int(cfg["max_trades_per_day"]), f["open_positions"],
            nselib.inr(f["day_loss_if_stopped"]), nselib.inr(f["max_daily_loss"])))
    out += ["    - " + b for b in r["blocks"]]
    out += ["    ! " + w for w in r["warnings"]]
    out.append("A PASS is a rules check, not a recommendation and not your yes.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PASS or BLOCK nse/order.json against your limits.")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    order = nselib.read_json(nselib.path("order.json"))
    if not order:
        print("No nse/order.json: run nse-budget first.")
        return 1
    now = market.now_ist(a.now)
    r = check(cfg, order, nselib.journal(), now)
    r["fingerprint"] = nselib.fingerprint(order)
    r["date"] = now.strftime("%Y-%m-%d")
    r["checked_at"] = now.strftime("%Y-%m-%d %H:%M")
    if not a.no_write:
        nselib.write_json(nselib.path("state", "risk.json"), r)
    print(json.dumps(r, indent=2) if a.json else describe(order, r, cfg))
    return 0 if r["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
