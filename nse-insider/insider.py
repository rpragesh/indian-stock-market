#!/usr/bin/env python3
"""nse-insider: today's bulk and block deals, and insider (SEBI PIT) disclosures, for your watchlist.

Bulk deals are trades of more than 0.5% of a company's shares in a day; block
deals go through the exchange's separate block window (at least Rs 10
crore a trade). NSE posts both as CSV files after the close. Insider and
promoter trades disclosed under SEBI's Prohibition of Insider Trading (PIT)
rules come from NSE's insider-trading RSS feed.

    python3 insider.py                                # watchlist: bulk, block, insider
    python3 insider.py --symbols SBIN,TATASTEEL
    python3 insider.py --all --top 15                 # the biggest deals across the market
    python3 insider.py --bulk-file bulk.csv --block-file block.csv --insider-file it.xml --json

A client that both bought and sold the same stock the same day is usually
an arbitrage or proprietary desk, not a view on the company; those deals
are marked "both sides". Analysis only, not a view on the stock.
"""

import argparse
import collections
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import feeds  # noqa: E402
import nselib  # noqa: E402
from nselib import market  # noqa: E402

PRICE_COLS = ("Trade Price / Wght. Avg. Price", "Trade Price / Wght. Avg. Price ", "Trade Price")
CRORE = 1e7
STALE_DAYS = 7


def _col(row, *names):
    for n in names:
        if n in row:
            return row[n]
    return ""


def parse_deals(text, kind):
    """Rows of bulk.csv or block.csv as dicts with a value in rupees."""
    out = []
    for r in feeds.csv_rows(text):
        qty, px = feeds.num(_col(r, "Quantity Traded")), feeds.num(_col(r, *PRICE_COLS))
        sym = _col(r, "Symbol").upper()
        if not sym or qty is None or px is None:
            continue
        side = _col(r, "Buy/Sell").upper()
        out.append({"kind": kind, "date": _col(r, "Date"), "symbol": sym, "name": _col(r, "Security Name"),
                    "client": _col(r, "Client Name"), "side": "BUY" if side.startswith("B") else "SELL",
                    "qty": int(qty), "price": px, "value": qty * px, "remarks": _col(r, "Remarks") or None})
    return out


def summarise(deals, symbols=None):
    """Per symbol: bought, sold, net, and each client's net, with both-sides clients marked."""
    want = {s.upper() for s in symbols} if symbols else None
    by = collections.OrderedDict()
    for d in sorted(deals, key=lambda x: -x["value"]):
        if want is not None and d["symbol"] not in want:
            continue
        s = by.setdefault(d["symbol"], {"symbol": d["symbol"], "name": d["name"], "bought": 0.0, "sold": 0.0,
                                        "clients": collections.OrderedDict(), "deals": []})
        s["bought" if d["side"] == "BUY" else "sold"] += d["value"]
        c = s["clients"].setdefault(d["client"], {"client": d["client"], "bought": 0.0, "sold": 0.0,
                                                  "qty_net": 0, "kinds": set()})
        c["bought" if d["side"] == "BUY" else "sold"] += d["value"]
        c["qty_net"] += d["qty"] if d["side"] == "BUY" else -d["qty"]
        c["kinds"].add(d["kind"])
        s["deals"].append(d)
    out = []
    for s in by.values():
        clients = []
        for c in s["clients"].values():
            c["both_sides"] = c["bought"] > 0 and c["sold"] > 0
            c["net"] = c["bought"] - c["sold"]
            c["kinds"] = sorted(c["kinds"])
            clients.append(c)
        clients.sort(key=lambda c: -abs(c["net"]))
        one_way = [c for c in clients if not c["both_sides"]]
        s.update(clients=clients, net=s["bought"] - s["sold"],
                 net_one_way=sum(c["net"] for c in one_way))
        out.append(s)
    out.sort(key=lambda s: -(s["bought"] + s["sold"]))
    return out


def insider_items(text, names, now, days=30):
    """Watchlist items from NSE's insider-trading RSS, and the newest date in the whole feed."""
    items = feeds.rss_items(text)
    newest, out = None, []
    cutoff = now.replace(tzinfo=None) - dt.timedelta(days=days)
    for it in items:
        pub = _pub(it["pub"])
        if pub and (newest is None or pub > newest):
            newest = pub
        if not feeds.name_matches(it["title"], names):
            continue
        if pub is not None and pub < cutoff:
            continue
        out.append({"company": it["title"], "time": pub.strftime("%Y-%m-%d %H:%M") if pub else it["pub"],
                    "detail": it["description"], "link": it["link"] or None})
    out.sort(key=lambda x: x["time"], reverse=True)
    stale = newest is None or (now.replace(tzinfo=None) - newest).days > STALE_DAYS
    return out, (newest.strftime("%Y-%m-%d") if newest else None), stale


def _pub(s):
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            d = dt.datetime.strptime(s, fmt)
            return d.replace(tzinfo=None) if d.tzinfo else d
        except ValueError:
            continue
    return None


def cr(v):
    return "%sRs %s cr" % ("-" if v < 0 else "", nselib.inr(abs(v) / CRORE).replace("Rs ", ""))


def describe(summary, ins, newest, stale, symbols, everyone, top, notes):
    who = "the whole market" if everyone else ", ".join(symbols) or "(empty watchlist)"
    lines = ["Bulk and block deals for %s: %d stock%s" % (who, len(summary), "" if len(summary) == 1 else "s")]
    for s in summary[:top] if everyone else summary:
        lines.append("  %s (%s): bought %s, sold %s, net %s%s" % (
            s["symbol"], s["name"], cr(s["bought"]), cr(s["sold"]), cr(s["net"]),
            "" if abs(s["net_one_way"] - s["net"]) < 1 else "; one-way clients only %s" % cr(s["net_one_way"])))
        for c in s["clients"][:5]:
            lines.append("      %-44s %s %s%s" % (
                c["client"][:44], "net " + cr(c["net"]), "/".join(c["kinds"]),
                "  (both sides, likely arbitrage)" if c["both_sides"] else ""))
    if not summary:
        lines.append("  No bulk or block deals.")
    if ins is not None:
        lines.append("Insider and promoter disclosures (SEBI PIT), watchlist: %d" % len(ins))
        for i in ins:
            lines.append("  %s  %s: %s" % (i["time"], i["company"], i["detail"][:120]))
            if i["link"]:
                lines.append("      %s" % i["link"])
        if stale:
            lines.append("  Note: the newest item in NSE's insider feed is from %s, so the feed looks stale. "
                         "Check nseindia.com > Companies > Insider Trading for recent filings." % (newest or "never"))
    lines.extend(notes)
    lines.append("A deal shows who traded, not why. Not financial advice.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bulk, block and insider deals for your watchlist.")
    ap.add_argument("--symbols", help="NSE symbols, comma separated (default: the watchlist)")
    ap.add_argument("--all", action="store_true", help="every stock with a deal")
    ap.add_argument("--top", type=int, default=10, help="with --all, how many stocks to show")
    ap.add_argument("--days", type=int, default=30, help="insider disclosures from the last N days")
    ap.add_argument("--no-insider", action="store_true")
    ap.add_argument("--bulk-file")
    ap.add_argument("--block-file")
    ap.add_argument("--insider-file")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    wl = cfg.get("watchlist") or {}
    symbols = [x.strip().upper() for x in a.symbols.split(",")] if a.symbols else list(wl.keys())
    names = symbols + [wl[s] for s in symbols if s in wl]
    deals, notes = [], []
    for kind, f in (("bulk", a.bulk_file), ("block", a.block_file)):
        try:
            deals += parse_deals(feeds.fetch(kind, f), kind)
        except OSError as e:
            notes.append("Could not read NSE's %s deals (%s). Save %s from a browser and pass --%s-file." % (
                kind, e, feeds.URLS[kind], kind))
    summary = summarise(deals, None if a.all else symbols)
    ins = newest = None
    stale = False
    if not a.no_insider:
        try:
            ins, newest, stale = insider_items(feeds.fetch("insider", a.insider_file), names,
                                               market.now_ist(a.now), a.days)
        except OSError as e:
            notes.append("Could not read NSE's insider-trading feed (%s). Pass --insider-file or --no-insider." % e)
    if a.json:
        print(json.dumps({"deals": summary if not a.all else summary[:a.top], "insider": ins,
                          "insider_feed_newest": newest, "insider_feed_stale": stale, "notes": notes}, indent=2))
    else:
        print(describe(summary, ins, newest, stale, symbols, a.all, a.top, notes))
    return 0 if deals or not notes else 1


if __name__ == "__main__":
    sys.exit(main())
