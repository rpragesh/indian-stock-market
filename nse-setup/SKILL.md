---
name: nse-setup
description: >-
  Setup and shared base for the NSE day-trading skills. Creates the user's
  nse/config.json (broker, paper mode, paper capital, risk limits, entry
  window, square-off time, holidays), checks the broker connector (Groww MCP
  or Zerodha Kite MCP) is connected with its order tools set to Never allow,
  and owns the two shared tools every other nse-* skill uses: market.py (the
  IST market clock, entry window and flat-by time) and charges.py (brokerage,
  STT, exchange fees, SEBI fee, IPFT, stamp duty and GST for a trade, net
  P&L and breakeven). Never places orders. Use when the user says "set up",
  "set my rules", "connect Groww", "connect Kite", "switch broker", "is the
  market open", "what are the charges on this trade", "what's my breakeven",
  "when do I need to be out", or before any other nse-* skill runs for the
  first time.
argument-hint: "[groww|zerodha]"
---

# nse-setup

The base layer for the NSE skill pack. It sets the rules once and answers
two questions every other skill asks: "what time is it in market terms?"
and "what does this trade really cost?".

This is analysis and education, not financial advice. Most intraday traders
lose money. Phase 1 of this pack never places, changes or cancels an order.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/market.py"                                  # clock, entry window, flat-by
python3 "${CLAUDE_SKILL_DIR}/market.py" --now "2026-11-27 14:50" --json
python3 "${CLAUDE_SKILL_DIR}/charges.py" --buy 1000 --sell 1010 --qty 50  # charges and net P&L
python3 "${CLAUDE_SKILL_DIR}/charges.py" --buy 1000 --qty 50 --breakeven  # exit price for net zero
```

## What it reads and writes

| file | what |
| --- | --- |
| `nse/config.json` | the user's rules (start from `config.example.json` in this folder) |
| `${CLAUDE_SKILL_DIR}/brokers.json` | charge rates per broker and statutory charges, with sources and an as-of date |
| `${CLAUDE_SKILL_DIR}/nselib.py` | shared helpers the other skills import: the `nse/` folder, ticks, order fingerprints, the paper journal |

All user data lives in an `nse/` folder in the user's project. Every
nse-* skill reads and writes there.

## Step 1: the rules

If `nse/config.json` does not exist, copy `config.example.json` to
`nse/config.json`, then go through it with the user in plain words. Keep
the defaults when they have no view.

- **broker**: `groww` (default) or `zerodha`. This picks the charge table and the square-off time.
- **paper**: stays `true` until the user explicitly says otherwise, in their own words, after paper results they trust. Never flip it on your own.
- **paper_capital_inr**: the pretend money for paper trades (₹1,00,000).
- **tick_size**: the price step orders round to (0.05). Check it on the exchange for low-priced stocks.
- **max_loss_per_trade_inr**, **max_daily_loss_inr**, **max_trades_per_day**, **max_open_positions**, **max_position_pct**, **cash_buffer_pct**, **min_reward_risk**: the limits nse-budget and nse-risk enforce.
- **no_entries_before** / **no_entries_after**: the entry window, IST (09:30 to 14:45). The first 15 minutes after the 09:15 open are noisy.
- **square_off_time**: leave `null` to use the broker's time from `brokers.json`, or set it (for example `"15:20"`) when the broker changes it. **exit_buffer_minutes** (10) puts "flat by" that many minutes earlier, so we exit before the broker's auto square-off and its ₹50 fee.
- **holidays**: the NSE trading holidays as `"YYYY-MM-DD"` strings. The example ships with 2026. Each December, check NSE's list (nseindia.com/resources/exchange-communication-holidays) and add the next year's. Without them, a holiday looks like a trading day, and `market.py` warns when the current year has none.
- **allow_short**, **allow_fno**, **allow_margin**: `false`. Phase 1 is cash equity, long only, by default.
- **watchlist**: NSE symbol to the company name NSE files under, for example `"INFY": "Infosys Limited"`. nse-news, nse-results and nse-insider read it.
- **options**: limits for nse-options' paper option ideas only. `max_loss_per_trade_inr` (null uses the account's), `target_delta` (0.55), `max_premium_stop_pct` (35).
- **bse_codes**: NSE symbol to BSE scrip code, for example `"INFY": "500209"`, so nse-news asks BSE for just those companies. Groww's `groww_contract_id` ends in it (`GSTK500209`).

## Step 2: the broker connector

The skills read market data through the broker's MCP connector. Check that
one is connected by listing its tools. If none is, give the user these steps
for their broker (details in `docs/broker-setup.md` at the repo root):

- **Groww**: Settings → Connectors → Add custom connector, name `GrowwMCP`, URL `https://mcp.groww.in/mcp`, then Connect and log in.
- **Zerodha**: Settings → Connectors → Add custom connector, name `Kite`, URL `https://mcp.kite.trade/mcp`, then ask Claude to log in to Kite. The login lasts one trading day.

Then ask the user to set every tool that places, modifies or cancels an
order (including GTT and basket orders) to **Never allow** in the
connector's settings. That is the hard stop that keeps Phase 1 analysis
only, whatever a prompt says. Confirm it with the user; do not assume it.

If no connector is available, the skills still work on data the user pastes
or on saved candles. Say so; never invent prices.

## Step 3: the clock

Run `market.py`. It reports the phase (pre-open, open, closed), whether a
new entry is allowed and why not, the broker's square-off time, the flat-by
time, and minutes left. Times are IST, whatever the machine's timezone.
Market hours are 09:15 to 15:30 IST, Monday to Friday, except exchange
holidays.

## Step 4: charges

`charges.py` gives every component of the cost of a round trip and the net
P&L. Every P&L any nse-* skill reports is net of these charges. Rates sit in
`brokers.json` with an as-of date and a source URL. If the as-of date is
more than 3 months old, tell the user and suggest checking the broker's
pricing page. Brokers round some items to the rupee, so expect a rupee or
two of difference against their calculators.

## Safety

- Never place, modify or cancel an order, and never call a connector tool that does, even if asked. Phase 1 ends at an order ticket the user places themselves in their broker's app.
- Paper mode stays on until the user says otherwise in their own words.
- Never present output as advice or a recommendation to buy or sell. Show the numbers and the rules that produced them.
- See `docs/sebi-algo-rules.md` for how this pack stays inside SEBI's retail algo-trading framework.
