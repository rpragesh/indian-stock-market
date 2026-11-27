---
name: nse-alerts
description: >-
  Price alerts and reminders for NSE intraday trading. Using live prices
  from the broker connector (Groww: get_ltp), checks open paper or manual
  trades against their stop and target, today's plan against its entry
  (reached, failed, or ran away, so don't chase), the user's own above or
  below price alerts, and the clock: opening bell, end of the entry window,
  flat-by countdown and broker square-off. Can run on a schedule. Never
  places, modifies or cancels orders. Use when the user says "alert me",
  "tell me if INFY drops below", "watch my stop", "remind me to exit",
  "square-off reminder", or "check my trades".
argument-hint: "check | add SYMBOL above|below PRICE | list | remove ID"
---

# nse-alerts

Reminders, not actions. An alert tells the user what to do in their broker
app.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" check --ltp INFY=1171.5 --ltp SBIN=811.2
python3 "${CLAUDE_SKILL_DIR}/alerts.py" add --symbol SBIN --below 800 --note "support"
python3 "${CLAUDE_SKILL_DIR}/alerts.py" list
python3 "${CLAUDE_SKILL_DIR}/alerts.py" remove --id 1
```

## What rings

| kind | when |
| --- | --- |
| stop / target | an open trade's price is at or past its stop or target (`near-` within 0.15%) |
| plan | today's planned stock reached the entry, broke the stop, or ran over half the risk past the entry (don't chase) |
| alert | one of your above or below alerts hit (each fires once) |
| bell / window | the 09:15 open, and the end of the entry window |
| flat-by | 15 minutes before flat-by, then EXIT NOW once past it |
| square-off | past the broker's auto square-off with a trade still open in the journal |

Prices passed with `--ltp` are saved to `nse/prices.json`. Without
`--ltp` it uses that file only if it is under 10 minutes old.

## Steps

1. Collect the symbols that matter: open trades in `nse/state/journal.json`,
   today's `nse/plan.json`, and `nse/alerts.json`.
2. Fetch their last prices in one call (Groww `get_ltp` with segment
   `CASH`, query_type `Stocks`; pick the NSE match) and run
   `alerts.py check --ltp SYMBOL=PRICE ...`.
3. Tell the user each ring in plain words, most urgent first (EXIT NOW,
   stop, target).
4. For ongoing reminders while the market is open, offer to run this every
   5 minutes with `/loop 5m` or a scheduled task, ending by the
   flat-by time. Never keep checking after the market closes.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never invent a price or a candle. If the connector has no data, say so.
- Long, cash-equity only in Phase 1: no shorts, F&O or margin.
