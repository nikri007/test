# The news check

`swing.py scan` reads prices only. Before an order goes to the user, and each
day a position is open, run this check and put its verdict in the output. It
is the same check every time, in this order. It is a filter: it can stop or
flag a trade. It can never add one.

## What news may and may not do

- It may mark an order SKIP or CAUTION, and mark an open position REVIEW.
- It may NOT pick a different stock, add a trade, raise the size, move the
  limit, the target or the stop, or extend the 3-session hold.
- On SKIP there is no order that session. Do not replace it with the next
  match. No trade is a normal day.
- Good news is never a reason to buy. The rule's edge was measured without
  news; this check only removes trades where the price data is distorted or
  the risk is of a different kind.

The window is the hold: the buy session through the last session
("still open on <day>" in the scan), three sessions in all.

## Step 1. Facts from the scan (always)

Read the `CHECK:` lines under the order and the NIFTY line.

| the scan says | verdict |
| --- | --- |
| corporate action in the data (dividend, split, bonus) dated on the signal day or the session before | SKIP: the fall may be the price adjustment, not a dip |
| closed at the day's low after a fall of 4.5% or more | SKIP if step 2 confirms a lower circuit; else CAUTION |
| fell 7% or more on the signal day | go to step 2 and find the reason; without a reason, CAUTION |
| NIFTY 50 under its 200-day average | the scan gives no order at all (market filter): nothing to check |
| "NIFTY 50: no data, so the market filter was NOT checked" | CAUTION: look up whether the NIFTY 50 is above its 200-day average; if it is not, SKIP |
| could not read corporate actions | say "corporate actions not verified" |

## Step 2. The company (search the last 5 days of news)

Search: "<company name> NSE" news, "<company name> results date", and
"<company name> board meeting". Use the company name from
`trader/universe.txt`, not only the symbol. Prefer the exchange's own pages,
the company's filings and the large business papers. Give each finding one
line with its source and date.

| finding | verdict |
| --- | --- |
| quarterly results, or a board meeting to approve them, on a session inside the window | SKIP |
| ex-date for a split, bonus, demerger, rights issue or a dividend above 2% of the price, inside the window or on the signal day | SKIP |
| fraud or forensic-audit allegation, a SEBI or other regulator's order against the company or its promoters, a raid, an auditor's resignation, a debt default or a rating cut to default | SKIP |
| trading suspended, the stock in a lower circuit, or moved into the ASM or GSM surveillance lists this week | SKIP |
| an open offer, delisting or merger that fixes the price | SKIP |
| promoter or large holder selling through a block deal, pledged shares invoked | CAUTION |
| results came out in the last 2 sessions and the dip is the reaction to them | CAUTION |
| a broker downgrade, a weak sector day, profit-taking after a run, or no news at all | CLEAR: this is the ordinary dip the rule buys |

## Step 3. The market (events inside the window)

| event inside the window | verdict |
| --- | --- |
| Union Budget day, or a general-election result day | SKIP |
| RBI policy decision, US Federal Reserve decision, monthly F&O expiry, a state-election result | CAUTION |
| the NIFTY 50 fell 2% or more on the signal day, or a major shock is in the news (war, a global market crash) | CAUTION |
| nothing scheduled | CLEAR |

## Step 4. One verdict

The strongest verdict wins: SKIP, then CAUTION, then CLEAR.

- CLEAR: give the order as the scan printed it.
- CAUTION: give the order, and above it one line with each reason. The user
  decides. Do not soften or strengthen it.
- SKIP: do not give the order's prices as an order. Say "SKIP: no order for
  <day>" and the reason with its source.

If a search fails, or sources disagree on a date, say so in plain words:
"results date not verified". Never guess a date and never invent a headline.
"Not verified" on the results date is a CAUTION, with the advice to confirm it
on nseindia.com or in the broker's app before placing the order.

## Open positions (each day of the hold)

Run step 2 for each open position, last 2 days of news only.

- Anything from the SKIP list that is NEW since the buy: mark it REVIEW and
  say what happened. The rule has no early exit for news; the user decides
  whether to sell before the time exit.
- Otherwise say "no new company news".

## What to print

```
News check: CLEAR | CAUTION | SKIP  (checked <date>)
- Company: <one line per finding, with source and date, or "nothing in the last 5 days">
- Results: <next results date and source, or "not verified">
- Market: <event and date, or "nothing scheduled in the window">
```

## Limits

This check was not part of the backtest: there is no ten-year news archive to
test it on. It is a risk filter, not an edge. Dips often come with bad
headlines, which is why only the listed reasons can stop a trade. A web
search can miss a filing or get a date wrong.
