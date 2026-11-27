# Indian Stock Market skills

Claude skills for intraday trading on India's NSE and BSE. They scan charts,
read corporate announcements, plan entries and exits, replay a trade
thousands of times, size positions after every charge, and check each trade
against your limits.

> **Not financial advice.** This is a tool for analysis and learning. Most
> intraday traders lose money. You make every decision and place every
> order yourself.

## Phase 1: analysis only

- **No orders, ever.** No skill places, modifies or cancels an order. The
  last step is an order ticket that you type into Groww or Kite yourself.
- **Paper first.** Paper mode is on by default (₹1,00,000 of pretend money)
  and stays on until you say otherwise.
- **Real costs.** Every P&L is net of brokerage, STT, exchange charges, the
  SEBI fee, IPFT, stamp duty and GST.
- **IST clock.** Market hours are 09:15 to 15:30 IST. The broker's intraday
  square-off time is a setting, because brokers change it.
- **SEBI.** See [docs/sebi-algo-rules.md](docs/sebi-algo-rules.md) for how
  this stays inside SEBI's retail algo-trading framework (April 2026).

## Brokers

The skills don't depend on one broker. Groww is the default and Zerodha also
works. Set `"broker"` in `nse/config.json`. See
[docs/broker-setup.md](docs/broker-setup.md) to connect your broker's MCP
connector and block its order tools.

## Install

In Claude Code, as a plugin:

```
/plugin marketplace add rpragesh/indian-stock-market
/plugin install indian-stock-market@indian-stock-market
```

Or copy the folders into your skills directory, keeping them side by side,
because the other skills use `nse-setup`'s tools:

```bash
git clone https://github.com/rpragesh/indian-stock-market.git
cp -r indian-stock-market/nse-* ~/.claude/skills/
```

Needs Python 3.8 or newer. There is nothing to pip install.

## The skills

| skill | job | status |
| --- | --- | --- |
| `nse-setup` | Your rules, the broker connector, the IST market clock, and the charges calculator | ready |
| `nse-budget` | Position size from capital and max loss, after charges | planned |
| `nse-risk` | PASS or BLOCK against your limits | planned |
| `nse-exit` | Stop, target, and out before square-off | planned |
| `nse-ticket` | An order ticket you place yourself in your broker's app | planned |
| `nse-scanner` | Opening-range breakouts, flags and oversold bounces on NSE stocks | planned |
| `nse-entry` | Watches a setup bar by bar | planned |
| `nse-timemachine` | Replays the trade 10,000 times from recent candles | planned |
| `nse-alerts` | Price, stop, target and square-off reminders | planned |
| `nse-news` | NSE and BSE corporate announcements and headlines | planned |
| `nse-results` | Quarterly results summary | planned |
| `nse-insider` | Bulk and block deals, plus promoter and insider trades (SEBI PIT disclosures) | planned |

## Try the base layer

```bash
python3 nse-setup/market.py                                   # is the market open, can I enter, when must I be flat
python3 nse-setup/charges.py --buy 1000 --sell 1010 --qty 50  # every charge and the net P&L
python3 nse-setup/charges.py --buy 1000 --qty 50 --breakeven  # the exit price that nets zero
```

Your settings and trade files live in an `nse/` folder in your project.
Start with `cp nse-setup/config.example.json nse/config.json`, or ask Claude
to "set up nse".

## Tests

```bash
python3 -m unittest discover -s tests
```

Inspired by the structure of
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill),
rebuilt for Indian markets.
