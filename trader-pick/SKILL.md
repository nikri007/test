---
name: trader-pick
description: >-
  Pick of the Day. The user names 3 to 5 NSE stocks in the evening; this reads
  each chart (trend, momentum, pattern, last candle and volume, support and
  resistance) and says which one, if any, is worth an order for a 3 to 5 day
  swing, with the entry price, the target, the stop-loss, the shares and the
  measured odds. Only one chart picture earns an order, because only one
  survived a 9-year test: a strong stock (up more than 20% in 3 months, above
  its 50-day average) after a 1 to 2 day dip. Everything else is NO TRADE,
  with what would have to change. Also lists today's other setups in the
  NIFTY 500 and follows each pick to its exit. Use when the user says "which
  of these should I buy", "best pick for tomorrow", "check these stocks",
  "read the chart of", "entry stop target for", "pick of the day", "is X a
  buy tomorrow", "how is my pick doing", or sends a short list of symbols in
  the evening.
argument-hint: "SYMBOL SYMBOL SYMBOL [SYMBOL SYMBOL]"
---

# trader-pick

The user brings the candidates; this skill reads the charts and gives one
honest verdict. Most evenings the verdict is NO TRADE. It never places an
order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It loads
`../trader-swing/swing.py`, so the two folders must sit side by side.

```bash
python3 "${CLAUDE_SKILL_DIR}/pick.py" pick RELIANCE TCS INFY   # after 3:45 PM IST
python3 "${CLAUDE_SKILL_DIR}/pick.py" pick SUNTV --no-scan     # without the NIFTY 500 list
python3 "${CLAUDE_SKILL_DIR}/pick.py" follow                   # the picks in trader/picks.json
python3 "${CLAUDE_SKILL_DIR}/pick.py" follow SUNTV --signal-day 2026-11-25 --qty 12
```

Flags: `--budget`, `--config trader/config.json`, `--now "2026-11-25 19:00"`
(IST), `--offline DIR`, `--json`, `--no-write`. Symbols are NSE symbols with
or without `.NS` (`M&M`, `BAJAJ-AUTO`).

## When to run it

Daily bars are final from 3:45 PM IST. Any time after that gives the same
answer, so run it when the user sends the list (they plan on 7 PM). The order
is for the next session. Run `follow` in the afternoon of each day a pick is
open.

## What it reads on each chart

| line | what |
| --- | --- |
| Trend | price against its 20, 50 and 200-day averages, the 50-day slope, distance from the 52-week high |
| Momentum | 1 week, 1 month, 3 months, 3 months against the NIFTY 50, RSI(14), RSI(2) |
| Pattern | pullback in a rising stock, 20-day breakout, bull flag, tight day, extended, falling |
| Today | the day's change, where it closed in its range, hammer, gap, volume against its 20-day average |
| Levels | support (20-day low, 50-day average), resistance (20-day and 52-week high), the usual daily move (ATR) |
| History | this stock's own past: how often the setup came up, filled, won |

## What decides, and what does not

Every signal was tested on 495 NIFTY 500 stocks, Nov 2016 to Nov 2025: buy
the next open, sell the 5th close, after 0.33% costs, against an ordinary day.

| signal | result against an ordinary day |
| --- | --- |
| 20-day breakout on high volume | about 0.2% worse, in both halves of the data |
| above the 50 or 200-day average, by itself | +0.05%: no help |
| hammer, bullish engulfing | nothing, or slightly worse |
| volume surge, three up days, RSI(2) over 90 | nothing, or slightly worse |
| strong stock plus a short dip | +0.64% better, in both halves |

So the reading is shown in full and one picture earns an order.

| verdict | when |
| --- | --- |
| GRADE A | above the 50-day average, up more than 20% in 3 months, RSI(2) under 15, liquid, and the NIFTY 50 above its 200-day average |
| WATCH (grade B) | the same shape, weaker: up more than 10%, RSI(2) under 25. No order: about +0.5% a trade before 2025, nothing in the last year |
| NO ORDER | anything else, with the reason ("no dip yet", "under its 50-day average", "market filter") |

With several grade A stocks, the pick is the one with the strongest 3-month
gain. One pick a day at most.

## The order

| part | rule |
| --- | --- |
| Entry | limit buy 2% under the close, good for the next session only. It fills about 1 time in 3 |
| Target | 2 x the 14-day ATR above the buy price, never under 4% or over 8% |
| Stop | 4 x ATR under the buy price, never closer than 8% or wider than 14% |
| Time | sell at the close of the 5th session |
| Size | whole shares within `pick_per_day_inr` in `trader/config.json` (Rs 10,000 for each day's pick) |

Why a limit and not the open: on the same setups, buying the open always
filled and averaged about +0.5 to +0.75% a trade; the limit 2% lower averaged
about +1.3%. Why the stop is wide: stops of 3 to 8% turned the test negative.

| period, grade A, this order, after costs | trades | won | average |
| --- | --- | --- | --- |
| 2017 to 2022 (used to choose) | 2,134 | 60% | +1.32% |
| 2023 to Nov 2025 (not used to choose) | 1,832 | 57% | +0.98% |
| Nov 2025 to Nov 2026 (looked at last) | 48 | 50% | +0.55% |

Winners average about +5.2%, losers about -4.5%.

## Steps

1. Run `pick.py pick` with the user's symbols.
2. Give the reading for each stock in a few plain lines, then the verdict.
3. If there is a PICK, run the news check in `../trader-swing/NEWS.md` on it,
   with a 5-session window, and any `CHECK` line the script printed. Put the
   verdict (CLEAR, CAUTION, SKIP) above the order. On SKIP there is no order;
   do not move to the next stock.
4. Give the order exactly as printed: entry, target, stop, last day, shares,
   loss at the stop, costs, and the odds line.
5. If there is no pick, say NO TRADE, say for each stock what is missing, and
   name the other grade A stocks the scan found, as stocks to read tomorrow,
   not as orders.
6. On later days run `pick.py follow` and report fill, day N of 5, target,
   stop or time exit, with the result after costs.

## Rules

- Never say a target or a profit is certain. Say the odds: about 57 in 100
  won and 43 lost in the test.
- Never turn a WATCH or NO ORDER into an order because the user wants a trade.
  No trade is a result.
- Never tighten the stop, raise the target or change the entry from the chat.
  A new rule is a new backtest.
- Rs 10,000 goes to each day's pick, so picks overlap: with a 5-session hold
  up to 5 can be open together, about Rs 50,000 in the market. Say the total
  in use when giving a new order, and warn if the pick is a stock already held.
- Say "matched the tested setup", never "will go up".

## What it cannot promise

- About 4 trades in 10 lose, and the loss at the stop can be up to Rs 1,400
  on a Rs 10,000 pick. Five open picks that all hit their stops in a market
  fall would lose about Rs 7,000.
- The last year had only 48 trades and a thinner edge. The stocks tested are
  today's index members, which flatters the numbers.
- Replayed as one small account over 9 years, a close cousin of this rule
  (see trader-swing) made less than simply holding a NIFTY index fund.
- Daily bars cannot show the order of a day's high and low; a real fill can
  be worse than the paper one.

## Safety

- Education and tooling, not financial advice. A grade is a rules check, not a recommendation.
- Nothing here places an order. The user places every order themselves and says yes to each one.
- Paper trading first. Delivery only: no margin, no short selling, no options, no leverage.
