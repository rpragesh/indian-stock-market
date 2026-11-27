"""nse-scanner, nse-entry, nse-timemachine and nse-alerts on real Groww candles and synthetic sessions."""

import io
import os
import random
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import ROOT, load
import synth

sc = load("nse-scanner", "scan")
en = load("nse-entry", "entry")
tm = load("nse-timemachine", "timemachine")
al = load("nse-alerts", "alerts")
ex = load("nse-exit", "exit")
import bars as B  # noqa: E402
import nselib  # noqa: E402
import setups as S  # noqa: E402

REAL = os.path.join(ROOT, "tests", "fixtures", "INFY-5m-2026-11-26-27.csv")


def run(mod, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = mod.main(list(args))
    return code, out.getvalue()


class Bars(unittest.TestCase):
    def test_real_groww_csv(self):
        bars_ = B.load(REAL)
        days = B.sessions(bars_)
        self.assertEqual(list(days), ["2026-11-26", "2026-11-27"])
        self.assertEqual(days["2026-11-27"][0]["o"], 1179.0)
        self.assertEqual(B.interval_minutes(bars_), 5)

    def test_groww_json_shape(self):
        txt = '{"result": {"candles": [{"timestamp": "2026-11-27T09:20:00", "open": 2, "high": 3, "low": 1, "close": 2.5, "volume": 9},' \
              '{"timestamp": "2026-11-27T09:15:00", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 5}]}}'
        b = B.parse(txt)
        self.assertEqual([x["hm"] for x in b], ["09:15", "09:20"])

    def test_until_uses_closed_bars_only(self):
        day = B.sessions(B.load(REAL))["2026-11-27"]
        self.assertEqual(B.until(day, "09:30")[-1]["hm"], "09:25")   # the 09:25 bar closes at 09:30
        self.assertEqual(len(B.until(day, "09:29")), 2)

    def test_rsi_extremes(self):
        self.assertEqual(B.rsi(list(range(1, 30))), 100.0)
        self.assertLess(B.rsi(list(range(30, 1, -1))), 1)
        self.assertIsNone(B.rsi([1, 2, 3]))


class RealORB(unittest.TestCase):
    """INFY 26 Nov 2026: range 1151.00 to 1166.50, first close above it at 14:00 (1168.30)."""

    def setUp(self):
        self.day = B.sessions(B.load(REAL))["2026-11-26"]
        self.p = S.params({})

    def test_forming_then_triggered_then_stale(self):
        r = S.orb(B.until(self.day, "11:00"), self.p, 0.05)
        self.assertEqual((r["state"], r["or_high"], r["or_low"]), ("forming", 1166.5, 1151.0))
        r = S.orb(B.until(self.day, "14:05"), self.p, 0.05)
        self.assertEqual((r["state"], r["entry"], r["bar"], r["stop"]), ("triggered", 1168.3, "14:00", 1158.75))
        self.assertFalse(r["volume_ok"])                       # 1.3x average: weak
        self.assertEqual(S.orb(B.until(self.day, "14:20"), self.p, 0.05)["state"], "stale")

    def test_failed_on_27th(self):
        day = B.sessions(B.load(REAL))["2026-11-27"]
        r = S.orb(B.until(day, "10:40"), self.p, 0.05)
        self.assertEqual(r["state"], "failed")                  # gap-down day: closed under the range low first


class Patterns(unittest.TestCase):
    def bar(self, hm, o, h, l, c, v=100000):
        return {"t": "2026-11-27 " + hm, "d": "2026-11-27", "hm": hm, "o": o, "h": h, "l": l, "c": c, "v": v}

    def test_flag(self):
        p = S.params({})
        seq = [("09:15", 100, 100.2, 99.9, 100.1), ("09:20", 100.1, 100.6, 100.0, 100.5),
               ("09:25", 100.5, 101.2, 100.4, 101.1), ("09:30", 101.1, 101.8, 101.0, 101.7),   # pole 99.9 -> 101.8
               ("09:35", 101.7, 101.75, 101.3, 101.4), ("09:40", 101.4, 101.5, 101.2, 101.3),  # flag
               ("09:45", 101.3, 101.45, 101.15, 101.35)]
        bars_ = [self.bar(*x) for x in seq]
        r = S.flag(bars_, p, 0.05)
        self.assertEqual(r["state"], "forming")
        self.assertEqual(r["stop"], 101.1)
        bars_.append(self.bar("09:50", 101.35, 102.0, 101.3, 101.9))
        r = S.flag(bars_, p, 0.05)
        self.assertEqual(r["state"], "triggered")
        self.assertEqual(r["entry"], 101.9)

    def test_deep_pullback_is_not_a_flag(self):
        seq = [("09:15", 100, 100.2, 99.9, 100.1), ("09:20", 100.1, 100.6, 100.0, 100.5),
               ("09:25", 100.5, 101.8, 100.4, 101.7), ("09:30", 101.7, 101.75, 100.2, 100.3),
               ("09:35", 100.3, 100.5, 100.1, 100.4)]
        self.assertIsNone(S.flag([self.bar(*x) for x in seq], S.params({}), 0.05))

    def test_bounce(self):
        p = S.params({})
        closes = [100 - 0.4 * k for k in range(30)]
        hist = [self.bar("09:15", c + 0.1, c + 0.2, c - 0.2, c) for c in closes[:20]]
        today = [self.bar("%02d:%02d" % divmod(9 * 60 + 15 + 5 * k, 60), c + 0.1, c + 0.2, c - 0.2, c)
                 for k, c in enumerate(closes[20:])]
        r = S.bounce(today, p, 0.05, hist)
        self.assertEqual(r["state"], "forming")
        last = today[-1]
        today.append(self.bar("10:05", last["c"], last["h"] + 0.6, last["c"] - 0.1, last["h"] + 0.5))
        r = S.bounce(today, p, 0.05, hist)
        self.assertEqual(r["state"], "triggered")
        self.assertLess(r["rsi_min"], 30)


class Tools(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = nselib.NSE_DIR
        nselib.NSE_DIR = self.dir
        os.makedirs(nselib.path("candles"))
        c = nselib.market.load_config(None)
        c["min_day_turnover_inr"] = 0
        nselib.write_json(nselib.path("config.json"), c)

    def tearDown(self):
        nselib.NSE_DIR = self.old
        shutil.rmtree(self.dir)

    def test_scan_real_day(self):
        shutil.copy(REAL, nselib.path("candles", "INFY-5m.csv"))
        code, out = run(sc, "--date", "2026-11-26", "--at", "14:10", "--write")
        self.assertEqual(code, 0)
        res = nselib.read_json(nselib.path("scan.json"))
        hit = [h for h in res["hits"] if h["setup"] == "orb"][0]
        self.assertEqual((hit["symbol"], hit["state"], hit["entry"]), ("INFY", "triggered", 1168.3))
        self.assertIn("--or-high 1166.50", hit["next"])

    def test_scan_skips_thin_and_blocked(self):
        shutil.copy(REAL, nselib.path("candles", "INFY.csv"))
        shutil.copy(REAL, nselib.path("candles", "TCS.csv"))
        c = nselib.config()
        c.update(min_day_turnover_inr=1e12, blocked=["TCS"])
        res = sc.run(c, sorted(__import__("glob").glob(nselib.path("candles", "*.csv"))), "2026-11-27", "11:00")
        reasons = {s["symbol"]: s["skipped"] for s in res["skipped"]}
        self.assertIn("thin", reasons["INFY"])
        self.assertIn("blocked", reasons["TCS"])

    def test_entry_writes_and_exit_reads_it(self):
        shutil.copy(REAL, nselib.path("candles", "INFY.csv"))
        code, out = run(en, "watch", "--symbol", "INFY", "--setup", "orb", "--date", "2026-11-26", "--at", "14:10",
                        "--write", "--now", "2026-11-26 14:10")
        self.assertIn("TRIGGERED", out)
        code, out = run(ex, "plan", "--from-entry", "--now", "2026-11-26 14:11", "--write")
        self.assertEqual(code, 0)
        p = nselib.read_json(nselib.path("plan.json"))
        self.assertEqual((p["entry"], p["stop"], p["setup"]), (1168.3, 1158.75, "orb"))

    def test_entry_level_and_late(self):
        shutil.copy(REAL, nselib.path("candles", "INFY.csv"))
        r = en.check(nselib.config(), "INFY", "level", B.load(REAL), "2026-11-27", "14:50", level=1164, stop=1150)
        self.assertEqual((r["state"], r["bar"]), ("triggered", "14:10"))
        self.assertIn("no entries after", r["late"])

    def test_timemachine_is_seeded_and_counts_add_up(self):
        sess = synth.history(25, 1000.0, seed=5, plant_every=3)
        with open(nselib.path("candles", "TEST.csv"), "w") as fh:
            fh.write(synth.csv(sess))
        date = sess[-1][0][0][:10]
        plan = ex.make_plan(nselib.config(), "TEST", 1000.0, "pct:0.5", "2R",
                            now=nselib.market.now_ist(date + " 10:05"), setup="orb")
        a = tm.run(nselib.config(), plan, B.load(nselib.path("candles", "TEST.csv")), 50, runs=2000, seed=1)
        b = tm.run(nselib.config(), plan, B.load(nselib.path("candles", "TEST.csv")), 50, runs=2000, seed=1)
        self.assertEqual(a["expected_net"], b["expected_net"])
        self.assertAlmostEqual(a["p_target"] + a["p_stop"] + a["p_flat"], 100.0, delta=0.2)
        self.assertLess(a["net_at_stop"], -250)                       # 50 x 5 risk, plus charges
        self.assertGreater(a["history_summary"]["fired"], 3)          # planted breakouts are found
        for h in a["history"]:
            self.assertIn(h["outcome"], ("target", "stop", "flat"))

    def test_timemachine_wide_target_rarely_hit(self):
        sess = synth.history(25, 1000.0, seed=9)
        with open(nselib.path("candles", "TEST.csv"), "w") as fh:
            fh.write(synth.csv(sess))
        date = sess[-1][0][0][:10]
        cfg = nselib.config()
        near = ex.make_plan(cfg, "TEST", 1000.0, "pct:0.5", "1R", now=nselib.market.now_ist(date + " 10:05"))
        far = ex.make_plan(cfg, "TEST", 1000.0, "pct:0.5", "6R", now=nselib.market.now_ist(date + " 10:05"))
        bars_ = B.load(nselib.path("candles", "TEST.csv"))
        self.assertGreater(tm.run(cfg, near, bars_, 10, 2000)["p_target"], tm.run(cfg, far, bars_, 10, 2000)["p_target"])

    def test_timemachine_needs_history(self):
        shutil.copy(REAL, nselib.path("candles", "INFY.csv"))
        plan = ex.make_plan(nselib.config(), "INFY", 1168.3, "pct:1", "2R", now=nselib.market.now_ist("2026-11-27 10:05"))
        with self.assertRaises(ValueError):
            tm.run(nselib.config(), plan, B.load(REAL), 10)

    def test_alerts(self):
        nselib.save_journal({"trades": [{"id": 1, "date": "2026-11-27", "symbol": "INFY", "qty": 40, "entry": 1160,
                                         "stop": 1150, "target": 1180, "status": "open", "max_loss_net": 450}]})
        now = nselib.market.now_ist("2026-11-27 11:00")
        rings, _ = al.check(nselib.config(), now, {"INFY": 1149.5}, nselib.journal(), None, {"alerts": []})
        self.assertEqual(rings[0][0], "stop")
        rings, _ = al.check(nselib.config(), now, {"INFY": 1181}, nselib.journal(), None, {"alerts": []})
        self.assertEqual(rings[0][0], "target")
        rings, _ = al.check(nselib.config(), nselib.market.now_ist("2026-11-27 15:12"), {"INFY": 1165},
                            nselib.journal(), None, {"alerts": []})
        self.assertIn("EXIT NOW", rings[0][1])
        rings, _ = al.check(nselib.config(), nselib.market.now_ist("2026-11-27 15:00"), {"INFY": 1165},
                            nselib.journal(), None, {"alerts": []})
        self.assertIn("10 minutes to flat-by", rings[0][1])

    def test_custom_alert_fires_once(self):
        run(al, "--now", "2026-11-27 10:00", "add", "--symbol", "SBIN", "--below", "800")
        code, out = run(al, "--now", "2026-11-27 10:05", "check", "--ltp", "SBIN=799")
        self.assertIn("#1 SBIN 799.00 is below 800.00", out)
        code, out = run(al, "--now", "2026-11-27 10:10", "check", "--ltp", "SBIN=798")
        self.assertNotIn("#1", out)

    def test_plan_chase_warning(self):
        plan = ex.make_plan(nselib.config(), "INFY", 1160, "price:1150", "2R", now=nselib.market.now_ist("2026-11-27 10:05"))
        rings, _ = al.check(nselib.config(), nselib.market.now_ist("2026-11-27 10:10"), {"INFY": 1166},
                            nselib.journal(), plan, {"alerts": []})
        self.assertIn("don't chase", rings[0][1])


if __name__ == "__main__":
    unittest.main()
