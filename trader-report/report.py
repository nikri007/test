#!/usr/bin/env python3
"""End-of-day report for a day-trade plan: how did it end? Standard library only.

    python3 report.py                                  # trader/plan.json, qty from trader/orders.json
    python3 report.py --plan trader/plan.json --qty 13 --json
    python3 report.py --now "2026-11-18 15:40" --offline chart.json
    python3 report.py --write                          # also add it to trader/journal.json

It replays the plan on the plan day's real 5-minute bars, from the bar after the
entry bar to the plan's flat-by time (15:15 IST by default):

  stop     a bar's low reached the stop. Checked before the target in every bar,
           so a bar that touches both counts as the stop (the conservative call,
           the same rule as trader-timemachine). A bar that opens below the stop
           fills at its open (a gap goes past the stop).
  target   a bar's high reached the target. A bar that opens above it fills at
           its open.
  flat     neither by the flat-by time: out at the close of the last bar before
           it (the 15:10 bar's close for a 15:15 flat-by).
  open     the day is not over yet (it is before the flat-by time): the last
           close so far.

R = (exit - entry) / risk a share; with --qty (or the plan's order in
trader/orders.json) also the rupee result for those shares. Brokerage, STT and
the other charges are NOT included: the rupee figure is before costs. A paper
result is not a real fill: a real order can fill worse than the bar says.

Data: Yahoo's free chart JSON (unofficial, can lag), query2 then query1.
Times are India time (IST, UTC+5:30); --now "2026-11-18 15:40" pins the clock.
"""

import argparse
import datetime
import gzip
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
HOSTS = ("query2", "query1")
STEP = 300                       # 5-minute bars
OPEN_MIN = 9 * 60 + 15           # 9:15 IST
IST = datetime.timedelta(hours=5, minutes=30)
EPOCH = datetime.datetime(1970, 1, 1)


class ReportError(Exception):
    pass


def ist_of(ts):
    return EPOCH + datetime.timedelta(seconds=int(ts)) + IST


def parse_now(text):
    """-> naive IST. No offset means IST; ...Z or +hh:mm is absolute."""
    if not text:
        return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0, tzinfo=None) + IST
    t = text.strip().replace("Z", "+00:00")
    try:
        dt = datetime.datetime.fromisoformat(t)
    except ValueError:
        raise ReportError('--now wants an IST time like "2026-11-18 15:40" (or ...Z for UTC)')
    if dt.tzinfo is None:
        return dt
    return (dt - dt.utcoffset()).replace(tzinfo=None) + IST


def hhmm_min(text, what):
    try:
        h, m = str(text).strip().split(":")
        h, m = int(h), int(m)
        assert 0 <= h <= 23 and 0 <= m <= 59
    except (ValueError, AssertionError):
        raise ReportError("%s wants a time like 15:15, not %r" % (what, text))
    return h * 60 + m


def clock12(minutes):
    h, m = divmod(minutes, 60)
    return "%d:%02d %s" % (h % 12 or 12, m, "AM" if h < 12 else "PM")


def rupees(x):
    sign = "-" if x < 0 else "+" if x > 0 else ""
    return "%s₹%s" % (sign, "{:,.2f}".format(abs(x)))


def read_json(path, what):
    if not os.path.isfile(path):
        raise ReportError("no %s at %s" % (what, path))
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as fh:
        try:
            return json.load(fh)
        except ValueError as e:
            raise ReportError("%s is not valid JSON: %s" % (path, e))


def yahoo_symbol(sym):
    s = sym.upper()
    return s if s.endswith(".NS") else s.replace(".", "-")


def chart_range(day, today):
    back = (today - day).days
    if back <= 4:
        return "5d"
    if back <= 28:
        return "1mo"
    if back <= 58:
        return "60d"
    raise ReportError("Yahoo keeps 5-minute bars for about 60 days: %s is too far back" % day)


def fetch_chart(sym, rng):
    path = "/v8/finance/chart/%s?range=%s&interval=5m" % (urllib.parse.quote(yahoo_symbol(sym), safe=".-^&"), rng)
    err = None
    for host in HOSTS:
        req = urllib.request.Request("https://%s.finance.yahoo.com%s" % (host, path),
                                     headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            err = "HTTP %d" % e.code
            if e.code == 429:
                time.sleep(5)
        except (urllib.error.URLError, OSError, ValueError) as e:
            err = str(e)
    raise ReportError("could not fetch %s's 5-minute bars from Yahoo (%s)" % (sym, err))


def day_bars(doc, day, now_ist):
    """{slot: bar} of the plan day's complete, on-grid, priced 5-minute bars."""
    try:
        res = doc["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        raise ReportError("Yahoo sent no chart data")
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0] or {}
    out = {}
    for i, ts in enumerate(res.get("timestamp") or []):
        if ts is None or int(ts) % STEP:
            continue
        vals = [(q.get(k) or [None] * (i + 1))[i] if i < len(q.get(k) or []) else None
                for k in ("open", "high", "low", "close")]
        if None in vals:
            continue
        start = ist_of(ts)
        if start.date() != day or start + datetime.timedelta(seconds=STEP) > now_ist:
            continue
        mins = start.hour * 60 + start.minute - OPEN_MIN
        if mins < 0:
            continue
        o, h, l, c = vals
        out[mins // 5] = {"slot": mins // 5, "start": start.strftime("%H:%M"), "o": o, "h": h, "l": l, "c": c}
    return out


def qty_from_orders(path, sym):
    if not path or not os.path.isfile(path):
        return None
    try:
        doc = read_json(path, "orders")
    except ReportError:
        return None
    for o in doc.get("orders", []) if isinstance(doc, dict) else []:
        if str(o.get("symbol", "")).upper() == sym and o.get("side") == "buy":
            try:
                return int(float(o.get("qty")))
            except (TypeError, ValueError):
                return None
    return None


def evaluate(plan, bars, now_ist, qty=None):
    """Pure: the plan and {slot: bar} of its day -> the result dict."""
    sym = plan["symbol"].upper()
    if plan.get("side", "buy") != "buy":
        raise ReportError("the report handles long (buy) plans only")
    entry, stop, target = float(plan["entry"]), float(plan["stop"]), float(plan["target"])
    k = int(plan["entry_bar"])
    risk = entry - stop
    if risk <= 0:
        raise ReportError("the plan's stop %.2f is not below its entry %.2f" % (stop, entry))
    flat = plan.get("flat_by") or "15:15"
    flat_min = hhmm_min(flat, "flat_by")
    last = (flat_min - OPEN_MIN) // 5 - 1            # the last bar that ends by the flat-by time
    day = datetime.date.fromisoformat(plan["date"])
    over = now_ist >= datetime.datetime.combine(day, datetime.time(flat_min // 60, flat_min % 60))
    res = {"symbol": sym, "date": plan["date"], "entry": entry, "entry_time": plan.get("entry_time"),
           "stop": stop, "target": target, "risk_per_share": round(risk, 2), "flat_by": flat, "qty": qty,
           "outcome": None, "exit": None, "exit_time": None, "R": None, "rupees": None,
           "high_after": None, "low_after": None, "missing_bars": [], "bars_checked": 0}
    if k not in bars:
        raise ReportError("no complete entry bar (bar %d) for %s on %s in the data" % (k, sym, plan["date"]))
    hi = lo = None
    for i in range(k + 1, last + 1):
        b = bars.get(i)
        if b is None:
            if over or OPEN_MIN + 5 * (i + 1) <= now_ist.hour * 60 + now_ist.minute:
                res["missing_bars"].append(clock12(OPEN_MIN + 5 * i))
            continue
        res["bars_checked"] += 1
        hi = b["h"] if hi is None else max(hi, b["h"])
        lo = b["l"] if lo is None else min(lo, b["l"])
        end = clock12(OPEN_MIN + 5 * (i + 1))
        if b["l"] <= stop:
            res.update(outcome="stop", exit=min(stop, b["o"]), exit_time="%s bar (to %s)" % (clock12(OPEN_MIN + 5 * i), end))
            break
        if b["h"] >= target:
            res.update(outcome="target", exit=max(target, b["o"]), exit_time="%s bar (to %s)" % (clock12(OPEN_MIN + 5 * i), end))
            break
    res["high_after"], res["low_after"] = hi, lo
    if res["outcome"] is None:
        done = [bars[i] for i in range(k + 1, last + 1) if i in bars]
        if not done:
            res.update(outcome="open" if not over else "no-data")
            if over:
                raise ReportError("no bars after the entry for %s on %s" % (sym, plan["date"]))
            return res
        lb = done[-1]
        res.update(outcome="flat" if over else "open", exit=lb["c"],
                   exit_time="%s bar close (%s)" % (clock12(OPEN_MIN + 5 * lb["slot"]), clock12(OPEN_MIN + 5 * (lb["slot"] + 1))))
    res["exit"] = round(res["exit"], 2)
    res["R"] = round((res["exit"] - entry) / risk, 2)
    if qty:
        res["rupees"] = round((res["exit"] - entry) * qty, 2)
    return res


WORDS = {"stop": "STOP hit", "target": "TARGET hit", "flat": "neither: closed at the flat-by",
         "open": "STILL OPEN (the day is not over)", "no-data": "no data"}


def report(r):
    lines = ["%s %s: %s" % (r["symbol"], r["date"], WORDS.get(r["outcome"], r["outcome"]))]
    lines.append("  Plan   entry ₹%.2f at %s | stop ₹%.2f | target ₹%.2f | risk ₹%.2f a share"
                 % (r["entry"], r["entry_time"], r["stop"], r["target"], r["risk_per_share"]))
    if r["exit"] is not None:
        res = "  Result exit ₹%.2f (%s) = %+.2fR" % (r["exit"], r["exit_time"], r["R"])
        if r["rupees"] is not None:
            res += ", %s on %d shares before costs" % (rupees(r["rupees"]), r["qty"])
        lines.append(res)
    if r["high_after"] is not None:
        lines.append("  After the entry: high ₹%.2f, low ₹%.2f (to the exit)" % (r["high_after"], r["low_after"]))
    if r["missing_bars"]:
        lines.append("  Missing bars (no price from Yahoo): %s" % ", ".join(r["missing_bars"][:6]))
    return "\n".join(lines)


def write_journal(path, r):
    doc = {"trades": []}
    if os.path.isfile(path):
        doc = read_json(path, "journal")
    doc["trades"] = [t for t in doc.get("trades", []) if not (t.get("symbol") == r["symbol"] and t.get("date") == r["date"])]
    doc["trades"].append({k: r[k] for k in ("date", "symbol", "entry", "entry_time", "stop", "target", "qty",
                                             "outcome", "exit", "exit_time", "R", "rupees")})
    doc["trades"].sort(key=lambda t: (t["date"], t["symbol"]))
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1, ensure_ascii=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description="End-of-day result of a day-trade plan (trader-report).")
    ap.add_argument("--plan", default="trader/plan.json")
    ap.add_argument("--orders", default="trader/orders.json", help="qty for the plan's symbol (from trader-budget)")
    ap.add_argument("--qty", type=int, help="shares, instead of the orders file")
    ap.add_argument("--offline", metavar="FILE", help="a saved Yahoo chart JSON (.json or .json.gz)")
    ap.add_argument("--now", help='pretend it is this IST time, e.g. "2026-11-18 15:40"')
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", nargs="?", const="trader/journal.json", metavar="PATH",
                    help="add the result to a journal (default trader/journal.json)")
    a = ap.parse_args(argv)
    try:
        plan = read_json(a.plan, "plan")
        for k in ("symbol", "date", "entry", "stop", "target", "entry_bar"):
            if plan.get(k) is None:
                raise ReportError("the plan has no %s (make it with trader-exit)" % k)
        now = parse_now(a.now)
        day = datetime.date.fromisoformat(plan["date"])
        if day > now.date():
            raise ReportError("the plan is for %s, which has not happened yet" % day)
        doc = read_json(a.offline, "chart") if a.offline else fetch_chart(plan["symbol"], chart_range(day, now.date()))
        qty = a.qty if a.qty else qty_from_orders(a.orders, plan["symbol"].upper())
        r = evaluate(plan, day_bars(doc, day, now), now, qty)
    except ReportError as e:
        print("report.py: %s" % e, file=sys.stderr)
        return 1
    if a.write:
        write_journal(a.write, r)
    print(json.dumps(r, indent=1, ensure_ascii=False) if a.json else report(r))
    if not a.json:
        print("Paper result from Yahoo's 5-minute bars, before brokerage and taxes. A real order can fill worse.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
