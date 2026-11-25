---
name: trader-swing
description: >-
  Swing Trader. Finds 2 to 3 day swing trades on NSE stocks after the close and
  follows each one to its exit. One tested rule: a strong stock (up more than
  20% in 3 months, above its 50-day average) that has dipped for a day or two
  (RSI(2) under 15); a limit buy 3% under the close, good for the next session
  only; sell at +6%, at a 12% safety stop, or at the close of day 3. Sizes the
  order to your budget, writes trader/swing.json, tracks a model portfolio with
  no hindsight, and carries its own backtest (11 setups, 40 exit rules, train
  and test split, costs included) so every number can be re-run. Delivery
  (CNC), long only, daily bars from Yahoo. Use when the user says "swing
  trade", "find me a swing setup", "2 to 3 day trade", "what do I buy
  tomorrow", "evening scan", "how are my swing trades doing", "backtest the
  swing rule", or asks for a short-term trade that is not intraday.
argument-hint: "[scan | track | backtest]"
---

# trader-swing

The Swing Trader replaces the intraday chain (scanner, entry, exit, time
machine, budget, risk) with one evening routine. It does three things: finds
the stocks that match one tested rule at the close, writes the order for the
next session, and follows that order to its exit. It never places an order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/swing.py" scan                 # after 3:45 PM IST: the next session's order
python3 "${CLAUDE_SKILL_DIR}/swing.py" track                # the recent orders and open positions
python3 "${CLAUDE_SKILL_DIR}/swing.py" track --live         # during the session, with today's bar so far
python3 "${CLAUDE_SKILL_DIR}/swing.py" fetch --range 10y --data DIR
python3 "${CLAUDE_SKILL_DIR}/swing.py" backtest --data DIR  # every setup and exit rule, train vs test
```

Flags: `--budget`, `--config trader/config.json`, `--now "2026-11-25 16:20"`
(IST), `--offline DIR` (saved bars), `--days 12`, `--json`, `--no-write`.

## The rule

| step | what |
| --- | --- |
| Setup, at the close | up more than 20% over 63 sessions, close above the 50-day average, RSI(2) under 15 |
| Filter | 20-day average traded value at least Rs 10 crore, price at least Rs 20, 210 bars of history |
| Rank | strongest 3-month gain first; one order per free slot |
| Entry | limit buy 3% under the signal close, rounded down to Rs 0.05, good for the next session only |
| Exits | limit sell 6% above the buy price; safety stop 12% under it; else the close of day 3 (buy day = day 1) |
| Product | delivery (CNC), long only, no margin |

## Why this rule, and what the test said

`swing.py backtest` ran 11 setups (pullbacks, breakouts, flags, momentum),
40 exit rules and 4 ways to enter on 495 NIFTY 500 stocks, daily bars from
November 2016, after 0.33% costs a round trip. Rules were chosen on signals
before 2023 only.

| period | trades | won | average, one trade, after costs |
| --- | --- | --- | --- |
| 2017 to 2022 (used to choose) | 2,769 | 60% | +1.08% |
| 2023 to Nov 2025 (not used to choose) | 1,178 | 59% | +0.89% |
| Nov 2025 to Nov 2026 (looked at once, last) | 208 | 57% | +0.88% |

What did not work, on the same data:

- Buying the next open instead of a limit below the close: about 0% after
  costs for every setup, breakouts and flags included.
- A fixed +2% target: it wins about 3 trades in 4 and still earns less, because
  the losers are bigger than the winners.
- Tight stops (3 to 5%): they turned every setup into a loser.
- The same limit buy on any liquid stock, without the setup: nothing.

## What it cannot promise

- About 4 trades in 10 lose. 2018, 2022 and 2025 were flat or slightly
  negative years. One account holding one position is far noisier than the
  averages above: a run of five or six losers is normal.
- The stock list is today's index members, the ones that survived and grew.
  That flatters every number in the table.
- Daily bars do not show the order of a day's high and low. A bar that touches
  both counts as the stop; a target on the buy day is not counted; a limit
  fill needs the low 0.1% through the limit. A real fill can still be worse.
- Only about 1 order in 4 fills. No fill means no trade that day.
- Costs matter at small size: the depository charge on each sell (about
  Rs 15.34) is 0.2% of a Rs 7,500 position on top of the 0.33%.
- The 12% stop is a safety net, not a tight stop. With Rs 7,500 in one stock
  the loss at the stop is about Rs 900. Size the budget to that.

## The news check

The scan reads prices only. Before an order goes to the user, run the check in
`NEWS.md` (same folder) and put its verdict above the order: CLEAR, CAUTION or
SKIP. It looks at the scan's own `CHECK:` lines (a dividend or split in the
data, a fall of 7% or more, the NIFTY under its 200-day average), then the
company's news for the last 5 days (results or a board meeting inside the
3-session hold, corporate actions, fraud or regulatory news), then market
events inside the hold (Budget, RBI policy, election results). News can stop
or flag a trade. It can never add one, pick another stock, or change a price.
It was not part of the backtest.

## Files

| file | what |
| --- | --- |
| `trader/universe.txt` | the symbols to scan, one `SYMBOL.NS\|Name` a line |
| `trader/config.json` | `budget`, `cash_buffer_pct` (10), `max_position_pct` (75), `swing_slots` (1) |
| `trader/swing.json` | written by `scan`: the rule, the matches, the orders and their status |

## Steps

1. After 3:45 PM IST on a trading day: `swing.py scan`. Tell the user the
   counts (charts fetched, with today's bar, matched) and the order: symbol,
   limit price, shares, the +6% sell, the 12% stop, the last day.
2. Run the news check in `NEWS.md` on the order (and on each open position)
   and print its verdict. On SKIP there is no order that session.
3. The user places the limit buy themselves (after-market order, or before
   9:15 AM), for that one session. If it fills, they place the two exits as
   GTT orders. If it does not fill by 3:30 PM, it is cancelled.
4. Any time: `swing.py track` (or `--live` in the session) shows each recent
   order: not filled, open (day 1, 2 or 3), target, stop or time exit, with
   the result after costs. On day 3 remind them to sell by 3:20 PM.
5. The model portfolio assumes every order was placed. If the user skipped
   one, their own record is the truth, not the model's.

## Rules

- Say "matched the rule" and "order", never "buy this" or "it will go up".
- Give the win rate with the loss rate: about 6 in 10 won, about 4 in 10 lost.
- Never print a result without "after costs" or "before costs".
- Do not change the rule's numbers from the chat. A new rule is a new backtest.

## Safety

- Education and tooling, not financial advice. A match is a rules check, not a recommendation.
- Nothing here places an order. The user places every order themselves and says yes to each one.
- Paper trading first: follow the model portfolio for a month before any real order.
- Delivery only: no margin, no short selling, no options, no leverage.
