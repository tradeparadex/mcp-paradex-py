# Features To-Do

Deferred tool proposals for future implementation.

---

## `paradex_pre_trade_check`

A compound tool that bundles everything an LLM needs to validate a trade idea before submitting an order: account health, current position in the target market, BBO for slippage estimation, and the market's min/max order constraints.

**Motivation:** Before placing an order the LLM typically needs four pieces of information spread across four separate tools. This tool fetches them all in one round-trip and surfaces a human-readable `ready_to_trade` flag.

**Proposed signature:**

```python
@server.tool(
    name="paradex_pre_trade_check",
    annotations=ToolAnnotations(readOnlyHint=True, requiresAuth=True),
)
async def pre_trade_check(
    market_id: Annotated[str, Field(description="Market symbol, e.g. 'BTC-USD-PERP'.")],
    side: Annotated[str, Field(description="'BUY' or 'SELL'.")],
    size: Annotated[float, Field(description="Desired position size in base asset units.")],
) -> dict:
    """
    Validate a trade idea before submitting an order.

    Returns:
    - account: free collateral, margin ratio, health status
    - current_position: existing position in this market (size, entry price, unrealized PnL)
    - bbo: best bid/ask to estimate entry price and slippage (from paradex_market_summaries)
    - market_constraints: tick size, min/max order size, max leverage
    - ready_to_trade: bool — True when account is healthy and size is within market limits
    """
```

**Implementation notes:**
- Fetches account summary, positions (filtered by `market_id`), market summary (has BBO + funding), and market details in parallel via `asyncio.gather`.
- `ready_to_trade` is `True` when: account health is not CRITICAL, free collateral > estimated margin for the order, and `size` is within `[min_order_size, max_order_size]`.
- Requires authentication.
- Note: `paradex_market_summaries` already includes `bid`, `ask`, `last_traded_price`, `funding_rate` — no need for separate BBO or funding calls.
