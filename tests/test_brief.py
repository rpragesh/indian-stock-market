"""nse-options and nse-brief: option charges, bearish setups, option plans on real Groww data, and the one-command check."""

import io
import json
import os
import random
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import ROOT, load
import synth

opt = load("nse-options", "options")
brief = load("nse-brief", "brief")
import bars as B  # noqa: E402
import charges  # noqa: E402
import nselib  # noqa: E402
import setups as S  # noqa: E402
from nselib import market  # noqa: E402

FX = os.path.join(ROOT, "tests", "fixtures")
INFY = os.path.join(FX, "INFY-5m-2026-11-26-27.csv")
NIFTY = os.path.join(FX, "NIFTY-5m-2026-11-27.csv")
CHAIN = os.path.join(FX, "groww-fno-NIFTY.json")


def read_json(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


class WithNse(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = nselib.NSE_DIR
        nselib.NSE_DIR = self.dir
        self.cfg = read_json(os.path.join(ROOT, "nse-setup", "config.example.json"))
        self.cfg["broker"] = "groww"
        nselib.write_json(nselib.path("config.json"), self.cfg)
        self.cfg = nselib.config()

    def tearDown(self):
        nselib.NSE_DIR = self.old
        shutil.rmtree(self.dir)


class OptionCharges(unittest.TestCase):
    def test_one_lot_round_trip(self):
        r = charges.trade_charges("groww", 100, 120, 65, "options")
        self.assertEqual(r["brokerage"], 40.0)                     # Rs 20 flat, each side
        self.assertAlmostEqual(r["stt"], round(120 * 65 * 0.15 / 100, 2))   # 0.15% of the sell premium
        self.assertAlmostEqual(r["exchange_txn"], round((100 + 120) * 65 * 0.03553 / 100, 2))
        self.assertAlmostEqual(r["stamp_duty"], round(100 * 65 * 0.003 / 100, 2))
        self.assertEqual(r["net_pnl"], round(1300 - r["total_charges"], 2))

    def test_equity_unchanged(self):
        r = charges.trade_charges("groww", 1000, 1010, 50, "intraday")
        self.assertEqual(r["brokerage"], 40.0)
        self.assertAlmostEqual(r["exchange_txn"], round(100500 * 0.00307 / 100, 2))


class Bearish(unittest.TestCase):
    def test_real_infy_breakdown(self):
        days = B.sessions(B.load(INFY))
        p = S.params({})
        hist = days["2026-11-26"]
        forming = [h for h in S.detect(B.until(days["2026-11-27"], "10:30"), p, 0.05, hist, bearish=True)
                   if h["setup"] == "orb_down"][0]
        self.assertEqual((forming["state"], forming["trigger"]), ("forming", 1155.55))
        later = [h for h in S.detect(B.until(days["2026-11-27"], "12:00"), p, 0.05, hist, bearish=True)
                 if h["setup"] == "orb_down"][0]
        self.assertEqual(later["state"], "stale")
        self.assertEqual(later["entry"], 1154.0)
        self.assertGreater(later["stop"], later["entry"])           # a put's stop is above

    def test_mirror_of_a_breakout_is_a_breakdown(self):
        rng = random.Random(3)
        rows = synth.session("2026-10-01", 1000.0, rng, plant="orb")
        today = B.until(B.parse(synth.csv([rows])), "10:10")
        bull = S.orb(today, S.params({}), 0.05)
        k = 1000.0 ** 2
        mirrored = [dict(b, o=k / b["o"], h=k / b["l"], l=k / b["h"], c=k / b["c"]) for b in today]
        bear = S.orb_down(mirrored, S.params({}), 0.05)
        self.assertEqual(bear["state"], bull["state"])               # same pattern, upside down
        self.assertEqual(bear["bar"], bull["bar"])

    def test_long_only_by_default(self):
        days = B.sessions(B.load(INFY))
        hits = S.detect(days["2026-11-27"], S.params({}), 0.05, days["2026-11-26"])
        self.assertTrue(all(h["setup"] in ("orb", "flag", "bounce") for h in hits))


class Options(WithNse):
    def chain(self):
        return opt.parse_chain(read_json(CHAIN))

    def test_parse_real_groww_answers(self):
        c = self.chain()
        self.assertEqual((c["lot"], c["expiry"], c["spot"]), (65, "2026-12-01", 25607.2))
        self.assertEqual(len(c["contracts"]), 8)                    # the 08 Dec put is dropped
        self.assertTrue(all(x["expiry"] == "2026-12-01" for x in c["contracts"]))

    def test_pick_nearest_055_delta(self):
        c, p = self.chain(), opt.params({})
        self.assertEqual(opt.pick_contract(c, "CE", p)["symbol"], "NIFTY26D0125500CE")
        self.assertEqual(opt.pick_contract(c, "PE", p)["symbol"], "NIFTY26D0125600PE")

    def hit(self, kind="CE"):
        if kind == "CE":
            return {"setup": "orb", "state": "triggered", "entry": 25607.2, "trigger": 25600.0, "stop": 25580.0,
                    "why": "test"}
        return {"setup": "orb_down", "state": "triggered", "entry": 25607.2, "trigger": 25610.0, "stop": 25635.0,
                "why": "test"}

    def test_call_plan_and_limits(self):
        now = market.now_ist("2026-11-27 13:00")
        o = opt.plan(self.cfg, "NIFTY", self.hit(), self.chain(), now, last_close=25607.2)
        self.assertEqual(o["type"], "CE")
        self.assertEqual(o["premium_entry"], 191.85)                # triggered at the spot: today's premium
        self.assertLess(o["premium_stop"], o["premium_entry"])
        self.assertGreater(o["premium_target"], o["premium_entry"])
        self.assertGreaterEqual(o["premium_stop"], round(191.85 * 0.65, 2) - 0.05)   # stop capped at 35%
        self.assertEqual(o["lot_size"], 65)
        self.assertEqual(o["flat_by"], "15:10")
        self.assertTrue(o["paper_only"])
        if o["lots"] == 0:
            self.assertIn("max loss", o["skip"])

    def test_bigger_fno_limit_gives_lots(self):
        self.cfg["options"] = {"max_loss_per_trade_inr": 5000}
        self.cfg["min_reward_risk"] = 0
        now = market.now_ist("2026-11-27 13:00")
        o = opt.plan(self.cfg, "NIFTY", self.hit("PE"), self.chain(), now, last_close=25607.2)
        self.assertEqual(o["type"], "PE")
        self.assertGreaterEqual(o["lots"], 1)
        self.assertLessEqual(o["loss_at_stop"], 5000)
        self.assertIsNone(o["skip"])

    def test_stale_option_prices_warn(self):
        now = market.now_ist("2026-11-27 10:40")
        o = opt.plan(self.cfg, "NIFTY", self.hit(), self.chain(), now, last_close=25785.3)
        self.assertTrue(any("rough" in w for w in o["warnings"]))

    def test_ideas_on_real_nifty(self):
        now = market.now_ist("2026-11-27 10:40")
        ideas, notes = opt.ideas(self.cfg, "NIFTY", B.load(NIFTY), read_json(CHAIN), "2026-11-27", "10:40", now)
        self.assertEqual(ideas[0]["setup"], "orb_down")
        self.assertEqual(ideas[0]["type"], "PE")


class Brief(WithNse):
    def stocks(self, n=3):
        os.makedirs(nselib.path("candles"))
        for i in range(n):
            sess = synth.history(8, 1000.0 + 100 * i, seed=20 + i, plant_every=1)
            with open(nselib.path("candles", "STK%d.csv" % i), "w") as fh:
                fh.write(synth.csv(sess))
        return synth.days(8)[-1]

    def test_ranks_planned_sized_checked(self):
        day = self.stocks()
        now = market.now_ist("%s 10:10" % day)
        b = brief.run(self.cfg, day, "10:10", now, top=10, runs=300, with_news=False)
        self.assertTrue(b["top"])
        scores = [r["score"] for r in b["top"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        r = b["top"][0]
        for k in ("entry", "stop", "target", "qty", "loss_at_stop", "gain_at_target", "verdict", "flat_by"):
            self.assertIn(k, r)
        self.assertLessEqual(r["loss_at_stop"], self.cfg["max_loss_per_trade_inr"])
        self.assertIn("replay", r)                                   # 8 sessions saved: replayed
        self.assertEqual(len({x["symbol"] for x in b["top"]}), len(b["top"]))   # one line per stock

    def test_report_and_fno_section(self):
        day = self.stocks(1)
        os.makedirs(nselib.path("fno"))
        shutil.copy(CHAIN, nselib.path("fno", "NIFTY.json"))
        shutil.copy(NIFTY, nselib.path("candles", "NIFTY.csv"))
        now = market.now_ist("2026-11-27 10:40")
        b = brief.run(self.cfg, "2026-11-27", "10:40", now, with_news=False)
        self.assertNotIn("NIFTY", [r["symbol"] for r in b["top"]])    # an index is not a cash trade
        self.assertEqual(b["fno"][0]["underlying"], "NIFTY")
        text = brief.describe(b)
        self.assertIn("Top intraday stocks", text)
        self.assertIn("F&O (option buying, paper only)", text)
        self.assertIn("Not financial advice", text)
        self.assertEqual(b["market"]["nifty_pcr"], 0.59)

    def test_cli(self):
        day = self.stocks(2)
        out = io.StringIO()
        with redirect_stdout(out):
            code = brief.main(["--date", day, "--at", "10:10", "--no-news", "--runs", "0", "--write"])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(nselib.path("brief.json")))
        self.assertIn("Exits for everything above", out.getvalue())


if __name__ == "__main__":
    unittest.main()
