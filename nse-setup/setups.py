"""The three intraday setups, read from closed bars only. Shared by nse-scanner,
nse-entry and nse-timemachine, so they all mean the same thing by a setup.

Each detector takes today's CLOSED bars (oldest first) and returns None or a
dict with: setup, state ("forming", "triggered", "stale" or "failed"),
trigger (the price that confirms it), entry (for a triggered one: the
close of the trigger bar), stop (where it has failed), bar (the trigger
bar's time) and why.

These are mechanical pattern definitions, not predictions. Read them before
trusting a scan.
"""

import bars as B
import nselib

DEFAULTS = {
    "or_minutes": 15,         # opening range: the first 15 minutes from 09:15
    "volume_mult": 1.5,       # breakout bar volume vs the average bar so far (the opening bar left out)
    "fresh_bars": 3,          # a breakout older than this many bars is stale
    "pole_min_pct": 1.0,      # flag pole: at least this % rise ...
    "pole_max_bars": 8,       # ... within this many bars
    "flag_min_bars": 2,
    "flag_max_bars": 10,
    "flag_max_retrace": 0.5,  # the flag may give back at most half the pole
    "rsi_len": 14,
    "rsi_oversold": 30,
    "bounce_lookback": 6,
}


def params(cfg):
    p = dict(DEFAULTS)
    p.update(cfg.get("setups", {}) or {})
    return p


def _hm_add(hm, minutes):
    h, m = map(int, hm.split(":"))
    t = h * 60 + m + minutes
    return "%02d:%02d" % (t // 60, t % 60)


def orb(today, p, tick, history=None):
    """Opening-range breakout: a close above the high of the first or_minutes."""
    if not today:
        return None
    step = B.interval_minutes(today) if len(today) > 1 else 5
    end = _hm_add("09:15", int(p["or_minutes"]))
    rng = [b for b in today if b["hm"] < end]
    if len(rng) < max(1, int(p["or_minutes"]) // step) or len(today) == len(rng):
        return None
    hi, lo = max(b["h"] for b in rng), min(b["l"] for b in rng)
    after = today[len(rng):]
    base = {"setup": "orb", "or_high": hi, "or_low": lo,
            "stop": nselib.to_tick((hi + lo) / 2.0, tick, "down"), "stop_rule": "or-mid"}
    for i, b in enumerate(after):
        if b["c"] < lo:
            return dict(base, state="failed", trigger=None, entry=None, bar=b["hm"],
                        why="closed under the opening-range low %.2f at %s before any breakout" % (lo, b["hm"]))
        if b["c"] > hi:
            prior = today[1:len(rng) + i] or today[:1]
            avg_v = sum(x["v"] for x in prior) / len(prior)
            vol_ok = b["v"] >= p["volume_mult"] * avg_v
            age = len(after) - 1 - i
            state = "triggered" if age < int(p["fresh_bars"]) else "stale"
            return dict(base, state=state, trigger=nselib.to_tick(hi, tick, "up"),
                        entry=nselib.to_tick(b["c"], tick, "nearest"), bar=b["hm"], volume_ok=vol_ok,
                        bars_ago=age,
                        why="closed %.2f above the opening-range high %.2f at %s, volume %.1fx average%s" % (
                            b["c"], hi, b["hm"], b["v"] / avg_v if avg_v else 0,
                            "" if vol_ok else " (weak)"))
    return dict(base, state="forming", trigger=nselib.to_tick(hi + tick, tick, "up"), entry=None,
                bar=today[-1]["hm"], why="inside the opening range %.2f to %.2f" % (lo, hi))


def _flag_at(bars_, p, tick):
    """A pole then a tight flag, in bars_ (all closed). Returns (pole_lo, pole_hi, flag) or None."""
    if len(bars_) < 4:
        return None
    j = max(range(len(bars_)), key=lambda k: (bars_[k]["h"], k))
    flag = bars_[j + 1:]
    if not (int(p["flag_min_bars"]) <= len(flag) <= int(p["flag_max_bars"])):
        return None
    lo_from = max(0, j - int(p["pole_max_bars"]))
    i = min(range(lo_from, j + 1), key=lambda k: bars_[k]["l"])
    if j - i < 2:
        return None
    pole_lo, pole_hi = bars_[i]["l"], bars_[j]["h"]
    height = pole_hi - pole_lo
    if height <= 0 or height / pole_lo * 100 < p["pole_min_pct"]:
        return None
    if min(b["l"] for b in flag) < pole_hi - p["flag_max_retrace"] * height:
        return None
    return pole_lo, pole_hi, flag


def flag(today, p, tick, history=None):
    """Bull flag: a sharp rise, a short tight pullback, then a close above the flag's high."""
    if len(today) >= 5:
        found = _flag_at(today[:-1], p, tick)
        if found:
            pole_lo, pole_hi, fl = found
            top = max(b["h"] for b in fl)
            last = today[-1]
            if last["c"] > top:
                return {"setup": "flag", "state": "triggered", "trigger": nselib.to_tick(top, tick, "up"),
                        "entry": nselib.to_tick(last["c"], tick, "nearest"),
                        "stop": nselib.to_tick(min(b["l"] for b in fl) - tick, tick, "down"), "stop_rule": "flag-low",
                        "bar": last["hm"], "pole": [pole_lo, pole_hi],
                        "why": "pole %.2f to %.2f (+%.1f%%), %d-bar flag, closed %.2f above its high %.2f" % (
                            pole_lo, pole_hi, (pole_hi - pole_lo) / pole_lo * 100, len(fl), last["c"], top)}
    found = _flag_at(today, p, tick)
    if found:
        pole_lo, pole_hi, fl = found
        top = max(b["h"] for b in fl)
        return {"setup": "flag", "state": "forming", "trigger": nselib.to_tick(top + tick, tick, "up"), "entry": None,
                "stop": nselib.to_tick(min(b["l"] for b in fl) - tick, tick, "down"), "stop_rule": "flag-low",
                "bar": today[-1]["hm"], "pole": [pole_lo, pole_hi],
                "why": "pole %.2f to %.2f (+%.1f%%), %d-bar flag so far" % (
                    pole_lo, pole_hi, (pole_hi - pole_lo) / pole_lo * 100, len(fl))}
    return None


def bounce(today, p, tick, history=None):
    """Oversold bounce: RSI under the oversold line in the last few bars, then a close above the prior bar's high."""
    closes = [b["c"] for b in (history or [])] + [b["c"] for b in today]
    n, look = int(p["rsi_len"]), int(p["bounce_lookback"])
    if len(today) < 3 or len(closes) < n + 2:
        return None
    off = len(closes) - len(today)
    rsis = [B.rsi(closes[:off + k + 1], n) for k in range(max(0, len(today) - look - 1), len(today))]
    rsis = [r for r in rsis if r is not None]
    if not rsis:
        return None
    recent = today[-look:]
    low = min(b["l"] for b in recent)
    last, prev = today[-1], today[-2]
    if min(rsis[:-1] or rsis) < p["rsi_oversold"] and last["c"] > prev["h"]:
        return {"setup": "bounce", "state": "triggered", "trigger": nselib.to_tick(prev["h"], tick, "up"),
                "entry": nselib.to_tick(last["c"], tick, "nearest"),
                "stop": nselib.to_tick(low - tick, tick, "down"), "stop_rule": "recent-low", "bar": last["hm"],
                "rsi_min": round(min(rsis), 1),
                "why": "RSI(%d) fell to %.1f, then %s closed %.2f above the prior bar's high %.2f" % (
                    n, min(rsis), last["hm"], last["c"], prev["h"])}
    if rsis[-1] < p["rsi_oversold"]:
        return {"setup": "bounce", "state": "forming", "trigger": nselib.to_tick(last["h"] + tick, tick, "up"),
                "entry": None, "stop": nselib.to_tick(low - tick, tick, "down"), "stop_rule": "recent-low",
                "bar": last["hm"], "rsi_min": round(min(rsis), 1),
                "why": "RSI(%d) %.1f, oversold; waiting for a close above %.2f" % (n, rsis[-1], last["h"])}
    return None


DETECTORS = {"orb": orb, "flag": flag, "bounce": bounce}


def detect(today, p, tick, history=None, which=None):
    out = []
    for name in (which or DETECTORS):
        r = DETECTORS[name](today, p, tick, history)
        if r:
            out.append(r)
    return out
