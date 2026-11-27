#!/usr/bin/env python3
"""Charges and net P&L for one NSE/BSE cash-equity trade.

Covers brokerage, STT, exchange transaction charges, SEBI fee, IPFT, stamp
duty, GST and (for delivery sells) DP charges, for the brokers listed in
brokers.json. Every rupee figure is rounded to paise. Brokers round some
items to the rupee on the contract note, so expect a difference of a rupee
or two against their calculators.

    python3 charges.py --broker groww --buy 1000 --sell 1010 --qty 50
    python3 charges.py --broker zerodha --buy 1000 --sell 990 --qty 50 --json
    python3 charges.py --broker groww --buy 1000 --qty 50 --breakeven

Analysis only. Nothing here talks to a broker or places an order.
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BROKERS_FILE = os.path.join(HERE, "brokers.json")
PRODUCTS = ("intraday", "delivery", "options")
EXCHANGES = ("NSE", "BSE")


def load_rates(path=BROKERS_FILE):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _r(x):
    return round(x + 0.0, 2)


def leg_brokerage(rule, value):
    """Brokerage for one executed order of `value` rupees."""
    if value <= 0:
        return 0.0
    if rule["flat_inr"] and not rule["pct"]:
        return float(rule["flat_inr"])  # a flat fee per order (options)
    b = min(rule["flat_inr"], value * rule["pct"] / 100.0) if rule["flat_inr"] else value * rule["pct"] / 100.0
    if rule.get("min_inr") and b < rule["min_inr"]:
        b = min(rule["min_inr"], value * rule.get("min_pct_of_value", 0) / 100.0) if rule.get("min_pct_of_value") else rule["min_inr"]
    return b


def trade_charges(broker, buy_price, sell_price, qty, product="intraday", exchange="NSE", rates=None):
    """Charges for one round trip: one buy order and one sell order of `qty` shares.

    Works the same for a short (sell first, buy back): charges depend on which
    side is the buy and which is the sell, not on the order they happen in.
    """
    rates = rates or load_rates()
    if broker not in rates["brokers"]:
        raise ValueError("unknown broker %r (have: %s)" % (broker, ", ".join(sorted(rates["brokers"]))))
    if product not in PRODUCTS:
        raise ValueError("product must be one of %s" % (PRODUCTS,))
    if exchange not in EXCHANGES:
        raise ValueError("exchange must be one of %s" % (EXCHANGES,))
    if qty <= 0 or buy_price <= 0 or sell_price <= 0:
        raise ValueError("prices and quantity must be positive")

    st = rates["statutory"]
    bk = rates["brokers"][broker]
    buy_val = buy_price * qty
    sell_val = sell_price * qty
    turnover = buy_val + sell_val

    rule = bk["brokerage"][product]
    brokerage = leg_brokerage(rule, buy_val) + leg_brokerage(rule, sell_val)
    stt = (buy_val * st["stt_pct"][product]["buy"] + sell_val * st["stt_pct"][product]["sell"]) / 100.0
    # options pay their own exchange and IPFT rates, on the premium
    exchange_txn = turnover * st.get("exchange_txn_pct_by_product", {}).get(product, st["exchange_txn_pct"])[exchange] / 100.0
    sebi_fee = turnover * st["sebi_fee_pct"] / 100.0
    ipft = turnover * st.get("ipft_pct_by_product", {}).get(product, st["ipft_pct"]).get(exchange, 0.0) / 100.0
    stamp = (buy_val * st["stamp_duty_pct"][product]["buy"] + sell_val * st["stamp_duty_pct"][product]["sell"]) / 100.0

    dp = 0.0
    if product == "delivery":
        d = bk["dp_charge_sell_inr"]
        dp = d["depository"] + (0.0 if sell_val < d.get("broker_waived_below_value_inr", 0) else d["broker"])

    parts = {"brokerage": brokerage, "exchange_txn": exchange_txn, "sebi_fee": sebi_fee, "ipft": ipft, "dp": dp}
    gst = sum(parts[k] for k in st["gst_applies_to"] if k in parts) * st["gst_pct"] / 100.0

    out = {
        "broker": broker,
        "product": product,
        "exchange": exchange,
        "qty": qty,
        "buy_price": buy_price,
        "sell_price": sell_price,
        "turnover": _r(turnover),
        "brokerage": _r(brokerage),
        "stt": _r(stt),
        "exchange_txn": _r(exchange_txn),
        "sebi_fee": _r(sebi_fee),
        "ipft": _r(ipft),
        "stamp_duty": _r(stamp),
        "dp": _r(dp),
        "gst": _r(gst),
    }
    total = brokerage + stt + exchange_txn + sebi_fee + ipft + stamp + dp + gst
    gross = sell_val - buy_val
    out["total_charges"] = _r(total)
    out["gross_pnl"] = _r(gross)
    out["net_pnl"] = _r(gross - total)
    out["rates_as_of"] = bk["as_of"]
    return out


def breakeven_exit(broker, entry, qty, side="long", product="intraday", exchange="NSE", rates=None):
    """The exit price at which net P&L is zero, to the paisa (found by bisection)."""
    rates = rates or load_rates()

    def net(exit_price):
        if side == "long":
            return trade_charges(broker, entry, exit_price, qty, product, exchange, rates)["net_pnl"]
        return trade_charges(broker, exit_price, entry, qty, product, exchange, rates)["net_pnl"]

    lo, hi = entry * 0.5, entry * 1.5
    for _ in range(80):
        mid = (lo + hi) / 2.0
        n = net(mid)
        if side == "long":
            lo, hi = (mid, hi) if n < 0 else (lo, mid)
        else:
            lo, hi = (lo, mid) if n < 0 else (mid, hi)
    price = hi if side == "long" else lo
    return round(price + (0.005 if side == "long" else -0.005), 2)


def main(argv=None):
    p = argparse.ArgumentParser(description="Charges and net P&L for one NSE/BSE equity trade.")
    p.add_argument("--broker", default=None, help="groww or zerodha (default: nse/config.json, else groww)")
    p.add_argument("--buy", type=float, required=True, help="buy price (entry for a long)")
    p.add_argument("--sell", type=float, help="sell price (exit for a long)")
    p.add_argument("--qty", type=int, required=True)
    p.add_argument("--product", choices=PRODUCTS, default="intraday")
    p.add_argument("--exchange", choices=EXCHANGES, default="NSE")
    p.add_argument("--breakeven", action="store_true", help="print the long breakeven exit for --buy")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    broker = a.broker
    if broker is None:
        try:
            with open(os.path.join("nse", "config.json"), encoding="utf-8") as fh:
                broker = json.load(fh).get("broker", "groww")
        except (OSError, ValueError):
            broker = "groww"

    if a.breakeven:
        be = breakeven_exit(broker, a.buy, a.qty, "long", a.product, a.exchange)
        res = {"broker": broker, "entry": a.buy, "qty": a.qty, "breakeven_exit": be,
               "move_needed_pct": round((be - a.buy) / a.buy * 100, 4)}
        print(json.dumps(res, indent=2) if a.json else
              "Breakeven exit for %d @ %.2f on %s: %.2f (+%.3f%%)" % (a.qty, a.buy, broker, be, res["move_needed_pct"]))
        return 0
    if a.sell is None:
        p.error("--sell is required unless --breakeven is given")

    res = trade_charges(broker, a.buy, a.sell, a.qty, a.product, a.exchange)
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print("%s %s on %s: %d shares, buy %.2f, sell %.2f" % (res["broker"].title(), a.product, a.exchange, a.qty, a.buy, a.sell))
    for k in ("brokerage", "stt", "exchange_txn", "sebi_fee", "ipft", "stamp_duty", "dp", "gst"):
        if res[k]:
            print("  %-13s Rs %10.2f" % (k, res[k]))
    print("  %-13s Rs %10.2f" % ("total charges", res["total_charges"]))
    print("  %-13s Rs %10.2f" % ("gross P&L", res["gross_pnl"]))
    print("  %-13s Rs %10.2f" % ("net P&L", res["net_pnl"]))
    print("Rates as of %s. Check them against the broker's own calculator." % res["rates_as_of"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
