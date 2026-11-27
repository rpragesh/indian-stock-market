---
name: nse-results
description: >-
  Quarterly results summary for NSE stocks. Fetches the company's reported
  financials with the broker connector (Groww: fetch_stocks_fundamental_data)
  and says what changed in the latest quarter: revenue, EBITDA, net profit
  and EPS against the previous quarter and the same quarter last year,
  operating and net margins in basis points, the yearly trend, and anything
  that stands out such as a loss, a margin squeeze or profit falling while
  revenue grows. Never places orders. Use when the user says "INFY results",
  "how was the quarter", "did Reliance beat last year", "summarise the
  results", or "check results before I trade".
argument-hint: "SYMBOL"
---

# nse-results

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It uses `nse-setup`'s
tools next to it.

```bash
python3 "${CLAUDE_SKILL_DIR}/results.py" --symbol INFY             # reads nse/results/INFY.json
python3 "${CLAUDE_SKILL_DIR}/results.py" --symbol INFY --json
python3 "${CLAUDE_SKILL_DIR}/results.py" --symbol INFY --company "Infosys" --file saved.json
```

## Getting the numbers from the connector

Python cannot call the connector, so you fetch and save. With Groww:

1. Call `fetch_stocks_fundamental_data` with the company name and the
   `financials_only` view.
2. Save the result exactly as returned to `nse/results/SYMBOL.json` (SYMBOL
   is the NSE symbol). Do not retype or round the numbers.
3. The answer can hold more than one company (a search for "Infosys" also
   returns HCL Infosystems). The tool picks the one that matches the
   watchlist name or `--company`, and prints which one it used. Check it.

With Zerodha, the Kite connector has no fundamentals. Say so, and point
the user to the results filing that nse-news links.

Figures are in crore as Groww reports them. Groww labels quarters by the
month they end, so "Sep '26" is July to September 2026 (Q2 FY27).

## Steps

1. Fetch and save as above, then run `results.py --symbol SYMBOL`.
2. Report the latest quarter: each line's value, QoQ and YoY change, the
   margins, and the "Watch" notes.
3. If results came out today (nse-news shows a results filing), the stock
   may move sharply. Say so before any intraday plan.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never invent a filing, a number or a deal. If a feed or the connector has nothing, say so.
- Quote what the filing says, link it, and let the user read it. Do not turn news into a buy or sell call.
