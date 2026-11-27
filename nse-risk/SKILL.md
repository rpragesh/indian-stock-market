---
name: nse-risk
description: >-
  Risk Manager for NSE/BSE trades. Checks the proposed order in
  nse/order.json against the user's limits and returns PASS or BLOCK with
  every reason: max loss per trade after charges, reward:risk after charges,
  position size, cash buffer, daily loss limit (losses so far plus open risk
  plus this trade), trades per day, open positions, duplicates, the blocked
  list, and the IST entry window and flat-by time. Recomputes every number
  itself and records the verdict with the order's fingerprint, which
  nse-ticket needs. Never places orders. Use when the user says "check this
  trade", "is this within my limits", "risk check", "can I take this", or
  after nse-budget writes an order.
argument-hint: ""
---

# nse-risk

The gate between a proposal and a ticket. A BLOCK is final for that order:
no ticket is made. A PASS only means the order may be shown to the user. It
is not a recommendation and not the user's yes.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/check.py"             # writes nse/state/risk.json
python3 "${CLAUDE_SKILL_DIR}/check.py" --json
python3 "${CLAUDE_SKILL_DIR}/check.py" --no-write  # look without recording
```

Exit code 0 is PASS, 1 is BLOCK.

## The checks

| check | blocks when |
| --- | --- |
| format | bad symbol, quantity not a whole number of 1 or more, not a BUY LIMIT, an order from another day |
| product | not cash equity, or not the product in your config |
| blocked | the symbol is on your `blocked` list |
| stop | no stop (`require_stop`), or a stop not under the entry |
| target | not above the entry, or nets nothing after charges |
| loss | the loss at the stop after charges is over `max_loss_per_trade_inr` |
| reward:risk | after charges, under `min_reward_risk` |
| position | over `max_position_pct` of paper equity |
| cash | would leave less than `cash_buffer_pct` in cash |
| daily loss | today's realized losses + open trades' max losses + this one is over `max_daily_loss_inr` |
| trades | `max_trades_per_day` already taken today |
| positions | `max_open_positions` already open |
| duplicate | an open trade in the same symbol |
| window | market closed or a holiday, before `no_entries_before`, after `no_entries_after`, or past flat-by |

Warnings that do not block: live mode, charge rates over 90 days old, an
order edited after sizing, no holidays loaded for this year.

## Steps

1. Run `check.py`.
2. Tell the user the result in plain words: the max loss after charges,
   reward:risk after charges, and how much of today's limits it uses. For a
   BLOCK, give each reason and its fix (fewer shares, a closer stop, a
   farther target, wait for the window, or skip the trade).
3. If the order changes in any way, check it again. nse-ticket matches the
   verdict by fingerprint, and a verdict from another day does not count.
4. On a PASS, hand off to nse-ticket.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never loosen a limit, widen a stop or edit an order to make it pass. Say the reason and the fix.
- Long, cash-equity only in Phase 1: no shorts, F&O or margin.
