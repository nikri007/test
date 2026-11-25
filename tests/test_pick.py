"""trader-pick: the grade, the order's levels and the chart reading (offline, synthetic bars)."""

import datetime
import unittest

from _load import load

pk = load("trader-pick", "pick")
sw = pk.sw


def series(closes, wiggle=0.01, vol=5e6):
    """Daily bars from a list of closes: open = the close before, a small range around both."""
    d0 = datetime.date(2024, 1, 1)
    S = {"symbol": "TEST.NS", "d": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    prev = closes[0]
    for k, c in enumerate(closes):
        S["d"].append((d0 + datetime.timedelta(days=k)).isoformat())
        S["o"].append(float(prev))
        S["h"].append(max(prev, c) * (1 + wiggle))
        S["l"].append(min(prev, c) * (1 - wiggle))
        S["c"].append(float(c))
        S["v"].append(vol)
        prev = c
    S = sw.prepare(S)
    S["ix"] = {d: i for i, d in enumerate(S["d"])}
    return S


def rising(n=300, start=100.0, step=0.004):
    out, x = [], start
    for _ in range(n):
        x *= 1 + step
        out.append(x)
    return out


class Grade(unittest.TestCase):
    def test_a_strong_stock_with_a_dip_is_grade_a(self):
        c = rising()
        c += [c[-1] * 0.975, c[-1] * 0.95]                 # two lower closes
        S = series(c)
        g, mom, r = pk.grade(S, len(c) - 1)
        self.assertEqual(g, "A")
        self.assertGreater(mom, 0.20)
        self.assertLess(r, 15)

    def test_no_dip_no_grade_and_a_weak_stock_never(self):
        S = series(rising())
        self.assertIsNone(pk.grade(S, 299)[0])            # strong, RSI(2) at 100
        self.assertIn("NO DIP yet", pk.what_is_missing(S, 299, None, *pk.grade(S, 299)[1:], True))
        flat = [100 + (k % 2) for k in range(300)] + [99, 98]
        g, mom, r = pk.grade(series(flat), 301)
        self.assertIsNone(g)
        down = rising()[::-1]
        S = series(down)
        self.assertIn("under its 50-day average", pk.what_is_missing(S, 299, *pk.grade(S, 299), True))

    def test_the_market_filter_and_grade_b_explain_themselves(self):
        c = rising()
        c += [c[-1] * 0.975, c[-1] * 0.95]
        S = series(c)
        self.assertIn("market filter", pk.what_is_missing(S, 301, "A", 0.3, 5.0, False))
        self.assertIn("grade B", pk.what_is_missing(S, 301, "B", 0.12, 20.0, True))


class Order(unittest.TestCase):
    def test_levels_are_clamped_to_the_tested_ranges(self):
        calm = series(rising(), wiggle=0.002)             # a tiny ATR: the floors apply
        lv = pk.levels(calm, 299)
        self.assertEqual((lv["target"], lv["stop"], lv["hold"], lv["limit"]), (4.0, 8.0, 5, 2.0))
        wild = series(rising(), wiggle=0.05)              # a huge ATR: the caps apply
        lv = pk.levels(wild, 299)
        self.assertEqual((lv["target"], lv["stop"]), (8.0, 14.0))

    def test_the_order_is_whole_shares_on_the_tick(self):
        S = series(rising(), wiggle=0.05)
        c = S["c"][299]
        od = pk.order(S, 299, 7500.0)
        self.assertAlmostEqual(od["limit_price"], sw.tick_down(c * 0.98))
        self.assertEqual(od["qty"], int(7500 // od["limit_price"]))
        self.assertAlmostEqual(od["target_price"], sw.tick_down(od["limit_price"] * 1.08))
        self.assertAlmostEqual(od["stop_price"], sw.tick_down(od["limit_price"] * 0.86))
        self.assertAlmostEqual(od["loss_at_stop"], od["qty"] * od["limit_price"] * 0.14)
        self.assertEqual(pk.order(S, 299, 10.0)["qty"], 0)

    def test_symbols_get_the_nse_suffix(self):
        self.assertEqual([pk.norm(x) for x in ("reliance", "M&M.NS", "tcs,")], ["RELIANCE.NS", "M&M.NS", "TCS.NS"])


class Chart(unittest.TestCase):
    def test_the_reading_names_the_trend_and_the_pattern(self):
        c = rising()
        f, lines = pk.read_chart(series(c), 299)
        self.assertEqual(f["trend"], "STRONG UPTREND")
        self.assertIn("EXTENDED", f["patterns"])
        self.assertIn("BREAKOUT", f["patterns"])
        self.assertEqual([ln.split()[0] for ln in lines], ["Trend", "Momentum", "Pattern", "Today", "Levels"])
        dip = c + [c[-1] * 0.975, c[-1] * 0.95]
        f, lines = pk.read_chart(series(dip), 301)
        self.assertIn("PULLBACK", f["patterns"])
        self.assertIn("2 lower closes", "\n".join(lines))
        f, _ = pk.read_chart(series(c[::-1]), 299)
        self.assertEqual(f["trend"], "DOWNTREND")

    def test_history_replays_the_same_order(self):
        c = rising(260)
        for _ in range(4):                                # four dips, each followed by a recovery
            top = c[-1]
            c += [top * 0.975, top * 0.95, top * 0.93, top * 0.96, top * 1.0, top * 1.03, top * 1.05]
            c += [c[-1] * 1.004 ** k for k in range(1, 12)]
        S = series(c)
        h = pk.history(S, len(c) - 1, None)
        self.assertGreater(h["signals"], 3)
        self.assertEqual(h["filled"], h["target"] + h["stop"] + h["time"])
        self.assertEqual(len(h["net"]), h["filled"])


if __name__ == "__main__":
    unittest.main()
