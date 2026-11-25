#!/usr/bin/env python3
"""Pick of the day for trader-pick: reads the charts of the 3 to 5 stocks you name and says which one,
if any, is worth an order for a 3 to 5 day swing. Standard library only (it loads ../trader-swing/swing.py).

    python3 pick.py pick RELIANCE TCS INFY            # after 3:45 PM IST: chart reading, the pick or NO TRADE
    python3 pick.py pick RELIANCE TCS --no-scan       # skip the list of setups in the whole universe
    python3 pick.py follow                            # how the picks in trader/picks.json stand
    python3 pick.py follow EMCURE --signal-day 2026-11-23

WHAT IT READS ON EACH CHART (daily bars): the trend (20, 50 and 200-day averages, the 50-day
slope, distance from the 52-week high), momentum (1 week, 1 month, 3 months, against the NIFTY 50,
RSI), the pattern (pullback, breakout, flag, tight range, extended, falling), the last candle and
its volume, and the levels (support, resistance, the usual daily move).

WHAT DECIDES (and what does not). Every signal above was tested on 495 NIFTY 500 stocks, daily bars
Nov 2016 to Nov 2025: buy the next open, sell the 5th close, after 0.33% costs, against an ordinary
day. Almost none of them moved the result:
    20-day breakout on high volume     0.2% WORSE than an ordinary day, in both halves of the data
    above the 50 or 200-day average    +0.05%: no help by itself
    hammer, bullish engulfing          nothing, or slightly worse
    volume surge, 3 up days, RSI(2)>90 nothing, or slightly worse
    strong stock + a short dip         +0.64% better, in both halves: the one that held up
So the chart reading is shown in full, but only one picture earns an order:

  GRADE A  above the 50-day average, up more than 20% in 3 months, RSI(2) under 15 (a 1 to 2 day dip),
           and the NIFTY 50 above its 200-day average.
  GRADE B  the same shape, weaker (up more than 10%, RSI(2) under 25). WATCH only: it averaged about
           +0.5% a trade before 2025 and nothing in the last year.
  anything else: NO ORDER, with what would have to change.

THE ORDER for a grade A stock:
  entry   a LIMIT BUY 2% under today's close, good for the next session only (it fills about 1 time
          in 3). Buying the open instead always fills but earned a third as much.
  target  2 x the stock's 14-day ATR above the buy price (its own usual move, so it is reachable),
          never under 4% and never over 8%
  stop    4 x ATR under the buy price, never closer than 8% and never wider than 14%. Stops closer
          than that lost money in every test; the 14% cap keeps one loss near Rs 1,000 on Rs 7,500.
  time    sell at the close of the 5th session if neither was hit.

WHAT THE TEST SAID about that order (grade A, after 0.33% costs, one trade):
    2017 to 2022 (used to choose)            2,134 trades  60% won  average +1.32%
    2023 to Nov 2025 (not used to choose)    1,832 trades  57% won  average +0.98%
    Nov 2025 to Nov 2026 (looked at last)       48 trades  50% won  average +0.55%
Winners average about +5.2%, losers about -4.5%. The last year had few trades (the market filter
was on for most of it) and is too small a sample to lean on either way. About 4 trades in 10 lose. No level is certain:
the target is the level reached first in a little under half of the filled trades.

The stocks tested are TODAY's index members (survivors), which flatters the numbers. Daily bars do
not show the order of a day's high and low: a bar touching both counts as the stop. Past results do
not predict future results. Education and tooling, not financial advice. Nothing is placed.
"""

import argparse
import datetime
import importlib.util
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_swing():
    path = os.path.join(HERE, "..", "trader-swing", "swing.py")
    if not os.path.isfile(path):
        sys.exit("pick.py needs trader-swing/swing.py next to the trader-pick folder (not found at %s)" % path)
    spec = importlib.util.spec_from_file_location("trader_swing_lib", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sw = _load_swing()
SwingError, rupees, wd = sw.SwingError, sw.rupees, sw.wd

RULE = {"limit": 2.0, "target_atr": 2.0, "target_range": (4.0, 8.0), "stop_atr": 4.0, "stop_range": (8.0, 14.0),
        "hold": 5, "market_filter": True}
ODDS = {"win": 57, "lose": 43, "avg": 1.0, "avg_win": 5.2, "avg_loss": 4.5, "fill": 35}   # the test, grade A
JOURNAL = "trader/picks.json"


# ---------------------------------------------------------------- the grade and the order

def grade(S, i):
    """("A" | "B" | None, 3-month gain, RSI(2)) at bar i. See the docstring."""
    c = S["c"]
    if i < 63 or S["sma50"][i] is None or S["rsi2"][i] is None:
        return None, None, None
    mom, r = c[i] / c[i - 63] - 1.0, S["rsi2"][i]
    if c[i] > S["sma50"][i]:
        if mom > 0.20 and r < 15:
            return "A", mom, r
        if mom > 0.10 and r < 25:
            return "B", mom, r
    return None, mom, r


def levels(S, i):
    """The order's percentages for bar i: the limit, and the target and stop from the 14-day ATR."""
    atr_pct = S["atr"][i] / S["c"][i] * 100.0
    clamp = lambda x, lo_hi: min(lo_hi[1], max(lo_hi[0], x))
    return {"limit": RULE["limit"], "target": clamp(RULE["target_atr"] * atr_pct, RULE["target_range"]),
            "stop": clamp(RULE["stop_atr"] * atr_pct, RULE["stop_range"]), "hold": RULE["hold"], "atr_pct": atr_pct}


def order(S, i, money):
    """The order from bar i's close: prices on the tick, whole shares within `money`."""
    lv = levels(S, i)
    lim = sw.tick_down(S["c"][i] * (1 - lv["limit"] / 100.0))
    qty = int(money // lim)
    return dict(lv, limit_price=lim, target_price=sw.tick_down(lim * (1 + lv["target"] / 100.0)),
                stop_price=sw.tick_down(lim * (1 - lv["stop"] / 100.0)), qty=qty, cost=qty * lim,
                loss_at_stop=qty * lim * lv["stop"] / 100.0,
                costs=qty * lim * sw.COST_PCT / 100.0 + sw.COST_FIXED)


def history(S, upto, regime):
    """This stock's own past: every earlier grade A day, the same order, followed to its exit."""
    out = {"signals": 0, "filled": 0, "won": 0, "target": 0, "stop": 0, "time": 0, "net": []}
    for i in range(sw.MIN_BARS, upto):
        if not sw.tradable(S, i) or (regime is not None and not regime.get(S["d"][i], False)):
            continue
        if grade(S, i)[0] != "A":
            continue
        out["signals"] += 1
        lv = levels(S, i)
        t = sw.trade(S, i, lv["target"], lv["stop"], lv["hold"], entry_mode="limit", limit=lv["limit"])
        if t is None:
            continue
        net = t[0] - sw.COST_PCT
        out["filled"] += 1
        out["won"] += net > 0
        out[t[1]] += 1
        out["net"].append(net)
    out["avg"] = sum(out["net"]) / len(out["net"]) if out["net"] else None
    return out


# ---------------------------------------------------------------- the chart reading

def pct(a, b):
    return (a / b - 1.0) * 100.0


def read_chart(S, i, N=None, ni=None):
    """Facts and plain sentences about bar i: trend, momentum, pattern, candle and volume, levels."""
    o, h, l, c, v = S["o"], S["h"], S["l"], S["c"], S["v"]
    s20, s50, s200 = S["sma20"][i], S["sma50"][i], S["sma200"][i]
    hi250, hi20, lo20 = max(h[max(0, i - 249):i + 1]), max(h[i - 19:i + 1]), min(l[i - 19:i + 1])
    chi20_prev = max(c[i - 20:i])
    slope50 = pct(s50, S["sma50"][i - 20])
    atr_pct = S["atr"][i] / c[i] * 100.0
    rng = h[i] - l[i]
    ibs = (c[i] - l[i]) / rng if rng > 0 else 0.5
    day = pct(c[i], c[i - 1])
    vol_x = v[i] / S["vavg"][i - 1] if S["vavg"][i - 1] else None
    f = {"close": c[i], "sma20": s20, "sma50": s50, "sma200": s200, "slope50": slope50, "from_52w_high": pct(c[i], hi250),
         "ret5": pct(c[i], c[i - 5]), "ret20": pct(c[i], c[i - 20]), "ret63": pct(c[i], c[i - 63]),
         "rsi14": S["rsi14"][i], "rsi2": S["rsi2"][i], "atr_pct": atr_pct, "day_change": day, "volume_x": vol_x,
         "support": [lo20, s50], "resistance": [hi20, hi250], "streak_down": S["streak"][i]}
    if N is not None and ni is not None and ni >= 63:
        f["vs_nifty63"] = f["ret63"] - pct(N["c"][ni], N["c"][ni - 63])

    if c[i] > s20 > s50 > s200 and slope50 > 2:
        trend = "STRONG UPTREND: price above its 20, 50 and 200-day averages, all in order, the 50-day rising"
    elif c[i] > s50 > s200:
        trend = "UPTREND: price above its 50-day average, and the 50-day above the 200-day"
    elif c[i] < s50 < s200:
        trend = "DOWNTREND: price under its 50-day average, and the 50-day under the 200-day"
    elif abs(pct(c[i], s50)) < 3 and abs(slope50) < 2:
        trend = "SIDEWAYS: price within 3% of a flat 50-day average"
    elif c[i] > s50 and c[i] > s200:
        trend = "RECOVERING: price back above its 50 and 200-day averages, but the 50-day is still under the 200-day"
    elif c[i] > s200:
        trend = "PULLING BACK: under its 50-day average but still above the 200-day; a deeper dip or a turn down"
    elif c[i] > s50:
        trend = "BOUNCE in a weak chart: above the 50-day average but under the 200-day"
    else:
        trend = "BREAKING DOWN: under both its 50 and 200-day averages"
    f["trend"] = trend.split(":")[0]

    pats = []
    up3 = c[i] > c[i - 1] > c[i - 2] > c[i - 3]
    if c[i] > s50 and f["ret63"] > 10 and S["rsi2"][i] < 25:
        pats.append("PULLBACK in a rising stock (%d lower close%s, RSI(2) %.0f): the one picture that tested well"
                    % (S["streak"][i], "" if S["streak"][i] == 1 else "s", S["rsi2"][i]))
    if c[i] > chi20_prev:
        pats.append("BREAKOUT to a 20-day closing high%s: in the test, buying the day after a breakout did slightly "
                    "WORSE than an ordinary day" % (" on %.1fx volume" % vol_x if vol_x and vol_x > 1.5 else ""))
    if c[i] > s50 and pct(c[i - 5], c[i - 15]) > 10 and (max(c[i - 4:i + 1]) - min(c[i - 4:i + 1])) / c[i] < 0.05:
        pats.append("BULL FLAG (a 10% run, then 5 tight closes): a small edge in the test, not enough alone")
    if rng == min(h[k] - l[k] for k in range(i - 6, i + 1)):
        pats.append("TIGHT DAY (narrowest range in 7 sessions): no edge in the test")
    if S["rsi2"][i] > 90 or (up3 and f["ret5"] > 8):
        pats.append("EXTENDED (RSI(2) %.0f, %+.0f%% in a week): buying here did slightly worse than an ordinary day"
                    % (S["rsi2"][i], f["ret5"]))
    if c[i] < s50 and f["ret5"] < -5:
        pats.append("FALLING under its 50-day average (%+.0f%% in a week): dips in weak stocks did not test well" % f["ret5"])
    if not pats:
        pats.append("no pattern worth a name: an ordinary day on this chart")
    f["patterns"] = [p.split(" ")[0].strip(":") for p in pats]

    body, lw = abs(c[i] - o[i]), min(o[i], c[i]) - l[i]
    candle = "closed %s its range" % ("near the top of" if ibs > 0.8 else "near the bottom of" if ibs < 0.2 else "in the middle of")
    if rng > 0 and lw > 2 * body and ibs > 0.6:
        candle += ", with a long lower wick (a hammer: no edge in the test)"
    if o[i] > h[i - 1]:
        candle += ", after a gap up"
    elif o[i] < l[i - 1]:
        candle += ", after a gap down"
    vol = ("%.1fx its 20-day average" % vol_x) if vol_x else "unknown"

    lines = [
        "Trend     %s. 50-day slope %+.1f%% in a month; %.1f%% under the 52-week high." % (trend, slope50, -f["from_52w_high"]),
        "Momentum  1 week %+.1f%%, 1 month %+.1f%%, 3 months %+.1f%%%s. RSI(14) %.0f, RSI(2) %.0f."
        % (f["ret5"], f["ret20"], f["ret63"],
           (" (%+.1f%% against the NIFTY 50)" % f["vs_nifty63"]) if "vs_nifty63" in f else "", f["rsi14"], f["rsi2"]),
        "Pattern   " + ("\n          ".join(pats)) + ".",
        "Today     %+.1f%%, %s; volume %s." % (day, candle, vol),
        "Levels    support %s (20-day low) and %s (50-day average); resistance %s (20-day high)%s. Usual daily move %.1f%%."
        % (rupees(lo20), rupees(s50), rupees(hi20),
           "" if hi250 <= hi20 * 1.001 else " and %s (52-week high)" % rupees(hi250), atr_pct),
    ]
    return f, lines


def what_is_missing(S, i, g, mom, r, market_ok):
    """Why there is no order, in the order the rule checks."""
    c = S["c"]
    if not sw.tradable(S, i):
        return "not tradable by the rule (too little trading, under Rs 20, a data error, or under 210 sessions of history)"
    if not market_ok:
        return "the NIFTY 50 is under its 200-day average: the market filter stops every order"
    if g == "B":
        return ("close, but grade B: up %.0f%% in 3 months with RSI(2) %.0f. Grade A needs more than 20%% and RSI(2) under 15"
                % (100 * mom, r))
    if c[i] <= S["sma50"][i]:
        return "it is under its 50-day average (%s): the rule only buys dips in stocks above it" % rupees(S["sma50"][i])
    if mom <= 0.10:
        return "not strong enough: %+.0f%% in 3 months (the rule wants more than 20%%)" % (100 * mom)
    if mom <= 0.20:
        return "up %.0f%% in 3 months, short of the 20%% the rule wants, and no dip (RSI(2) %.0f)" % (100 * mom, r)
    return ("strong enough (+%.0f%% in 3 months) but NO DIP yet: RSI(2) is %.0f and the rule wants under 15. "
            "One or two lower closes would make it a setup" % (100 * mom, r))


# ---------------------------------------------------------------- commands

def norm(sym):
    s = sym.strip().upper().rstrip(",")
    return s if s.endswith(".NS") or s.startswith("^") else s + ".NS"


def prepared(doc, sym, upto):
    S = sw.prepare(sw.series_from_chart(doc, sym, upto))
    S["ix"] = {d: i for i, d in enumerate(S["d"])}
    return S


def load(symbols, now, rng="10y", offline=None, keep_today=False):
    last = sw.last_complete_day(now)
    upto = now.date().isoformat() if keep_today else last.isoformat()
    data, failed = {}, []
    if offline:
        allv = sw.load_folder(offline, upto)
        for s in symbols + ["^NSEI"]:
            if s in allv:
                S = sw.prepare(allv[s])
                S["ix"] = {d: i for i, d in enumerate(S["d"])}
                data[s] = S
            elif s != "^NSEI":
                failed.append(s)
    else:
        raw = sw.fetch_all(symbols + ["^NSEI"], rng)
        for s in symbols + ["^NSEI"]:
            try:
                data[s] = prepared(raw[s], s, upto)
            except (KeyError, SwingError):
                if s != "^NSEI":
                    failed.append(s)
    return data, failed, last


def order_block(sym, S, i, od, trade_day, exit_by, n=""):
    lv = od
    return [
        "%s%s  closed %s" % (n, sym, rupees(S["c"][i])),
        "   ENTRY   BUY LIMIT %s (2%% under the close), %d share%s = %s. Delivery (CNC). Good for %s only: cancel it if it"
        " has not filled by 3:30 PM. It fills about 1 time in 3." % (rupees(lv["limit_price"]), lv["qty"],
                                                                   "" if lv["qty"] == 1 else "s", rupees(lv["cost"]), wd(trade_day)),
        "   TARGET  SELL LIMIT %s (+%.1f%%; its usual daily move is %.1f%%)." % (rupees(lv["target_price"]), lv["target"],
                                                                              lv["atr_pct"]),
        "   STOP    STOP-LOSS %s (-%.1f%%, a safety stop: closer stops lost money in the test). Place both as GTT orders"
        " once the buy fills." % (rupees(lv["stop_price"]), lv["stop"]),
        "   TIME    still open on %s? Sell at market by 3:20 PM (day 5)." % wd(exit_by),
        "   MONEY   loss at the stop about %s; costs about %s a round trip. If it fills lower at the open, set target"
        " and stop from your real buy price." % (rupees(lv["loss_at_stop"]), rupees(lv["costs"])),
    ]


def cmd_pick(a):
    now = sw.parse_now(a.now)
    cfg = sw.load_config(a.config)
    money, _ = sw.per_order(dict(cfg, swing_slots=1), a.budget)
    syms = []
    for s in a.symbols:
        for part in s.replace(",", " ").split():
            if norm(part) not in syms:
                syms.append(norm(part))
    if not syms:
        raise SwingError("name the stocks: pick.py pick RELIANCE TCS INFY")
    data, failed, last = load(syms, now, offline=a.offline)
    last_day = last.isoformat()
    N = data.get("^NSEI")
    ni = N["ix"].get(last_day) if N else None
    mkt = sw.market_line(data, last_day) if N else None
    market_ok = not (mkt and mkt["below200"])
    regime = sw.market_ok(N) if N else None
    trade_day = sw.next_session(last).isoformat()
    exit_by = sw.next_session(datetime.date.fromisoformat(trade_day), RULE["hold"] - 1).isoformat()
    out = ["Pick of the day, %s IST. Daily bars through %s. Your stocks: %s."
           % (now.strftime("%a %Y-%m-%d %H:%M"), wd(last_day), ", ".join(s.replace(".NS", "") for s in syms))]
    out.append(("NIFTY 50 closed %s (%+.2f%% on the day), %s its 200-day average."
                % ("{:,.2f}".format(mkt["close"]), mkt["change"], "BELOW" if mkt["below200"] else "above")) if mkt
               else "NIFTY 50: no data, so the market filter was NOT checked.")
    for s in failed:
        out.append("%s: no chart from Yahoo. Check the NSE symbol (for example M&M, BAJAJ-AUTO)." % s.replace(".NS", ""))
    rows, doc_rows = [], []
    for sym in syms:
        S = data.get(sym)
        if S is None:
            continue
        i = S["ix"].get(last_day)
        out.append("")
        if i is None or i < 260:
            out.append("%s: %s. No reading." % (sym, "no bar for %s yet" % wd(last_day) if i is None
                                                 else "under 260 sessions of history"))
            continue
        g, mom, r = grade(S, i)
        ok = sw.tradable(S, i)
        facts, lines = read_chart(S, i, N, ni)
        is_a = g == "A" and ok and market_ok
        verdict = ("GRADE A: the tested setup" if is_a else
                   "WATCH (grade B)" if g == "B" and ok and market_ok else "NO ORDER")
        out.append("%s  %s  ->  %s" % (sym, rupees(S["c"][i]), verdict))
        out += ["  " + ln.replace("\n", "\n  ") for ln in lines]
        od = order(S, i, money) if is_a else None
        hist = history(S, i, regime)
        if hist["filled"]:
            out.append("  History   on this stock the setup came up %d times since %s; the order filled %d of them: %d won, "
                       "average %+.2f%% after costs (target first %d, stop %d, time exit %d)."
                       % (hist["signals"], S["d"][0][:4], hist["filled"], hist["won"], hist["avg"], hist["target"],
                          hist["stop"], hist["time"]))
        else:
            out.append("  History   the setup has %s on this stock since %s."
                       % ("never filled" if hist["signals"] else "never come up", S["d"][0][:4]))
        if not is_a:
            out.append("  Why not   " + what_is_missing(S, i, g, mom, r, market_ok) + ".")
        elif od["qty"] < 1:
            out.append("  Why not   one share at %s costs more than the %s for one order." % (rupees(od["limit_price"]), rupees(money)))
            is_a = False
        rows.append((is_a, mom or 0, sym, S, i, od))
        doc_rows.append({"symbol": sym, "grade": g if ok else None, "verdict": verdict, "facts": facts,
                         "history": {k: v for k, v in hist.items() if k != "net"}, "order": od})
    best = sorted((r for r in rows if r[0]), key=lambda r: -r[1])
    out.append("")
    pick = None
    if best:
        _, mom, sym, S, i, od = best[0]
        pick = {"symbol": sym, "signal_day": last_day, "trade_day": trade_day, "exit_by": exit_by, "close": S["c"][i], **od}
        out.append("THE PICK for %s: %s%s" % (wd(trade_day), sym,
                                             " (the strongest of %d grade A stocks)" % len(best) if len(best) > 1 else ""))
        out += order_block(sym, S, i, od, trade_day, exit_by)[1:]
        acts = []
        if not a.offline:
            try:
                acts = sw.actions_from_chart(sw.fetch_chart(sym, "3mo", events=True), sw.session_days(last, 4)[0])
            except SwingError:
                acts = ["could not read corporate actions from Yahoo: check them by hand"]
        fl = sw.data_flags(S, i, mkt, acts)
        pick["flags"] = fl["flags"]
        for x in fl["flags"]:
            out.append("   CHECK   " + x)
        out.append("   ODDS    in the test about %d trades in 100 like this won and %d lost; winners averaged +%.1f%%, losers"
                   " -%.1f%%. No level is certain." % (ODDS["win"], ODDS["lose"], ODDS["avg_win"], ODDS["avg_loss"]))
        out.append("BEFORE YOU PLACE IT: run the news check in trader-swing/NEWS.md for %s over the 5-session hold"
                   " (results dates, corporate actions, fraud or regulatory news, market events)." % sym)
    else:
        out.append("NO TRADE for %s: none of your stocks is a grade A setup today. That is the normal answer on most days."
                   % wd(trade_day))
    others = []
    if not a.no_scan and not a.offline:
        try:
            uni = [s for s in sw.read_universe(a.universe) if s not in syms]
            raw = sw.fetch_all(uni, "2y")
            for s, d in raw.items():
                try:
                    U = prepared(d, s, last_day)
                except SwingError:
                    continue
                j = U["ix"].get(last_day)
                if j is not None and sw.tradable(U, j) and grade(U, j)[0] == "A":
                    od = order(U, j, money)
                    if od["qty"] >= 1:
                        others.append((grade(U, j)[1], s, U["c"][j], od["limit_price"]))
            others.sort(reverse=True)
            if not market_ok:
                out.append("NIFTY 500 scan: the market filter is on, so no stock is a setup today.")
            elif others:
                out.append("Also grade A today in the NIFTY 500 (%d, strongest first; name any of them tomorrow for a full reading): %s"
                           % (len(others), ", ".join("%s %s (limit %s)" % (s.replace(".NS", ""), rupees(c_), rupees(lp))
                                                     for _, s, c_, lp in others[:a.show])))
            else:
                out.append("NIFTY 500 scan: no other stock is a grade A setup today either.")
        except SwingError as e:
            out.append("NIFTY 500 scan skipped: %s" % e)
    out.append("A chart reading is not a forecast. About 4 trades in 10 lose. Nothing was placed. Not financial advice.")
    doc = {"created_by": "trader-pick", "created_at": now.strftime("%Y-%m-%dT%H:%M:%S+05:30"), "rule": RULE,
           "signal_day": last_day, "trade_day": trade_day, "per_order_inr": money, "market": mkt, "stocks": doc_rows,
           "pick": pick, "also_grade_a": [{"symbol": s, "close": c_, "limit": lp} for _, s, c_, lp in others]}
    print(json.dumps(doc, indent=1, ensure_ascii=False) if a.json else "\n".join(out))
    if not a.no_write:
        os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, ensure_ascii=False)
        if pick:
            j = {"picks": []}
            if os.path.isfile(a.journal):
                with open(a.journal, encoding="utf-8") as fh:
                    j = json.load(fh)
            j["picks"] = [p for p in j.get("picks", []) if not (p["symbol"] == pick["symbol"] and p["signal_day"] == last_day)]
            j["picks"].append({k: pick[k] for k in ("symbol", "signal_day", "trade_day", "exit_by", "limit_price", "qty")})
            with open(a.journal, "w", encoding="utf-8") as fh:
                json.dump(j, fh, indent=1)
    return 0


def follow_one(S, sym, signal_day, qty, live_day):
    i = S["ix"].get(signal_day)
    if i is None:
        return "%s: no bar for the signal day %s" % (sym, signal_day), None
    lv = levels(S, i)
    f = sw.follow(S, i, {"limit": lv["limit"], "target": lv["target"], "stop": lv["stop"], "hold": lv["hold"]}, live_day)
    trade_day = sw.next_session(datetime.date.fromisoformat(signal_day)).isoformat()
    exit_by = sw.next_session(datetime.date.fromisoformat(trade_day), lv["hold"] - 1).isoformat()
    q = qty or 1
    f.update(symbol=sym, signal_day=signal_day, trade_day=trade_day, qty=q, exit_by=exit_by)
    if f["status"] in ("open",) + sw.CLOSED:
        f["net_pct"] = f["gross"] - sw.COST_PCT
        f["pnl"] = q * f["entry"] * f["net_pct"] / 100.0 - sw.COST_FIXED
    words = dict(sw.STATUS_WORDS, time="TIME EXIT at the day-5 close")
    old = sw.STATUS_WORDS
    sw.STATUS_WORDS = words
    try:
        line = sw.status_line(f, {"hold": lv["hold"], "target": lv["target"], "stop": lv["stop"]})
    finally:
        sw.STATUS_WORDS = old
    return line, f


def cmd_follow(a):
    now = sw.parse_now(a.now)
    todo = []
    if a.symbol:
        if not a.signal_day:
            raise SwingError("follow SYMBOL needs --signal-day YYYY-MM-DD (the day of the pick, not the buy day)")
        todo.append((norm(a.symbol), a.signal_day, a.qty))
    else:
        if not os.path.isfile(a.journal):
            raise SwingError("no picks yet at %s: run pick.py pick first, or name a symbol and --signal-day" % a.journal)
        with open(a.journal, encoding="utf-8") as fh:
            for p in json.load(fh).get("picks", [])[-a.last:]:
                todo.append((p["symbol"], p["signal_day"], p.get("qty")))
    live = (now.hour, now.minute) < sw.CLOSE_READY and sw.is_session(now.date())
    data, failed, last = load(sorted({t[0] for t in todo}), now, rng="1y", offline=a.offline, keep_today=live)
    print("Pick tracker, %s IST%s." % (now.strftime("%a %Y-%m-%d %H:%M"), " (today's bar is not final)" if live else ""))
    done = []
    for sym, day, qty in todo:
        if sym not in data:
            print("  %s: no chart from Yahoo" % sym)
            continue
        line, f = follow_one(data[sym], sym, day, qty, now.date().isoformat() if live else None)
        print("  " + line.replace("\n", "\n  "))
        if f and f["status"] in sw.CLOSED:
            done.append(f)
    if done:
        print("Finished: %d trade%s, %d won, total %s after costs."
              % (len(done), "" if len(done) == 1 else "s", sum(1 for f in done if f["pnl"] > 0),
                 rupees(sum(f["pnl"] for f in done), signed=True)))
    print("Paper results from free daily bars: your broker's fills are the truth. Not financial advice.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pick of the day from the stocks you name (trader-pick).")
    sub = ap.add_subparsers(dest="cmd")
    p = sub.add_parser("pick", help="read the charts and name the pick, or NO TRADE")
    p.add_argument("symbols", nargs="+", help="3 to 5 NSE symbols, e.g. RELIANCE TCS INFY")
    p.add_argument("--no-scan", action="store_true", help="skip the list of grade A stocks in the universe")
    p.add_argument("--universe", default="trader/universe.txt")
    p.add_argument("--show", type=int, default=8)
    p.add_argument("--out", default="trader/pick.json")
    p.add_argument("--no-write", action="store_true")
    p.add_argument("--json", action="store_true")
    f = sub.add_parser("follow", help="how the picks stand")
    f.add_argument("symbol", nargs="?")
    f.add_argument("--signal-day")
    f.add_argument("--qty", type=int)
    f.add_argument("--last", type=int, default=10, help="how many journal picks to show")
    for q in (p, f):
        q.add_argument("--config", default="trader/config.json")
        q.add_argument("--budget", type=float)
        q.add_argument("--journal", default=JOURNAL)
        q.add_argument("--offline", metavar="DIR", help="saved daily bars instead of Yahoo")
        q.add_argument("--now", help='pretend it is this IST time, e.g. "2026-11-25 19:00"')
    a = ap.parse_args(argv)
    try:
        if a.cmd == "pick":
            return cmd_pick(a)
        if a.cmd == "follow":
            return cmd_follow(a)
        ap.print_help()
        return 1
    except SwingError as e:
        print("pick.py: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
