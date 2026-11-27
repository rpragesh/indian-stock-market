#!/usr/bin/env python3
"""nse-insider: who is buying and selling big: bulk and block deals, insider filings, and shareholding changes.

1. Bulk and block deals. A bulk deal is one client trading more than 0.5% of
   a company's shares in a day; a block deal goes through the exchange's
   separate block window (at least Rs 10 crore a trade). NSE posts both as
   CSV files after the close.
2. Insider and promoter filings under SEBI's Prohibition of Insider Trading
   (PIT) rules, from NSE's insider-trading list (the data NSE's own page
   loads). Since 4 May 2026 companies file these in XBRL, and the list for
   those gives the filing and its link; who traded and how much are inside
   the filing. Filings before then come with the details.
3. Shareholding by quarter from the broker connector (Groww:
   fetch_stocks_fundamental_data, view shareholding_only), saved to
   nse/holding/SYMBOL.json: promoter, FII, DII and public stakes, and which
   promoter holders changed.

    python3 insider.py                                # watchlist: deals and insider filings
    python3 insider.py --symbols SBIN --holding       # plus shareholding changes
    python3 insider.py --all --top 15                 # the biggest deals and filers across the market
    python3 insider.py --bulk-file bulk.csv --block-file block.csv --insider-file pit.json --json

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


# NSE's insider-list field names: the older list (before May 2026) first, the XBRL-era list after
PIT_FIELDS = {
    "symbol": ("symbol",),
    "company": ("company", "companyName"),
    "person": ("acqName",),
    "category": ("personCategory",),
    "txn": ("tdpTransactionType",),
    "mode": ("acqMode",),
    "qty": ("secAcq",),
    "value": ("secVal",),
    "before_pct": ("befAcqSharesPer",),
    "after_pct": ("afterAcqSharesPer",),
    "time": ("intimDt", "broadcastDateTime", "date"),
    "regulation": ("regulation", "anex"),
    "link": ("ixbrl", "xbrl", "attachment"),
}


def parse_pit(data):
    """Rows of NSE's insider-trading list, in one shape whichever list they came from."""
    rows = data.get("data", data) if isinstance(data, dict) else data
    out = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        g = {k: next((r[n] for n in names if r.get(n) not in (None, "", "-", "Nil")), None)
             for k, names in PIT_FIELDS.items()}
        if not g["symbol"]:
            continue
        g["symbol"] = str(g["symbol"]).upper()
        g["qty"], g["value"] = feeds.num(g["qty"]) if g["qty"] is not None else None, \
            feeds.num(g["value"]) if g["value"] is not None else None
        for k in ("before_pct", "after_pct"):
            g[k] = feeds.num(g[k]) if g[k] is not None else None
        t = (g["txn"] or "").lower()
        g["side"] = "BUY" if t.startswith(("buy", "acq", "pledge creation")) else (
            "SELL" if t.startswith(("sell", "dis", "sale")) else None)
        g["link"] = g["link"] if g["link"] and str(g["link"]).startswith("http") else None
        out.append(g)
    return out


def pit_summary(rows, symbols=None, since=None):
    """Per symbol: the filings since `since`, and where NSE gives the details, what insiders bought and sold."""
    want = {s.upper() for s in symbols} if symbols else None
    by = collections.OrderedDict()
    seen = set()
    for r in rows:
        if want is not None and r["symbol"] not in want:
            continue
        t = _sortable(r["time"])
        if since is not None and t != dt.datetime.min and t < since:
            continue
        key = (r["symbol"], r["person"], r["time"], r["qty"], r["link"])
        if key in seen:
            continue  # the old and new lists can both carry a filing
        seen.add(key)
        s = by.setdefault(r["symbol"], {"symbol": r["symbol"], "company": r["company"], "filings": [],
                                        "bought": 0.0, "sold": 0.0, "promoter_net": 0.0, "with_details": 0})
        s["filings"].append(r)
        if r["side"] and r["value"]:
            s["with_details"] += 1
            s["bought" if r["side"] == "BUY" else "sold"] += r["value"]
            if "promoter" in (r["category"] or "").lower():
                s["promoter_net"] += r["value"] if r["side"] == "BUY" else -r["value"]
    for s in by.values():
        s["filings"].sort(key=lambda r: _sortable(r["time"]), reverse=True)
    return sorted(by.values(), key=lambda s: -(s["bought"] + s["sold"] + len(s["filings"])))


def _sortable(t):
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.datetime.strptime(str(t)[:20].strip(), fmt)
        except ValueError:
            continue
    return dt.datetime.min


def fetch_pit(now, days, file=None):
    """Both insider lists for the last `days` days; returns (rows, notes)."""
    if file:
        try:
            return parse_pit(feeds.nse_json("pit", {}, file)), []
        except (OSError, ValueError) as e:
            return [], ["the saved file %s: %s" % (file, e)]
    params = {"index": "equities", "from_date": (now - dt.timedelta(days=days)).strftime("%d-%m-%Y"),
              "to_date": now.strftime("%d-%m-%Y")}
    rows, notes = [], []
    for kind in ("pit", "pit_old"):
        try:
            rows += parse_pit(feeds.nse_json(kind, params))
        except (OSError, ValueError) as e:
            notes.append("NSE's %s insider list: %s" % ("XBRL-era" if kind == "pit" else "older", e))
    return rows, notes


def holding_changes(sp):
    """Shareholding by quarter (Groww's shareholding_pattern) -> group and promoter changes."""
    qs = sorted(sp, key=_qkey)
    if not qs:
        raise ValueError("no quarters in the shareholding pattern")
    latest = qs[-1]
    prev = qs[-2] if len(qs) > 1 else None
    yago = next((q for q in qs if _qkey(q) == _qkey(latest).replace(year=_qkey(latest).year - 1)), None)
    groups = []
    for g in ("promoters", "fii", "dii", "public", "others"):
        v = lambda q: (sp.get(q, {}).get(g) or {}).get("totalPercent") if q else None  # noqa: E731
        groups.append({"group": g, "latest": v(latest), "qoq_pp": _pp(v(latest), v(prev)),
                       "yoy_pp": _pp(v(latest), v(yago))})
    def holders(q):
        """Promoter holders keyed on the name without a "(formerly ...)" note, so a rename is not a sale."""
        out = {}
        for h in ((sp.get(q, {}).get("promoters") or {}).get("holders") or []) if q else []:
            key = feeds.norm_name(h["name"].split("(")[0])
            out.setdefault(key, [h["name"].split("(")[0].strip(), 0.0])[1] += h.get("allocationPercent") or 0.0
        return out
    now_h, prev_h = holders(latest), holders(prev)
    moves, minor, list_note = [], 0, None
    if prev and not (now_h and prev_h):
        missing = [q for q, h in ((latest, now_h), (prev, prev_h)) if not h]
        list_note = "no promoter-by-name list for %s, so individual promoter moves can't be compared" % " or ".join(missing)
    else:
        for key in sorted(set(now_h) | set(prev_h)):
            name = (now_h.get(key) or prev_h.get(key))[0]
            a, b = (now_h.get(key) or [None, None])[1], (prev_h.get(key) or [None, None])[1]
            if a is None:
                m = {"name": name, "prev": b, "latest": None, "note": "no longer listed as a promoter holder"}
            elif b is None:
                m = {"name": name, "prev": None, "latest": a, "note": "newly listed"}
            elif abs(a - b) >= 0.05:
                m = {"name": name, "prev": b, "latest": a, "note": "%+.2f pp" % (a - b)}
            else:
                continue
            if abs((a or 0) - (b or 0)) < 0.05:   # a holder of ~0% appearing or leaving: regrouping, not a trade
                minor += 1
                continue
            moves.append(m)
    flags = []
    pr = groups[0]
    if pr["qoq_pp"] is not None and pr["qoq_pp"] <= -0.5:
        flags.append("promoters cut their stake by %.2f pp last quarter" % -pr["qoq_pp"])
    if pr["qoq_pp"] is not None and pr["qoq_pp"] >= 0.5:
        flags.append("promoters raised their stake by %.2f pp last quarter" % pr["qoq_pp"])
    for g in groups[1:3]:
        if g["qoq_pp"] is not None and abs(g["qoq_pp"]) >= 2:
            flags.append("%s holding moved %+.2f pp last quarter" % (g["group"].upper(), g["qoq_pp"]))
    return {"quarter": latest, "prev_quarter": prev, "year_ago_quarter": yago, "groups": groups,
            "promoter_moves": moves, "promoter_minor": minor, "promoter_list_note": list_note, "flags": flags}


def _qkey(label):
    try:
        return dt.datetime.strptime(label.replace("'", ""), "%b %y").date()
    except ValueError:
        return dt.date.min


def _pp(a, b):
    return None if a is None or b is None else round(a - b, 2)


def cr(v):
    return "%sRs %s cr" % ("-" if v < 0 else "", nselib.inr(abs(v) / CRORE).replace("Rs ", ""))


def describe_deals(summary, symbols, everyone, top):
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
    return lines


def describe_pit(pit, days):
    lines = ["Insider and promoter filings (SEBI PIT) on NSE, last %d days: %d stock%s" % (
        days, len(pit), "" if len(pit) == 1 else "s")]
    for s in pit:
        head = "  %s (%s): %d filing%s" % (s["symbol"], s["company"] or "", len(s["filings"]),
                                          "" if len(s["filings"]) == 1 else "s")
        if s["with_details"]:
            head += "; insiders bought %s, sold %s; promoters net %s" % (cr(s["bought"]), cr(s["sold"]), cr(s["promoter_net"]))
        lines.append(head)
        for r in s["filings"][:6]:
            if r["person"]:
                lines.append("      %s  %s (%s) %s %s shares%s%s" % (
                    r["time"], r["person"][:40], r["category"] or "?", (r["txn"] or "?").lower(),
                    "{:,}".format(int(r["qty"])) if r["qty"] else "?",
                    " worth %s" % cr(r["value"]) if r["value"] else "",
                    ", holding %.2f%% -> %.2f%%" % (r["before_pct"], r["after_pct"])
                    if r["before_pct"] is not None and r["after_pct"] is not None else ""))
            else:
                lines.append("      %s  %s filing; who and how much are in the filing" % (
                    r["time"], r["regulation"] or "PIT"))
            if r["link"]:
                lines.append("        %s" % r["link"])
    if not pit:
        lines.append("  No filings.")
    return lines


def describe_holding(sym, h):
    lines = ["Shareholding of %s, %s (vs %s, and %s a year ago), from the connector" % (
        sym, h["quarter"], h["prev_quarter"] or "-", h["year_ago_quarter"] or "-")]
    for g in h["groups"]:
        if g["latest"] is None or (g["group"] == "others" and not g["latest"]):
            continue
        lines.append("  %-10s %6.2f%%   QoQ %s   YoY %s" % (
            g["group"].upper() if g["group"] in ("fii", "dii") else g["group"].capitalize(), g["latest"],
            "-" if g["qoq_pp"] is None else "%+.2f pp" % g["qoq_pp"],
            "-" if g["yoy_pp"] is None else "%+.2f pp" % g["yoy_pp"]))
    for m in h["promoter_moves"]:
        lines.append("    promoter %s: %s%s" % (m["name"], m["note"], "" if m["prev"] is None or m["latest"] is None
                                               else " (%.2f%% -> %.2f%%)" % (m["prev"], m["latest"])))
    if h.get("promoter_minor"):
        lines.append("    plus %d promoter entities with ~0%% added or dropped from the list (regrouping, not a trade)"
                     % h["promoter_minor"])
    if h.get("promoter_list_note"):
        lines.append("    " + h["promoter_list_note"])
    lines.append("  Watch: " + ("; ".join(h["flags"]) if h["flags"] else "no big change in who owns it"))
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bulk, block and insider deals, and shareholding changes, for your watchlist.")
    ap.add_argument("--symbols", help="NSE symbols, comma separated (default: the watchlist)")
    ap.add_argument("--all", action="store_true", help="every stock with a deal or filing")
    ap.add_argument("--top", type=int, default=10, help="with --all, how many stocks to show")
    ap.add_argument("--days", type=int, default=30, help="insider filings from the last N days")
    ap.add_argument("--no-deals", action="store_true")
    ap.add_argument("--no-insider", action="store_true")
    ap.add_argument("--holding", action="store_true", help="also read nse/holding/SYMBOL.json (Groww shareholding)")
    ap.add_argument("--bulk-file")
    ap.add_argument("--block-file")
    ap.add_argument("--insider-file", help="a saved copy of NSE's insider list (JSON)")
    ap.add_argument("--holding-file", help="a saved Groww shareholding answer, with one --symbols")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    wl = cfg.get("watchlist") or {}
    symbols = [x.strip().upper() for x in a.symbols.split(",")] if a.symbols else list(wl.keys())
    out, lines, notes = {}, [], []
    deals_ok = pit_ok = False

    if not a.no_deals:
        deals = []
        for kind, f in (("bulk", a.bulk_file), ("block", a.block_file)):
            try:
                deals += parse_deals(feeds.fetch(kind, f), kind)
                deals_ok = True
            except OSError as e:
                notes.append("Could not read NSE's %s deals (%s). Save %s from a browser and pass --%s-file." % (
                    kind, e, feeds.URLS[kind], kind))
        summary = summarise(deals, None if a.all else symbols)
        out["deals"] = summary[:a.top] if a.all else summary
        lines += describe_deals(summary, symbols, a.all, a.top)

    if not a.no_insider:
        now = market.now_ist(a.now).replace(tzinfo=None)
        rows, n = fetch_pit(now, a.days, a.insider_file)
        pit_ok = bool(rows) or not n
        if n and not rows:
            notes.append("Could not read NSE's insider-trading lists (%s). Open nseindia.com > Companies > "
                         "Insider Trading, or pass --insider-file." % "; ".join(n))
        pit = pit_summary(rows, None if a.all else symbols, now - dt.timedelta(days=a.days))
        out["insider"] = pit[:a.top] if a.all else pit
        if pit_ok:
            lines += describe_pit(pit[:a.top] if a.all else pit, a.days)

    if a.holding:
        out["holding"] = {}
        for sym in symbols:
            f = a.holding_file if a.holding_file and len(symbols) == 1 else nselib.path("holding", sym + ".json")
            data = nselib.read_json(f)
            if not data:
                notes.append("No shareholding saved for %s: fetch it with the connector (Groww "
                             "fetch_stocks_fundamental_data, view shareholding_only) and save it to %s." % (sym, f))
                continue
            try:
                sp, _ = feeds.groww_pick(data, "shareholding_pattern", sym, wl.get(sym))
                h = holding_changes(sp)
            except ValueError as e:
                notes.append("%s shareholding: %s" % (sym, e))
                continue
            out["holding"][sym] = h
            lines += describe_holding(sym, h)

    out["notes"] = notes
    if a.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        lines += notes
        lines.append("A deal or filing shows who traded, not why. Not financial advice.")
        print("\n".join(lines))
    return 0 if deals_ok or pit_ok or out.get("holding") else 1


if __name__ == "__main__":
    sys.exit(main())
