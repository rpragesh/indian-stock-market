"""Shared helpers for the nse-* skills: files, ticks, fingerprints, the paper journal.

Other skills load this with:

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
    import nselib

Analysis only. Nothing here talks to a broker or places an order.
"""

import hashlib
import json
import math
import os

import charges  # noqa: F401  (re-exported for the skills)
import market   # noqa: F401

NSE_DIR = os.environ.get("NSE_DIR", "nse")


def path(*parts):
    return os.path.join(NSE_DIR, *parts)


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(p, data):
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, p)


def config():
    return market.load_config(path("config.json"))


def tick(cfg):
    return float(cfg.get("tick_size", 0.05))


def to_tick(price, size, how="nearest"):
    """Round a price to the exchange tick: 'down', 'up' or 'nearest' (half up)."""
    n = price / size
    eps = 1e-9
    if how == "down":
        n = math.floor(n + eps)
    elif how == "up":
        n = math.ceil(n - eps)
    else:
        n = math.floor(n + 0.5 + eps)
    return round(n * size, 2)


def fingerprint(order):
    """A short hash of the fields that make an order what it is."""
    keys = ("date", "symbol", "exchange", "product", "side", "qty", "entry", "stop", "target")
    blob = json.dumps({k: order.get(k) for k in keys}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


# ---- the journal: every paper (or manually placed) trade, open and closed ----

def journal():
    return read_json(path("state", "journal.json"), {"trades": []})


def save_journal(j):
    write_json(path("state", "journal.json"), j)


def trades_on(j, date):
    return [t for t in j["trades"] if t["date"] == date]


def open_trades(j):
    return [t for t in j["trades"] if t.get("status") == "open"]


def realized_pnl(j, date=None):
    return round(sum(t.get("net_pnl", 0.0) for t in j["trades"]
                     if t.get("status") == "closed" and (date is None or t["date"] == date)), 2)


def cash(cfg, j):
    """Paper cash: starting capital plus realized net P&L, minus money tied up in open trades."""
    tied = sum(t["entry"] * t["qty"] for t in open_trades(j))
    return round(float(cfg.get("paper_capital_inr", 0)) + realized_pnl(j) - tied, 2)


def equity(cfg, j):
    return round(float(cfg.get("paper_capital_inr", 0)) + realized_pnl(j), 2)


def inr(x):
    """Indian digit grouping: 123456.5 -> '1,23,456.50'."""
    neg = x < 0
    s = "%.2f" % abs(x)
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("-" if neg else "") + "Rs " + whole + "." + frac
