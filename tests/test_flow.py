"""nse-exit -> nse-budget -> nse-risk -> nse-ticket, end to end on a temp nse/ folder."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import load

ex = load("nse-exit", "exit")
bud = load("nse-budget", "size")
rk = load("nse-risk", "check")
tk = load("nse-ticket", "ticket")
import nselib  # noqa: E402  (on sys.path once a skill is loaded)

NOW = "2026-11-27 10:05"   # a Friday, inside the entry window


def run(mod, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = mod.main(list(args))
    return code, out.getvalue()


class Flow(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = nselib.NSE_DIR
        nselib.NSE_DIR = self.dir

    def tearDown(self):
        nselib.NSE_DIR = self.old
        shutil.rmtree(self.dir)

    def config(self, **over):
        c = nselib.market.load_config(None)
        c.update(over)
        nselib.write_json(nselib.path("config.json"), c)

    def plan(self, target="2R", **kw):
        args = ["plan", "--symbol", "INFY", "--entry", "1612.50", "--or-high", "1610", "--or-low", "1596.20",
                "--target", target, "--now", NOW, "--write"]
        return run(ex, *args)

    # ---- nse-exit ----
    def test_plan_rounds_stop_down_and_targets_2r(self):
        code, _ = self.plan()
        self.assertEqual(code, 0)
        p = nselib.read_json(nselib.path("plan.json"))
        self.assertEqual(p["stop"], 1603.10)      # (1610 + 1596.20) / 2 = 1603.10
        self.assertEqual(p["risk_per_share"], 9.40)
        self.assertEqual(p["target"], 1631.30)    # 1612.50 + 2 x 9.40
        self.assertEqual(p["flat_by"], "15:10")

    def test_plan_refusals(self):
        c = nselib.market.load_config(None)
        with self.assertRaises(ex.Refused):
            ex.make_plan(c, "SBIN", 800, "price:801")
        with self.assertRaises(ex.Refused):
            ex.make_plan(c, "SBIN", 800, "price:799.80")          # 0.025%: too tight
        with self.assertRaises(ex.Refused):
            ex.make_plan(c, "SBIN", 800, "pct:1", "price:790")
        with self.assertRaises(ex.Refused):
            ex.make_plan(c, "SBIN", 800, "pct:1", now=nselib.market.now_ist("2026-11-27 15:12"))
        with self.assertRaises(ex.Refused):
            ex.make_plan(dict(c, blocked=["SBIN"]), "SBIN", 800, "pct:1")

    def test_pct_stop_rounds_away_from_entry(self):
        p = ex.make_plan(nselib.market.load_config(None), "TATASTEEL", 152.40, "pct:1",
                         now=nselib.market.now_ist(NOW))
        self.assertEqual(p["stop"], 150.85)   # 150.876 rounded down to the 0.05 tick

    # ---- nse-budget ----
    def test_size_after_charges(self):
        self.config()
        self.plan()
        code, _ = run(bud, "--now", NOW, "--write")
        self.assertEqual(code, 0)
        o = nselib.read_json(nselib.path("order.json"))
        self.assertEqual(o["qty"], 31)
        self.assertEqual(o["decided_by"], "max position")
        self.assertEqual(o["max_loss_net"], 356.37)
        self.assertEqual(o["reward_risk_net"], 1.45)

    def test_charges_can_decide_the_size(self):
        # max loss 100 at 9.40 a share: floor(100 / 9.40) = 10, but charges push 10 shares over
        self.config(max_loss_per_trade_inr=100)
        self.plan()
        run(bud, "--now", NOW, "--write")
        o = nselib.read_json(nselib.path("order.json"))
        self.assertLess(o["qty"], 10)
        self.assertLessEqual(o["max_loss_net"], 100)
        self.assertIn("after charges", o["decided_by"])

    def test_size_refuses_when_one_share_is_too_much(self):
        self.config(max_loss_per_trade_inr=5)
        self.plan()
        code, out = run(bud, "--now", NOW)
        self.assertEqual(code, 2)
        self.assertIn("closer stop", out)

    def test_size_refuses_old_plan(self):
        self.config()
        self.plan()
        code, _ = run(bud, "--now", "2026-11-30 10:05")
        self.assertEqual(code, 2)

    # ---- nse-risk ----
    def test_risk_blocks_low_net_reward_risk_then_passes_wider_target(self):
        self.config()
        self.plan("2R")
        run(bud, "--now", NOW, "--write")
        code, out = run(rk, "--now", NOW)
        self.assertEqual(code, 1)
        self.assertIn("reward:risk", out)
        self.plan("2.5R")
        run(bud, "--now", NOW, "--write")
        code, _ = run(rk, "--now", NOW)
        self.assertEqual(code, 0)

    def test_risk_recomputes_an_edited_order(self):
        self.config()
        self.plan("2.5R")
        run(bud, "--now", NOW, "--write")
        o = nselib.read_json(nselib.path("order.json"))
        o["qty"] = 60                                   # hand-edited past the limits
        nselib.write_json(nselib.path("order.json"), o)
        r = rk.check(nselib.config(), o, nselib.journal(), nselib.market.now_ist(NOW))
        self.assertEqual(r["verdict"], "BLOCK")
        self.assertTrue(any(b.startswith("position") for b in r["blocks"]))
        self.assertTrue(any("edited" in w for w in r["warnings"]))

    def test_risk_window(self):
        self.config()
        self.plan("2.5R")
        run(bud, "--now", NOW, "--write")
        o = nselib.read_json(nselib.path("order.json"))
        r = rk.check(nselib.config(), o, nselib.journal(), nselib.market.now_ist("2026-11-27 14:50"))
        self.assertTrue(any(b.startswith("window") for b in r["blocks"]))

    def test_risk_daily_loss_and_trade_count(self):
        self.config(max_daily_loss_inr=600, max_trades_per_day=1)
        j = {"trades": [{"id": 1, "date": "2026-11-27", "symbol": "SBIN", "status": "closed", "net_pnl": -300.0,
                         "qty": 1, "entry": 800}]}
        nselib.save_journal(j)
        self.plan("2.5R")
        run(bud, "--now", NOW, "--write")
        o = nselib.read_json(nselib.path("order.json"))
        r = rk.check(nselib.config(), o, nselib.journal(), nselib.market.now_ist(NOW))
        names = [b.split(":")[0] for b in r["blocks"]]
        self.assertIn("daily loss", names)   # 300 lost + 356.37 at risk > 600
        self.assertIn("trades", names)

    # ---- nse-ticket ----
    def test_ticket_needs_pass_and_confirm_then_journals_net_pnl(self):
        self.config()
        self.plan("2R")
        run(bud, "--now", NOW, "--write")
        run(rk, "--now", NOW)                                  # BLOCK
        code, out = run(tk, "--now", NOW, "show")
        self.assertEqual(code, 2)
        self.assertIn("BLOCKED", out)

        self.plan("2.5R")
        run(bud, "--now", NOW, "--write")
        code, out = run(tk, "--now", NOW, "show")               # new order, old verdict
        self.assertEqual(code, 2)
        self.assertIn("has not checked this exact order", out)

        run(rk, "--now", NOW)                                  # PASS
        code, out = run(tk, "--now", NOW, "show")
        self.assertEqual(code, 0)
        self.assertIn("SL-M", out)
        self.assertIn("end up short", out)
        self.assertIn("PAPER", out)

        self.assertEqual(run(tk, "--now", NOW, "log")[0], 2)    # no --confirm, no log
        self.assertEqual(run(tk, "--now", NOW, "log", "--confirm")[0], 0)
        self.assertEqual(run(tk, "--now", NOW, "log", "--confirm")[0], 2)   # not twice

        code, out = run(tk, "--now", "2026-11-27 11:30", "close", "--symbol", "INFY", "--exit", "1636",
                        "--reason", "target")
        self.assertEqual(code, 0)
        t = nselib.journal()["trades"][0]
        self.assertEqual(t["net_pnl"], 663.24)
        self.assertEqual(nselib.equity(nselib.config(), nselib.journal()), 100663.24)

    def test_ticket_verdict_from_yesterday_does_not_count(self):
        self.config()
        self.plan("2.5R")
        run(bud, "--now", NOW, "--write")
        run(rk, "--now", NOW)
        r = nselib.read_json(nselib.path("state", "risk.json"))
        r["date"] = "2026-11-26"
        nselib.write_json(nselib.path("state", "risk.json"), r)
        code, out = run(tk, "--now", NOW, "show")
        self.assertEqual(code, 2)
        self.assertIn("not today", out)

    def test_live_mode_needs_the_real_fill(self):
        self.config(paper=False)
        self.plan("2.5R")
        run(bud, "--now", NOW, "--write")
        run(rk, "--now", NOW)
        code, out = run(tk, "--now", NOW, "log", "--confirm")
        self.assertEqual(code, 2)
        self.assertIn("--fill", out)
        self.assertEqual(run(tk, "--now", NOW, "log", "--confirm", "--fill", "1612.65")[0], 0)
        self.assertEqual(nselib.journal()["trades"][0]["mode"], "manual")


class Helpers(unittest.TestCase):
    def test_ticks(self):
        self.assertEqual(nselib.to_tick(150.876, 0.05, "down"), 150.85)
        self.assertEqual(nselib.to_tick(150.85, 0.05, "down"), 150.85)
        self.assertEqual(nselib.to_tick(150.876, 0.05, "up"), 150.9)
        self.assertEqual(nselib.to_tick(150.875, 0.05), 150.9)

    def test_inr_grouping(self):
        self.assertEqual(nselib.inr(100663.24), "Rs 1,00,663.24")
        self.assertEqual(nselib.inr(12345678), "Rs 1,23,45,678.00")
        self.assertEqual(nselib.inr(-356.37), "-Rs 356.37")


if __name__ == "__main__":
    unittest.main()
