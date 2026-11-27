#!/usr/bin/env python3
"""nse-ticket: the order ticket you type into Groww or Kite yourself, and the trade journal.

    python3 ticket.py show                               # the ticket for nse/order.json (needs today's PASS)
    python3 ticket.py log --confirm                      # record it: a paper fill at the limit price
    python3 ticket.py log --confirm --fill 1612.65       # or the price you actually got
    python3 ticket.py close --symbol INFY --exit 1636 --reason target
    python3 ticket.py today                              # today's trades and net P&L

It never places, modifies or cancels an order, and it has no way to: it
only prints text and writes nse/state/journal.json. --confirm is passed only
after the user typed an explicit yes for this one ticket.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import nselib  # noqa: E402
from nselib import charges, market  # noqa: E402

REASONS = ("stop", "target", "flat", "manual")


class Refused(Exception):
    pass


def passed_order(now):
    order = nselib.read_json(nselib.path("order.json"))
    if not order:
        raise Refused("no nse/order.json: size a trade with nse-budget first")
    risk = nselib.read_json(nselib.path("state", "risk.json"))
    fp = nselib.fingerprint(order)
    if not risk or risk.get("fingerprint") != fp:
        raise Refused("nse-risk has not checked this exact order: run nse-risk first")
    if risk.get("date") != now.strftime("%Y-%m-%d"):
        raise Refused("the risk check is from %s, not today: run nse-risk again" % risk.get("date"))
    if risk.get("verdict") != "PASS":
        raise Refused("nse-risk BLOCKED this order: %s" % "; ".join(risk.get("blocks", [])))
    return order, risk, fp


def ticket_text(order, cfg):
    o = order
    broker = cfg["broker"]
    app = {"groww": "Groww", "zerodha": "Kite"}.get(broker, broker.title())
    product = {"groww": "Intraday", "zerodha": "MIS"}.get(broker, "Intraday") if o["product"] == "intraday" \
        else {"groww": "Delivery", "zerodha": "CNC"}.get(broker, "Delivery")
    mode = "PAPER TRADE: do not place this in %s, it is logged as a paper fill" % app if cfg.get("paper", True) \
        else "You place this yourself in %s. Nothing here sends it." % app
    return "\n".join([
        "ORDER TICKET  %s  (%s)" % (o["date"], mode),
        "",
        "1. Entry, now",
        "   %s > search %s (%s) > BUY > %s" % (app, o["symbol"], o["exchange"], product),
        "   Qty %d, order type LIMIT, price %.2f  (about %s)" % (o["qty"], o["entry"], nselib.inr(o["qty"] * o["entry"])),
        "",
        "2. Stop, as soon as the entry fills",
        "   %s > %s > SELL > %s > Qty %d > Stop loss market (SL-M), trigger %.2f" % (app, o["symbol"], product, o["qty"], o["stop"]),
        "   Max loss if it fills at the trigger: %s after charges. A gap can fill worse." % nselib.inr(o["max_loss_net"]),
        "",
        "3. Target %.2f" % o["target"],
        "   Do NOT also leave a sell limit at the target open next to the stop: if both fill you end up short.",
        "   When the price reaches %.2f, cancel the stop, then sell %d. Net about %s." % (o["target"], o["qty"], nselib.inr(o["net_pnl_at_target"])),
        "",
        "4. Out by %s IST, win or lose" % o["flat_by"],
        "   Cancel the stop and sell at market. The broker squares off later and charges for it.",
        "",
        "Breakeven exit %.2f. Not financial advice: you decide whether to place it." % o["breakeven_exit"],
    ])


def log_trade(cfg, now, fill=None):
    order, risk, fp = passed_order(now)
    j = nselib.journal()
    if any(t.get("fingerprint") == fp for t in j["trades"]):
        raise Refused("this exact ticket is already in the journal")
    if not cfg.get("paper", True) and fill is None:
        raise Refused("live mode: give --fill with the price %s actually filled at" % cfg["broker"].title())
    price = round(float(fill if fill is not None else order["entry"]), 2)
    trade = {
        "id": len(j["trades"]) + 1,
        "date": order["date"],
        "opened_at": now.strftime("%Y-%m-%d %H:%M"),
        "mode": "paper" if cfg.get("paper", True) else "manual",
        "broker": cfg["broker"],
        "symbol": order["symbol"],
        "exchange": order["exchange"],
        "product": order["product"],
        "qty": order["qty"],
        "entry": price,
        "stop": order["stop"],
        "target": order["target"],
        "flat_by": order["flat_by"],
        "max_loss_net": -charges.trade_charges(cfg["broker"], price, order["stop"], order["qty"],
                                               order["product"], order["exchange"])["net_pnl"],
        "fingerprint": fp,
        "status": "open",
    }
    j["trades"].append(trade)
    nselib.save_journal(j)
    return trade


def close_trade(cfg, symbol, exit_price, reason, now):
    if reason not in REASONS:
        raise Refused("reason must be one of %s" % ", ".join(REASONS))
    j = nselib.journal()
    opens = [t for t in nselib.open_trades(j) if t["symbol"] == symbol.upper()]
    if not opens:
        raise Refused("no open %s trade in the journal" % symbol.upper())
    t = opens[0]
    c = charges.trade_charges(t["broker"], t["entry"], exit_price, t["qty"], t["product"], t["exchange"])
    t.update(status="closed", exit=round(exit_price, 2), exit_reason=reason, closed_at=now.strftime("%Y-%m-%d %H:%M"),
             gross_pnl=c["gross_pnl"], charges=c["total_charges"], net_pnl=c["net_pnl"])
    nselib.save_journal(j)
    return t


def today_text(cfg, now):
    j = nselib.journal()
    d = now.strftime("%Y-%m-%d")
    ts = nselib.trades_on(j, d)
    lines = ["Journal %s (%s): %d trade(s)" % (d, "paper" if cfg.get("paper", True) else "live", len(ts))]
    for t in ts:
        if t["status"] == "open":
            lines.append("  #%d %s %d @ %.2f  OPEN  stop %.2f, target %.2f, out by %s" % (
                t["id"], t["symbol"], t["qty"], t["entry"], t["stop"], t["target"], t["flat_by"]))
        else:
            lines.append("  #%d %s %d @ %.2f -> %.2f (%s)  net %s after %s charges" % (
                t["id"], t["symbol"], t["qty"], t["entry"], t["exit"], t["exit_reason"],
                nselib.inr(t["net_pnl"]), nselib.inr(t["charges"])))
    lines.append("Net P&L today %s. Paper equity %s, cash %s." % (
        nselib.inr(nselib.realized_pnl(j, d)), nselib.inr(nselib.equity(cfg, j)), nselib.inr(nselib.cash(cfg, j))))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Order ticket and trade journal. Never places orders.")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    lg = sub.add_parser("log")
    lg.add_argument("--confirm", action="store_true", help="the user typed an explicit yes for this ticket")
    lg.add_argument("--fill", type=float)
    cl = sub.add_parser("close")
    cl.add_argument("--symbol", required=True)
    cl.add_argument("--exit", type=float, required=True)
    cl.add_argument("--reason", default="manual", choices=REASONS)
    sub.add_parser("today")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    now = market.now_ist(a.now)
    try:
        if a.cmd == "show":
            order, _, _ = passed_order(now)
            print(ticket_text(order, cfg))
        elif a.cmd == "log":
            if not a.confirm:
                raise Refused("needs --confirm, given only after the user's explicit yes for this ticket")
            t = log_trade(cfg, now, a.fill)
            print("Logged #%d: %s %s %d @ %.2f, stop %.2f, target %.2f, out by %s." % (
                t["id"], t["mode"].upper(), t["symbol"], t["qty"], t["entry"], t["stop"], t["target"], t["flat_by"]))
        elif a.cmd == "close":
            t = close_trade(cfg, a.symbol, a.exit, a.reason, now)
            print("Closed #%d %s at %.2f (%s): gross %s, charges %s, net %s." % (
                t["id"], t["symbol"], t["exit"], t["exit_reason"], nselib.inr(t["gross_pnl"]),
                nselib.inr(t["charges"]), nselib.inr(t["net_pnl"])))
        else:
            print(today_text(cfg, now))
    except Refused as e:
        print("REFUSED: %s" % e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
