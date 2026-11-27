---
name: nse-scanner
description: >-
  Chart scanner for NSE stocks. Narrows the market with the broker
  connector's screeners and movers lists (Groww: technical screener, top
  gainers, volume shockers, intraday favourites), fetches today's 5-minute
  candles for the shortlist, and scans them for three intraday setups:
  opening-range breakouts (with volume), bull flags and oversold bounces.
  Says for each whether it is forming, triggered, stale or failed, with the
  trigger, entry and stop, and the next command to plan it. Skips thin
  stocks and your blocked list. Never places orders. Use when the user says
  "scan the market", "find setups", "any breakouts", "what's moving",
  "opening range breakouts today", "oversold stocks", or "find me a trade".
argument-hint: "[orb|flag|bounce] [--at HH:MM]"
---

# nse-scanner

Finds stocks whose bars match one of three mechanical setups. A hit is a
pattern match, not a recommendation.

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It uses `nse-setup`'s
tools next to it.

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py"                       # today, bars closed by now (IST)
python3 "${CLAUDE_SKILL_DIR}/scan.py" --setups orb --write  # breakouts only, save nse/scan.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" --date 2026-11-26 --at 14:10   # replay a past moment
```

## The setups

| setup | forming | triggered | stop |
| --- | --- | --- | --- |
| `orb` opening-range breakout | inside the first 15 minutes' range (09:15 to 09:30) | a 5-minute close above the range high; volume over 1.5x the average bar is flagged as strong, under it as weak | range midpoint (`or-mid`) |
| `flag` bull flag | a rise of 1%+ within 8 bars, then 2 to 10 bars that give back at most half of it | a close above the flag's high | under the flag's low |
| `bounce` oversold bounce | RSI(14) under 30 | after RSI under 30 in the last 6 bars, a close above the prior bar's high | under the low of the last 6 bars |

A breakout older than 3 bars is **stale** (don't chase it). An ORB that
closed under the range low first has **failed**. Tune these under
`"setups"` in `nse/config.json` (keys in `nse-setup/setups.py`). Stocks
trading under `min_day_turnover_inr` a day (₹10 crore by default) are
skipped as too thin.

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

1. Check the clock with `nse-setup/market.py` (or the connector's market
   time tool). Before 09:30 the opening range is not finished. After the
   entry window closes, scan only to learn, and say so.
2. Build a shortlist of about 5 to 10 liquid NSE stocks. Use the user's
   watchlist if they have one. Otherwise use the connector's lists, for
   Groww `fetch_market_movers_and_trending_stocks_funds` (TOP_GAINERS_LARGE,
   VOLUME_SHOCKERS, POPULAR_STOCKS_INTRADAY_VOLUME) or
   `fetch_technical_screener` (near breakout, RSI under 30), limited to
   NIFTY 100 or NIFTY 500 names. Drop the blocked list.
3. For each one, fetch the 5-minute candles for today and the previous
   trading day (`last_n_days: 2`) and save them to `nse/candles/SYMBOL.csv`.
   The previous day warms up the RSI and sets the liquidity check.
4. Run `scan.py --write`. Present triggered hits first, then forming ones,
   with the trigger, entry, stop and why. Mention weak volume.
5. Hand off: a triggered hit goes to nse-exit with the command shown. A
   forming one goes to nse-entry to watch. nse-timemachine can replay it
   first.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never invent a price or a candle. If the connector has no data, say so.
- Long, cash-equity only in Phase 1: no shorts, F&O or margin.
