---
name: nse-options
description: >-
  Option-buying plans for NIFTY, BANKNIFTY and F&O stocks, on paper. Reads
  the underlying's chart for a bullish setup (breakout, bull flag, oversold
  bounce: buy a call, CE) or a bearish one (breakdown, bear flag, overbought
  fade: buy a put, PE), picks the liquid strike near 0.55 delta in the
  nearest sensible expiry, and works out the entry, stop and target on the
  premium, the time decay to the flat-by time, and how many lots fit your
  max loss after charges. Never places orders. Use when the user asks
  "which CE or PE", "nifty option for today", "F&O pick", "should I buy a
  call or put", or "plan a NIFTY option trade".
argument-hint: "UNDERLYING (NIFTY, BANKNIFTY, RELIANCE ...)"
---

# nse-options

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It uses `nse-setup`'s
tools next to it. nse-brief runs it for every underlying you save data for.

```bash
python3 "${CLAUDE_SKILL_DIR}/options.py" --underlying NIFTY             # bars closed by now
python3 "${CLAUDE_SKILL_DIR}/options.py" --underlying NIFTY --date 2026-11-27 --at 11:00 --json
```

## How a plan is made

| step | rule |
| --- | --- |
| direction | the underlying's best live setup: bullish means CE, bearish means PE |
| expiry | the nearest one Groww's OI tool reports; avoid expiry day (fetch the next expiry instead) |
| strike | the contract with volume and open interest whose delta is nearest 0.55 |
| entry | today's premium, moved by delta (and gamma) to where the underlying triggers |
| stop | the underlying's stop through delta, plus half the time decay, never more than 35% of the premium |
| target | the underlying's 2R target through delta, less the full time decay to the flat-by time |
| lots | as many as keep the loss at the stop, after charges, inside the max loss, and the premium inside your position and cash limits |
| exit | the premium stop, the target, or the flat-by time, whichever comes first |

Options cost more than they look. Charges are in `nse-setup/brokers.json`:
Rs 20 brokerage an order, STT 0.15% of the premium on the sell, NSE's
0.03553% exchange charge, stamp duty, SEBI and IPFT fees and GST.

**Your max loss decides most of it.** A NIFTY lot is 65 units, so with the
default Rs 500 max loss a premium stop can only be about 7 points away.
Most plans will say "SKIP under your limits". That is the point of the
limit. If the user wants to study bigger option trades on paper, they can
set `"options": {"max_loss_per_trade_inr": 2000}` in `nse/config.json`, which
applies to option ideas only. Don't change it for them.

## Getting the data from the connector

Python cannot call the connector, so you fetch and save. With Groww, for
each underlying:

1. `get_open_interest_analysis` with `view: metrics_only` gives the spot,
   ATM strike, lot size, put-call ratio and the expiry it used (in `note`).
   If that expiry is today, ask again with the next expiry date.
2. `get_ltp` with segment `FNO` and query type `fno` for the ATM strike
   and two strikes either side, calls and puts, in that expiry, for example
   `"nifty 25600 1 dec call"`, `"nifty 25600 1 dec put"`. NIFTY strikes are
   50 apart, BANKNIFTY 100; for a stock, `fno_mcx_contracts_search_tool`
   lists them.
3. `get_greeks_for_fno_contract` for the same contracts and expiry.
4. Save the three answers exactly as returned to `nse/fno/UNDERLYING.json`:
   `{"oi": ..., "ltp": ..., "greeks": ...}`.
5. Save the underlying's 5-minute candles for today and the previous day
   to `nse/candles/UNDERLYING.csv` (`fetch_historical_candle_data`; segment
   `INDEX` and the index name, for example "Nifty 50", for an index).

Fetch option prices at the same time as the candles. If they're more than
0.3% apart the tool says the premium levels are rough; fetch again.

The tool reads Groww's answers. With Zerodha, the Kite connector has
quotes but no greeks and a different shape, so nse-options can't plan from
it yet: say so rather than guessing a delta.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money, and SEBI's study of FY22 to FY24 found about nine in ten individual F&O traders lost money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words. Option ideas are paper only, whatever the config says.
- Option BUYING only: never suggest selling (writing) options, whose loss has no limit.
- Never invent a price, a candle, an option premium or a greek. If the connector has no data, say so.
- Present the ranked list as pattern matches ranked by fixed rules, not as picks you believe in. Don't add a view the tools didn't produce.
