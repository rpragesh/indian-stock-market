#!/usr/bin/env python3
"""nse-options: turn a setup on an index or F&O stock into an option-buying plan, on paper.

The direction comes from the underlying's chart: a bullish setup (opening-
range breakout, bull flag, oversold bounce) means a call (CE); a bearish one
(opening-range breakdown, bear flag, overbought fade) means a put (PE). The
contract, entry, stop, target and lots are worked out on the premium:

- strike: the liquid one whose delta is nearest 0.55 (at or just in the money)
- entry: today's premium, moved by delta to where the underlying triggers
- stop and target: the underlying's stop and target, turned into premium with
  delta (and gamma), less the time decay (theta) until the flat-by time, with
  the stop never more than `max_premium_stop_pct` under the entry
- lots: as many as keep the loss at the stop, after charges, inside your max
  loss per trade, and the premium inside your position and cash limits

Claude saves what the broker connector returns for the underlying to
nse/fno/UNDERLYING.json, exactly as returned:

    {"oi": <get_open_interest_analysis, view metrics_only>,
     "ltp": <get_ltp, segment FNO, for strikes around the money, CE and PE>,
     "greeks": <get_greeks_for_fno_contract for the same strikes>}

and the underlying's 5-minute candles to nse/candles/UNDERLYING.csv.

    python3 options.py --underlying NIFTY                # today, bars closed by now
    python3 options.py --underlying NIFTY --date 2026-11-27 --at 11:00 --json

Option BUYING only, PAPER only, analysis only. Never places an order. Most
individual F&O traders lose money (SEBI's study of FY22 to FY24 found about
nine in ten did). Not financial advice.
"""

import argparse
import datetime as dt
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nse-setup"))
import bars as B  # noqa: E402
import charges  # noqa: E402
import nselib  # noqa: E402
import setups as S  # noqa: E402
from nselib import market  # noqa: E402

DEFAULTS = {"target_delta": 0.55, "max_premium_stop_pct": 35, "target_r": 2.0, "min_days_to_expiry": 1,
            "max_loss_per_trade_inr": None,   # None: use the account's max_loss_per_trade_inr
            "max_spot_gap_pct": 0.3}          # option prices taken this far from the chart's last close are rough
BULLISH = ("orb", "flag", "bounce")
BEARISH = ("orb_down", "bear_flag", "fade")
INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
STATE_RANK = {"triggered": 0, "forming": 1}
SETUP_NAME = {"orb": "opening-range breakout", "flag": "bull flag", "bounce": "oversold bounce",
              "orb_down": "opening-range breakdown", "bear_flag": "bear flag", "fade": "overbought fade"}


class Refused(Exception):
    pass


def params(cfg):
    p = dict(DEFAULTS)
    p.update(cfg.get("options", {}) or {})
    return p


def _res(x):
    return (x or {}).get("result", x or {})


def parse_chain(saved):
    """The saved connector answers -> {spot, lot, pcr, atm, expiry, contracts: [...]}."""
    oi, ltp, greeks = _res(saved.get("oi")), _res(saved.get("ltp")), _res(saved.get("greeks"))
    meta, metrics = oi.get("meta") or {}, oi.get("metrics") or {}
    m = re.search(r"Expiry:\s*(\d{4}-\d{2}-\d{2})", oi.get("note") or "")
    g_by = {g.get("growwContractId"): g for g in greeks.get("fno_contract_greeks") or []}
    contracts = []
    for title, q in (ltp.get("ltp_results") or {}).items():
        t = re.search(r"(\d{1,2} \w{3}) (\d+(?:\.\d+)?) (Call|Put)$", title)
        sym = q.get("symbol")
        if not t or not sym:
            continue
        g = g_by.get(sym, {})
        contracts.append({
            "symbol": sym, "title": title.replace("NSE-", "").replace("BSE-", ""),
            "type": "CE" if t.group(3) == "Call" else "PE", "strike": float(t.group(2)),
            "expiry": g.get("expiryDate"), "ltp": q.get("ltp"), "volume": q.get("volume") or 0,
            "oi": q.get("open_interest") or 0, "oi_change_pct": q.get("oi_day_change_perc"),
            "delta": g.get("delta"), "gamma": g.get("gamma"), "theta": g.get("theta"), "iv": g.get("iv")})
    expiry = m.group(1) if m else None
    if expiry:
        want = dt.date.fromisoformat(expiry).strftime("%d %b").lstrip("0")
        for c in contracts:
            if c["expiry"] is None:   # no greeks: read the expiry off the title ("01 Dec")
                d = re.search(r"(\d{1,2} \w{3}) \d", c["title"])
                c["expiry"] = expiry if d and d.group(1).lstrip("0") == want else "other"
        contracts = [c for c in contracts if c["expiry"] == expiry]
    return {"spot": meta.get("spot_price"), "lot": int(meta.get("lot_size") or metrics.get("lot_size") or 0),
            "pcr": metrics.get("pcr", meta.get("api_pcr")), "atm": metrics.get("atm_strike"),
            "expiry": expiry, "contracts": contracts}


def setups_for(bars_, cfg, date, at):
    """Bullish and bearish setups on the underlying's closed bars, best first."""
    days = B.sessions(bars_)
    if date not in days:
        return None, []
    today = B.until(days[date], at) if at else days[date]
    if not today:
        return None, []
    prior = [d for d in days if d < date]
    hist = [b for d in prior[-2:] for b in days[d]]
    hits = [h for h in S.detect(today, S.params(cfg), nselib.tick(cfg), hist, bearish=True)
            if h["state"] in STATE_RANK]
    hits.sort(key=lambda h: (STATE_RANK[h["state"]], not h.get("volume_ok", True),
                             (BULLISH + BEARISH).index(h["setup"])))
    return today[-1], hits


def pick_contract(chain, kind, p):
    """The liquid contract of this kind whose |delta| is nearest the target delta."""
    c = [x for x in chain["contracts"] if x["type"] == kind and x["ltp"] and x["ltp"] > 0]
    liquid = [x for x in c if x["volume"] and x["oi"]] or c
    if not liquid:
        return None
    with_delta = [x for x in liquid if x["delta"] is not None]
    if with_delta:
        return min(with_delta, key=lambda x: (abs(abs(x["delta"]) - p["target_delta"]), -x["oi"]))
    spot = chain["spot"] or 0
    return min(liquid, key=lambda x: abs(x["strike"] - spot))


def hours_left(now_hm, flat_by):
    a, b = (int(x) for x in now_hm.split(":")), (int(x) for x in flat_by.split(":"))
    (ah, am), (bh, bm) = a, b
    return max(0.0, ((bh * 60 + bm) - (ah * 60 + am)) / 60.0)


def plan(cfg, underlying, hit, chain, now, journal=None, last_close=None):
    """One option-buying plan from a setup on the underlying. Raises Refused when it can't be planned."""
    p = params(cfg)
    tick = nselib.tick(cfg)
    kind = "CE" if hit["setup"] in BULLISH else "PE"
    sign = 1 if kind == "CE" else -1
    if not chain["lot"]:
        raise Refused("no lot size in the saved option data")
    if not chain["spot"]:
        raise Refused("no spot price in the saved option data")
    today = now.date()
    if chain["expiry"]:
        dte = (dt.date.fromisoformat(chain["expiry"]) - today).days
    else:
        dte = None
    c = pick_contract(chain, kind, p)
    if not c:
        raise Refused("no %s prices in the saved option data" % kind)
    delta = abs(c["delta"]) if c["delta"] is not None else 0.5
    gamma = c["gamma"] or 0.0
    theta = abs(c["theta"] or 0.0)

    u_entry = hit["entry"] if hit["state"] == "triggered" else hit["trigger"]
    u_stop = hit["stop"]
    u_risk = abs(u_entry - u_stop)
    if u_risk <= 0 or sign * (u_entry - u_stop) <= 0:
        raise Refused("the setup's stop %.2f is on the wrong side of its entry %.2f" % (u_stop, u_entry))
    u_target = u_entry + sign * p["target_r"] * u_risk

    clock = market.status(now, cfg)
    hrs = hours_left(now.strftime("%H:%M"), clock["flat_by"])
    decay = theta * min(hrs, 6.25) / 6.25          # theta is per day; a trading day is 6h15m
    move_in = sign * (u_entry - chain["spot"])     # how far the underlying has to go to trigger, in our favour
    p_entry = c["ltp"] + delta * move_in + 0.5 * gamma * move_in * abs(move_in)
    p_entry = nselib.to_tick(max(p_entry, tick), tick, "nearest")
    # at the stop we are out early, so count half the decay; at the target, all of it (worst case)
    lose = delta * u_risk - 0.5 * gamma * u_risk ** 2 + decay / 2
    floor_pct = p["max_premium_stop_pct"]
    stop_note = "the underlying's stop, through delta, plus time decay"
    if lose > p_entry * floor_pct / 100.0:
        lose = p_entry * floor_pct / 100.0
        stop_note = "capped at %g%% of the premium (the chart stop is further)" % floor_pct
    p_stop = nselib.to_tick(max(p_entry - lose, tick), tick, "down")
    gain = delta * p["target_r"] * u_risk + 0.5 * gamma * (p["target_r"] * u_risk) ** 2 - decay
    p_target = nselib.to_tick(p_entry + max(gain, tick), tick, "up")

    lot = chain["lot"]
    broker, ex = cfg["broker"], "NSE" if underlying not in ("SENSEX", "BANKEX") else "BSE"
    max_loss = float(p["max_loss_per_trade_inr"] or cfg["max_loss_per_trade_inr"])
    journal = journal or {"trades": []}
    equity, cash = nselib.equity(cfg, journal), nselib.cash(cfg, journal)
    spendable = cash - equity * float(cfg.get("cash_buffer_pct", 0)) / 100.0
    cap = equity * float(cfg["max_position_pct"]) / 100.0
    one = charges.trade_charges(broker, p_entry, p_stop, lot, "options", ex)
    per_lot_loss = -one["net_pnl"]
    lots = int(math.floor(min(max_loss / per_lot_loss if per_lot_loss > 0 else 0,
                              max(spendable, 0) / (p_entry * lot), cap / (p_entry * lot))))
    while lots > 0 and -charges.trade_charges(broker, p_entry, p_stop, lot * lots, "options", ex)["net_pnl"] > max_loss:
        lots -= 1
    qty = max(lots, 1) * lot
    at_stop = charges.trade_charges(broker, p_entry, p_stop, qty, "options", ex)
    at_target = charges.trade_charges(broker, p_entry, p_target, qty, "options", ex)
    warnings = []
    if dte is not None and dte <= 0:
        warnings.append("it is expiry day: premiums can lose most of their value in hours")
    elif dte is not None and dte < p["min_days_to_expiry"]:
        warnings.append("expiry is %d day(s) away: time decay is fastest now" % dte)
    if c["volume"] == 0 or c["oi"] == 0:
        warnings.append("thin contract: no volume or open interest in the saved data")
    if hit["state"] == "forming":
        warnings.append("not triggered yet: enter only if the underlying closes %s %.2f" % (
            "above" if kind == "CE" else "below", u_entry))
    gap = abs(last_close - chain["spot"]) / chain["spot"] * 100 if last_close else 0
    if gap > p["max_spot_gap_pct"]:
        warnings.append("the option prices were saved with the underlying at %.2f, but the chart's last close is %.2f: "
                        "fetch fresh option prices, the premium levels here are rough" % (chain["spot"], last_close))
    if not cfg.get("allow_fno"):
        warnings.append("paper only: allow_fno is off in your config, so nse-risk and nse-ticket won't take it")
    rr = at_target["net_pnl"] / -at_stop["net_pnl"] if at_stop["net_pnl"] < 0 else None
    skip = None
    if rr is not None and rr < float(cfg.get("min_reward_risk", 0)):
        skip = "reward:risk after charges and time decay is %.2f, under your minimum %.2f" % (
            rr, float(cfg["min_reward_risk"]))
    if lots < 1:
        skip = ("1 lot (%d) loses %s at the stop after charges, over your %s max loss per trade"
                % (lot, nselib.inr(per_lot_loss), nselib.inr(max_loss))
                if per_lot_loss > max_loss else
                "1 lot costs %s, over your position or cash limit" % nselib.inr(p_entry * lot))
    return {
        "underlying": underlying, "spot": chain["spot"], "pcr": round(chain["pcr"], 2) if chain["pcr"] else None,
        "setup": hit["setup"], "setup_name": SETUP_NAME[hit["setup"]], "state": hit["state"], "why": hit["why"],
        "view": "bullish" if kind == "CE" else "bearish",
        "underlying_entry": u_entry, "underlying_stop": u_stop, "underlying_target": nselib.to_tick(u_target, tick, "nearest"),
        "contract": c["symbol"], "title": c["title"], "type": kind, "strike": c["strike"], "expiry": chain["expiry"],
        "days_to_expiry": dte, "ltp": c["ltp"], "delta": c["delta"], "theta": c["theta"], "iv": c["iv"],
        "oi": c["oi"], "volume": c["volume"],
        "premium_entry": p_entry, "premium_stop": p_stop, "premium_target": p_target, "stop_rule": stop_note,
        "decay_to_flat_by": round(decay, 2), "lot_size": lot, "lots": lots, "qty": qty,
        "premium_outlay": round(p_entry * qty, 2),
        "loss_at_stop": round(-at_stop["net_pnl"], 2), "gain_at_target": round(at_target["net_pnl"], 2),
        "charges_round_trip": at_stop["total_charges"],
        "reward_risk_net": round(rr, 2) if rr is not None else None, "max_loss_used": max_loss,
        "flat_by": clock["flat_by"], "warnings": warnings, "skip": skip, "paper_only": True,
    }


def ideas(cfg, underlying, bars_, saved, date, at, now, journal=None):
    """Every plannable setup on one underlying, best first."""
    chain = parse_chain(saved)
    last, hits = setups_for(bars_, cfg, date, at)
    out, notes = [], []
    if last is None:
        return [], ["%s: no candles for %s" % (underlying, date)]
    if chain["spot"] is None:
        chain["spot"] = last["c"]
    for h in hits:
        try:
            out.append(plan(cfg, underlying, h, chain, now, journal, last["c"]))
        except Refused as e:
            notes.append("%s %s: %s" % (underlying, h["setup"], e))
    return out, notes


def score(o):
    """Higher is better: triggered over forming, then net reward:risk, then liquidity."""
    s = (10 if o["state"] == "triggered" else 5) + min(o["reward_risk_net"] or 0, 4)
    s += 1 if (o["oi"] or 0) > 0 and (o["volume"] or 0) > 0 else -3
    s -= 3 if o["days_to_expiry"] is not None and o["days_to_expiry"] <= 0 else 0
    s -= 2 if o["skip"] else 0
    return round(s, 2)


def describe(o):
    lines = ["%s: %s %s, %s %s (%s)" % (o["underlying"], "BUY", o["title"], o["view"], o["setup_name"],
                                        o["state"].upper()),
             "  why: %s" % o["why"],
             "  underlying: entry %.2f, stop %.2f, target %.2f (spot %.2f%s)" % (
                 o["underlying_entry"], o["underlying_stop"], o["underlying_target"], o["spot"],
                 ", PCR %.2f" % o["pcr"] if o["pcr"] else ""),
             "  premium: entry %.2f, stop %.2f, target %.2f (now %.2f, delta %s, theta %s/day, ~%.2f decay to %s)" % (
                 o["premium_entry"], o["premium_stop"], o["premium_target"], o["ltp"],
                 "%.2f" % o["delta"] if o["delta"] is not None else "?",
                 "%.1f" % o["theta"] if o["theta"] is not None else "?", o["decay_to_flat_by"], o["flat_by"]),
             "  size: %s, %d qty, premium %s; loses %s at the stop, makes %s at the target after %s charges" % (
                 "%d lot%s" % (o["lots"], "" if o["lots"] == 1 else "s") if o["lots"] else "0 lots",
                 o["qty"], nselib.inr(o["premium_outlay"]), nselib.inr(o["loss_at_stop"]),
                 nselib.inr(o["gain_at_target"]), nselib.inr(o["charges_round_trip"])),
             "  exit: at the premium stop or target, or by %s whatever happens" % o["flat_by"]]
    if o["skip"]:
        lines.append("  SKIP under your limits: %s" % o["skip"])
    for w in o["warnings"]:
        lines.append("  note: %s" % w)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Option-buying plan from a setup on the underlying (paper only).")
    ap.add_argument("--underlying", required=True)
    ap.add_argument("--date")
    ap.add_argument("--at", help="HH:MM: use bars closed by then")
    ap.add_argument("--now", help='"YYYY-MM-DD HH:MM" IST')
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = nselib.config()
    u = a.underlying.upper()
    now = market.now_ist(a.now) if a.now else (
        market.now_ist("%s %s" % (a.date, a.at)) if a.date and a.at else market.now_ist())
    date = a.date or now.strftime("%Y-%m-%d")
    saved = nselib.read_json(nselib.path("fno", u + ".json"))
    if not saved:
        print("No option data at %s: save the connector's OI, LTP and greeks answers there (see SKILL.md)."
              % nselib.path("fno", u + ".json"))
        return 1
    f = next((nselib.path("candles", u + ext) for ext in (".csv", ".json")
              if os.path.exists(nselib.path("candles", u + ext))), None)
    if not f:
        print("No candles for %s in %s." % (u, nselib.path("candles")))
        return 1
    out, notes = ideas(cfg, u, B.load(f), saved, date, a.at, now, nselib.journal())
    out.sort(key=score, reverse=True)
    if a.json:
        print(json.dumps({"ideas": out, "notes": notes}, indent=2))
    else:
        print("\n".join(describe(o) for o in out) or "%s: no triggered or forming setup right now." % u)
        for n in notes:
            print("  " + n)
        print("Option buying, paper only. A pattern match, not a recommendation. Not financial advice.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
