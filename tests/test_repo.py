import json
import os
import re
import unittest

from _load import ROOT

READY = ["nse-setup"]
# words that would mean a skill calls an order tool
ORDER_CALLS = re.compile(r"\b(place_order|modify_order|cancel_order|place_gtt|placeOrder)\s*\(")


def skill_dirs():
    return sorted(d for d in os.listdir(ROOT) if os.path.isfile(os.path.join(ROOT, d, "SKILL.md")))


class Repo(unittest.TestCase):
    def test_ready_skills_present(self):
        self.assertEqual(skill_dirs(), READY)

    def test_frontmatter(self):
        for s in skill_dirs():
            with open(os.path.join(ROOT, s, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read()
            m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
            self.assertTrue(m, s)
            self.assertIn("name: %s\n" % s, m.group(1) + "\n")
            self.assertGreater(len(m.group(1)), 200, s)

    def test_every_skill_says_no_orders_and_not_advice(self):
        for s in skill_dirs():
            with open(os.path.join(ROOT, s, "SKILL.md"), encoding="utf-8") as fh:
                text = fh.read().lower()
            self.assertIn("never place", text, s)
            self.assertIn("not financial advice", text, s)

    def test_no_code_calls_an_order_tool(self):
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", "tests")]
            for f in files:
                if f.endswith(".py"):
                    with open(os.path.join(base, f), encoding="utf-8") as fh:
                        self.assertIsNone(ORDER_CALLS.search(fh.read()), f)

    def test_json_files_parse(self):
        for base, dirs, files in os.walk(ROOT):
            dirs[:] = [d for d in dirs if d != ".git"]
            for f in files:
                if f.endswith(".json"):
                    with open(os.path.join(base, f), encoding="utf-8") as fh:
                        json.load(fh)

    def test_example_config_is_paper(self):
        with open(os.path.join(ROOT, "nse-setup", "config.example.json"), encoding="utf-8") as fh:
            c = json.load(fh)
        self.assertTrue(c["paper"])
        self.assertIn(c["broker"], ("groww", "zerodha"))

    def test_brokers_have_sources_and_dates(self):
        with open(os.path.join(ROOT, "nse-setup", "brokers.json"), encoding="utf-8") as fh:
            b = json.load(fh)
        for name, bk in b["brokers"].items():
            self.assertTrue(bk["source"].startswith("https://"), name)
            self.assertRegex(bk["as_of"], r"^\d{4}-\d{2}-\d{2}$", name)
            self.assertRegex(bk["auto_square_off"], r"^\d{2}:\d{2}$", name)


if __name__ == "__main__":
    unittest.main()
