---
name: nse-insider
description: >-
  Bulk and block deals, insider and promoter trades, and shareholding
  changes for NSE stocks. Reads NSE's daily bulk-deal and block-deal files,
  NSE's insider-trading (SEBI PIT) filings, and the quarterly shareholding
  pattern from the broker connector. Shows who bought and sold, how much in
  crore, each client's net, which clients traded both sides the same day
  (usually arbitrage desks, not a view), and how promoter, FII and DII
  stakes moved. Can also list the biggest deals across the market.
  Never places orders. Use when the user says "bulk deals today", "block
  deals in HDFC Bank", "did promoters sell", "insider trades in Reliance",
  "who bought INFY", or "any big money in my watchlist".
argument-hint: "[--symbols A,B] [--all]"
---

# nse-insider

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It uses `nse-setup`'s
tools next to it.

```bash
python3 "${CLAUDE_SKILL_DIR}/insider.py"                         # watchlist: deals and insider filings, 30 days
python3 "${CLAUDE_SKILL_DIR}/insider.py" --symbols SBIN --holding  # plus shareholding changes
python3 "${CLAUDE_SKILL_DIR}/insider.py" --all --top 15          # the biggest deals and filers in the market
python3 "${CLAUDE_SKILL_DIR}/insider.py" --bulk-file bulk.csv --block-file block.csv --insider-file pit.json
```

## What the deals mean

- **Bulk deal:** one client traded more than 0.5% of the company's shares
  in a day, in the normal market.
- **Block deal:** a single large trade (at least Rs 10 crore) in the
  exchange's separate block-deal window.
- **Insider disclosure:** a promoter, director or employee reported a trade
  under SEBI's Prohibition of Insider Trading rules.
- **Shareholding pattern:** what promoters, foreign institutions (FII),
  domestic institutions (DII) and the public held at each quarter end.

NSE publishes bulk and block files after the close, so during the day they
show the previous session. "Both sides" marks a client that bought and
sold the same stock the same day; the "one-way" net leaves those out.

## Where the data comes from

- **Bulk and block deals:** public files on `nsearchives.nseindia.com`, no
  login: `content/equities/bulk.csv` and `content/equities/block.csv`.
- **Insider filings:** the data NSE's own Insider Trading page loads,
  `https://www.nseindia.in/api/corporates-pit-gg` and, for older filings,
  `/api/corporates-pit`. It is not an official API: the tool first visits
  NSE's home page for the cookies a browser gets, and NSE can change or
  block it without notice. Since 4 May 2026 companies file these in XBRL
  (NSE circular NSE/CML/2026/12). For those filings the list gives the
  company, the regulation and a link; who traded and how much are inside
  the linked filing, so open it before saying what an insider did. Filings
  before May 2026 come with the person, category, buy or sell, shares,
  value and holding before and after.
- **Shareholding:** the broker connector. With Groww, call
  `fetch_stocks_fundamental_data` with the company name and the
  `shareholding_only` view, and save the answer exactly as returned to
  `nse/holding/SYMBOL.json`. A search can return more than one company; the
  tool picks the one matching the watchlist name and prints which. Groww
  lists every promoter holder but only the largest FII and DII names, so a
  big fund vanishing from those lists may just mean it fell below the cut.

NSE data is cached under `nse/cache/` for 5 minutes. If the tool can't
reach a source (some networks block NSE), it says so and carries on with
the rest. To work from saved copies, open the URL in a browser, save it,
and pass the `--*-file` options.

## Steps

1. Run `insider.py` for the watchlist, or `--symbols` for the stock in
   question.
2. Report each stock's net, the biggest clients, and any both-sides
   clients. Give amounts in crore.
3. Report insider filings with their links. For an XBRL-era filing, say
   that the details are in the filing rather than guessing them.
4. With `--holding`, report the promoter, FII and DII changes and the
   "Watch" line. Shareholding is quarterly, so it says who moved over three
   months, not today.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never invent a filing, a number or a deal. If a feed or the connector has nothing, say so.
- Quote what the filing says, link it, and let the user read it. Do not turn news into a buy or sell call.
