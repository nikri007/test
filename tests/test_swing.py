"""trader-swing: the rule's trade logic, the live follow-up and the no-hindsight account (offline, synthetic bars)."""

import datetime
import unittest

from _load import load

sw = load("trader-swing", "swing")
RULE = {"setup": "dipmom", "limit": 3.0, "target": 6.0, "stop": 12.0, "hold": 3}


def series(rows, start="2026-01-01"):
    """rows of (o, h, l, c) -> a series on consecutive calendar days (the tests do not need real sessions)."""
    d0 = datetime.date.fromisoformat(start)
    S = {"symbol": "TEST.NS", "d": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for k, (o, h, l, c) in enumerate(rows):
        S["d"].append((d0 + datetime.timedelta(days=k)).isoformat())
        for key, x in zip("ohlc", (o, h, l, c)):
            S[key].append(float(x))
        S["v"].append(1e6)
    return S


FLAT = (100, 100.5, 99.5, 100)


class Indicators(unittest.TestCase):
    def test_sma_and_rsi(self):
        self.assertEqual(sw.sma([1, 2, 3, 4], 2), [None, 1.5, 2.5, 3.5])
        self.assertEqual(sw.rsi([1, 2, 3, 4, 5], 2)[-1], 100.0)          # only gains
        self.assertEqual(sw.rsi([5, 4, 3, 2, 1], 2)[-1], 0.0)            # only losses
        r = sw.rsi([10, 11, 10, 11, 10, 11], 2)
        self.assertTrue(0 < r[-2] < 50 < r[-1] < 100)

    def test_a_bad_move_is_remembered(self):
        S = sw.prepare(series([FLAT] * 3 + [(40, 41, 39, 40)] + [(40, 41, 39, 40)] * 3))
        self.assertEqual(S["bad"][2], -1000)
        self.assertEqual(S["bad"][5], 3)                                  # the unadjusted split at bar 3


class Trade(unittest.TestCase):
    def t(self, rows, **kw):
        S = series([FLAT] + rows)
        kw.setdefault("entry_mode", "limit")
        kw.setdefault("limit", 3.0)
        return sw.trade(S, 0, 6.0, 12.0, 3, **kw)

    def test_no_fill_when_the_low_stays_above_the_limit(self):
        self.assertIsNone(self.t([(100, 101, 97.5, 100), FLAT, FLAT]))
        self.assertIsNone(self.t([(100, 101, 97.0, 100), FLAT, FLAT]))   # touched, not traded through

    def test_a_fill_then_the_time_exit(self):
        g, oc, j, entry = self.t([(100, 101, 96.5, 98), (98, 99, 97, 98.5), (98.5, 100, 98, 99.91)])
        self.assertEqual((oc, j, entry), ("time", 3, 97.0))
        self.assertAlmostEqual(g, 3.0, places=2)

    def test_a_gap_down_open_fills_at_the_open(self):
        g, oc, j, entry = self.t([(95, 96, 94, 95.5), (95.5, 96, 95, 95.5), (95.5, 96, 95, 95.0)])
        self.assertEqual((oc, entry), ("time", 95.0))
        self.assertAlmostEqual(g, 0.0)

    def test_the_target_is_not_counted_on_the_buy_day(self):
        g, oc, j, _ = self.t([(100, 104, 96.5, 98), (98, 103.5, 97.5, 103), FLAT])
        self.assertEqual((oc, j, round(g, 2)), ("target", 2, 6.0))       # 97 x 1.06 = 102.82, hit on day 2

    def test_the_stop_counts_first_and_a_gap_fills_at_the_open(self):
        g, oc, j, _ = self.t([(100, 100, 96.5, 97), (97, 104, 85, 99), FLAT])
        self.assertEqual((oc, round(g, 2)), ("stop", -12.0))             # the bar touched both: the stop
        g, oc, j, _ = self.t([(100, 100, 96.5, 97), (80, 82, 79, 81), FLAT])
        self.assertEqual((oc, round(g, 2)), ("stop", round((80 / 97 - 1) * 100, 2)))

    def test_open_entry_and_missing_bars(self):
        S = series([FLAT, (101, 102, 100, 101.5), (101.5, 103, 101, 102)])
        self.assertIsNone(sw.trade(S, 0, None, None, 3))                 # the hold runs past the data
        g, oc, j, entry = sw.trade(S, 0, None, None, 2)
        self.assertEqual((oc, entry), ("time", 101.0))


class Follow(unittest.TestCase):
    def test_statuses(self):
        S = series([FLAT])
        self.assertEqual(sw.follow(S, 0, RULE)["status"], "pending")
        S = series([FLAT, (100, 101, 98, 100)])
        self.assertEqual(sw.follow(S, 0, RULE)["status"], "unfilled")
        self.assertEqual(sw.follow(S, 0, RULE, live_day=S["d"][1])["status"], "waiting")
        S = series([FLAT, (100, 101, 96.5, 98), (98, 99, 97, 98.5)])
        f = sw.follow(S, 0, RULE)
        self.assertEqual((f["status"], f["day_no"], f["entry"]), ("open", 2, 97.0))
        S = series([FLAT, (100, 101, 96.5, 98), (98, 99, 97, 98.5), (98.5, 100, 98, 99.91)])
        self.assertEqual(sw.follow(S, 0, RULE)["status"], "time")
        self.assertEqual(sw.follow(S, 0, RULE, live_day=S["d"][3])["status"], "open")   # day 3 is not over

    def test_it_agrees_with_the_backtest_trade(self):
        rows = [(100, 101, 96.5, 98), (98, 103.5, 97.5, 103), FLAT]
        S = series([FLAT] + rows)
        g, oc, j, entry = sw.trade(S, 0, 6.0, 12.0, 3, entry_mode="limit", limit=3.0)
        f = sw.follow(S, 0, RULE)
        self.assertEqual((f["status"], f["exit_day"], f["entry"]), (oc, S["d"][j], entry))
        self.assertAlmostEqual(f["gross"], g)


class Account(unittest.TestCase):
    def test_no_hindsight_one_order_per_free_slot(self):
        orders = [
            {"in": "2026-01-02", "score": 2.0, "entry": 100.0, "filled": False},                 # best rank: no fill
            {"in": "2026-01-02", "score": 1.0, "entry": 100.0, "net": 5.0, "out": "2026-01-06"},  # filled, but not ordered
            {"in": "2026-01-05", "score": 1.0, "entry": 50.0, "net": 2.0, "out": "2026-01-07"},
            {"in": "2026-01-06", "score": 9.0, "entry": 50.0, "net": 9.0, "out": "2026-01-08"},   # slot busy
            {"in": "2026-01-08", "score": 1.0, "entry": 20000.0, "net": 9.0, "out": "2026-01-09"},  # one share too dear
        ]
        ac = sw.account(orders, slots=1, start=10000.0, invest=0.75, fixed=10.0)
        self.assertEqual((ac["orders"], ac["trades"]), (2, 1))
        self.assertAlmostEqual(ac["end"], 10000 + 150 * 50 * 0.02 - 10)


class DataFlags(unittest.TestCase):
    def test_actions_from_a_chart_with_events(self):
        ts = lambda d: int((datetime.datetime.fromisoformat(d + "T03:45:00") - datetime.datetime(1970, 1, 1)).total_seconds())
        doc = {"chart": {"result": [{"events": {
            "dividends": {"1": {"amount": 5.5, "date": ts("2026-11-20")}, "2": {"amount": 4.0, "date": ts("2026-08-01")}},
            "splits": {"3": {"numerator": 5, "denominator": 1, "date": ts("2026-11-23")}}}}]}}
        self.assertEqual(sw.actions_from_chart(doc, "2026-11-18"),
                         ["dividend ₹5.50 a share, ex-date 2026-11-20", "split or bonus 1:5, ex-date 2026-11-23"])
        self.assertEqual(sw.actions_from_chart({"chart": {"result": [{}]}}, "2026-11-18"), [])
        self.assertEqual(sw.actions_from_chart({}, "2026-11-18"), [])

    def test_flags_are_facts_from_the_data(self):
        S = series([FLAT, FLAT, (100, 100, 92, 92)])
        f = sw.data_flags(S, 2, {"below200": True}, ["dividend ₹5 a share, ex-date 2026-01-03"])
        self.assertAlmostEqual(f["day_change"], -8.0)
        text = " | ".join(f["flags"])
        for want in ("fell 8.0% on the signal day", "lower circuit", "corporate action in the data", "200-day average"):
            self.assertIn(want, text)
        calm = sw.data_flags(series([FLAT, FLAT, (100, 100.5, 98.5, 99)]), 2, {"below200": False}, [])
        self.assertEqual(calm["flags"], [])


class Calendar(unittest.TestCase):
    def test_sessions_skip_weekends_and_nse_holidays(self):
        D = datetime.date
        self.assertEqual(sw.next_session(D(2026, 11, 23)), D(2026, 11, 25))          # Nov 24: Guru Nanak Jayanti
        self.assertEqual(sw.next_session(D(2026, 11, 27)), D(2026, 11, 30))          # the weekend
        self.assertEqual(sw.next_session(D(2026, 11, 25), 2), D(2026, 11, 27))
        DT = datetime.datetime
        self.assertEqual(sw.last_complete_day(DT(2026, 11, 25, 12, 0)), D(2026, 11, 23))
        self.assertEqual(sw.last_complete_day(DT(2026, 11, 25, 15, 45)), D(2026, 11, 25))
        self.assertEqual(sw.session_days(D(2026, 11, 25), 3), ["2026-11-20", "2026-11-23", "2026-11-25"])

    def test_prices_round_down_to_the_tick(self):
        self.assertAlmostEqual(sw.tick_down(2240.603), 2240.60)
        self.assertAlmostEqual(sw.tick_down(100.0), 100.0)
        self.assertEqual(sw.rupees(-197.5), "-₹197.50")
        self.assertEqual(sw.rupees(7500, signed=True), "+₹7,500")


if __name__ == "__main__":
    unittest.main()
