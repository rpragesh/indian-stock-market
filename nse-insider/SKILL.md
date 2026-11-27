---
name: nse-insider
description: >-
  Bulk and block deals plus insider and promoter trades for NSE stocks.
  Reads NSE's daily bulk-deal and block-deal files and its insider-trading
  (SEBI PIT disclosure) feed, keeps the watchlist or the stocks the user
  names, and shows who bought and sold, how much in crore, each client's
  net, and which clients traded both sides the same day (usually arbitrage
  desks, not a view). Can also list the biggest deals across the market.
  Never places orders. Use when the user says "bulk deals today", "block
  deals in HDFC Bank", "did promoters sell", "insider trades in Reliance",
  "who bought INFY", or "any big money in my watchlist".
argument-hint: "[--symbols A,B] [--all]"
---

# nse-insider

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It uses `nse-setup`'s
tools next to it.

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py"                         # watchlist: bulk, block and insider
python3 "${CLAUDE_SKILL_DIR}/insider.py" --symbols SBIN,TATASTEEL
python3 "${CLAUDE_SKILL_DIR}/insider.py" --all --top 15          # the biggest deals in the market
python3 "${CLAUDE_SKILL_DIR}/insider.py" --bulk-file bulk.csv --block-file block.csv --insider-file it.xml
```

## What the deals mean

- **Bulk deal:** one client traded more than 0.5% of the company's shares
  in a day, in the normal market.
- **Block deal:** a single large trade (at least Rs 10 crore) in the
  exchange's separate block-deal window.
- **Insider disclosure:** a promoter, director or employee reported a trade
  under SEBI's Prohibition of Insider Trading rules.

NSE publishes bulk and block files after the close, so during the day they
show the previous session. "Both sides" marks a client that bought and
sold the same stock the same day; the "one-way" net leaves those out.

## Where the data comes from

Public files on `nsearchives.nseindia.com`, no login:
`content/equities/bulk.csv`, `content/equities/block.csv` and
`content/RSS/Insider_Trading.xml`, cached under `nse/cache/` for 5
minutes. If the tool can't reach them, open each URL in a browser, save it,
and pass the `--*-file` options.

The insider feed has looked stale (its newest item was from May 2026 when
this was written) and gives only the company and a link to the filing,
not who traded or how much. The tool says when the feed is more than a
week old. For recent insider trades, point the user to nseindia.com,
Companies, Insider Trading.

## Steps

1. Run `insider.py` for the watchlist, or `--symbols` for the stock in
   question.
2. Report each stock's net, the biggest clients, and any both-sides
   clients. Give amounts in crore.
3. Report insider disclosures with their links, and the stale-feed note
   when it appears.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never invent a filing, a number or a deal. If a feed or the connector has nothing, say so.
- Quote what the filing says, link it, and let the user read it. Do not turn news into a buy or sell call.
