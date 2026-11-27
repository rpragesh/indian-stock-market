---
name: nse-entry
description: >-
  Entry timer for NSE intraday setups. Watches one stock's setup (opening
  range breakout, bull flag, oversold bounce, or a price level you name)
  bar by bar on closed 5-minute candles, and says the moment it triggers,
  with the entry and the stop; or that it is still forming, has gone stale,
  has failed, or is too late in the day. Can replay any past day bar by bar.
  Writes nse/entry.json for nse-exit. Never places orders. Use when the
  user says "watch INFY for a breakout", "tell me when it breaks 812",
  "is it time to get in", "has it triggered", or after nse-scanner finds
  a forming setup.
argument-hint: "SYMBOL [orb|flag|bounce|level PRICE]"
---

# nse-entry

Watches a setup on closed bars only, so a half-formed bar never triggers it.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch --symbol INFY --setup orb --write
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch --symbol SBIN --setup level --level 812 --stop 805 --write
python3 "${CLAUDE_SKILL_DIR}/entry.py" replay --symbol INFY --setup orb --date 2026-11-26
```

States: **WAITING** (forming: shows the trigger), **TRIGGERED** (entry and
stop), **STALE** (broke out more than 3 bars ago: don't chase), **FAILED**
(broke the wrong way first), **NONE** (no such setup today). "Too late"
means the setup is live but the entry window or flat-by has passed.

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

## Steps

1. Refresh today's 5-minute candles for the stock (`last_n_days: 2`) and
   save them to `nse/candles/SYMBOL.csv`.
2. Run `entry.py watch ... --write`.
3. WAITING: tell the user the trigger price and offer to check again after
   the next 5-minute bar closes. For repeated checks use `/loop 5m` or a
   scheduled reminder, refreshing the candles each time. Stop at the end of
   the entry window.
4. TRIGGERED: hand off to nse-exit with `exit.py plan --from-entry`.
   Mention weak volume. If the trigger was more than one bar ago, check the
   live price with `get_ltp` first. Over half the risk past the entry is a
   chase: say so.
5. STALE, FAILED or too late: say so plainly and stop watching.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never invent a price or a candle. If the connector has no data, say so.
- Long, cash-equity only in Phase 1: no shorts, F&O or margin.
