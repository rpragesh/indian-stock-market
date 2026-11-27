#!/usr/bin/env python3
"""The NSE/BSE clock, in IST: is the market open, may I enter, when must I be flat.

    python3 market.py                       # status right now
    python3 market.py --now "2026-11-27 14:50"
    python3 market.py --json

Reads nse/config.json (start from config.example.json) for market hours,
entry windows, holidays and the square-off time. The square-off time is a
setting because brokers change it: square_off_time in the config wins, else
the broker's value in brokers.json. "Flat by" is square-off minus
exit_buffer_minutes, so the plan exits on our terms before the broker's
auto square-off (and its fee) kicks in.

Analysis only. Nothing here talks to a broker or places an order.
"""

import argparse
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join("nse", "config.json")

try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except Exception:  # Python < 3.9 or no tz database: IST has no DST
    IST = dt.timezone(dt.timedelta(hours=5, minutes=30), "IST")


def load_config(path=CONFIG_FILE):
    """nse/config.json laid over config.example.json, so missing keys get defaults."""
    with open(os.path.join(HERE, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            cfg.update(json.load(fh))
    return cfg


def load_brokers():
    with open(os.path.join(HERE, "brokers.json"), encoding="utf-8") as fh:
        return json.load(fh)


def now_ist(text=None):
    if text:
        return dt.datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    return dt.datetime.now(IST)


def hm(text):
    h, m = text.split(":")
    return dt.time(int(h), int(m))


def square_off_time(cfg, brokers=None):
    if cfg.get("square_off_time"):
        return hm(cfg["square_off_time"])
    brokers = brokers or load_brokers()
    return hm(brokers["brokers"][cfg["broker"]]["auto_square_off"])


def flat_by(cfg, brokers=None):
    so = square_off_time(cfg, brokers)
    t = dt.datetime.combine(dt.date(2000, 1, 1), so) - dt.timedelta(minutes=int(cfg.get("exit_buffer_minutes", 0)))
    return t.time()


def is_trading_day(day, cfg):
    return day.weekday() < 5 and day.isoformat() not in set(cfg.get("holidays", []))


def status(now, cfg, brokers=None):
    """Everything a skill needs to know about the clock right now."""
    t = now.time().replace(second=0, microsecond=0)
    trading_day = is_trading_day(now.date(), cfg)
    open_t, close_t = hm(cfg["market_open"]), hm(cfg["market_close"])
    so, fb = square_off_time(cfg, brokers), flat_by(cfg, brokers)

    if not trading_day:
        phase = "closed, weekend or holiday"
    elif t < dt.time(9, 0):
        phase = "before pre-open"
    elif t < open_t:
        phase = "pre-open"
    elif t < close_t:
        phase = "open"
    else:
        phase = "closed for the day"

    can_enter, why = True, "inside the entry window"
    if phase != "open":
        can_enter, why = False, "market is " + phase
    elif t < hm(cfg["no_entries_before"]):
        can_enter, why = False, "no entries before %s" % cfg["no_entries_before"]
    elif t >= hm(cfg["no_entries_after"]):
        can_enter, why = False, "no entries after %s" % cfg["no_entries_after"]
    elif cfg.get("product") == "intraday" and t >= fb:
        can_enter, why = False, "past the flat-by time %s" % fb.strftime("%H:%M")

    minutes_to_flat = None
    if trading_day and phase == "open":
        delta = dt.datetime.combine(now.date(), fb) - dt.datetime.combine(now.date(), t)
        minutes_to_flat = int(delta.total_seconds() // 60)

    return {
        "now_ist": now.strftime("%Y-%m-%d %H:%M"),
        "trading_day": trading_day,
        "phase": phase,
        "can_enter": can_enter,
        "reason": why,
        "square_off": so.strftime("%H:%M"),
        "flat_by": fb.strftime("%H:%M"),
        "minutes_to_flat": minutes_to_flat,
        "must_exit_now": bool(cfg.get("product") == "intraday" and phase == "open" and t >= fb),
        "paper": bool(cfg.get("paper", True)),
        "broker": cfg["broker"],
        "holidays_loaded": len(cfg.get("holidays", [])),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description="NSE/BSE market clock in IST.")
    p.add_argument("--now", help='pin the clock, "YYYY-MM-DD HH:MM" IST')
    p.add_argument("--config", default=CONFIG_FILE)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    cfg = load_config(a.config)
    s = status(now_ist(a.now), cfg)
    if a.json:
        print(json.dumps(s, indent=2))
        return 0
    print("%s IST: market %s." % (s["now_ist"], s["phase"]))
    print("New entries: %s (%s)." % ("yes" if s["can_enter"] else "no", s["reason"]))
    print("%s square-off %s, so be flat by %s." % (s["broker"].title(), s["square_off"], s["flat_by"]))
    if s["must_exit_now"]:
        print("EXIT NOW: past the flat-by time.")
    elif s["minutes_to_flat"] is not None:
        print("%d minutes until flat-by." % s["minutes_to_flat"])
    print("Mode: %s." % ("PAPER" if s["paper"] else "LIVE TICKETS (you place every order yourself)"))
    if not s["holidays_loaded"]:
        print("Note: no exchange holidays loaded in nse/config.json, so holidays look like trading days.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
