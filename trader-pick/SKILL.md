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
python3 "${CLAUDE_SKILL_DIR}/pick.py" scan                     # rate every setup in the universe; ALERT at 7/10 or better
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

## The rating

A grade A setup is rated out of 10 by how hard the stock fell on the signal
day. The same order did better the deeper the dip, in every period (filled
trades, after costs):

| rating | fall on the signal day | trades | in profit | at the full target | average |
| --- | --- | --- | --- | --- | --- |
| 7/10 | 7% or more | 153 | 90% | 48% | +5.0% |
| 6/10 | 5 to 7% | 308 | 83% | 16% | +1.9% |
| 5/10 | 3 to 5% | 1,014 | 82% | 14% | +1.6% |
| 4/10 | under 3% | 2,533 | 79% | 7% | +0.7% |

A 7 is rare: about 2 or 3 a month across 495 stocks, mostly on days the
market sells off. A fall that sharp always has a reason, so the news check
matters most exactly when the rating is highest. The rating is the chart's
odds; it says nothing about the news. Nothing rates above 7.

`pick.py scan` rates every grade A stock in `trader/universe.txt` and prints
ALERT with the full order when one is rated 7 or better (`--min-rating`).

With several grade A stocks, the pick is the best rated, then the strongest
3-month gain. One pick a day at most.

## The order

| part | rule |
| --- | --- |
| Entry | limit buy 2% under the close, good for the next session only. It fills about 1 time in 3 |
| Target | 2 x the 14-day ATR above the buy price, never under 4% or over 8% |
| Stop | 4 x ATR under the buy price, never closer than 8% or wider than 14% |
| Fallback | not at the target by the close of day 2 (the buy day is day 1)? From day 3 move the sell limit down to 1% above the buy price |
| Time | sell at the close of the 5th session if nothing was hit |
| Size | whole shares within `pick_per_day_inr` in `trader/config.json` (Rs 10,000 for each day's pick) |

Why a limit and not the open: on the same setups, buying the open always
filled and averaged about +0.5 to +0.75% a trade; the limit 2% lower averaged
about +1.3%. Why the stop is wide: stops of 3 to 8% turned the test negative.

| period, grade A, this order, after costs | trades | in profit | average | lost more than 3% |
| --- | --- | --- | --- | --- |
| 2017 to 2022 (used to choose) | 2,134 | 81% | +1.32% | 14% |
| 2023 to Nov 2025 (not used to choose) | 1,841 | 80% | +1.02% | 15% |
| Nov 2025 to Nov 2026 (looked at last) | 48 | 73% | +1.07% | 13% |

## The fallback: a smaller profit instead of a loss

A swing that has not reached its target by day 2 rarely does later. So from
day 3 the sell limit drops to +1%: enough to cover costs and leave a little.
On the same trades, without the fallback, the average was the same but only
57 to 60% ended in profit and 22 to 23% lost more than 3%. With it, about
80% end in profit and about 15% lose more than 3%.

Of 100 filled trades: about 20 reach the full target on day 2, about 60 leave
through the +1% fallback, about 3 hit the stop and about 17 are sold at the
day-5 close. It does not remove losses: about 2 in 10 still lose, about 1 in
11 loses more than 6%, and a gap can jump the stop (the worst trade in the
test lost 19%).

What the user does: on the evening of day 2, if the target has not filled,
change the sell limit (GTT) to the fallback price the order printed. Keep the
stop. `pick.py follow` says when the fallback is on and at what price.

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
6. On later days run `pick.py follow` and report fill, day N of 5, the sell
   limit in force (full target or fallback), and any exit with the result
   after costs. On the evening of day 2 remind the user to move the sell limit
   to the fallback price.

## Rules

- Give the rating with its numbers, never alone, and never raise it because
  the user wants a 7. If nothing is rated 7, say so.
- Never say a target or a profit is certain, and never say the fallback means
  "no loss". Say the odds: about 80 in 100 filled trades ended in profit and
  20 lost in the test.
- Never turn a WATCH or NO ORDER into an order because the user wants a trade.
  No trade is a result.
- Never tighten the stop, raise the target or change the entry from the chat.
  A new rule is a new backtest.
- Rs 10,000 goes to each day's pick, so picks overlap: with a 5-session hold
  up to 5 can be open together, about Rs 50,000 in the market. Say the total
  in use when giving a new order, and warn if the pick is a stock already held.
- Say "matched the tested setup", never "will go up".

## What it cannot promise

- About 2 trades in 10 lose even with the fallback, and the loss at the stop can be up to Rs 1,400
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
