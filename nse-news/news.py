#!/usr/bin/env python3
"""nse-news: NSE corporate announcements for your watchlist, sorted by what tends to move a stock.

Reads NSE's public announcements feed (nsearchives.nseindia.com), keeps the
companies on your watchlist (nse/config.json "watchlist", plus --names),
and tags each filing: results, orders, deals, fund raising, ratings,
management exits, defaults, regulator action, exchange queries, dividends
and splits, or routine.

    python3 news.py                              # watchlist, last 24 hours
    python3 news.py --names "Tata Steel,SBIN" --hours 72
    python3 news.py --all --hours 2              # every company, high-impact only
    python3 news.py --file saved.xml --json

Analysis only. A tag is a keyword match on the filing's subject, not a judgement on the news.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import feeds  # noqa: E402
import nselib  # noqa: E402
from nselib import market  # noqa: E402

# (tag, impact, pattern) checked in order; the first match wins
TAGS = [
    ("default", "high", r"insolvency|nclt|\bcirp\b|default in (payment|repayment)|winding up"),
    ("regulator", "high", r"sebi order|penalty|show cause|search and seizure|income tax (search|survey)|raid|adjudicat|enforcement directorate"),
    ("exchange query", "high", r"spurt in volume|clarification sought|price movement|clarification.*news"),
    ("results", "high", r"financial result|results? for the (quarter|period|year)|un-?audited|audited financial"),
    ("deal", "high", r"acqui|merger|amalgamation|scheme of arrangement|demerger|joint venture|stake (sale|purchase)|divest"),
    ("order win", "high", r"award(ed)? of (an )?order|bagging|receipt of (an )?order|order (win|received|inflow)|letter of (award|intent)|contract (win|award)"),
    ("fund raising", "high", r"\bqip\b|preferential (issue|allotment)|rights issue|fund ?rais|issue of (shares|warrants|ncd|debentures)|ofs\b|offer for sale"),
    ("rating", "medium", r"credit rating|rating (action|revision|upgrade|downgrade)"),
    ("management", "medium", r"resign|cessation|appointment of (ceo|cfo|managing|md|chief)|change in (management|kmp|auditor)"),
    ("pledge", "medium", r"pledge|encumbrance"),
    ("buyback", "medium", r"buy-?back"),
    ("corporate action", "medium", r"dividend|bonus|split|sub-division|record date"),
    ("board meeting", "medium", r"board meeting|outcome of (the )?board"),
    ("routine", "low", r"trading window|newspaper|publication|investor (meet|presentation)|analyst|earnings call|transcript|"
                       r"regulation 74|74\(5\)|loss of share certificate|duplicate share|esop|esos|allotment of equity shares under|"
                       r"compliance certificate|secretarial|shareholding pattern|book closure|postal ballot|agm|e-?voting"),
]
IMPACT_RANK = {"high": 0, "medium": 1, "low": 2, "other": 3}


def classify(text):
    t = text.lower()
    for tag, impact, pat in TAGS:
        if re.search(pat, t):
            return tag, impact
    return "other", "other"


def parse_pub(s):
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            d = dt.datetime.strptime(s, fmt)
            return d.replace(tzinfo=None) if d.tzinfo else d
        except ValueError:
            continue
    return None


def subject_of(desc):
    m = re.search(r"\|\s*SUBJECT\s*:\s*(.*)$", desc, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"informed the Exchange (about|regarding)\s+(.*)", desc, re.I)
    return (m.group(2) if m else desc).strip()


def nse_items(text):
    """NSE's announcements RSS as plain items."""
    out = []
    for it in feeds.rss_items(text):
        out.append({"exchange": "NSE", "company": it["title"], "subject": subject_of(it["description"]),
                    "extra": it["description"], "pub": parse_pub(it["pub"]), "pub_raw": it["pub"],
                    "link": it["link"] or None})
    return out


def bse_items(data):
    """BSE's announcements answer (AnnSubCategoryGetData) as plain items."""
    out = []
    for r in (data or {}).get("Table") or []:
        subj = (r.get("HEADLINE") or "").strip() or re.sub(r"^.*? - \d{6} - ", "", r.get("NEWSSUB") or "").strip()
        when = str(r.get("NEWS_DT") or r.get("DissemDT") or "")
        try:
            pub = dt.datetime.strptime(when[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pub = None
        att = (r.get("ATTACHMENTNAME") or "").strip()
        out.append({"exchange": "BSE", "company": (r.get("SLONGNAME") or "").strip(), "subject": subj,
                    "extra": " ".join(str(r.get(k) or "") for k in ("NEWSSUB", "CATEGORYNAME", "SUBCATNAME")),
                    "pub": pub, "pub_raw": when, "link": feeds.BSE_ATTACH + att if att else (r.get("NSURL") or None),
                    "bse_code": str(r.get("SCRIP_CD") or "")})
    return out


def bse_fetch(now, hours, codes=None, max_pages=10, file=None):
    """BSE announcements for the window: one ask per scrip code if we have codes, else page through all."""
    if file:
        return bse_items(feeds.bse_json("", {}, file))
    start = (now - dt.timedelta(hours=hours)).strftime("%Y%m%d")
    base = {"strCat": "-1", "subcategory": "-1", "strPrevDate": start, "strToDate": now.strftime("%Y%m%d"),
            "strSearch": "P", "strType": "C"}
    out = []
    for code in (codes or [""]):
        page = 1
        while page <= max_pages:
            data = feeds.bse_json("AnnSubCategoryGetData/w", dict(base, pageno=page, strScrip=code))
            rows = bse_items(data)
            out += rows
            pages = int(((data.get("Table") or [{}])[0] or {}).get("TotalPageCnt") or 1) if rows else 0
            if page >= pages:
                break
            page += 1
    return out


def filter_items(items, names, now, hours=24, everyone=False, min_impact="other"):
    cutoff = now.replace(tzinfo=None) - dt.timedelta(hours=hours)
    out, seen = [], set()
    for it in items:
        if not everyone and not feeds.name_matches(it["company"], names):
            continue
        pub = it["pub"]
        if pub is not None and pub < cutoff:
            continue
        tag, impact = classify(it["subject"] + " " + it["extra"])
        if IMPACT_RANK[impact] > IMPACT_RANK[min_impact]:
            continue
        key = (feeds.norm_name(it["company"]), feeds.norm_name(it["subject"])[:60], pub.date() if pub else None)
        if key in seen:
            continue  # the same filing on both exchanges
        seen.add(key)
        out.append({"exchange": it["exchange"], "company": it["company"], "subject": it["subject"], "tag": tag,
                    "impact": impact, "time": pub.strftime("%Y-%m-%d %H:%M") if pub else it["pub_raw"],
                    "link": it["link"]})
    out.sort(key=lambda x: (IMPACT_RANK[x["impact"]], -int(re.sub(r"\D", "", x["time"]) or 0)))
    return out


def run(text, names, now, hours=24, everyone=False, min_impact="other", bse=None):
    """NSE's RSS text (and BSE items, if given) -> the filings that matter, high impact first."""
    items = (nse_items(text) if text else []) + (bse or [])
    return filter_items(items, names, now, hours, everyone, min_impact)


def describe(rows, hours, names, everyone):
    who = "all companies" if everyone else ", ".join(names) or "(empty watchlist)"
    out = ["Announcements, last %d hours, %s: %d" % (hours, who, len(rows))]
    for r in rows:
        out.append("  [%s/%s] %s %s  %s: %s" % (r["impact"], r["tag"], r["exchange"], r["time"], r["company"],
                                                r["subject"][:160]))
        if r["link"]:
            out.append("      %s" % r["link"])
    if not rows:
        out.append("  Nothing filed.")
    out.append("Tags are keyword matches on the filing subject. Read the filing before acting on it. Not financial advice.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="NSE and BSE announcements for your watchlist.")
    ap.add_argument("--names", help="extra company names or symbols, comma separated")
    ap.add_argument("--all", action="store_true", help="every company (pair with --min-impact high)")
    ap.add_argument("--min-impact", choices=("high", "medium", "low", "other"), default=None)
    ap.add_argument("--hours", type=int, default=24)
    ap.add_argument("--exchange", choices=("nse", "bse", "both"), default="both")
    ap.add_argument("--bse-pages", type=int, default=10, help="without BSE codes, how many pages of BSE filings to read")
    ap.add_argument("--file", help="a saved copy of NSE's announcements RSS")
    ap.add_argument("--bse-file", help="a saved copy of BSE's announcements answer (JSON)")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    wl = cfg.get("watchlist") or {}
    extra = [x.strip() for x in a.names.split(",")] if a.names else []
    names = list(wl.values()) + list(wl.keys()) + extra
    now = market.now_ist(a.now).replace(tzinfo=None)
    text, bse, notes = None, [], []
    if a.exchange in ("nse", "both"):
        try:
            text = feeds.fetch("announcements", a.file)
        except OSError as e:
            notes.append("Could not reach NSE's announcements feed (%s). Save %s from a browser and pass --file." % (
                e, feeds.URLS["announcements"]))
    if a.exchange in ("bse", "both"):
        codes = None if (a.all or extra) else [str(c) for c in (cfg.get("bse_codes") or {}).values()] or None
        try:
            bse = bse_fetch(now, a.hours, codes, a.bse_pages, a.bse_file)
        except (OSError, ValueError) as e:
            notes.append("Could not reach BSE's announcements (%s). Pass --bse-file with a saved copy, "
                         "or --exchange nse." % e)
    if text is None and not bse and notes:
        print("\n".join(notes))
        return 1
    min_impact = a.min_impact or ("high" if a.all else "other")
    rows = run(text, names, now, a.hours, a.all, min_impact, bse)
    if a.json:
        print(json.dumps({"filings": rows, "notes": notes}, indent=2))
    else:
        print(describe(rows, a.hours, list(wl.keys()) + extra, a.all))
        for n in notes:
            print(n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
