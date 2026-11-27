import unittest

from _load import load

mk = load("nse-setup", "market")


def cfg(**over):
    c = mk.load_config(None)
    c.update(over)
    return c


def at(text, **over):
    return mk.status(mk.now_ist(text), cfg(**over))


class Clock(unittest.TestCase):
    # 2026-11-27 is a Friday, 2026-11-28 a Saturday
    def test_phases(self):
        self.assertEqual(at("2026-11-27 08:30")["phase"], "before pre-open")
        self.assertEqual(at("2026-11-27 09:05")["phase"], "pre-open")
        self.assertEqual(at("2026-11-27 09:15")["phase"], "open")
        self.assertEqual(at("2026-11-27 15:29")["phase"], "open")
        self.assertEqual(at("2026-11-27 15:30")["phase"], "closed for the day")
        self.assertFalse(at("2026-11-28 11:00")["trading_day"])

    def test_holiday_from_config(self):
        s = at("2026-11-27 11:00", holidays=["2026-11-27"])
        self.assertFalse(s["trading_day"])
        self.assertFalse(s["can_enter"])

    def test_entry_window(self):
        self.assertFalse(at("2026-11-27 09:20")["can_enter"])
        self.assertTrue(at("2026-11-27 09:30")["can_enter"])
        self.assertTrue(at("2026-11-27 14:44")["can_enter"])
        self.assertFalse(at("2026-11-27 14:45")["can_enter"])


class SquareOff(unittest.TestCase):
    def test_broker_default_and_buffer(self):
        s = at("2026-11-27 15:00")
        self.assertEqual(s["square_off"], "15:20")
        self.assertEqual(s["flat_by"], "15:10")
        self.assertEqual(s["minutes_to_flat"], 10)
        self.assertFalse(s["must_exit_now"])

    def test_setting_overrides_broker(self):
        s = at("2026-11-27 15:00", square_off_time="15:25", exit_buffer_minutes=5)
        self.assertEqual(s["square_off"], "15:25")
        self.assertEqual(s["flat_by"], "15:20")

    def test_must_exit_after_flat_by(self):
        self.assertTrue(at("2026-11-27 15:12")["must_exit_now"])

    def test_late_entry_window_still_blocked_by_flat_by(self):
        s = at("2026-11-27 15:05", no_entries_after="15:25", square_off_time="15:10", exit_buffer_minutes=5)
        self.assertFalse(s["can_enter"])
        self.assertIn("flat-by", s["reason"])

    def test_paper_is_the_default(self):
        self.assertTrue(at("2026-11-27 10:00")["paper"])


if __name__ == "__main__":
    unittest.main()
