# Connecting your broker

The skills read quotes, candles, holdings and positions through your
broker's MCP connector. Groww is the default and Zerodha also works. Pick
yours with `"broker"` in `nse/config.json`.

## Groww

1. In Claude, open **Settings → Connectors → Add custom connector**.
2. Name: `GrowwMCP`. URL: `https://mcp.groww.in/mcp`. Save.
3. Click **Connect** and log in to Groww in the browser window.
4. In a new chat, try: "Show my Groww holdings".

Groww calls its connector early-stage. It lists holdings, positions and
daily candles. Whether it gives live quotes and intraday candles is not
confirmed yet. The data skills will check this before relying on it.
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
