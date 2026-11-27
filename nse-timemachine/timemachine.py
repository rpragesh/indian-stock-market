#!/usr/bin/env python3
"""nse-timemachine: replay the planned trade 10,000 times before risking a rupee.

Two honest looks at the plan in nse/plan.json, both after charges:

1. Simulated sessions. Each run walks from the entry time to the flat-by
   time one bar at a time. For every bar slot (say 10:35) it borrows the
   moves of that same slot from a randomly picked past session of the same
   stock (the bar's high, low and close relative to its open), scaled to
   how volatile today has been. A bar that touches both the stop and the
   target counts as the stop. 10,000 runs, seeded, so a re-run gives the
   same answer.
2. Every past day the setup fired. The same setup rules, run bar by bar on
   each saved past session, with the plan's reward:risk, played out on what
   really happened next.

    python3 timemachine.py                     # nse/plan.json, qty from nse/order.json
    python3 timemachine.py --qty 40 --runs 20000 --seed 7
    python3 timemachine.py --json

Needs the stock's saved 5-minute candles (nse/candles/SYMBOL.json|csv), the
more past sessions the better (Groww keeps 90 days). Analysis only: the
odds describe the past, not the future, and nothing here places an order.
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import bars as B  # noqa: E402
import nselib  # noqa: E402
import setups as S  # noqa: E402
from nselib import charges, market  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-entry"))


def _mins(hm):
    h, m = map(int, hm.split(":"))
    return h * 60 + m


def slot_table(days, exclude):
    """hm -> list of (high/open, low/open, close/open) from past sessions."""
    table = {}
    for d, sess in days.items():
        if d == exclude:
            continue
        for b in sess:
            if b["o"] > 0 and b["v"] > 1:
                table.setdefault(b["hm"], []).append((b["h"] / b["o"], b["l"] / b["o"], b["c"] / b["o"]))
    return table


def vol_scale(days, date, at, table):
    """How volatile today's closed bars were vs the same slots in the past, clamped to 0.5..2."""
    today = B.until(days.get(date, []), at) if at else []
    num = den = 0.0
    for b in today:
        past = table.get(b["hm"])
        if past and b["o"] > 0:
            num += (b["h"] - b["l"]) / b["o"]
            den += sum(h - l for h, l, _ in past) / len(past)
    if den <= 0:
        return 1.0
    return max(0.5, min(2.0, num / den))


def simulate(plan, table, start_hm, flat_by, runs, seed, scale=1.0):
    rng = random.Random(seed)
    slots = sorted(hm for hm in table if _mins(hm) >= _mins(start_hm) and _mins(hm) < _mins(flat_by))
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    out = []
    for _ in range(runs):
        price, result = entry, None
        for hm in slots:
            h, l, c = rng.choice(table[hm])
            h, l, c = 1 + (h - 1) * scale, 1 + (l - 1) * scale, 1 + (c - 1) * scale
            if price * l <= stop:
                result = ("stop", stop, hm)
                break
            if price * h >= target:
                result = ("target", target, hm)
                break
            price *= c
        out.append(result or ("flat", round(price, 2), flat_by))
    return out, slots


def history(plan, days, cfg, rr):
    """Every past session where the plan's setup fired, played out on the real bars."""
    setup = plan.get("setup")
    if setup not in S.DETECTORS:
        return None
    p, tick = S.params(cfg), nselib.tick(cfg)
    last_entry, flat_by = cfg.get("no_entries_after", "14:45"), plan["flat_by"]
    dates = [d for d in days if d != plan["date"]]
    rows = []
    for i, d in enumerate(dates):
        sess = days[d]
        prev = [b for dd in dates[max(0, i - 2):i] for b in days[dd]]
        fired = None
        for k in range(1, len(sess) + 1):
            if sess[k - 1]["hm"] >= last_entry:
                break
            r = S.DETECTORS[setup](sess[:k], p, tick, prev)
            if r and r["state"] == "triggered" and r.get("bar") == sess[k - 1]["hm"]:
                fired = (k, r)
                break
        if not fired:
            continue
        k, r = fired
        e, s = r["entry"], r["stop"]
        if s is None or s >= e:
            continue
        t = e + rr * (e - s)
        outcome, px = "flat", sess[-1]["c"]
        for b in sess[k:]:
            if b["hm"] >= flat_by:
                break
            if b["l"] <= s:
                outcome, px = "stop", s
                break
            if b["h"] >= t:
                outcome, px = "target", t
                break
            px = b["c"]
        rows.append({"date": d, "bar": r["bar"], "entry": e, "stop": s, "target": round(t, 2), "outcome": outcome,
                     "exit": round(px, 2), "r": round((px - e) / (e - s), 2)})
    return rows


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return 0.0
    i = min(len(xs) - 1, max(0, int(round(q / 100.0 * (len(xs) - 1)))))
    return xs[i]


def run(cfg, plan, bars_, qty, runs=10000, seed=42, at=None):
    days = B.sessions(bars_)
    past = [d for d in days if d != plan["date"]]
    if len(past) < 5:
        raise ValueError("only %d past sessions saved: fetch at least 20 days of 5-minute candles" % len(past))
    table = slot_table(days, plan["date"])
    start = at or plan.get("written_at", "")[11:16] or "09:30"
    scale = vol_scale(days, plan["date"], start, table)
    sims, slots = simulate(plan, table, start, plan["flat_by"], runs, seed, scale)
    if not slots:
        raise ValueError("no bars between %s and the flat-by time %s" % (start, plan["flat_by"]))

    b, pr, ex = cfg["broker"], plan["product"], plan["exchange"]
    cache = {}

    def net(exit_px):
        k = round(exit_px, 2)
        if k not in cache:
            cache[k] = charges.trade_charges(b, plan["entry"], k, qty, pr, ex)["net_pnl"]
        return cache[k]

    pnls = [net(px) for _, px, _ in sims]
    counts = {k: sum(1 for o, _, _ in sims if o == k) for k in ("target", "stop", "flat")}
    flat_net = [p for (o, _, _), p in zip(sims, pnls) if o == "flat"]
    rr = plan["reward_risk_gross"]
    hist = history(plan, days, cfg, rr)
    res = {
        "symbol": plan["symbol"], "date": plan["date"], "setup": plan.get("setup"),
        "entry": plan["entry"], "stop": plan["stop"], "target": plan["target"], "qty": qty,
        "from": start, "flat_by": plan["flat_by"], "runs": runs, "seed": seed,
        "past_sessions": len(past), "bar_slots": len(slots), "vol_scale": round(scale, 2),
        "p_target": round(counts["target"] / runs * 100, 1),
        "p_stop": round(counts["stop"] / runs * 100, 1),
        "p_flat": round(counts["flat"] / runs * 100, 1),
        "p_net_profit": round(sum(1 for p in pnls if p > 0) / runs * 100, 1),
        "net_at_target": net(plan["target"]), "net_at_stop": net(plan["stop"]),
        "flat_avg_net": round(sum(flat_net) / len(flat_net), 2) if flat_net else None,
        "expected_net": round(sum(pnls) / runs, 2),
        "net_p5": round(pct(pnls, 5), 2), "net_median": round(pct(pnls, 50), 2), "net_p95": round(pct(pnls, 95), 2),
        "history": hist,
    }
    if hist is not None:
        res["history_summary"] = {
            "fired": len(hist), "target": sum(1 for h in hist if h["outcome"] == "target"),
            "stop": sum(1 for h in hist if h["outcome"] == "stop"), "flat": sum(1 for h in hist if h["outcome"] == "flat"),
            "avg_r": round(sum(h["r"] for h in hist) / len(hist), 2) if hist else None}
    return res


def describe(r):
    out = [
        "Time machine: %s %s, %d shares, entry %.2f, stop %.2f, target %.2f, from %s to flat-by %s IST" % (
            r["symbol"], r["setup"] or "", r["qty"], r["entry"], r["stop"], r["target"], r["from"], r["flat_by"]),
        "",
        "%s simulated sessions, built from %d past sessions (%d bar slots, today's volatility x%.2f):" % (
            "{:,}".format(r["runs"]), r["past_sessions"], r["bar_slots"], r["vol_scale"]),
        "  Target first   %5.1f%%   net %s" % (r["p_target"], nselib.inr(r["net_at_target"])),
        "  Stop first     %5.1f%%   net %s" % (r["p_stop"], nselib.inr(r["net_at_stop"])),
        "  Out at flat-by %5.1f%%   average net %s" % (r["p_flat"], nselib.inr(r["flat_avg_net"]) if r["flat_avg_net"] is not None else "-"),
        "  Net profit after charges in %.1f%% of runs. Average %s a trade; middle %s; worst 5%% %s or less; best 5%% %s or more." % (
            r["p_net_profit"], nselib.inr(r["expected_net"]), nselib.inr(r["net_median"]), nselib.inr(r["net_p5"]),
            nselib.inr(r["net_p95"])),
    ]
    hs = r.get("history_summary")
    if hs is not None:
        out += ["", "Every past day the %s setup fired (same rules, reward:risk as planned): %d" % (r["setup"], hs["fired"])]
        for h in r["history"][-10:]:
            out.append("  %s %s  entry %.2f stop %.2f target %.2f -> %-6s %.2f (%+.2fR)" % (
                h["date"], h["bar"], h["entry"], h["stop"], h["target"], h["outcome"], h["exit"], h["r"]))
        if hs["fired"]:
            out.append("  Target %d, stop %d, flat %d; average %+.2fR before charges." % (hs["target"], hs["stop"], hs["flat"], hs["avg_r"]))
        if hs["fired"] < 20:
            out.append("  Only %d past cases: too few to lean on." % hs["fired"])
    if r["expected_net"] <= 0:
        out += ["", "On this history the trade loses money on average after charges."]
    out.append("These are odds from the past, not a forecast. Not financial advice.")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Replay the plan 10,000 times, after charges.")
    ap.add_argument("--qty", type=int)
    ap.add_argument("--runs", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--at", help="HH:MM entry time (default: when the plan was written)")
    ap.add_argument("--file", help="candle file (default nse/candles/SYMBOL.json|csv)")
    ap.add_argument("--write", action="store_true", help="write nse/timemachine.json")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    plan = nselib.read_json(nselib.path("plan.json"))
    if not plan:
        print("No nse/plan.json: run nse-exit first.")
        return 1
    qty = a.qty
    if qty is None:
        o = nselib.read_json(nselib.path("order.json")) or {}
        qty = o.get("qty") if o.get("symbol") == plan["symbol"] and o.get("date") == plan["date"] else None
    if qty is None:
        print("No quantity: run nse-budget first, or pass --qty.")
        return 1
    import entry as E  # noqa: E402  (nse-entry's candle_file)
    f = a.file or E.candle_file(plan["symbol"])
    if not f:
        print("No candles for %s in %s." % (plan["symbol"], nselib.path("candles")))
        return 1
    try:
        r = run(cfg, plan, B.load(f), qty, a.runs, a.seed, a.at)
    except ValueError as e:
        print("REFUSED: %s" % e)
        return 2
    if a.write:
        nselib.write_json(nselib.path("timemachine.json"), r)
    print(json.dumps(r, indent=2) if a.json else describe(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
