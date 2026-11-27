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
BULK, BLOCK, PIT, HOLD, BSE = (os.path.join(FX, f) for f in (
    "nse-bulk.csv", "nse-block.csv", "nse-pit.json", "groww-shareholding-INFY.json", "bse-announcements.json"))
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
        code, out = run(nw, "--file", ANN, "--now", "2026-11-27 18:00", "--hours", "48", "--exchange", "nse")
        self.assertEqual(code, 0)
        self.assertIn("Not financial advice", out)

    def test_bse_items(self):
        items = nw.bse_items(json.loads(read(BSE)))
        self.assertEqual(items[0]["company"], "Infosys Ltd")
        self.assertEqual(items[0]["link"], "https://www.bseindia.com/xml-data/corpfiling/AttachLive/test-1.pdf")
        self.assertEqual(items[1]["subject"], "Clarification sought on spurt in volume")  # no headline: from NEWSSUB
        self.assertEqual(items[1]["link"], "https://www.bseindia.com/stock-share-price/reliance-industries-ltd/reliance/500325/")

    def test_nse_and_bse_together(self):
        bse = nw.bse_items(json.loads(read(BSE)))
        rows = nw.run(read(ANN), list(WATCH.values()), dt.datetime(2026, 11, 27, 18, 0), hours=24, bse=bse)
        by = {(r["exchange"], r["company"]): r for r in rows}
        self.assertEqual(by[("BSE", "Infosys Ltd")]["tag"], "order win")
        self.assertNotIn(("BSE", "PAN ELECTRONICS INDIA LTD."), by)
        # Reliance's volume query is on both exchanges with the same subject: shown once
        self.assertEqual(sum(1 for r in rows if r["company"].startswith("Reliance") and r["tag"] == "exchange query"), 1)

    def test_cli_bse_file(self):
        code, out = run(nw, "--exchange", "bse", "--bse-file", BSE, "--now", "2026-11-27 18:00")
        self.assertEqual(code, 0)
        self.assertIn("BSE", out)
        self.assertIn("awarded an order", out)


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

    def test_pit_both_lists(self):
        rows = ins.parse_pit(json.loads(read(PIT)))
        self.assertEqual(len(rows), 5)
        old = [r for r in rows if r["person"] == "Example Promoter"][0]
        self.assertEqual((old["side"], old["qty"], old["value"]), ("SELL", 100000, 117000000))
        new = rows[0]
        self.assertIsNone(new["person"])
        self.assertTrue(new["link"].startswith("https://"))
        self.assertIsNone([r for r in rows if r["person"] == "Example Director"][0]["link"])  # "-" is no link

    def test_pit_summary_window_and_promoter_net(self):
        rows = ins.parse_pit(json.loads(read(PIT)))
        s = {x["symbol"]: x for x in ins.pit_summary(rows, ["INFY"], dt.datetime(2026, 4, 1))}
        self.assertEqual(list(s), ["INFY"])
        self.assertEqual(len(s["INFY"]["filings"]), 3)
        self.assertAlmostEqual(s["INFY"]["promoter_net"], -117000000)
        s = ins.pit_summary(rows, ["INFY"], dt.datetime(2026, 10, 28))
        self.assertEqual(len(s[0]["filings"]), 1)

    def test_holding_changes_real_groww(self):
        sp, key = feeds.groww_pick(json.loads(read(HOLD)), "shareholding_pattern", "INFY", "Infosys Limited")
        self.assertEqual(key, "infosys-ltd")
        h = ins.holding_changes(sp)
        self.assertEqual((h["quarter"], h["prev_quarter"], h["year_ago_quarter"]), ("Sep '26", "Jun '26", "Sep '25"))
        g = {x["group"]: x for x in h["groups"]}
        self.assertEqual(g["promoters"]["latest"], 13.9)
        self.assertEqual(g["promoters"]["qoq_pp"], 0.08)
        self.assertEqual(g["dii"]["qoq_pp"], -3.98)
        self.assertIn("DII holding moved -3.98 pp last quarter", h["flags"])

    def test_holding_a_promoter_leaving(self):
        sp, _ = feeds.groww_pick(json.loads(read(HOLD)), "shareholding_pattern", "INFY", "Infosys Limited")
        h = ins.holding_changes({q: sp[q] for q in ("Mar '26", "Jun '26")})
        gone = [m for m in h["promoter_moves"] if m["name"] == "Shreyas Shibulal"]
        self.assertEqual(gone[0]["note"], "no longer listed as a promoter holder")

    def test_cli(self):
        code, out = run(ins, "--bulk-file", BULK, "--block-file", BLOCK, "--insider-file", PIT,
                        "--now", "2026-11-27 18:00", "--holding", "--symbols", "INFY,HDFCBANK", "--holding-file", HOLD)
        self.assertEqual(code, 0)
        self.assertIn("both sides", out)
        self.assertIn("who and how much are in the filing", out)
        self.assertIn("No shareholding saved for INFY", out)  # --holding-file only with a single symbol
        self.assertNotIn("SMALLCO", out)
        self.assertIn("Not financial advice", out)
        code, out = run(ins, "--symbols", "INFY", "--no-deals", "--insider-file", PIT, "--now", "2026-11-27 18:00",
                        "--holding", "--holding-file", HOLD)
        self.assertIn("Shareholding of INFY, Sep '26", out)
        code, out = run(ins, "--all", "--bulk-file", BULK, "--block-file", BLOCK, "--no-insider", "--json")
        self.assertEqual(json.loads(out)["deals"][2]["symbol"], "SMALLCO")

    def test_bad_insider_file_is_a_note(self):
        code, out = run(ins, "--no-deals", "--insider-file", BULK)
        self.assertEqual(code, 1)
        self.assertIn("Could not read NSE's insider-trading lists", out)


if __name__ == "__main__":
    unittest.main()
