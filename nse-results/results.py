#!/usr/bin/env python3
"""nse-results: what changed in a company's latest quarterly results.

Claude fetches the numbers with the broker connector (Groww:
fetch_stocks_fundamental_data, view "financials_only") and saves the result
to nse/results/SYMBOL.json. This reads the quarterly income statement and
says what moved: revenue, EBITDA, net profit and EPS against the previous
quarter (QoQ) and the same quarter a year ago (YoY), margins in basis
points, plus the yearly trend.

    python3 results.py --symbol INFY
    python3 results.py --symbol INFY --file saved.json --json

Analysis only: a summary of reported numbers, not a view on the stock.
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import feeds  # noqa: E402
import nselib  # noqa: E402

LINES = ["Revenue", "EBITDA", "Net Profit", "Earning Per Share (Diluted)"]
MARGINS = ["Operating Profit Margin", "Net Profit Margin"]


def qkey(label):
    """"Sep '25" -> date(2025, 9, 1) for sorting."""
    try:
        return dt.datetime.strptime(label.replace("'", ""), "%b %y").date()
    except ValueError:
        return dt.date.min


def pick_company(data, symbol, name=None):
    """The one company's financialStatement out of whatever shape was saved."""
    return feeds.groww_pick(data, "financialStatement", symbol, name)


def chg(a, b):
    if a is None or b in (None, 0):
        return None
    return round((a - b) / abs(b) * 100, 1)


def summarise(fs):
    q = fs.get("Income Statement", {}).get("quarterlyFinancial", {})
    y = fs.get("Income Statement", {}).get("yearlyFinancial", {})
    if not q.get("Revenue"):
        raise ValueError("no quarterly revenue in the saved numbers")
    quarters = sorted(q["Revenue"]["values"], key=qkey)
    latest = quarters[-1]
    prev = quarters[-2] if len(quarters) > 1 else None
    yago = next((k for k in quarters if qkey(k) == qkey(latest).replace(year=qkey(latest).year - 1)), None)
    rows = []
    for line in LINES:
        if line not in q:
            continue
        v = q[line]["values"]
        rows.append({"line": "EPS" if line.startswith("Earning") else line, "latest": v.get(latest),
                     "prev": v.get(prev), "year_ago": v.get(yago),
                     "qoq_pct": chg(v.get(latest), v.get(prev)), "yoy_pct": chg(v.get(latest), v.get(yago)),
                     "unit": q[line].get("unit", "")})
    margins = []
    for m in MARGINS:
        if m in q:
            v = q[m]["values"]
            bp = lambda a, b: None if a is None or b is None else int(round((a - b) * 100))  # noqa: E731
            margins.append({"line": m, "latest": v.get(latest), "qoq_bps": bp(v.get(latest), v.get(prev)),
                            "yoy_bps": bp(v.get(latest), v.get(yago))})
    yearly = []
    if y.get("Revenue") and y.get("Net Profit"):
        ys = sorted(y["Revenue"]["values"])
        for a, b in zip(ys, ys[1:]):
            yearly.append({"year": b, "revenue_pct": chg(y["Revenue"]["values"][b], y["Revenue"]["values"][a]),
                           "profit_pct": chg(y["Net Profit"]["values"].get(b), y["Net Profit"]["values"].get(a))})
    flags = []
    by = {r["line"]: r for r in rows}
    np_, rev = by.get("Net Profit"), by.get("Revenue")
    if np_ and np_["latest"] is not None and np_["latest"] < 0:
        flags.append("a net loss this quarter")
    if np_ and np_["yoy_pct"] is not None and np_["yoy_pct"] <= -10:
        flags.append("net profit down %.1f%% on the year" % -np_["yoy_pct"])
    if rev and rev["yoy_pct"] is not None and rev["yoy_pct"] < 0:
        flags.append("revenue down %.1f%% on the year" % -rev["yoy_pct"])
    for m in margins:
        if m["yoy_bps"] is not None and m["yoy_bps"] <= -100:
            flags.append("%s down %d bps on the year" % (m["line"].lower(), -m["yoy_bps"]))
    if rev and np_ and rev["yoy_pct"] is not None and np_["yoy_pct"] is not None and np_["yoy_pct"] < rev["yoy_pct"] - 5:
        flags.append("profit growing slower than revenue")
    return {"quarter": latest, "prev_quarter": prev, "year_ago_quarter": yago, "lines": rows, "margins": margins,
            "yearly": yearly, "flags": flags}


def fmt(v, unit=""):
    if v is None:
        return "-"
    return ("%s cr" % "{:,.0f}".format(v)) if "Cr" in unit else "%.2f" % v


def pc(x):
    return "-" if x is None else "%+.1f%%" % x


def describe(sym, s):
    out = ["%s results, quarter to %s (vs %s and %s)" % (sym, s["quarter"], s["prev_quarter"] or "-", s["year_ago_quarter"] or "-")]
    for r in s["lines"]:
        out.append("  %-11s %14s   QoQ %7s   YoY %7s" % (r["line"], fmt(r["latest"], r["unit"]), pc(r["qoq_pct"]), pc(r["yoy_pct"])))
    for m in s["margins"]:
        bps = lambda x: "-" if x is None else "%+d bps" % x  # noqa: E731
        out.append("  %-24s %6.2f%%   QoQ %9s   YoY %9s" % (m["line"], m["latest"], bps(m["qoq_bps"]), bps(m["yoy_bps"])))
    if s["yearly"]:
        out.append("  Years: " + "; ".join("FY%s revenue %s, profit %s" % (y["year"][-2:], pc(y["revenue_pct"]), pc(y["profit_pct"])) for y in s["yearly"][-3:]))
    out.append("  Watch: " + ("; ".join(s["flags"]) if s["flags"] else "nothing stands out in the headline numbers"))
    out.append("Figures as Groww reports them (consolidated where Groww uses it). Check the filing on NSE for the detail. Not financial advice.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Summarise the latest quarterly results.")
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--company", help="company name, when the saved file has several")
    ap.add_argument("--file", help="default nse/results/SYMBOL.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    sym = a.symbol.upper()
    f = a.file or nselib.path("results", sym + ".json")
    data = nselib.read_json(f)
    if not data:
        print("No saved results at %s: fetch them with the connector (Groww fetch_stocks_fundamental_data, view financials_only) and save the JSON there." % f)
        return 1
    name = a.company or (nselib.config().get("watchlist") or {}).get(sym)
    try:
        fs, key = pick_company(data, sym, name)
        s = summarise(fs)
    except ValueError as e:
        print("REFUSED: %s" % e)
        return 2
    s["company_key"] = key
    print(json.dumps(s, indent=2) if a.json else describe(sym, s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
