"""Candles: load them, split them into sessions, and the few indicators the skills use.

Python cannot call the broker connector, so Claude fetches candles with the
connector (Groww: fetch_historical_candle_data) and saves them under
nse/candles/. Two formats load:

1. The connector's JSON as returned, or just its list of candles:
   {"result": {"candles": [{"timestamp": "2026-11-27T09:15:00", "open": .., "high": ..,
                            "low": .., "close": .., "volume": ..}, ...]}}
2. Compact CSV, one bar a line, cheaper to write:
   2026-11-27 09:15,1179,1179,1160.6,1161,470477

Times are IST exchange times. Bars are sorted and de-duplicated by time.
"""

import collections
import json
import math


def _bar(ts, o, h, l, c, v):
    ts = str(ts).replace("T", " ")[:16]
    return {"t": ts, "d": ts[:10], "hm": ts[11:16], "o": float(o), "h": float(h), "l": float(l),
            "c": float(c), "v": float(v or 0)}


def parse(text):
    text = text.strip()
    bars = []
    if text.startswith("{") or text.startswith("["):
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("result", data)
            data = data.get("candles", data)
        for b in data:
            if isinstance(b, dict):
                bars.append(_bar(b.get("timestamp") or b.get("t"), b.get("open", b.get("o")),
                                 b.get("high", b.get("h")), b.get("low", b.get("l")),
                                 b.get("close", b.get("c")), b.get("volume", b.get("v"))))
            else:  # [ts, o, h, l, c, v]
                bars.append(_bar(*b[:6]))
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line or line[0].isalpha() or line.startswith("#"):
                continue  # header or comment
            parts = [p.strip() for p in line.split(",")]
            bars.append(_bar(parts[0], *parts[1:6]))
    seen = {}
    for b in bars:
        seen[b["t"]] = b
    return [seen[k] for k in sorted(seen)]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read())


def interval_minutes(bars):
    """The most common gap between bars inside a session."""
    gaps = collections.Counter()
    for a, b in zip(bars, bars[1:]):
        if a["d"] == b["d"]:
            ha, ma = map(int, a["hm"].split(":"))
            hb, mb = map(int, b["hm"].split(":"))
            gaps[(hb * 60 + mb) - (ha * 60 + ma)] += 1
    return gaps.most_common(1)[0][0] if gaps else 5


def sessions(bars, start="09:15", end="15:30"):
    """date -> that day's bars inside market hours, in order."""
    out = collections.OrderedDict()
    for b in bars:
        if start <= b["hm"] < end:
            out.setdefault(b["d"], []).append(b)
    return out


def until(session, hm):
    """Bars that have CLOSED by time hm (a bar stamped 10:00 on 5-minute candles closes at 10:05)."""
    step = interval_minutes(session) if len(session) > 1 else 5
    h, m = map(int, hm.split(":"))
    now = h * 60 + m
    out = []
    for b in session:
        bh, bm = map(int, b["hm"].split(":"))
        if bh * 60 + bm + step <= now:
            out.append(b)
    return out


def sma(xs, n):
    xs = xs[-n:]
    return sum(xs) / len(xs) if xs else 0.0


def atr(bars, n=14):
    """Average true range over the last n bars (fewer if that is all there is)."""
    trs = []
    for i, b in enumerate(bars):
        if i == 0:
            trs.append(b["h"] - b["l"])
        else:
            pc = bars[i - 1]["c"]
            trs.append(max(b["h"] - b["l"], abs(b["h"] - pc), abs(b["l"] - pc)))
    return sma(trs, n)


def rsi(closes, n=14):
    """Wilder's RSI on the closes; None until there are n + 1 of them."""
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[:n], closes[1:n + 1]):
        gains += max(b - a, 0)
        losses += max(a - b, 0)
    ag, al = gains / n, losses / n
    for a, b in zip(closes[n:], closes[n + 1:]):
        ag = (ag * (n - 1) + max(b - a, 0)) / n
        al = (al * (n - 1) + max(a - b, 0)) / n
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def vwap(session):
    pv = vol = 0.0
    for b in session:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        pv += tp * b["v"]
        vol += b["v"]
    return pv / vol if vol else (session[-1]["c"] if session else math.nan)
