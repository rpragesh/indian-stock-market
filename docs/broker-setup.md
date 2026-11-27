# Connecting your broker

The skills read quotes, candles, holdings and positions through your
broker's MCP connector. Groww is the default and Zerodha also works. Pick
yours with `"broker"` in `nse/config.json`.

## Groww

1. In Claude, open **Settings → Connectors → Add custom connector**.
2. Name: `GrowwMCP`. URL: `https://mcp.groww.in/mcp`. Save.
3. Click **Connect** and log in to Groww in the browser window.
4. In a new chat, try: "Show my Groww holdings".

Checked on 27 Nov 2026: the connector gives live prices (`get_ltp`, up to
50 names a call), bid/ask depth (`get_quotes_and_depth`), and OHLCV candles
(`fetch_historical_candle_data`) at 1 to 240 minutes going back 90 days,
and daily candles for 5 years. It also has screeners and market-mover lists
that nse-scanner uses for a shortlist. Groww calls it early-stage.
Source: [Groww MCP announcement](https://groww.in/updates/groww-mcp).

## Zerodha

1. In Claude, open **Settings → Connectors → Add custom connector**.
2. Name: `Kite`. URL: `https://mcp.kite.trade/mcp`. Save.
3. In a chat, ask Claude to "log in to Kite" and open the link it gives you.
4. The login lasts one trading day, so repeat step 3 each morning.

Source: [Kite MCP server](https://github.com/zerodha/kite-mcp-server).

## Do this for either broker: block the order tools

Both connectors can place orders. Phase 1 never does. Open the connector's
settings in Claude and set every tool that places, modifies or cancels an
order (including GTT and basket orders) to **Never allow**. Leave the
read-only tools (quotes, candles, holdings, positions, instruments) on.
