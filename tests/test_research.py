"""nse-news, nse-results and nse-insider on saved NSE feeds and real Groww fundamentals."""

import datetime as dt
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

from _load import ROOT, load

nw = load("nse-news", "news")
rs = load("nse-results", "results")
ins = load("nse-insider", "insider")
import feeds  # noqa: E402
import nselib  # noqa: E402

FX = os.path.join(ROOT, "tests", "fixtures")
ANN = os.path.join(FX, "nse-announcements.xml")
FUND = os.path.join(FX, "groww-fundamentals-INFY.json")
BULK, BLOCK, IT = (os.path.join(FX, f) for f in ("nse-bulk.csv", "nse-block.csv", "nse-insider.xml"))
WATCH = {"INFY": "Infosys Limited", "RELIANCE": "Reliance Industries Limited", "HDFCBANK": "HDFC Bank Limited"}


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def run(mod, *args):
    out = io.StringIO()
    with redirect_stdout(out):
        code = mod.main(list(args))
    return code, out.getvalue()


class WithNse(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.old = nselib.NSE_DIR
        nselib.NSE_DIR = self.dir
        with open(os.path.join(ROOT, "nse-setup", "config.example.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
        nselib.write_json(nselib.path("config.json"), cfg)

    def tearDown(self):
        nselib.NSE_DIR = self.old
        shutil.rmtree(self.dir)


class Feeds(unittest.TestCase):
    def test_name_match_is_exact(self):
        self.assertTrue(feeds.name_matches("Infosys Limited", ["Infosys Ltd."]))
        self.assertTrue(feeds.name_matches("INFOSYS LIMITED", ["infosys"]))
        self.assertFalse(feeds.name_matches("Infosys BPM Services Limited", ["Infosys Limited"]))

    def test_csv_and_numbers(self):
        rows = feeds.csv_rows(read(BULK))
        self.assertEqual(rows[0]["Symbol"], "INFY")
        self.assertEqual(feeds.num("1,170.25"), 1170.25)
        self.assertIsNone(feeds.num("-"))


class News(WithNse):
    def rows(self, **kw):
        text = read(ANN)
        names = list(WATCH.values()) + list(WATCH)
        return nw.run(text, names, dt.datetime(2026, 11, 27, 18, 0), **kw)

    def test_classify(self):
        self.assertEqual(nw.classify("Outcome of Board Meeting - financial results for the quarter"), ("results", "high"))
        self.assertEqual(nw.classify("Bagging of order worth Rs 500 crore"), ("order win", "high"))
        self.assertEqual(nw.classify("Closure of Trading Window"), ("routine", "low"))
        self.assertEqual(nw.classify("Something else"), ("other", "other"))

    def test_watchlist_only_high_first_and_no_subsidiary(self):
        rows = self.rows()
        companies = {r["company"] for r in rows}
        self.assertNotIn("Infosys BPM Services Limited", companies)
        self.assertNotIn("Example Infra Projects Limited", companies)
        ranks = [nw.IMPACT_RANK[r["impact"]] for r in rows]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(rows[0]["impact"], "high")

    def test_hours_window(self):
        self.assertLess(len(self.rows(hours=1)), len(self.rows(hours=24 * 30)))

    def test_all_high_only(self):
        rows = nw.run(read(ANN), [], dt.datetime(2026, 11, 27, 18, 0),
                      hours=48, everyone=True, min_impact="high")
        self.assertTrue(rows)
        self.assertTrue(all(r["impact"] == "high" for r in rows))

    def test_cli(self):
        code, out = run(nw, "--file", ANN, "--now", "2026-11-27 18:00", "--hours", "48")
        self.assertEqual(code, 0)
        self.assertIn("Not financial advice", out)


class Results(WithNse):
    def test_infy_sep_26(self):
        data = json.loads(read(FUND))
        fs, key = rs.pick_company(data, "INFY", "Infosys Limited")
        self.assertNotIn("hcl", key.lower())
        s = rs.summarise(fs)
        self.assertEqual(s["quarter"], "Sep '26")
        self.assertEqual(s["year_ago_quarter"], "Sep '25")
        rev = {r["line"]: r for r in s["lines"]}["Revenue"]
        self.assertEqual(rev["qoq_pct"], 1.8)
        self.assertEqual(rev["yoy_pct"], 10.2)

    def test_qkey(self):
        self.assertLess(rs.qkey("Dec '25"), rs.qkey("Mar '26"))

    def test_cli_and_missing_file(self):
        code, out = run(rs, "--symbol", "INFY", "--file", FUND)
        self.assertEqual(code, 0)
        self.assertIn("Sep '26", out)
        code, out = run(rs, "--symbol", "NOPE")
        self.assertEqual(code, 1)
        self.assertIn("fetch_stocks_fundamental_data", out)


class Insider(WithNse):
    def deals(self):
        return (ins.parse_deals(read(BULK), "bulk")
                + ins.parse_deals(read(BLOCK), "block"))

    def test_parse(self):
        d = self.deals()
        self.assertEqual(len(d), 6)
        self.assertAlmostEqual(d[0]["value"], 2500000 * 1170.25)
        self.assertEqual(d[-1]["side"], "SELL")

    def test_watchlist_filter_and_both_sides(self):
        s = {x["symbol"]: x for x in ins.summarise(self.deals(), ["INFY", "HDFCBANK"])}
        self.assertEqual(set(s), {"INFY", "HDFCBANK"})
        infy = s["INFY"]
        prop = [c for c in infy["clients"] if c["client"].startswith("XYZ")][0]
        fund = [c for c in infy["clients"] if c["client"].startswith("ABC")][0]
        self.assertTrue(prop["both_sides"])
        self.assertEqual(prop["qty_net"], 10000)
        self.assertFalse(fund["both_sides"])
        self.assertAlmostEqual(infy["net_one_way"], fund["net"])
        self.assertAlmostEqual(s["HDFCBANK"]["net"], 0.0)

    def test_all_sorted_by_size(self):
        s = ins.summarise(self.deals())
        self.assertEqual([x["symbol"] for x in s], ["INFY", "HDFCBANK", "SMALLCO"])

    def test_insider_feed_stale_and_exact_names(self):
        text = read(IT)
        items, newest, stale = ins.insider_items(text, list(WATCH.values()), dt.datetime(2026, 11, 27, 18), days=400)
        self.assertEqual([i["company"] for i in items], ["Infosys Limited", "Reliance Industries Limited"])
        self.assertEqual(newest, "2026-05-02")
        self.assertTrue(stale)
        _, _, stale = ins.insider_items(text, [], dt.datetime(2026, 5, 3, 9), days=30)
        self.assertFalse(stale)

    def test_cli(self):
        code, out = run(ins, "--bulk-file", BULK, "--block-file", BLOCK, "--insider-file", IT,
                        "--now", "2026-11-27 18:00")
        self.assertEqual(code, 0)
        self.assertIn("both sides", out)
        self.assertIn("stale", out)
        self.assertNotIn("SMALLCO", out)
        self.assertIn("Not financial advice", out)
        code, out = run(ins, "--all", "--bulk-file", BULK, "--block-file", BLOCK, "--no-insider", "--json")
        self.assertEqual(json.loads(out)["deals"][2]["symbol"], "SMALLCO")


if __name__ == "__main__":
    unittest.main()
