"""trader-report: how a plan ended on its day's 5-minute bars (offline, synthetic bars)."""

import datetime
import unittest

from _load import load

rep = load("trader-report", "report")
DT = datetime.datetime

PLAN = {"symbol": "TEST.NS", "side": "buy", "date": "2026-11-18", "entry": 100.0, "entry_time": "9:45 AM",
        "entry_bar": 5, "stop": 99.0, "target": 102.0, "flat_by": "15:15"}


def bars(rows):
    """{slot: bar} from (slot, o, h, l, c); slots not given are missing."""
    return {s: {"slot": s, "start": "", "o": o, "h": h, "l": l, "c": c} for s, o, h, l, c in rows}


def flat_day(price=100.2):
    return [(i, price, price + 0.1, price - 0.1, price) for i in range(0, 75)]


AFTER = DT(2026, 11, 18, 15, 40)


class Outcomes(unittest.TestCase):
    def test_target(self):
        b = bars(flat_day() [:6] + [(6, 100.5, 102.3, 100.4, 102.1)] + flat_day()[7:])
        r = rep.evaluate(PLAN, b, AFTER, qty=10)
        self.assertEqual((r["outcome"], r["exit"], r["R"], r["rupees"]), ("target", 102.0, 2.0, 20.0))

    def test_stop_is_checked_first_in_a_bar_that_touches_both(self):
        b = bars(flat_day()[:6] + [(6, 100.5, 102.5, 98.9, 101.0)] + flat_day()[7:])
        r = rep.evaluate(PLAN, b, AFTER, qty=10)
        self.assertEqual((r["outcome"], r["exit"], r["R"]), ("stop", 99.0, -1.0))

    def test_a_gap_below_the_stop_fills_at_the_open(self):
        b = bars(flat_day()[:6] + [(6, 98.5, 98.8, 98.0, 98.2)] + flat_day()[7:])
        r = rep.evaluate(PLAN, b, AFTER)
        self.assertEqual((r["outcome"], r["exit"], r["R"]), ("stop", 98.5, -1.5))

    def test_neither_exits_at_the_last_bar_before_the_flat_by(self):
        rows = flat_day(100.5)
        rows[71] = (71, 100.5, 100.8, 100.4, 100.7)    # the 15:10 bar closes at 100.70
        rows[72] = (72, 100.7, 105.0, 100.6, 104.0)    # the 15:15 bar is after the flat-by: ignored
        r = rep.evaluate(PLAN, bars(rows), AFTER, qty=5)
        self.assertEqual((r["outcome"], r["exit"], r["R"], r["rupees"]), ("flat", 100.7, 0.7, 3.5))

    def test_before_the_flat_by_it_is_still_open(self):
        rows = [r for r in flat_day(100.4) if r[0] <= 12]
        r = rep.evaluate(PLAN, bars(rows), DT(2026, 11, 18, 10, 20))
        self.assertEqual((r["outcome"], r["exit"], r["R"], r["missing_bars"]), ("open", 100.4, 0.4, []))

    def test_missing_bars_are_listed(self):
        rows = [r for r in flat_day() if r[0] != 20]
        r = rep.evaluate(PLAN, bars(rows), AFTER)
        self.assertEqual(r["missing_bars"], ["10:55 AM"])

    def test_no_entry_bar_is_an_error(self):
        rows = [r for r in flat_day() if r[0] != 5]
        with self.assertRaises(rep.ReportError):
            rep.evaluate(PLAN, bars(rows), AFTER)


if __name__ == "__main__":
    unittest.main()
