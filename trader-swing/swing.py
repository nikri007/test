#!/usr/bin/env python3
"""Swing trades for trader-swing: 2 to 3 day holds on NSE stocks. Standard library only.

    python3 swing.py scan                              # after the close: tomorrow's order -> trader/swing.json
    python3 swing.py track                             # how the recent orders and open positions stand
    python3 swing.py track --live                      # during the session: with today's bar so far
    python3 swing.py fetch --range 10y --data DIR      # daily bars for trader/universe.txt -> DIR
    python3 swing.py backtest --data DIR               # every setup x exit rule, train vs test
    python3 swing.py backtest --data DIR --setup dipmom --entry limit --limit 3 --target 6 --stop 12 --hold 3 --years --account

THE RULE (long only, bought for delivery / CNC, never on margin):
  setup    on a day's CLOSE: a strong stock (up more than 20% in 3 months and above its
           50-day average) that has dipped for a day or two (RSI(2) under 15)
  entry    a LIMIT BUY 3% under that close, good for the next session only. No fill, no trade.
  exits    a limit sell 6% above the buy price, or a safety stop-loss 12% under it, or the
           CLOSE of the 3rd session (the buy day is day 1), whichever comes first.
  market   no new order on an evening when the NIFTY 50 closed under its 200-day average
  Signals are ranked by 3-month strength; the model portfolio places one order per free slot.
  STOP-TRADING RULE: 6 losing trades in a row pause new orders for 10 sessions; a fall of 50% of
  the budget from the model's best point stops it (worse than anything in 9 years of history).

WHY THIS RULE: `swing.py backtest` tried 11 setups x 40 exit rules x 4 ways to enter on 495
NIFTY 500 stocks, daily bars from Nov 2016. Rules were chosen on signals before 2023 only.
After 0.33% costs, per trade:
    chosen on    2017 to 2022   2,769 trades  60% won  average +1.08%
    checked on   2023 to Nov 2025 (not used to choose)  1,178 trades  59% won  average +0.89%
    checked on   Nov 2025 to Nov 2026 (looked at once, last)  208 trades  57% won  +0.88%
Buying the next OPEN instead of the limit made about 0% after costs for every setup. A fixed
+2% target wins about 3 trades in 4 but earns less: the losers are bigger than the winners.
Tight stops (3 to 5%) turned every setup into a loser. 2018, 2022 and 2025 were flat or
slightly negative years. One account with one position is much noisier than these averages.

ONE SMALL ACCOUNT IS NOT THE AVERAGE. Replayed as one account (Rs 10,000, one position of up to
Rs 7,500, the market filter on, every order placed, Oct 2017 to Nov 2026): 249 trades, 135 won,
+Rs 7,890 in total. 2018 lost Rs 3,012 and 2022 lost Rs 3,225; the worst fall from a peak was
Rs 4,544. Picking a different one of each evening's matches moved the 9-year total anywhere from
+Rs 4,900 to +Rs 16,000. Over the same years the NIFTY 50 rose 157%: Rs 10,000 left in an index
fund grew by about Rs 15,700 with no work. At this size the rule did not beat simply holding the
index. Smaller positions do worse (the fixed charge weighs more): Rs 5,000 a trade made +Rs 3,552.
The market filter: with it, 2023 to 2026 made the same total on a quarter fewer trades with a
smaller worst fall; the trades it removes averaged about zero with larger losses.

HONEST LIMITS: the stocks are TODAY's index members (the ones that survived and grew), which
flatters every number. Daily bars cannot show the order of the day's high and low: a bar that
touches stop and target counts as the stop, and a target on the buy day is not counted. A limit
fill needs the low 0.1% through the limit. Past results do not predict future results.

Costs (delivery): STT 0.1% each side, stamp duty 0.015% on the buy, exchange fees and GST
about 0.004% each side, slippage 0.05% each side = 0.33% a round trip (--cost-pct), plus the
depository (DP) charge on each sell, about Rs 15.34 (0.2% of a Rs 7,500 position). Brokerage
is taken as zero (true for delivery at some discount brokers; add yours).

In a bar that touches both, the stop counts first. A gap through a level fills at the open.
Data: Yahoo's free chart JSON (unofficial, can lag), query2 then query1. Times are India time
(IST). --now "2026-11-25 16:20" pins the clock. Education and tooling, not financial advice.
"""

import argparse
import concurrent.futures
import datetime
import gzip
import json
import math
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
HOSTS = ("query2", "query1")
PAUSE = 0.25
IST = 19800                      # seconds east of UTC
COST_PCT = 0.33                  # % of the position, a round trip
COST_FIXED = 15.34               # rupees a round trip (DP charge on the sell)
MIN_TURNOVER = 1e8               # 20-day average traded value: Rs 10 crore
MIN_PRICE = 20.0
MIN_BARS = 210                   # 200-day average + a few
BAD_MOVE = (0.6, 1.6)            # a close-to-close ratio outside this is a data error (an unadjusted split)
SPLIT_DATE = "2023-01-01"        # signals before: train; from here on: test
RULE = {"setup": "dipmom", "limit": 3.0, "target": 6.0, "stop": 12.0, "hold": 3, "market_filter": True}
GUARD = {"losses": 6, "pause_sessions": 10, "drawdown_pct": 50.0}   # the stop-trading rule, see the docstring
BENCH = {"fill": 25.0, "win": 60.0, "avg": 1.0, "sd": 4.5}          # what the backtest showed, per trade, in percent
TICK = 0.05
CLOSE_READY = (15, 45)           # the day's bar counts as final from 3:45 PM IST
NSE_HOLIDAYS = {                 # NSE equity segment, 2026 (NSE circulars NSE/CMTR/71775 and 72260)
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03", "2026-04-14",
    "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10",
    "2026-11-24", "2026-12-25",
}
CALENDAR_YEARS = (2026,)


class SwingError(Exception):
    pass


# ---------------------------------------------------------------- data

def day_of(ts):
    return (datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(ts) + IST)).date().isoformat()


def yahoo_symbol(sym):
    s = sym.upper()
    return s if s.endswith(".NS") or s.startswith("^") else s.replace(".", "-")


def fetch_chart(sym, rng, events=False):
    path = "/v8/finance/chart/%s?range=%s&interval=1d%s" % (urllib.parse.quote(yahoo_symbol(sym), safe=".-^"), rng,
                                                           "&events=div%2Csplits" if events else "")
    err = None
    for attempt in range(2):
        for host in HOSTS:
            req = urllib.request.Request("https://%s.finance.yahoo.com%s" % (host, path),
                                         headers={"User-Agent": UA, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=25) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                err = "HTTP %d" % e.code
                if e.code == 404:
                    raise SwingError("Yahoo has no chart for %s" % sym)
            except (urllib.error.URLError, OSError, ValueError) as e:
                err = str(e)
        time.sleep(3)
    raise SwingError("could not fetch %s (%s)" % (sym, err))


def series_from_chart(doc, sym, last_day=None):
    """Yahoo chart JSON -> {"symbol", "d", "o", "h", "l", "c", "v"}: complete daily bars, oldest first.
    Bars with a missing price are dropped; a bar dated after last_day (today's unfinished bar) too."""
    try:
        r = doc["chart"]["result"][0]
        q = r["indicators"]["quote"][0]
    except (KeyError, IndexError, TypeError):
        raise SwingError("Yahoo sent no chart data for %s" % sym)
    S = {"symbol": sym, "d": [], "o": [], "h": [], "l": [], "c": [], "v": []}
    for i, ts in enumerate(r.get("timestamp") or []):
        row = [q[k][i] if i < len(q.get(k) or []) else None for k in ("open", "high", "low", "close")]
        if ts is None or None in row or min(row) <= 0:
            continue
        d = day_of(ts)
        if last_day and d > last_day:
            continue
        if S["d"] and d == S["d"][-1]:
            continue
        S["d"].append(d)
        for k, x in zip("ohlc", row):
            S[k].append(float(x))
        S["v"].append(float((q.get("volume") or [0] * (i + 1))[i] or 0))
    return S


def save_series(S, folder):
    os.makedirs(folder, exist_ok=True)
    with gzip.open(os.path.join(folder, S["symbol"].replace("^", "_") + ".json.gz"), "wt", encoding="utf-8") as fh:
        json.dump(S, fh)


def load_folder(folder, last_day=None):
    """Every saved series in a folder: ours ({"d": [...]}) or a raw download ({"t": [...]})."""
    out = {}
    if not os.path.isdir(folder):
        raise SwingError("no data folder at %s (run: swing.py fetch --data %s)" % (folder, folder))
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json.gz"):
            continue
        with gzip.open(os.path.join(folder, name), "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
        if "d" in raw:
            S = raw
        else:
            S = {"symbol": raw["symbol"], "d": [], "o": [], "h": [], "l": [], "c": [], "v": []}
            for i, ts in enumerate(raw["t"]):
                row = [raw[k][i] for k in "ohlc"]
                if None in row or min(row) <= 0:
                    continue
                S["d"].append(day_of(ts))
                for k, x in zip("ohlc", row):
                    S[k].append(float(x))
                S["v"].append(float(raw["v"][i] or 0))
        if last_day:
            n = len([d for d in S["d"] if d <= last_day])
            S = {k: (v[:n] if isinstance(v, list) else v) for k, v in S.items()}
        out[S["symbol"]] = S
    return out


def read_universe(path):
    if not os.path.isfile(path):
        raise SwingError("no symbol list at %s" % path)
    out = []
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                out.append(ln.split("|")[0].strip().upper())
    return out


# ---------------------------------------------------------------- indicators

def sma(x, n):
    out, s = [None] * len(x), 0.0
    for i, v in enumerate(x):
        s += v
        if i >= n:
            s -= x[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def rsi(c, n):
    """Wilder's RSI."""
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        ch = c[i] - c[i - 1]
        g += max(ch, 0.0)
        l += max(-ch, 0.0)
    g, l = g / n, l / n
    out[n] = 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)
    for i in range(n + 1, len(c)):
        ch = c[i] - c[i - 1]
        g = (g * (n - 1) + max(ch, 0.0)) / n
        l = (l * (n - 1) + max(-ch, 0.0)) / n
        out[i] = 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)
    return out


def atr(S, n=14):
    h, l, c = S["h"], S["l"], S["c"]
    out = [None] * len(c)
    if len(c) <= n:
        return out
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    a = sum(tr[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def prepare(S):
    """Add the indicator columns every setup reads. All of them use bars up to and including i."""
    c, v, n = S["c"], S["v"], len(S["c"])
    S["sma5"], S["sma20"], S["sma50"], S["sma200"] = sma(c, 5), sma(c, 20), sma(c, 50), sma(c, 200)
    S["rsi2"], S["rsi14"], S["atr"] = rsi(c, 2), rsi(c, 14), atr(S)
    S["turn"] = sma([c[i] * v[i] for i in range(n)], 20)
    S["vavg"] = sma(v, 20)
    S["streak"] = [0] * n                       # consecutive lower closes ending at i
    S["bad"] = [0] * n                          # index of the last data error at or before i (-1000 if none)
    last_bad = -1000
    for i in range(1, n):
        if c[i] < c[i - 1]:
            S["streak"][i] = S["streak"][i - 1] + 1
        r = c[i] / c[i - 1]
        if r < BAD_MOVE[0] or r > BAD_MOVE[1]:
            last_bad = i
        S["bad"][i] = last_bad
    if n:
        S["bad"][0] = -1000
    return S


def tradable(S, i):
    """Enough history, liquid, a sane price, and no data error in the last 200 bars."""
    return (i >= MIN_BARS and S["sma200"][i] is not None and S["turn"][i] is not None
            and S["turn"][i] >= MIN_TURNOVER and S["c"][i] >= MIN_PRICE and i - S["bad"][i] > 200)


# ---------------------------------------------------------------- setups
# Each returns a rank score (higher = better) when the setup is on at bar i's close, else None.

def s_rsi2(S, i, limit=10.0):
    """Uptrend pullback: close above the 200-day average and RSI(2) under 10."""
    if S["c"][i] > S["sma200"][i] and S["rsi2"][i] is not None and S["rsi2"][i] < limit:
        return -S["rsi2"][i]


def s_rsi2_5(S, i):
    return s_rsi2(S, i, 5.0)


def s_down3(S, i):
    """Uptrend, three lower closes in a row."""
    if S["c"][i] > S["sma200"][i] and S["streak"][i] >= 3:
        return -(S["c"][i] / S["c"][i - 3] - 1.0)


def s_ibs(S, i):
    """Uptrend, close in the bottom 10% of the day's range and under the 5-day average."""
    h, l, c = S["h"][i], S["l"][i], S["c"][i]
    if c > S["sma200"][i] and h > l and c < S["sma5"][i]:
        ibs = (c - l) / (h - l)
        if ibs < 0.10:
            return -ibs


def s_bblow(S, i):
    """Uptrend, close more than 2 standard deviations under the 20-day average."""
    c = S["c"]
    if c[i] > S["sma200"][i]:
        sd = statistics.pstdev(c[i - 19:i + 1])
        if sd > 0 and c[i] < S["sma20"][i] - 2 * sd:
            return (S["sma20"][i] - c[i]) / sd


def s_dipmom(S, i):
    """A strong stock (up 20% in 3 months, above its 50-day average) with RSI(2) under 15."""
    c = S["c"]
    if i >= 63 and c[i] > S["sma50"][i] and S["rsi2"][i] is not None and S["rsi2"][i] < 15:
        r = c[i] / c[i - 63] - 1.0
        if r > 0.20:
            return r


def s_breakout(S, i):
    """A 20-day closing high on 1.5x the average volume, above the 50-day average."""
    c, v = S["c"], S["v"]
    if c[i] > S["sma50"][i] and c[i] > max(c[i - 20:i]) and S["vavg"][i - 1] and v[i] > 1.5 * S["vavg"][i - 1]:
        return v[i] / S["vavg"][i - 1]


def s_strongclose(S, i):
    """A 20-day closing high that also closes in the top 10% of the day's range."""
    c, h, l = S["c"], S["h"][i], S["l"][i]
    if c[i] > S["sma50"][i] and c[i] > max(c[i - 20:i]) and h > l and (c[i] - l) / (h - l) > 0.9:
        return c[i] / c[i - 1] - 1.0


def s_flag(S, i):
    """Bull flag: up more than 10% over the 10 sessions before the last 5, then 5 closes inside 5%."""
    c = S["c"]
    last5 = c[i - 4:i + 1]
    run = c[i - 5] / c[i - 15] - 1.0
    if c[i] > S["sma50"][i] and run > 0.10 and (max(last5) - min(last5)) / c[i] < 0.05:
        return run


def s_reclaim(S, i):
    """Uptrend, back above the 20-day average after a close below it."""
    c = S["c"]
    if c[i] > S["sma200"][i] and c[i - 1] < S["sma20"][i - 1] and c[i] > S["sma20"][i]:
        return c[i] / c[i - 1] - 1.0


def s_surge(S, i):
    """Momentum: up more than 8% in 5 sessions, above the 50-day average."""
    c = S["c"]
    r = c[i] / c[i - 5] - 1.0
    if c[i] > S["sma50"][i] and r > 0.08:
        return r


def s_uptrend(S, i):
    """Baseline: any day in an uptrend (close above the 200-day average). Not a setup."""
    if S["c"][i] > S["sma200"][i]:
        return 0.0


def s_any(S, i):
    """Baseline: any liquid stock, any day. Not a setup."""
    return 0.0


SETUPS = {
    "rsi2": s_rsi2, "rsi2_5": s_rsi2_5, "down3": s_down3, "ibs": s_ibs, "bblow": s_bblow, "dipmom": s_dipmom,
    "breakout": s_breakout, "strongclose": s_strongclose, "flag": s_flag, "reclaim": s_reclaim, "surge": s_surge,
    "uptrend": s_uptrend, "any": s_any,
}
BASELINES = ("uptrend", "any")
LABELS = {
    "rsi2": "uptrend pullback: above the 200-day average, RSI(2) under 10",
    "rsi2_5": "uptrend pullback: above the 200-day average, RSI(2) under 5",
    "down3": "uptrend, three lower closes in a row",
    "ibs": "uptrend, close in the bottom 10% of the day's range",
    "bblow": "uptrend, close 2 standard deviations under the 20-day average",
    "dipmom": "strong stock (+20% in 3 months) with RSI(2) under 15",
    "breakout": "20-day closing high on 1.5x volume",
    "strongclose": "20-day closing high, close in the top 10% of the range",
    "flag": "bull flag (10% run, then 5 tight closes)",
    "reclaim": "back above the 20-day average, in an uptrend",
    "surge": "up more than 8% in 5 sessions",
    "uptrend": "BASELINE: any day above the 200-day average",
    "any": "BASELINE: any liquid stock, any day",
}


# ---------------------------------------------------------------- one trade

FILL_THROUGH = 0.001             # a limit buy counts as filled only when the low trades 0.1% through it
MAX_WICK = 0.0                   # > 0: ignore a fill day whose low is this far under both open and close


def limit_price(S, i, mode, x):
    """The limit buy price for the session after bar i: x percent under the close ("limit"),
    or x times the 14-day ATR under it ("atr")."""
    if mode == "atr":
        return S["c"][i] - x * S["atr"][i]
    return S["c"][i] * (1 - x / 100.0)


def trade(S, i, target, stop, hold, max_gap=None, entry_mode="open", limit=None, exit_open=False):
    """The trade a signal at bar i's close makes. target / stop in percent of the entry (None = off).
    entry_mode  "open"   buy bar i+1's open
                "close"  buy bar i's close (an order in the last minutes of the signal day)
                "limit"  a limit buy `limit` percent under bar i's close, good for bar i+1 only:
                         filled at the limit (or the open, if it opens lower) when the low reaches it
    Day 1 of the hold is the first session held: bar i+1. exit_open sells the next open after the hold
    instead of the last close. On the entry day of a limit buy the target is not counted (the high may
    have come before the fill); the stop always is.
    -> (gross return %, outcome, exit index, entry price) or None (no fill, no data, a data error)."""
    o, h, l, c = S["o"], S["h"], S["l"], S["c"]
    e_i, x_i = i + 1, i + hold
    last = x_i + 1 if exit_open else x_i
    if last >= len(c):
        return None
    for j in range(e_i, last + 1):
        r = c[j] / c[j - 1]
        if r < BAD_MOVE[0] or r > BAD_MOVE[1]:
            return None
    if entry_mode == "close":
        entry = c[i]
    elif entry_mode in ("limit", "atr"):
        lim = limit_price(S, i, entry_mode, limit)
        if l[e_i] > lim * (1 - FILL_THROUGH) or (MAX_WICK and l[e_i] < min(o[e_i], c[e_i]) * (1 - MAX_WICK)):
            return None                   # not reached (or a bad tick: a low far under both the open and the close)
        entry = min(o[e_i], lim)
    else:
        entry = o[e_i]
        if max_gap is not None and (entry / c[i] - 1.0) * 100.0 > max_gap:
            return None
    tgt = entry * (1 + target / 100.0) if target else None
    stp = entry * (1 - stop / 100.0) if stop else None
    for j in range(e_i, x_i + 1):
        if j > e_i or entry_mode == "close":
            if stp is not None and o[j] <= stp:
                return (o[j] / entry - 1) * 100.0, "stop", j, entry
            if tgt is not None and o[j] >= tgt:
                return (o[j] / entry - 1) * 100.0, "target", j, entry
        if stp is not None and l[j] <= stp:
            return -float(stop), "stop", j, entry
        if tgt is not None and h[j] >= tgt and not (entry_mode in ("limit", "atr") and j == e_i):
            return float(target), "target", j, entry
    if exit_open:
        return (o[x_i + 1] / entry - 1) * 100.0, "time", x_i + 1, entry
    return (c[x_i] / entry - 1) * 100.0, "time", x_i, entry


# ---------------------------------------------------------------- backtest

def market_ok(mkt):
    """{date: True when the NIFTY 50 closed above its 200-day average}."""
    if not mkt:
        return {}
    m = sma(mkt["c"], 200)
    return {d: (m[i] is not None and mkt["c"][i] > m[i]) for i, d in enumerate(mkt["d"])}


def signals(data, setup, regime=None, step=1):
    """Every (symbol series, bar index, score) where the setup is on. step > 1 thins a baseline."""
    fn = SETUPS[setup]
    out = []
    for sym, S in data.items():
        if sym.startswith("^"):
            continue
        d = S["d"]
        for i in range(MIN_BARS, len(d) - 1, step):
            if not tradable(S, i):
                continue
            if regime is not None and not regime.get(d[i], False):
                continue
            sc = fn(S, i)
            if sc is not None:
                out.append((S, i, sc))
    return out


def stats(rets):
    """Per-trade numbers from a list of net returns in percent."""
    n = len(rets)
    if not n:
        return {"n": 0}
    wins = [r for r in rets if r > 0]
    loss = [r for r in rets if r <= 0]
    mean = sum(rets) / n
    sd = statistics.pstdev(rets) if n > 1 else 0.0
    return {"n": n, "win": 100.0 * len(wins) / n, "avg": mean, "med": statistics.median(rets),
            "avg_win": sum(wins) / len(wins) if wins else 0.0, "avg_loss": sum(loss) / len(loss) if loss else 0.0,
            "pf": (sum(wins) / -sum(loss)) if loss and sum(loss) < 0 else float("inf"),
            "t": mean / (sd / math.sqrt(n)) if sd > 0 else 0.0}


def run(sigs, target, stop, hold, cost_pct=COST_PCT, max_gap=None, entry_mode="open", limit=None, exit_open=False,
        unfilled=False):
    """-> list of trades {sym, signal day, entry day, exit day, gross, net, outcome, score}.
    unfilled=True also keeps the orders that never filled ({"filled": False}), for the account replay."""
    out = []
    for S, i, sc in sigs:
        t = trade(S, i, target, stop, hold, max_gap, entry_mode, limit, exit_open)
        if t is None:
            if unfilled and i + 1 < len(S["d"]):
                px = limit_price(S, i, entry_mode, limit) if entry_mode in ("limit", "atr") else S["c"][i]
                out.append({"sym": S["symbol"], "sig": S["d"][i], "in": S["d"][i + 1], "score": sc,
                            "entry": px, "filled": False})
            continue
        g, oc, j, entry = t
        out.append({"sym": S["symbol"], "sig": S["d"][i], "in": S["d"][i if entry_mode == "close" else i + 1],
                    "out": S["d"][j], "gross": g, "net": g - cost_pct, "oc": oc, "score": sc, "entry": entry})
    return out


def account(orders, slots=1, start=10000.0, invest=0.75, fixed=COST_FIXED):
    """One real account, with no hindsight. Each evening it places one order per free slot, for the
    best-ranked signals (it cannot know which will fill); each order is for whole shares worth at most
    `invest`/slots of the equity; a slot is free again the day after its exit. `orders` is run(...,
    unfilled=True). Fixed costs (the DP charge) are in rupees a trade."""
    by_day = {}
    for t in orders:
        by_day.setdefault(t["in"], []).append(t)
    eq, peak, dd = start, start, 0.0
    open_until, taken, placed = [], [], 0
    for day in sorted(by_day):
        open_until = [d for d in open_until if d >= day]
        free = slots - len(open_until)
        for t in sorted(by_day[day], key=lambda x: -x["score"]):
            if free <= 0:
                break
            qty = int((eq * invest / slots) // t["entry"])
            if qty < 1:
                continue                      # one share costs more than the slot: next signal
            free -= 1
            placed += 1
            if t.get("filled") is False:
                continue                      # the order was placed and did not fill
            size = qty * t["entry"]
            pnl = size * t["net"] / 100.0 - fixed
            eq += pnl
            open_until.append(t["out"])
            taken.append(dict(t, pnl=pnl, size=size, qty=qty))
            peak = max(peak, eq)
            dd = max(dd, 1 - eq / peak)
    return {"start": start, "end": eq, "orders": placed, "trades": len(taken), "max_dd": 100.0 * dd,
            "taken": taken, "wins": sum(1 for t in taken if t["pnl"] > 0)}


def fmt_row(name, s):
    if not s.get("n"):
        return "%-22s  no trades" % name
    return "%-22s %7d  %5.1f%%  %+6.3f%%  %+6.2f%%  %+5.2f%% / %+5.2f%%  %5.2f  %+5.1f" % (
        name, s["n"], s["win"], s["avg"], s["med"], s["avg_win"], s["avg_loss"], min(s["pf"], 99.99), s["t"])


HEAD = "%-22s %7s  %6s  %7s  %7s  %15s  %5s  %5s" % ("", "trades", "win", "avg net", "median", "avg win / loss", "PF", "t")
GRID = [(t, s, h) for h in (2, 3) for t in (2.0, 3.0, 4.0, 6.0, None) for s in (3.0, 5.0, 8.0, None)]


def exit_name(t, s, h):
    return "T%s S%s %dd" % ("%g" % t if t else "-", "%g" % s if s else "-", h)


def cmd_backtest(a):
    global MAX_WICK
    MAX_WICK = a.max_wick
    data = load_folder(a.data, a.until)
    for S in data.values():
        prepare(S)
    mkt = data.get("^NSEI")
    regime = market_ok(mkt) if a.regime else None
    days = sorted({d for S in data.values() for d in S["d"]})
    print("Data: %d stocks, %s to %s. Train: signals before %s. Test: from then on (never used to choose)."
          % (len([s for s in data if not s.startswith("^")]), days[0], days[-1], a.split))
    print("Liquid only (20-day average traded value >= Rs %.0f crore), price >= Rs %.0f. Net = after %.2f%% costs."
          % (MIN_TURNOVER / 1e7, MIN_PRICE, a.cost_pct))
    if a.regime:
        print("Market filter ON: signals only on days the NIFTY 50 closed above its 200-day average.")
    names = [a.setup] if a.setup else list(SETUPS)
    best = {}
    for name in names:
        sigs = signals(data, name, regime, step=7 if name in BASELINES else 1)
        tr_s = [x for x in sigs if x[0]["d"][x[1]] < a.split]
        te_s = [x for x in sigs if x[0]["d"][x[1]] >= a.split]
        grid = [(a.target, a.stop, a.hold)] if a.hold else GRID
        rows = []
        for (t, s, h) in grid:
            tr = stats([x["net"] for x in run(tr_s, t, s, h, a.cost_pct, a.max_gap, a.entry, a.limit, a.exit_open)])
            rows.append(((t, s, h), tr))
        rows = [r for r in rows if r[1].get("n", 0) >= 200] or rows
        (t, s, h), tr = max(rows, key=lambda r: r[1].get("avg", -99))
        te_all = run(te_s, t, s, h, a.cost_pct, a.max_gap, a.entry, a.limit, a.exit_open, unfilled=True)
        te_tr = [x for x in te_all if x.get("filled") is not False]
        te = stats([x["net"] for x in te_tr])
        best[name] = ((t, s, h), tr, te, te_tr, tr_s, te_s)
        print("\n%s: %s" % (name, LABELS[name]))
        print(HEAD)
        if a.grid:
            for (tt, ss, hh), st in sorted(rows, key=lambda r: -r[1].get("avg", -99)):
                print(fmt_row("  train " + exit_name(tt, ss, hh), st))
        print(fmt_row("TRAIN best " + exit_name(t, s, h), tr))
        print(fmt_row("TEST  same " + exit_name(t, s, h), te))
        if a.years:
            yrs = {}
            for x in run(tr_s + te_s, t, s, h, a.cost_pct, a.max_gap, a.entry, a.limit, a.exit_open):
                yrs.setdefault(x["sig"][:4], []).append(x["net"])
            for y in sorted(yrs):
                print(fmt_row("  %s" % y, stats(yrs[y])))
        if a.account:
            for slots in (1, 2):
                ac = account(te_all, slots=slots, start=a.start)
                print("  TEST as one Rs %s account, %d position(s) at a time, Rs %.2f fixed cost a trade: %d orders, "
                      "%d trades, %d won, ended Rs %s, worst fall from a peak %.1f%%"
                      % ("{:,.0f}".format(a.start), slots, COST_FIXED, ac["orders"], ac["trades"], ac["wins"],
                         "{:,.0f}".format(ac["end"]), ac["max_dd"]))
    print("\nRead it this way: 'avg net' is the average result of ONE trade after costs, in percent of the position.")
    print("The universe is today's index members (survivors), which flatters every row. The TEST row is the honest one.")
    return 0


def cmd_fetch(a):
    syms = read_universe(a.universe) + ["^NSEI"]
    if a.limit:
        syms = syms[:a.limit]
    ok = bad = 0
    for k, sym in enumerate(syms):
        try:
            save_series(series_from_chart(fetch_chart(sym, a.range), sym), a.data)
            ok += 1
        except SwingError as e:
            bad += 1
            print("  skipped %s: %s" % (sym, e), file=sys.stderr)
        time.sleep(PAUSE)
    print("Fetched %d of %d charts (%d failed) into %s." % (ok, len(syms), bad, a.data))
    return 0 if ok else 1


# ---------------------------------------------------------------- live: scan and track

def parse_now(text):
    """-> naive IST. No offset means IST; ...Z or +hh:mm is absolute."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None) \
            + datetime.timedelta(seconds=IST)
    try:
        dt = datetime.datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise SwingError('--now wants an IST time like "2026-11-25 16:20" (or ...Z for UTC)')
    if dt.tzinfo is None:
        return dt
    return (dt - dt.utcoffset()).replace(tzinfo=None) + datetime.timedelta(seconds=IST)


def is_session(d):
    return d.weekday() < 5 and d.isoformat() not in NSE_HOLIDAYS


def next_session(d, n=1):
    """The n-th trading day after date d (weekends and the NSE holiday list)."""
    while n > 0:
        d += datetime.timedelta(days=1)
        if is_session(d):
            n -= 1
    return d


def last_complete_day(now):
    """The last session whose daily bar is final at `now`."""
    d = now.date()
    if is_session(d) and (now.hour, now.minute) >= CLOSE_READY:
        return d
    d -= datetime.timedelta(days=1)
    while not is_session(d):
        d -= datetime.timedelta(days=1)
    return d


def tick_down(x):
    return math.floor(x / TICK + 1e-9) * TICK


def rupees(x, signed=False):
    s = "{:,.2f}".format(abs(x))
    if s.endswith(".00"):
        s = s[:-3]
    return ("-" if x < 0 else "+" if signed and x > 0 else "") + "₹" + s


def wd(day):
    return datetime.date.fromisoformat(day).strftime("%a %Y-%m-%d")


def load_config(path):
    cfg = {"budget": None, "cash_buffer_pct": 10, "max_position_pct": 75, "swing_slots": 1, "swing_start": None}
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            try:
                cfg.update(json.load(fh))
            except ValueError as e:
                raise SwingError("%s is not valid JSON: %s" % (path, e))
    return cfg


def per_order(cfg, budget=None):
    """Rupees one order may use: the position cap and the cash after the buffer, shared by the slots."""
    b = budget if budget else cfg.get("budget")
    if not b:
        raise SwingError('no budget: pass --budget or set "budget" in trader/config.json')
    slots = max(1, int(cfg.get("swing_slots") or 1))
    cap = min(b * float(cfg["max_position_pct"]) / 100.0, b * (1 - float(cfg["cash_buffer_pct"]) / 100.0))
    return cap / slots if slots > 1 else cap, slots


def fetch_all(syms, rng, workers=4):
    """{symbol: raw chart JSON}; failures are left out."""
    def one(sym):
        try:
            return sym, fetch_chart(sym, rng)
        except SwingError:
            return sym, None
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        return {s: d for s, d in ex.map(one, syms) if d is not None}


def live_data(a, now, keep_today=False):
    """Prepared series for the universe, bars through the last complete day (or through today so far)."""
    last = last_complete_day(now)
    upto = now.date().isoformat() if keep_today else last.isoformat()
    if a.offline:
        data = load_folder(a.offline, upto)
        asked = len([s for s in data if not s.startswith("^")])
    else:
        syms = read_universe(a.universe)
        asked = len(syms)
        raw = fetch_all(syms + ["^NSEI"], "2y")
        data = {}
        for sym, doc in raw.items():
            try:
                data[sym] = series_from_chart(doc, sym, upto)
            except SwingError:
                pass
    for S in data.values():
        prepare(S)
        S["ix"] = {d: i for i, d in enumerate(S["d"])}
    return data, asked, last


def actions_from_chart(doc, since_day):
    """Dividends and splits dated on or after since_day in a Yahoo chart fetched with events.
    -> ["dividend ₹5.50 a share, ex-date 2026-11-20", "split 1:5, ex-date ..."] (oldest first)."""
    try:
        ev = doc["chart"]["result"][0].get("events") or {}
    except (KeyError, IndexError, TypeError):
        return []
    out = []
    for e in (ev.get("dividends") or {}).values():
        d = day_of(e.get("date", 0))
        if d >= since_day and e.get("amount"):
            out.append((d, "dividend %s a share, ex-date %s" % (rupees(float(e["amount"])), d)))
    for e in (ev.get("splits") or {}).values():
        d = day_of(e.get("date", 0))
        if d >= since_day:
            out.append((d, "split or bonus %s:%s, ex-date %s" % (e.get("denominator"), e.get("numerator"), d)))
    return [t for _, t in sorted(out)]


def data_flags(S, i, mkt, actions):
    """Facts from the data alone that the news check must look at (see NEWS.md). Never a verdict."""
    c = S["c"]
    day, two = (c[i] / c[i - 1] - 1) * 100.0, (c[i] / c[i - 2] - 1) * 100.0
    flags = []
    if day <= -7.0:
        flags.append("fell %.1f%% on the signal day: find out why before ordering" % -day)
    if S["h"][i] > S["l"][i] and c[i] <= S["l"][i] * 1.001 and day <= -4.5:
        flags.append("closed at the day's low after a %.1f%% fall: check for a lower circuit" % -day)
    for a in actions:
        flags.append("corporate action in the data: %s (the price drop may be the adjustment, not a dip)" % a)
    if mkt and mkt.get("below200"):
        flags.append("the NIFTY 50 is under its 200-day average: the rule's weak years (2018, 2022) looked like this")
    return {"day_change": day, "two_day_change": two, "flags": flags}


def market_line(data, day):
    """The NIFTY 50 on `day`: its change and where it sits against its 200-day average."""
    M = data.get("^NSEI")
    i = (M or {}).get("ix", {}).get(day)
    if M is None or i is None or i < 1:
        return None
    ch = (M["c"][i] / M["c"][i - 1] - 1) * 100.0
    m200 = M["sma200"][i]
    return {"close": M["c"][i], "change": ch, "below200": m200 is not None and M["c"][i] < m200}


def follow(S, i, rule, live_day=None):
    """The live rule's order from the signal at bar i, followed over the bars that exist.
    status: "pending" (its session has no bar yet), "waiting" (its session is still running),
    "unfilled", "open", "target", "stop", "time". live_day is today's date while its bar is not final:
    on that bar an order that has not filled is still waiting, and the time exit has not happened."""
    o, h, l, c, d = S["o"], S["h"], S["l"], S["c"], S["d"]
    lim = tick_down(limit_price(S, i, "limit", rule["limit"]))
    r = {"limit": lim, "status": "pending", "entry": None, "exit": None, "exit_day": None, "day_no": 0,
         "last_close": c[i], "gross": None}
    e = i + 1
    if e >= len(c):
        return r
    if l[e] > lim * (1 - FILL_THROUGH):
        r["status"] = "waiting" if d[e] == live_day else "unfilled"
        return r
    entry = min(o[e], lim)
    tgt, stp = entry * (1 + rule["target"] / 100.0), entry * (1 - rule["stop"] / 100.0)
    r.update(status="open", entry=entry, entry_day=d[e], target=tgt, stop=stp)
    for j in range(e, min(i + rule["hold"], len(c) - 1) + 1):
        r["day_no"], r["last_close"] = j - i, c[j]
        if j > e and o[j] <= stp:
            r.update(status="stop", exit=o[j], exit_day=d[j])
        elif j > e and o[j] >= tgt:
            r.update(status="target", exit=o[j], exit_day=d[j])
        elif l[j] <= stp:
            r.update(status="stop", exit=stp, exit_day=d[j])
        elif j > e and h[j] >= tgt:
            r.update(status="target", exit=tgt, exit_day=d[j])
        elif j == i + rule["hold"] and d[j] != live_day:
            r.update(status="time", exit=c[j], exit_day=d[j])
        if r["exit"] is not None:
            break
    px = r["exit"] if r["exit"] is not None else r["last_close"]
    r["gross"] = (px / entry - 1) * 100.0
    return r


def candidates(data, day, rule):
    """Every stock whose setup is on at `day`'s close, best rank first."""
    fn = SETUPS[rule["setup"]]
    out = []
    for sym, S in data.items():
        i = S.get("ix", {}).get(day)
        if sym.startswith("^") or i is None or not tradable(S, i):
            continue
        sc = fn(S, i)
        if sc is not None:
            out.append((sc, sym, i))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


CLOSED = ("target", "stop", "time")


def guard_state(orders, day, budget, guard):
    """Where the stop-trading rule stands on the evening of `day`, from the trades finished by then.
    -> {"streak", "pause_until", "stopped", "pnl", "drop", "closed", "wins", "worst_streak"}.
    A pause starts at the 6th loss in a row and lasts 10 sessions; the count then starts again.
    A fall of 50% of the budget from the best point so far stops the model for good. That line is
    past the worst fall of the 9-year replay (45% of the budget, in 2018): crossing it means the rule
    is not behaving as tested. It is not a comfort level: position size is what limits the risk."""
    done = sorted((f for f in orders if f["status"] in CLOSED and f["exit_day"] <= day), key=lambda f: f["exit_day"])
    st = {"streak": 0, "pause_until": None, "stopped": False, "pnl": 0.0, "drop": 0.0, "closed": len(done),
          "wins": sum(1 for f in done if f["pnl"] > 0), "worst_streak": 0}
    peak = run_ = 0.0
    for f in done:
        run_ += f["pnl"]
        peak = max(peak, run_)
        st["drop"] = max(st["drop"], peak - run_) if guard else st["drop"]
        st["streak"] = st["streak"] + 1 if f["pnl"] <= 0 else 0
        st["worst_streak"] = max(st["worst_streak"], st["streak"])
        if guard and budget and peak - run_ >= budget * guard["drawdown_pct"] / 100.0:
            st["stopped"] = True
        if guard and st["streak"] >= guard["losses"]:
            st["pause_until"] = next_session(datetime.date.fromisoformat(f["exit_day"]), guard["pause_sessions"]).isoformat()
            st["streak"] = 0
    st["pnl"] = run_
    st["now_drop"] = peak - run_
    return st


def replay(data, days, rule, rupees_per_order, slots, live_day=None, budget=None, guard=None):
    """The model portfolio over `days` (signal days, oldest first), with no hindsight: each evening one
    order per free slot for the best-ranked signals it can afford one share of. No orders on an evening
    when the market filter is off (NIFTY 50 under its 200-day average) or the stop-trading rule is on.
    -> (orders, matched, notes): matched = {signal day: [(score, symbol, index)]}, notes = {signal day:
    why there was no order ("market", "paused until <day>", "stopped")}."""
    orders, matched, notes, busy = [], {}, {}, []   # busy: exit day of each open position (None = still open)
    for day in days:
        cands = candidates(data, day, rule)
        matched[day] = cands
        trade_day = next_session(datetime.date.fromisoformat(day)).isoformat()
        if guard:
            g = guard_state(orders, day, budget, guard)
            if g["stopped"]:
                notes[day] = "stopped"
                continue
            if g["pause_until"] and trade_day <= g["pause_until"]:
                notes[day] = "paused until %s" % g["pause_until"]
                continue
        if rule.get("market_filter"):
            m = market_line(data, day)
            if m and m["below200"]:
                notes[day] = "market"
                continue
        free = slots - len([x for x in busy if x is None or x >= trade_day])
        for sc, sym, i in cands:
            if free <= 0:
                break
            S = data[sym]
            f = follow(S, i, rule, live_day)
            qty = int(rupees_per_order // f["limit"])
            if qty < 1:
                continue
            free -= 1
            f.update(symbol=sym, signal_day=day, trade_day=trade_day, qty=qty, close=S["c"][i], score=sc,
                     rsi2=S["rsi2"][i], last_day_no=rule["hold"],
                     exit_by=next_session(datetime.date.fromisoformat(trade_day), rule["hold"] - 1).isoformat())
            if f["status"] == "waiting":
                busy.append(None)             # the order is working today: the slot is not free
            if f["status"] in ("open",) + CLOSED:
                busy.append(f["exit_day"])
                size = qty * f["entry"]
                f["net_pct"] = f["gross"] - COST_PCT
                f["pnl"] = size * f["net_pct"] / 100.0 - COST_FIXED
            orders.append(f)
    return orders, matched, notes


def order_lines(f, rule, n=None):
    lim, qty = f["limit"], f["qty"]
    extra = []
    if f.get("day_change") is not None:
        extra.append("   Signal day %+.1f%%, two days %+.1f%%." % (f["day_change"], f["two_day_change"]))
    for fl in f.get("flags", []):
        extra.append("   CHECK: " + fl)
    tgt, stp = tick_down(lim * (1 + rule["target"] / 100.0)), tick_down(lim * (1 - rule["stop"] / 100.0))
    cost = qty * lim * COST_PCT / 100.0 + COST_FIXED
    return [
        "%s%s  closed %s, up %.0f%% in 3 months, RSI(2) %.1f" % ("%d. " % n if n else "", f["symbol"], rupees(f["close"]),
                                                                  100 * f["score"], f["rsi2"]),
        "   BUY LIMIT %s (3%% under the close), %d share%s = %s. Delivery (CNC). Good for %s only: cancel it if it"
        " has not filled by 3:30 PM." % (rupees(lim), qty, "" if qty == 1 else "s", rupees(qty * lim), wd(f["trade_day"])),
        "   If it fills: SELL LIMIT %s (+%g%%) and a STOP-LOSS at %s (-%g%%), both as GTT orders. Still open on %s?"
        " Sell at market by 3:20 PM." % (rupees(tgt), rule["target"], rupees(stp), rule["stop"], wd(f["exit_by"])),
        "   If it fills lower at the open, set both from your real buy price. Loss at the stop: about %s. Costs: about %s."
        % (rupees(qty * lim * rule["stop"] / 100.0), rupees(cost)),
    ] + extra


STATUS_WORDS = {"waiting": "NOT FILLED SO FAR today (the order works until 3:30 PM)", "unfilled": "NOT FILLED (the low stayed above the limit): no trade", "target": "TARGET hit",
                "stop": "SAFETY STOP hit", "time": "TIME EXIT at the day-3 close", "pending": "order for the next session"}


def status_line(f, rule):
    head = "%s  signal %s, order for %s: limit %s x %d" % (f["symbol"], f["signal_day"], wd(f["trade_day"]),
                                                          rupees(f["limit"]), f["qty"])
    st = f["status"]
    if st in ("pending", "unfilled", "waiting"):
        return head + "\n   " + STATUS_WORDS[st]
    if st == "open":
        left = rule["hold"] - f["day_no"]
        tail = ("day %d of %d, last close %s (%+.2f%% before costs). " % (f["day_no"], rule["hold"], rupees(f["last_close"]),
                                                                        f["gross"]))
        tail += ("LAST DAY is %s: sell at market by 3:20 PM if the target has not filled." % wd(f["exit_by"]) if left <= 1
                 else "Target %s, stop %s, time exit %s." % (rupees(tick_down(f["target"])), rupees(tick_down(f["stop"])),
                                                             wd(f["exit_by"])))
        return head + "\n   FILLED at %s on %s. OPEN: %s" % (rupees(f["entry"]), wd(f["entry_day"]), tail)
    return head + "\n   FILLED at %s on %s. %s on %s at %s: %+.2f%% after costs, %s" % (
        rupees(f["entry"]), wd(f["entry_day"]), STATUS_WORDS[st], wd(f["exit_day"]), rupees(f["exit"]), f["net_pct"],
        rupees(f["pnl"], signed=True))


def session_days(last, n):
    """The last n sessions up to and including `last` (a date), oldest first."""
    out, d = [], last
    while len(out) < n:
        if is_session(d):
            out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out[::-1]


def sessions_from(start, last, cap=250):
    """Every session from date `start` to date `last`, oldest first, at most `cap` (the latest ones)."""
    out, d = [], last
    while d >= start and len(out) < cap:
        if is_session(d):
            out.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    return out[::-1]


def review_lines(orders, g, start, n_sessions, guard, budget):
    """The model portfolio against what the backtest showed. Plain numbers and one plain verdict."""
    placed = [f for f in orders if f["status"] not in ("pending", "waiting")]
    filled = [f for f in placed if f["status"] != "unfilled"]
    done = [f for f in placed if f["status"] in CLOSED]
    out = ["Since %s (%d sessions): %d order%s placed, %d filled%s." % (
        wd(start), n_sessions, len(placed), "" if len(placed) == 1 else "s", len(filled),
        " (%.0f%%; the backtest filled about 1 in 4)" % (100.0 * len(filled) / len(placed)) if placed else "")]
    if not done:
        out.append("No finished trade yet: nothing to judge. Weeks without a fill are normal with this rule.")
        return out
    pct = [100.0 * f["pnl"] / (f["qty"] * f["entry"]) for f in done]
    avg, n = sum(pct) / len(pct), len(done)
    band = 2 * BENCH["sd"] / math.sqrt(n)
    out.append("Finished trades: %d. Won %d (%.0f%%; the backtest won about 6 in 10). Total %s after all costs."
               % (n, g["wins"], 100.0 * g["wins"] / n, rupees(g["pnl"], signed=True)))
    out.append("Average %+.2f%% a trade after all costs (the backtest: about +0.9%% before the Rs 15 DP charge, "
               "about +0.7%% after it at this size)." % avg)
    out.append("Longest losing run %d (now %d; the rule pauses at %d). Down %s from the best point (the rule stops at %s)."
               % (g["worst_streak"], g["streak"], guard["losses"], rupees(g["now_drop"]),
                  rupees(budget * guard["drawdown_pct"] / 100.0)))
    if n < 20:
        out.append("VERDICT: too few trades to judge. With %d trades, an average anywhere from %+.1f%% to %+.1f%% is "
                   "ordinary luck. Look again at 20 trades." % (n, 0.7 - band, 0.7 + band))
    elif avg < 0.7 - band:
        out.append("VERDICT: BELOW what the test showed, by more than luck explains (%d trades, average %+.2f%%). "
                   "Do not put real money on it; if it is still under zero at 30 trades, stop using the rule." % (n, avg))
    elif avg < 0:
        out.append("VERDICT: losing so far, but still inside what luck explains over %d trades. Keep it on paper." % n)
    else:
        out.append("VERDICT: in line with the test so far (%d trades). That is not proof it will continue." % n)
    return out


def cmd_scan(a, mode="scan"):
    track_only = mode != "scan"
    now = parse_now(a.now)
    cfg = load_config(a.config)
    rule, guard = dict(RULE), dict(GUARD)
    money, slots = per_order(cfg, a.budget)
    budget = a.budget or cfg["budget"]
    live = mode == "track" and a.live
    data, asked, last = live_data(a, now, keep_today=live)
    last_day = last.isoformat()
    got = len([s for s in data if not s.startswith("^")])
    fresh = len([s for s, S in data.items() if not s.startswith("^") and S["d"] and S["d"][-1] >= last_day])
    if not got:
        raise SwingError("no charts came back from Yahoo: try again in a few minutes")
    start = cfg.get("swing_start")
    if start:
        try:
            days = sessions_from(datetime.date.fromisoformat(start), last)
        except ValueError:
            raise SwingError('"swing_start" in the config wants a date like 2026-11-23')
        if not days:
            raise SwingError("swing_start %s is after the last complete session %s" % (start, last_day))
    else:
        days = session_days(last, a.days)
    orders, matched, notes = replay(data, days, rule, money, slots, now.date().isoformat() if live else None,
                                    budget, guard)
    g = guard_state(orders, last_day, budget, guard)
    today = matched[last_day]
    trade_day = next_session(last).isoformat()
    pending = [f for f in orders if f["signal_day"] == last_day]
    openp = [f for f in orders if f["status"] == "open"]
    mkt = market_line(data, last_day)
    since = session_days(last, 4)[0]
    for f in pending if not track_only else []:
        S = data[f["symbol"]]
        acts = []
        if not a.offline:
            try:
                acts = actions_from_chart(fetch_chart(f["symbol"], "3mo", events=True), since)
            except SwingError:
                acts = ["could not read corporate actions from Yahoo: check them by hand"]
        f.update(data_flags(S, S["ix"][last_day], mkt, acts))
    out = []
    nifty = ("NIFTY 50 closed %s (%+.2f%% on the day), %s its 200-day average."
             % ("{:,.2f}".format(mkt["close"]), mkt["change"], "BELOW" if mkt["below200"] else "above")) if mkt else \
        "NIFTY 50: no data, so the market filter was NOT checked today."
    if mode == "scan":
        out.append("Swing scan, %s IST. Daily bars through %s." % (now.strftime("%a %Y-%m-%d %H:%M"), wd(last_day)))
        out.append("Fetched %d of %d charts; %d have %s's bar; %d matched the rule (strong stock, short dip)."
                   % (got, asked, fresh, wd(last_day), len(today)))
        if fresh < 0.8 * got:
            out.append("WARNING: only %d of %d charts have %s's bar yet. Yahoo may be late: run the scan again later."
                       % (fresh, got, wd(last_day)))
        out.append(nifty)
        out.append("Model portfolio: %s to use on one order, %d position%s at a time (budget %s)."
                   % (rupees(money), slots, "" if slots == 1 else "s", rupees(budget)))
        out.append("")
        why = notes.get(last_day, "")
        if pending:
            when = ("today: place it now if you have not" if trade_day == now.date().isoformat()
                    else "place tonight as an after-market order, or before 9:15 AM")
            out.append("ORDER%s FOR %s (%s):" % ("S" if len(pending) > 1 else "", wd(trade_day), when))
            for n, f in enumerate(pending, 1):
                out += order_lines(f, rule, n)
        elif why == "market":
            out.append("NO ORDER for %s: MARKET FILTER. The NIFTY 50 is under its 200-day average; in the backtest the "
                       "rule made nothing in such markets and its losses were bigger. This can last weeks or months."
                       % wd(trade_day))
        elif why == "stopped":
            out.append("NO ORDER: STOPPED. The model portfolio is down %s from its best point, past the %g%% limit (%s). "
                       "Review the rule before any new trade; a new \"swing_start\" date in the config starts a fresh count."
                       % (rupees(g["now_drop"]), guard["drawdown_pct"], rupees(budget * guard["drawdown_pct"] / 100.0)))
        elif why.startswith("paused"):
            out.append("NO ORDER for %s: PAUSED after %d losses in a row. Orders start again after %s."
                       % (wd(trade_day), guard["losses"], wd(why.split()[-1])))
        elif openp:
            out.append("NO NEW ORDER for %s: the slot is in use (%s)." % (wd(trade_day), ", ".join(f["symbol"] for f in openp)))
        elif today:
            out.append("NO ORDER for %s: one share of every match costs more than %s." % (wd(trade_day), rupees(money)))
        else:
            out.append("NO ORDER for %s: nothing matched the rule today. No trade is a normal day." % wd(trade_day))
        rest = [(sc, sym, i) for sc, sym, i in today if sym not in {f["symbol"] for f in pending}][:a.show]
        if rest:
            out.append("Also matched, not ordered (%s): %s" % (
                "no order today" if not pending else "one order per free slot",
                ", ".join("%s %s" % (sym, rupees(data[sym]["c"][i])) for sc, sym, i in rest)))
        if pending:
            out.append("BEFORE YOU PLACE IT: run the news check in NEWS.md (results dates, corporate actions, fraud or"
                       " regulatory news, market events). This scan reads prices only.")
        out.append("")
    elif mode == "track":
        out.append("Swing tracker, %s IST. Bars through %s%s." % (
            now.strftime("%a %Y-%m-%d %H:%M"), wd(max((S["d"][-1] for S in data.values() if S["d"]), default=last_day)),
            " (today's bar is not final)" if live else ""))
    else:
        out.append("Swing review, %s IST. Daily bars through %s." % (now.strftime("%a %Y-%m-%d %H:%M"), wd(last_day)))
        out.append(nifty)
        out += review_lines(orders, g, days[0], len(days), guard, budget)
        if g["stopped"]:
            out.append("STATUS: STOPPED (down %g%% of the budget from the best point). No new orders until you review."
                       % guard["drawdown_pct"])
        elif g["pause_until"] and trade_day <= g["pause_until"]:
            out.append("STATUS: PAUSED after %d losses in a row, until %s." % (guard["losses"], wd(g["pause_until"])))
        quiet = sum(1 for d in days if notes.get(d) == "market")
        if quiet:
            out.append("Market filter: no orders on %d of %d evenings (NIFTY 50 under its 200-day average)." % (quiet, len(days)))
        out.append("")
    shown = set(session_days(last, a.days))
    recent = [f for f in orders if f["status"] != "pending" and (f["signal_day"] in shown or f["status"] in ("open", "waiting"))]
    out.append("Model portfolio, orders of the last %d sessions (it assumes every order was placed):" % a.days)
    if not recent:
        out.append("  none")
    for f in recent:
        out.append("  " + status_line(f, rule).replace("\n", "\n  "))
    if mode != "review":
        if start and g["closed"]:
            out.append("Since %s: %d finished trade%s, %d won, total %s after costs. Losing run now %d (pause at %d)."
                       % (wd(days[0]), g["closed"], "" if g["closed"] == 1 else "s", g["wins"], rupees(g["pnl"], signed=True),
                          g["streak"], guard["losses"]))
        elif not start:
            done = [f for f in recent if f["status"] in CLOSED]
            if done:
                out.append("Finished: %d trade%s, %d won, total %s after costs."
                           % (len(done), "" if len(done) == 1 else "s", sum(1 for f in done if f["pnl"] > 0),
                              rupees(sum(f["pnl"] for f in done), signed=True)))
    else:
        out.append("The model assumes every order was placed and no order was skipped by the news check. Your own "
                   "journal of what you really did is the record that counts.")
    if datetime.date.fromisoformat(trade_day).year not in CALENDAR_YEARS:
        out.append("The NSE holiday list covers %s only: check nseindia.com for %s." % (CALENDAR_YEARS[0], trade_day))
    out.append("Paper results from free daily bars: a real fill can be worse, and the order of a day's high and low is"
               " unknown. In backtests about 4 trades in 10 lost. Nothing was placed. Not financial advice.")
    doc = {"created_by": "trader-swing", "created_at": now.strftime("%Y-%m-%dT%H:%M:%S+05:30"), "rule": rule,
           "guard": dict(guard, state=g), "signal_day": last_day, "trade_day": trade_day, "per_order_inr": money,
           "slots": slots, "market": mkt, "no_order_reason": notes.get(last_day),
           "matched": [{"symbol": sym, "close": data[sym]["c"][i], "ret63": sc, "rsi2": data[sym]["rsi2"][i]}
                       for sc, sym, i in today],
           "orders": [{k: v for k, v in f.items() if k != "score"} for f in orders]}
    if a.json:
        print(json.dumps(doc, indent=1, ensure_ascii=False))
    else:
        print("\n".join(out))
    if not a.no_write and mode == "scan":
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        if not a.json:
            print("Wrote %s." % a.out)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Swing trades, 2 to 3 day holds (trader-swing).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("fetch", help="download daily bars for the universe")
    p.add_argument("--universe", default="trader/universe.txt")
    p.add_argument("--data", required=True)
    p.add_argument("--range", default="10y")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("backtest", help="test every setup and exit rule, train vs test")
    p.add_argument("--data", required=True)
    p.add_argument("--setup", choices=list(SETUPS))
    p.add_argument("--target", type=float)
    p.add_argument("--stop", type=float)
    p.add_argument("--hold", type=int, help="with --target/--stop: test this one exit rule only")
    p.add_argument("--max-gap", type=float, help="skip a trade whose open is more than this %% above the signal close")
    p.add_argument("--entry", choices=["open", "close", "limit", "atr"], default="open")
    p.add_argument("--limit", type=float, help="--entry limit: percent under the signal close; --entry atr: ATRs under it")
    p.add_argument("--max-wick", type=float, default=0.0, help="bad-tick check: ignore fills whose low is this fraction under open and close")
    p.add_argument("--exit-open", action="store_true", help="sell the open after the hold, not the last close")
    p.add_argument("--split", default=SPLIT_DATE)
    p.add_argument("--until", help="ignore bars after this date (YYYY-MM-DD)")
    p.add_argument("--cost-pct", type=float, default=COST_PCT)
    p.add_argument("--start", type=float, default=10000.0)
    p.add_argument("--regime", action="store_true", help="only when the NIFTY 50 is above its 200-day average")
    p.add_argument("--grid", action="store_true", help="print every exit rule on the train part")
    p.add_argument("--years", action="store_true")
    p.add_argument("--account", action="store_true")
    for name, hlp in (("scan", "after the close: the next session's order"),
                      ("track", "how the recent orders and open positions stand"),
                      ("review", "the model portfolio against what the backtest showed")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--universe", default="trader/universe.txt")
        p.add_argument("--config", default="trader/config.json")
        p.add_argument("--budget", type=float)
        p.add_argument("--offline", metavar="DIR", help="saved daily bars (swing.py fetch) instead of Yahoo")
        p.add_argument("--now", help='pretend it is this IST time, e.g. "2026-11-25 16:20"')
        p.add_argument("--days", type=int, default=20 if name == "review" else 12,
                       help="sessions of orders to list (the model runs from swing_start when the config has one)")
        p.add_argument("--show", type=int, default=8)
        p.add_argument("--out", default="trader/swing.json")
        p.add_argument("--no-write", action="store_true")
        p.add_argument("--json", action="store_true")
        if name == "track":
            p.add_argument("--live", action="store_true", help="include today's unfinished bar")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "scan":
            return cmd_scan(a)
        if a.cmd in ("track", "review"):
            return cmd_scan(a, mode=a.cmd)
        if a.cmd == "fetch":
            return cmd_fetch(a)
        if a.cmd == "backtest":
            return cmd_backtest(a)
        ap.print_help()
        return 1
    except SwingError as e:
        print("swing.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
