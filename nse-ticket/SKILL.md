---
name: nse-ticket
description: >-
  Order ticket and trade journal for NSE/BSE, Phase 1. For an order that
  nse-risk passed today, prints a step-by-step ticket the user types into
  Groww or Kite themselves (entry limit, SL-M stop after the fill, how to
  take the target without ending up short, out by flat-by), then, only after
  the user's explicit yes, logs it in nse/state/journal.json as a paper fill
  (or the user's real fill in live mode). Closes trades with net P&L after
  charges and shows today's results. Never places, modifies or cancels an
  order. Use when the user says "give me the ticket", "how do I place this",
  "log the trade", "paper trade it", "I got out at", "close the trade", "how
  did I do today", or after nse-risk passes.
argument-hint: "show | log | close | today"
---

# nse-ticket

The last step of Phase 1. It turns a passed order into instructions the user
follows by hand in their broker's app, and keeps the record. There is no
code path here that reaches a broker.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/ticket.py" show                          # needs today's PASS for this exact order
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log --confirm                 # only after the user's explicit yes
python3 "${CLAUDE_SKILL_DIR}/ticket.py" log --confirm --fill 1612.65  # live mode: the price they really got
python3 "${CLAUDE_SKILL_DIR}/ticket.py" close --symbol INFY --exit 1636 --reason target
python3 "${CLAUDE_SKILL_DIR}/ticket.py" today
```

## Steps

1. Run `ticket.py show`. If it refuses (no PASS, a PASS for a different or
   edited order, a PASS from another day, or a BLOCK), say why and send the
   user back to the right skill.
2. Show the ticket. Then ask one plain question: "Log this as a paper trade?"
   (or, in live mode, "Did you place it, and at what price?").
3. Only when the user answers yes in their own words, run
   `ticket.py log --confirm`. Never pass `--confirm` on your own, from an
   earlier yes, or from a yes about a different ticket.
4. When the user says the trade ended (stop, target, flat-by or by hand), run
   `ticket.py close` with the exit price they give. Read back the net P&L.
   Paper exits use the price the user names or that a data skill shows.
   Never invent one.
5. `ticket.py today` shows the day: each trade, net P&L after charges, paper
   equity and cash.

## The ticket

- **Entry**: a LIMIT buy in Intraday (Groww) or MIS (Kite).
- **Stop**: a SELL SL-M order with the stop as trigger, placed as soon as the
  entry fills.
- **Target**: never a sell limit left open next to the stop. If both fill,
  the user is short. At the target, cancel the stop, then sell.
- **Flat-by**: out by the flat-by time, win or lose, before the broker's auto
  square-off and its fee.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never loosen a limit, widen a stop or edit an order to make it pass. Say the reason and the fix.
- Long, cash-equity only in Phase 1: no shorts, F&O or margin.
