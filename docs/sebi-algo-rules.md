# SEBI retail algo-trading rules and this skill pack

Notes, not legal advice. Last checked 2026-11-27. The sources below are
broker and press summaries, not the SEBI circular itself. Read the circular
before Phase 2 and update this page.

## The framework

- SEBI's circular "Safer participation of retail investors in Algorithmic
  trading" (February 2025) sets rules for retail clients who trade through
  broker APIs.
- It was due on 1 August 2025, was pushed to 1 October 2025 with a glide
  path, and has applied to all brokers since **1 April 2026**.
- What brokers report it means for a retail API user:
  - **Orders per second.** Up to 10 orders per second per exchange per
    client needs no separate strategy registration. Above that, the strategy
    must be registered with the exchange through the broker, and orders
    beyond the limit may be rejected.
  - **Algo ID.** Automated orders carry an exchange-assigned algo ID, so
    every order can be traced to a strategy and a broker.
  - **Static IP.** API orders are accepted only from a registered app
    mapped to a whitelisted static IP.
  - **Daily login.** A full two-factor login once every trading day. No
    long-lived refresh tokens.
  - **Broker responsibility.** The broker answers for every algo that runs
    through its systems. Algo providers cannot connect to the exchange
    directly.

## Where this pack sits

**Phase 1 (now) places no orders.** It reads market data, does maths and
writes an order ticket. You type the ticket into Groww or Kite yourself.
That is a manual order, not an API or algo order, so the framework's order
rules (order rate, algo ID, static IP) do not come into play.

To keep it that way:

1. No skill calls an order tool. Each SKILL.md says so.
2. You set the connector's order tools to **Never allow**, so a prompt
   cannot change that.
3. Paper mode is on until you say otherwise.

**Phase 2 (only if you decide to, later)** would place orders through the
broker's API. Before any work on it:

- Read the circular and the broker's current API rules (app registration,
  static IP, algo ID, daily 2FA, empanelment of third-party platforms).
- Decide whether orders go through the broker's own registered API app.
  No order should come from an unregistered route.
- Keep the order rate far below the threshold and keep your yes on every
  order.

## Sources

- [SEBI circular page](https://www.sebi.gov.in/legal/circulars/feb-2025/safer-participation-of-retail-investors-in-algorithmic-trading_91614.html) (not yet read for these notes)
- [Fyers: new SEBI rules for retail algo trading from 1 April 2026](https://support.fyers.in/portal/en/kb/articles/what-are-the-new-sebi-rules-for-retail-algo-trading-from-april-01-2026)
- [Business Standard: SEBI extends retail algo framework rollout to 2026](https://www.business-standard.com/markets/news/sebi-extends-retail-algo-trading-framework-rollout-to-2026-125093000956_1.html)
