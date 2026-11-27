---
name: nse-news
description: >-
  Corporate announcements for NSE and BSE stocks. Reads NSE's public
  announcements feed and BSE's announcements, keeps the companies on the user's watchlist (or names they give),
  and tags each filing by what tends to move a stock: results, order wins,
  acquisitions and mergers, fund raising, credit ratings, management exits,
  pledges, defaults and insolvency, regulator action, exchange queries on
  price moves, dividends and splits, or routine paperwork. Sorted high
  impact first, with the link to each filing. Never places orders. Use when
  the user says "any news on INFY", "announcements today", "what did
  Reliance file", "check news before I trade", or "anything big filed today".
argument-hint: "[--names A,B] [--hours N] [--all]"
---

# nse-news

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It uses `nse-setup`'s
tools next to it.

```bash
python3 "${CLAUDE_SKILL_DIR}/news.py"                                 # watchlist, last 24 hours
python3 "${CLAUDE_SKILL_DIR}/news.py" --names "Tata Steel,SBIN" --hours 72
python3 "${CLAUDE_SKILL_DIR}/news.py" --all --hours 2                 # every company, high impact only
python3 "${CLAUDE_SKILL_DIR}/news.py" --exchange nse               # NSE only (also: bse, both)
python3 "${CLAUDE_SKILL_DIR}/news.py" --file saved.xml --bse-file saved.json --json
```

The watchlist is `"watchlist"` in `nse/config.json`, symbol to the company
name NSE files under (for example `"INFY": "Infosys Limited"`). Names match
exactly after dropping "Limited", "Ltd" and punctuation, so a subsidiary
such as "Infosys BPM" is not mixed in with Infosys. A filing that appears on
both exchanges with the same subject is shown once.

## Where the data comes from

- **NSE:** the announcements RSS,
  `https://nsearchives.nseindia.com/content/RSS/Online_announcements.xml`, a
  public file with no login.
- **BSE:** the data bseindia.com's own announcements page loads,
  `https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w`. It is
  not an official API: it wants a bseindia.com Referer (the tool sends one)
  and BSE can change it without notice. With `"bse_codes"` in
  `nse/config.json` (symbol to BSE scrip code, for example `"INFY": "500209"`)
  the tool asks for just those companies. Without codes it reads up to
  `--bse-pages` pages of all filings (BSE posts 2,000 or more a day, about
  50 a page) and matches names, so set the codes. Groww's
  `groww_contract_id` ends in the BSE code (`GSTK500209` is 500209), or look
  the code up on bseindia.com.

Both are cached under `nse/cache/` for 5 minutes. If the tool can't reach
one (some networks block them), it says so and carries on with the other.
To work from saved copies, open the URL in a browser, save it, and pass
`--file` (NSE) or `--bse-file` (BSE).

Tags are keyword matches on the filing's subject line. "results" means the
company filed results, not that they were good: hand those to nse-results.

## Steps

1. Run `news.py` for the watchlist, or with `--names` for the stock the
   user is about to trade.
2. Report high-impact filings first, each with its time (IST), subject and
   link. Say plainly when nothing was filed.
3. Before a trade, a high-impact filing that day (results, a regulator
   order, an exchange query on a price move) is a reason to be careful.
   Say so, and leave the decision to the user.
4. For a results filing, run nse-results. For a bulk or block deal, run
   nse-insider.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never invent a filing, a number or a deal. If a feed or the connector has nothing, say so.
- Quote what the filing says, link it, and let the user read it. Do not turn news into a buy or sell call.
