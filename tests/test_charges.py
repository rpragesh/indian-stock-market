import unittest

from _load import load

ch = load("nse-setup", "charges")


class GrowwIntraday(unittest.TestCase):
    # 50 shares, buy 1000, sell 1010 on NSE. Worked by hand from brokers.json:
    # brokerage 20 + 20 (0.1% of 50,000 is 50, capped at 20 a leg)
    # STT 0.025% of 50,500 sell = 12.625
    # exchange 0.00307% of 1,00,500 = 3.08535; SEBI and IPFT 0.0001% each = 0.1005
    # stamp 0.003% of 50,000 buy = 1.50
    # GST 18% of (40 + 3.08535 + 0.1005 + 0.1005) = 7.79154
    def setUp(self):
        self.r = ch.trade_charges("groww", 1000, 1010, 50)

    def test_components(self):
        self.assertEqual(self.r["brokerage"], 40.0)
        self.assertAlmostEqual(self.r["stt"], 12.62, delta=0.011)
        self.assertEqual(self.r["exchange_txn"], 3.09)
        self.assertEqual(self.r["sebi_fee"], 0.1)
        self.assertEqual(self.r["ipft"], 0.1)
        self.assertEqual(self.r["stamp_duty"], 1.5)
        self.assertEqual(self.r["gst"], 7.79)
        self.assertEqual(self.r["dp"], 0.0)

    def test_totals(self):
        self.assertEqual(self.r["total_charges"], 65.2)
        self.assertEqual(self.r["gross_pnl"], 500.0)
        self.assertEqual(self.r["net_pnl"], 434.8)


class Brokerage(unittest.TestCase):
    def test_groww_minimum(self):
        # 2 shares at 50: 0.1% of 100 is 0.10, below the 5 minimum, so min(5, 2.5% of 100) = 2.50
        r = ch.trade_charges("groww", 50, 51, 2)
        self.assertEqual(r["brokerage"], 5.05)

    def test_groww_minimum_caps_at_5(self):
        # 10 shares at 100: 0.1% of 1,000 is 1, below 5, and 2.5% of 1,000 is 25, so 5 a leg
        r = ch.trade_charges("groww", 100, 100, 10)
        self.assertEqual(r["brokerage"], 10.0)

    def test_zerodha_pct_below_cap(self):
        # 0.03% of 50,000 = 15 and of 50,500 = 15.15, both under the 20 cap
        r = ch.trade_charges("zerodha", 1000, 1010, 50)
        self.assertEqual(r["brokerage"], 30.15)

    def test_zerodha_cap(self):
        r = ch.trade_charges("zerodha", 1000, 1010, 500)
        self.assertEqual(r["brokerage"], 40.0)

    def test_zerodha_delivery_free_but_dp_on_sell(self):
        r = ch.trade_charges("zerodha", 1000, 1010, 10, product="delivery")
        self.assertEqual(r["brokerage"], 0.0)
        self.assertEqual(r["dp"], 13.0)


class Statutory(unittest.TestCase):
    def test_delivery_stt_both_sides_and_higher_stamp(self):
        r = ch.trade_charges("groww", 1000, 1000, 10, product="delivery")
        self.assertEqual(r["stt"], 20.0)        # 0.1% of 10,000 twice
        self.assertEqual(r["stamp_duty"], 1.5)  # 0.015% of 10,000 buy

    def test_bse_rate_and_no_ipft(self):
        r = ch.trade_charges("groww", 1000, 1000, 100, exchange="BSE")
        self.assertEqual(r["exchange_txn"], 7.5)  # 0.00375% of 2,00,000
        self.assertEqual(r["ipft"], 0.0)

    def test_losing_trade_net_is_worse_than_gross(self):
        r = ch.trade_charges("groww", 1000, 990, 50)
        self.assertEqual(r["gross_pnl"], -500.0)
        self.assertLess(r["net_pnl"], -500.0)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            ch.trade_charges("upstox", 1, 1, 1)
        with self.assertRaises(ValueError):
            ch.trade_charges("groww", 1, 1, 0)


class Breakeven(unittest.TestCase):
    def test_long_breakeven_nets_zero(self):
        be = ch.breakeven_exit("groww", 1000, 50)
        self.assertGreaterEqual(ch.trade_charges("groww", 1000, be, 50)["net_pnl"], 0)
        self.assertLess(ch.trade_charges("groww", 1000, be - 0.05, 50)["net_pnl"], 0)

    def test_short_breakeven_is_below_entry(self):
        be = ch.breakeven_exit("zerodha", 1000, 50, side="short")
        self.assertLess(be, 1000)
        self.assertGreaterEqual(ch.trade_charges("zerodha", be, 1000, 50)["net_pnl"], 0)


if __name__ == "__main__":
    unittest.main()
