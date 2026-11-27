---
name: nse-brief
description: >-
  One-command market check for NSE intraday trading, using every skill in
  the pack. Builds a shortlist from the broker connector's movers and
  screeners, fetches candles, scans for setups, plans entry, stop, target
  and exit time, sizes each after charges, runs the risk rules, replays
  them, flags big filings, and ranks the top 10 intraday stocks. Adds an
  F&O pick (which CE or PE to buy, entry, stop, target and lots on the
  premium) on paper. Never places orders. Use when the user says "check
  the market", "what should I trade today", "top stocks for intraday",
  "market scan", "give me today's picks", or "morning brief".
argument-hint: "[--at HH:MM] [--top N]"
---

# nse-brief

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It uses the other
`nse-*` skills next to it.

```bash
python3 "${CLAUDE_SKILL_DIR}/brief.py" --write                 # now (IST), saves nse/brief.json
python3 "${CLAUDE_SKILL_DIR}/brief.py" --date 2026-11-27 --at 11:00
python3 "${CLAUDE_SKILL_DIR}/brief.py" --top 5 --no-news --json
```

## What it runs, in order

1. **nse-scanner**: every stock in `nse/candles/` for opening-range
   breakouts, bull flags and oversold bounces. Triggered and forming ones go on.
2. **nse-exit**: entry, stop (range midpoint for a breakout, the setup's
   own stop otherwise), a 2R target and the flat-by time.
3. **nse-budget**: shares, so the loss at the stop after charges stays
   inside your max loss, the position and cash limits hold.
4. **nse-risk**: PASS or BLOCK with every reason.
5. **nse-timemachine**: 2,000 replays when 6 or more sessions are saved.
6. **nse-news**: today's high-impact NSE filings for those names.
7. Rank and keep the top 10, one line per stock.
8. **nse-options**: for each underlying with data in `nse/fno/`, the best
   bullish or bearish setup as a CE or PE to buy, paper only.

The score is fixed, not judgement: triggered (30) beats forming (20); plus
3 per point of net reward:risk (up to 4); plus 2 for breakout volume, 1 for
trading over VWAP, 3 for a positive replay (minus 3 for a negative one);
minus 10 for a BLOCK and 2 for a big filing today.

## Steps

1. **Clock.** Run `nse-setup/market.py` (or the connector's market time
   tool). Before 09:30 the opening range isn't finished: say so and offer
   to run again after 09:30. After 14:45 no new entries are allowed: run it
   anyway as study, and say so in the first line.
2. **Shortlist, 10 to 15 liquid stocks.** The user's watchlist, plus Groww's
   `fetch_market_movers_and_trending_stocks_funds` (TOP_GAINERS_LARGE,
   VOLUME_SHOCKERS, POPULAR_STOCKS_INTRADAY_VOLUME) and
   `fetch_technical_screener` (NIFTY 100, near breakout or RSI under 30).
   Drop the blocked list. Save symbol to company name in
   `nse/shortlist.json` (`{"INFY": "Infosys Limited", ...}`) so filings
   can be matched.
3. **Candles.** For each, `fetch_historical_candle_data`, 5-minute,
   `last_n_days: 2`, saved as compact CSV to `nse/candles/SYMBOL.csv`
   (format in nse-scanner's SKILL.md). Also NIFTY (segment `INDEX`,
   "Nifty 50") to `nse/candles/NIFTY.csv` for the market line and F&O.
4. **F&O data.** NIFTY always. Add up to two F&O stocks from the shortlist
   that `fetch_curated_fno` (TOP_TRADED) also lists. Fetch and save
   each as nse-options' SKILL.md says.
5. **Run** `brief.py --write`.
6. **Report** in this order, keeping the tool's numbers exactly:
   - one line on the clock and the market (NIFTY, its change, PCR)
   - the top 10 as a table: stock, setup, state, entry, stop, target,
     shares, loss at stop, gain at target, PASS/BLOCK
   - the F&O pick: contract, buy at, stop, target, lots, loss and gain, and
     its notes (SKIP, rough prices, expiry day)
   - exits: stop, target, or the flat-by time
   - what was left out and why, in one line
7. **Hand off.** To take a stock on paper: `nse-exit/exit.py plan` with the
   numbers shown, then nse-budget, nse-risk and nse-ticket. Forming setups
   go to nse-entry to watch. F&O ideas stop at the plan: there is no
   option ticket yet.

Every candle and quote costs tokens. 15 stocks at 2 days of 5-minute
candles is about 2,250 rows; keep the shortlist tight.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money, and SEBI's study of FY22 to FY24 found about nine in ten individual F&O traders lost money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words. Option ideas are paper only, whatever the config says.
- Option BUYING only: never suggest selling (writing) options, whose loss has no limit.
- Never invent a price, a candle, an option premium or a greek. If the connector has no data, say so.
- Present the ranked list as pattern matches ranked by fixed rules, not as picks you believe in. Don't add a view the tools didn't produce.
