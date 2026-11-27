"""Synthetic 5-minute sessions for tests: a seeded random walk, optionally with a planted setup."""

import random


def session(date, start_price, rng, vol=0.0015, bars=75, plant=None):
    """One NSE session of 5-minute bars, 09:15 to 15:25. plant='orb' forces a breakout at 10:00."""
    out, price = [], start_price
    for k in range(bars):
        t = 9 * 60 + 15 + 5 * k
        hm = "%02d:%02d" % divmod(t, 60)
        o = price
        c = o * (1 + rng.gauss(0, vol))
        if plant == "orb" and hm == "10:00":
            c = max(x[2] for x in out[:3]) * 1.004
        h = max(o, c) * (1 + abs(rng.gauss(0, vol / 2)))
        l = min(o, c) * (1 - abs(rng.gauss(0, vol / 2)))
        v = int(abs(rng.gauss(200000, 50000))) + (600000 if plant == "orb" and hm == "10:00" else 0)
        out.append(("%s %s" % (date, hm), round(o, 2), round(h, 2), round(l, 2), round(c, 2), v))
        price = c
    return out


def csv(sessions_):
    lines = ["time,open,high,low,close,volume"]
    for s in sessions_:
        for b in s:
            lines.append("%s,%s,%s,%s,%s,%s" % b)
    return "\n".join(lines) + "\n"


def days(n, start="2026-10-01"):
    import datetime as dt
    d = dt.date.fromisoformat(start)
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def history(n=25, price=1000.0, seed=1, plant_every=0):
    rng = random.Random(seed)
    out = []
    for i, d in enumerate(days(n)):
        plant = "orb" if plant_every and i % plant_every == 0 else None
        s = session(d, price, rng, plant=plant)
        out.append(s)
        price = s[-1][4]
    return out
