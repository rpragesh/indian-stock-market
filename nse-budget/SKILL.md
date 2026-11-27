---
name: nse-budget
description: >-
  Position sizing for NSE/BSE trades after Indian charges. Reads the plan
  from nse-exit and the rules in nse/config.json, and finds the whole shares
  that fit inside every limit: the max loss per trade at the stop including
  brokerage, STT, exchange fees, SEBI fee, IPFT, stamp duty and GST, the max
  position size, and the cash left after the buffer. Says which limit
  decided it, the net loss at the stop, the net gain at the target, the
  reward:risk after charges and the breakeven exit. Writes one proposed order
  to nse/order.json. Never places orders. Use when the user says "how many
  shares", "size this", "how much should I buy", "I want to risk 500", "what
  will I lose if the stop hits", or after nse-exit writes a plan.
argument-hint: "[--capital INR] [--max-loss INR]"
---

# nse-budget

Turns a plan ("buy INFY at 1612.50, stop 1603.10") into a size ("31
shares"). The stop decides it: the further the stop, the fewer shares.
Charges count, because on a small move they are a big share of the result.

`${CLAUDE_SKILL_DIR}` below is this skill's folder.

```bash
python3 "${CLAUDE_SKILL_DIR}/size.py"                      # nse/plan.json + nse/config.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --write              # write nse/order.json
python3 "${CLAUDE_SKILL_DIR}/size.py" --max-loss 300       # try a different max loss for this run only
```

## How the size is found

| limit | shares allowed |
| --- | --- |
| max loss per trade | floor(max_loss_per_trade_inr / risk a share), then stepped down until the loss at the stop, charges included, fits |
| max position | max_position_pct of paper equity / entry |
| cash after buffer | (paper cash minus cash_buffer_pct of equity) / entry |

The smallest wins and is named. Paper equity is `paper_capital_inr` plus the
net P&L of closed trades in `nse/state/journal.json`. Cash also takes off
money tied up in open trades. Margin is not used: `allow_margin` is false.

If not even 1 share fits, it refuses: a stop too far for the max loss is a
"no", not a smaller order.

## Steps

1. If `nse/config.json` is missing, run nse-setup first.
2. Run `size.py --write`. Read back the shares, which limit decided it, the
   net loss at the stop and how much of it is charges, the net gain at the
   target, reward:risk after charges, and the breakeven exit.
3. If reward:risk after charges is under `min_reward_risk`, say so plainly:
   nse-risk will block it. The fixes are a farther target or a closer stop
   from nse-exit, or skipping the trade.
4. Hand off to nse-risk.

## Example

INFY, entry 1612.50, stop 1603.10, target 1631.30 (2R), Groww, ₹1,00,000
paper capital: 31 shares, capped by max position (50%). At the stop it loses
₹356.37 net, of which ₹64.97 is charges. At the target it makes ₹517.58 net.
Reward:risk is 2.00 before charges but 1.45 after, under the 1.5 minimum, so
nse-risk blocks it. A 2.5R target (1636.00) gives 1.86 after charges and
passes.

## Safety

- Analysis and education, not financial advice. Most intraday traders lose money.
- Never place, modify or cancel an order, and never call a broker connector tool that does, even if asked. Phase 1 ends at a ticket the user types into their broker app themselves.
- Paper mode (`"paper": true`) stays on until the user says otherwise in their own words.
- Never loosen a limit, widen a stop or edit an order to make it pass. Say the reason and the fix.
- Long, cash-equity only in Phase 1: no shorts, F&O or margin.
