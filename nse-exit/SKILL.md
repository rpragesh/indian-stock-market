---
name: nse-exit
description: >-
  Exit Planner for NSE/BSE intraday trades. Sets the stop, the target and the
  flat-by time before the entry: stop from the opening-range midpoint or low,
  a price or a percent, rounded to the tick away from the entry; target as a
  multiple of the risk (2R by default) or a price; flat-by from the broker's
  square-off time minus a buffer. Refuses a stop on the wrong side, a stop
  too tight to survive normal moves, or a plan past the flat-by time. Writes
  nse/plan.json for nse-budget. Never places orders. Use when the user says
  "where's my stop", "set a target", "plan the exit", "when do I get out",
  "plan this trade", or after a setup triggers.
argument-hint: "SYMBOL ENTRY [stop rule] [target rule]"
---

# nse-exit

Decides how a trade ends before it starts. The stop is where the setup has
failed, the target is where you take what you came for, and flat-by is when
you are out regardless, before the broker's auto square-off. All three are
written down before the entry, so nothing gets decided mid-move.

`${CLAUDE_SKILL_DIR}` below is this skill's folder. It uses `nse-setup`'s
tools, which sit next to it.

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol INFY --entry 1612.50 --or-high 1610 --or-low 1596.20
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol SBIN --entry 812.35 --stop price:805 --target 2.5R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol TATASTEEL --entry 152.40 --stop pct:1 --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

`--now "2026-11-27 10:05"` pins the clock (IST).

## Stops and targets

| stop | where |
| --- | --- |
| `or-mid` (default) | opening-range midpoint, for an opening-range breakout. Needs `--or-high` and `--or-low` |
| `or-low` | opening-range low: wider, so fewer shares for the same max loss |
| `price:X` | your price |
| `pct:X` | X percent under the entry |

The stop rounds DOWN to the tick (`tick_size` in config, 0.05). The target
is `2R` by default (entry + 2 x risk), or `1.5R`, `3R`, `price:X`, rounded
to the nearest tick. Reward:risk here is before charges. nse-budget works it
out after charges for the real quantity, and that is the number nse-risk
enforces.

Refused, with the reason: a stop at or above the entry, a target at or under
it, a stop closer than 0.1% of the price, a blocked symbol, or any plan after
the flat-by time.

## Steps

1. Get the entry and, for a breakout, the opening range from the user or the
   setup. Never invent a price.
2. Run `exit.py plan ... --write`. Read back the entry, stop and its rule,
   target and its rule, risk a share and flat-by.
3. If it refuses, give the reason and the fix (a closer or wider stop, a
   farther target). Never move the stop yourself to make it pass.
4. Say once that a stop is a plan, not a guarantee: a gap can fill past it.
5. Hand off to nse-budget to size it.

## Rules

- Stop and target are set before the entry, never after.
- Once the trade is on, a stop never moves further from the entry.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never loosen a limit, widen a stop or edit an order to make it pass. Say the reason and the fix.
- Long, cash-equity only in Phase 1: no shorts, F&O or margin.
