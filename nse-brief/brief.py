#!/usr/bin/env python3
"""nse-brief: "check the market" in one go, using every skill in the pack.

From the candles and connector answers Claude has saved under nse/, it:

1. scans every saved stock for the long setups (nse-scanner),
2. plans each live one: entry, stop, target, flat-by time (nse-exit),
3. sizes it after charges against your limits (nse-budget),
4. runs your PASS/BLOCK rules on it (nse-risk),
5. replays it on past sessions when enough candles are saved (nse-timemachine),
6. flags any high-impact NSE filing today (nse-news),
7. ranks them and keeps the top 10, and
8. for each index or F&O stock with saved option data, turns its best setup,
   bullish or bearish, into an option-buying plan (nse-options): which CE or PE,
   entry, stop and target on the premium, and how many lots.

    python3 brief.py                          # now (IST)
    python3 brief.py --date 2026-11-27 --at 11:00
    python3 brief.py --top 5 --no-news --json --write

Analysis only. A ranked list of pattern matches, not recommendations, and
nothing here places an order. F&O ideas are option buying on paper only.
Not financial advice.
"""

import argparse
import glob
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "nse-setup"))
import bars as B  # noqa: E402
import nselib  # noqa: E402
from nselib import market  # noqa: E402


def _load(folder, name):
    spec = importlib.util.spec_from_file_location("brief_" + name, os.path.join(ROOT, folder, name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


scan = _load("nse-scanner", "scan")
ex = _load("nse-exit", "exit")
bud = _load("nse-budget", "size")
risk = _load("nse-risk", "check")
tm = _load("nse-timemachine", "timemachine")
opt = _load("nse-options", "options")
news = _load("nse-news", "news")
import feeds  # noqa: E402

STATE_POINTS = {"triggered": 30, "forming": 20}


def candle_files():
    files = sorted(glob.glob(nselib.path("candles", "*.csv")) + glob.glob(nselib.path("candles", "*.json")))
    cash, under = [], {}
    for f in files:
        sym = scan.symbol_of(f)
        if sym in opt.INDICES:
            under[sym] = f
            continue
        cash.append(f)
        under.setdefault(sym, f)
    return cash, under


def names_for(cfg):
    """Symbol -> company name, from nse/shortlist.json and the watchlist (for matching filings)."""
    out = dict(cfg.get("watchlist") or {})
    sl = nselib.read_json(nselib.path("shortlist.json")) or {}
    out.update(sl if isinstance(sl, dict) else {})
    return out


def filings_today(cfg, now, names):
    """High-impact NSE filings in the last 24 hours, by symbol. ({}, note) when the feed can't be read."""
    try:
        text = feeds.fetch("announcements")
    except OSError as e:
        return {}, "news not checked: could not reach NSE's announcements feed (%s)" % e
    out = {}
    for sym, name in names.items():
        rows = news.run(text, [name, sym], now, hours=24, min_impact="high")
        if rows:
            out[sym] = rows
    return out, None


def plan_hit(cfg, h, now, journal, bars_, target, runs):
    """One scanner hit through exit, budget, risk and (when possible) the time machine."""
    sym = h["symbol"]
    entry = h["entry"] if h["state"] == "triggered" else h["trigger"]
    row = {"symbol": sym, "setup": h["setup"], "state": h["state"], "why": h["why"], "last": h["last"],
           "vwap": h.get("vwap"), "day_change_pct": h.get("day_change_pct"), "volume_ok": h.get("volume_ok", True),
           "entry": entry}
    try:
        if h["setup"] == "orb":
            p = ex.make_plan(cfg, sym, entry, "or-mid", target, h["or_high"], h["or_low"], now=now, setup="orb")
        else:
            p = ex.make_plan(cfg, sym, entry, "price:%.2f" % h["stop"], target, now=now, setup=h["setup"])
    except ex.Refused as e:
        row["dropped"] = "no plan: %s" % e
        return row
    row.update(stop=p["stop"], target=p["target"], flat_by=p["flat_by"], stop_rule=p["stop_rule"])
    try:
        o = bud.size(cfg, p, journal, now)
    except bud.Refused as e:
        row["dropped"] = "no size: %s" % e
        return row
    r = risk.check(cfg, o, journal, now)
    row.update(qty=o["qty"], value=o["value"], loss_at_stop=o["max_loss_net"], gain_at_target=o["net_pnl_at_target"],
               reward_risk_net=o["reward_risk_net"], breakeven=o["breakeven_exit"],
               verdict=r["verdict"], blocks=r["blocks"])
    if len(B.sessions(bars_)) >= 6 and runs:
        try:
            t = tm.run(cfg, p, bars_, o["qty"], runs=runs, at=now.strftime("%H:%M"))
            row["replay"] = {"p_net_profit": t["p_net_profit"], "expected_net": t["expected_net"],
                             "p_target": t["p_target"], "p_stop": t["p_stop"], "runs": runs,
                             "past_fired": (t.get("history_summary") or {}).get("fired")}
        except ValueError as e:
            row["replay_note"] = str(e)
    return row


def score(row):
    """Higher is better. Triggered beats forming; then net reward:risk, volume, VWAP and the replay."""
    s = STATE_POINTS[row["state"]] + 3 * min(row.get("reward_risk_net") or 0, 4)
    s += 2 if row.get("volume_ok") else 0
    s += 1 if row.get("vwap") and row.get("last", 0) > row["vwap"] else 0
    rp = row.get("replay")
    if rp:
        s += 3 if rp["expected_net"] > 0 else -3
    if row.get("verdict") == "BLOCK":
        s -= 10
    if row.get("news"):
        s -= 2   # a big filing today makes the move less predictable, either way
    return round(s, 2)


def run(cfg, date, at, now, top=10, target="2R", runs=2000, with_news=True):
    journal = nselib.journal()
    cash, under = candle_files()
    res = scan.run(cfg, cash, date, at)
    loaded = {scan.symbol_of(f): f for f in cash}
    rows = []
    for h in res["hits"]:
        if h["state"] not in STATE_POINTS:
            continue
        rows.append(plan_hit(cfg, h, now, journal, B.load(loaded[h["symbol"]]), target, runs))
    notes = []
    if with_news:
        flags, note = filings_today(cfg, now, names_for(cfg))
        if note:
            notes.append(note)
        for r in rows:
            if r["symbol"] in flags:
                r["news"] = ["%s: %s" % (x["tag"], x["subject"][:90]) for x in flags[r["symbol"]]]
    live = [r for r in rows if "dropped" not in r]
    for r in live:
        r["score"] = score(r)
    live.sort(key=lambda r: -r["score"])
    best = {}
    for r in live:   # one line per stock: its best setup
        best.setdefault(r["symbol"], r)
    ranked = list(best.values())

    fno, fno_notes = [], []
    for u in sorted(os.path.splitext(os.path.basename(f))[0].upper() for f in glob.glob(nselib.path("fno", "*.json"))):
        f = under.get(u)
        saved = nselib.read_json(nselib.path("fno", u + ".json"))
        if not f:
            fno_notes.append("%s: option data saved but no candles in nse/candles/%s.csv" % (u, u))
            continue
        ideas, n = opt.ideas(cfg, u, B.load(f), saved, date, at, now, journal)
        fno += ideas
        fno_notes += n
    for o in fno:
        o["score"] = opt.score(o)
    fno.sort(key=lambda o: -o["score"])

    clock = market.status(now, cfg)
    ctx = {}
    if "NIFTY" in under:
        days = B.sessions(B.load(under["NIFTY"]))
        if date in days:
            today = B.until(days[date], at) if at else days[date]
            prev = [d for d in days if d < date]
            if today:
                ctx = {"nifty": today[-1]["c"],
                       "nifty_change_pct": round((today[-1]["c"] / days[prev[-1]][-1]["c"] - 1) * 100, 2) if prev else None}
        pcr = opt.parse_chain(nselib.read_json(nselib.path("fno", "NIFTY.json")) or {}).get("pcr")
        if pcr:
            ctx["nifty_pcr"] = round(pcr, 2)
    return {"date": date, "as_of": at or now.strftime("%H:%M"), "phase": clock["phase"],
            "can_enter": clock["can_enter"], "clock_reason": clock.get("reason"), "flat_by": clock["flat_by"],
            "market": ctx, "scanned": res["scanned"], "skipped": res["skipped"],
            "top": ranked[:top], "more": ranked[top:], "dropped": [r for r in rows if "dropped" in r],
            "fno": fno, "fno_notes": fno_notes, "notes": notes, "paper": bool(cfg.get("paper", True))}


def _inr(x):
    return nselib.inr(x) if x is not None else "-"


def describe(b, fno_top=3):
    head = "Market check %s, as of %s IST" % (b["date"], b["as_of"])
    if not b["can_enter"]:
        head += " (no new entries now: %s; read this as study, or as levels to watch next session)" % (
            b["clock_reason"] or b["phase"])
    out = [head]
    m = b["market"]
    if m.get("nifty"):
        out.append("Market: NIFTY %.2f%s%s" % (
            m["nifty"], " (%+.2f%% on the day)" % m["nifty_change_pct"] if m.get("nifty_change_pct") is not None else "",
            ", put-call ratio %.2f" % m["nifty_pcr"] if m.get("nifty_pcr") else ""))
    out.append("")
    out.append("Top intraday stocks (cash, long): %d of %d scanned" % (len(b["top"]), b["scanned"]))
    if not b["top"]:
        out.append("  None: no stock has a triggered or forming setup that plans and sizes inside your limits.")
    for i, r in enumerate(b["top"], 1):
        out.append("%2d. %-10s %s %s, score %.1f  %s" % (
            i, r["symbol"], scan_name(r["setup"]), r["state"].upper(), r["score"],
            "PASS" if r["verdict"] == "PASS" else "BLOCK"))
        out.append("    %s" % r["why"])
        out.append("    %s %.2f, stop %.2f, target %.2f, flat by %s; %d shares (%s)" % (
            "buy at" if r["state"] == "triggered" else "buy only on a close above", r["entry"], r["stop"],
            r["target"], r["flat_by"], r["qty"], _inr(r["value"])))
        out.append("    loses %s at the stop, makes %s at the target after charges (%.2f:1)" % (
            _inr(r["loss_at_stop"]), _inr(r["gain_at_target"]), r["reward_risk_net"] or 0))
        if r.get("replay"):
            rp = r["replay"]
            out.append("    replay: net profit in %.0f%% of %d runs, average %s" % (
                rp["p_net_profit"], rp["runs"], _inr(rp["expected_net"])))
        for blk in r.get("blocks") or []:
            out.append("    blocked: %s" % blk)
        for n in r.get("news") or []:
            out.append("    filing today: %s" % n)
    if b["more"]:
        out.append("  Also: " + ", ".join("%s (%s %s)" % (r["symbol"], r["setup"], r["state"]) for r in b["more"]))
    if b["dropped"]:
        out.append("  Left out: " + "; ".join("%s %s: %s" % (r["symbol"], r["setup"], r["dropped"]) for r in b["dropped"][:6]))

    out.append("")
    out.append("F&O (option buying, paper only):")
    if not b["fno"]:
        out.append("  No idea: save option data for NIFTY or an F&O stock (see SKILL.md), or no setup is live.")
    else:
        usable = [o for o in b["fno"] if not o["skip"]]
        pick = usable[0] if usable else b["fno"][0]
        out.append("  Top pick:" if usable else "  Best idea, but it doesn't fit your limits:")
        out.append("  " + opt.describe(pick).replace("\n", "\n  "))
        others = [o for o in b["fno"] if o is not pick][:fno_top - 1]
        for o in others:
            out.append("  Also: %s %s at %.2f (stop %.2f, target %.2f), %s%s" % (
                o["title"], o["state"], o["premium_entry"], o["premium_stop"], o["premium_target"],
                o["setup_name"], "; skip: " + o["skip"] if o["skip"] else ""))
    for n in b["fno_notes"]:
        out.append("  note: %s" % n)

    out.append("")
    out.append("Exits for everything above: the stop, the target, or the flat-by time %s, whichever comes first. "
               "Put the stop in as soon as you are in." % b["flat_by"])
    for n in b["notes"]:
        out.append("Note: %s" % n)
    out.append("%s mode. Ranked pattern matches, not recommendations: you decide and place every order yourself. "
               "Most intraday and F&O traders lose money. Not financial advice." % ("Paper" if b["paper"] else "LIVE"))
    return "\n".join(out)


def scan_name(setup):
    return opt.SETUP_NAME.get(setup, setup)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check the market: top intraday stocks and an F&O pick, from saved data.")
    ap.add_argument("--date", help="YYYY-MM-DD (default today)")
    ap.add_argument("--at", help="HH:MM: use bars closed by then (default now)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--target", default="2R", help="target rule for stocks (2R, 2.5R ...)")
    ap.add_argument("--runs", type=int, default=2000, help="time-machine runs per stock with enough history (0 = off)")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="also save nse/brief.json")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    if a.date and a.at:
        now = market.now_ist("%s %s" % (a.date, a.at))
    else:
        now = market.now_ist()
    date = a.date or now.strftime("%Y-%m-%d")
    b = run(cfg, date, a.at, now, a.top, a.target, a.runs, not a.no_news)
    if a.write:
        nselib.write_json(nselib.path("brief.json"), b)
    print(json.dumps(b, indent=2, default=str) if a.json else describe(b))
    return 0


if __name__ == "__main__":
    sys.exit(main())
