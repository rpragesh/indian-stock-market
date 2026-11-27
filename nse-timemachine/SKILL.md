---
name: nse-timemachine
description: >-
  Time Machine for NSE intraday trades. Before risking a rupee, replays the
  planned trade (entry, stop, target, flat-by) 10,000 times through
  simulated sessions built from the stock's own past bars at the same
  times of day, scaled to today's volatility, and plays the same setup on
  every past day it fired. Reports the odds of hitting the target first,
  the stop first, or running out of time, and the net P&L after charges:
  average, median, worst 5% and best 5%. Never places orders. Use when the
  user says "what are the odds", "replay this trade", "backtest this",
  "would this have worked", "time machine", or after nse-exit writes a plan.
argument-hint: "[--qty N] [--runs 10000]"
---

# nse-timemachine

Puts honest numbers on a plan before you take it. It describes the past,
not the future.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py"                 # nse/plan.json, qty from nse/order.json
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" --qty 40 --write
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" --runs 20000 --seed 7
```

## How it works

1. **10,000 simulated sessions.** From the entry time to flat-by, each run
   takes one bar slot at a time (say 10:35). For that slot it borrows the
   high, low and close, relative to the open, from a random past session of
   the same stock at 10:35. The moves are scaled by how volatile today has
   been against those slots (between 0.5x and 2x). A bar that reaches both
   the stop and the target counts as the stop. Runs are seeded, so the same
   inputs give the same answer.
2. **Every past day the setup fired.** The same nse-scanner rules run bar by
   bar on each saved past session. The first trigger before the entry window
   closes becomes the entry, with the setup's stop and the plan's
   reward:risk. It then plays out on what really happened next.

All P&L is net of charges for the planned quantity.

## Getting candles from the connector

Python cannot call the connector, so you fetch and save. With Groww:

- `fetch_historical_candle_data` (company_name, segment `CASH`, interval_in_minutes, last_n_days or start_date/end_date) gives OHLCV candles in IST. 1 to 240 minute candles go back 90 days.
- `get_ltp` gives last prices for up to 50 names in one call. `get_quotes_and_depth` gives bid/ask depth.
- `resolve_market_time_and_calendar` gives the official date, time and whether the market is open.

Save candles as compact CSV, one bar a line, oldest first, to `nse/candles/SYMBOL.csv` (SYMBOL is the NSE symbol, for example `INFY`):

```
time,open,high,low,close,volume
2026-11-27 09:15,1179,1179,1160.6,1161,470477
```

Every candle you write costs tokens, so fetch only what the job needs. Copy the numbers exactly as the connector returned them; never fill a gap. With Zerodha, use the Kite connector's historical data and quote tools the same way.

For the time machine, fetch **20 to 30 trading days** of candles for the one
stock. 15-minute candles (`interval_in_minutes: 15`) keep that to about 25
bars a day and work just as well. Use 5-minute candles if you want the
replay at the same bar size as the scan. Put today's bars in the same file.

## Steps

1. Needs `nse/plan.json` (nse-exit) and a quantity, from nse-budget or
   `--qty`.
2. Fetch and save the candles as above.
3. Run `timemachine.py --write`. Report the target, stop and flat-by
   percentages, the chance of a net profit, and the average net P&L. If the
   average is negative after charges, lead with that.
4. Under 20 past cases of the setup is too few to lean on: say so.
5. Never present the odds as a forecast or a reason to trade.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never invent a price or a candle. If the connector has no data, say so.
- Long, cash-equity only in Phase 1: no shorts, F&O or margin.
