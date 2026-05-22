"""
Block-trade tools — OTC block trades on Paradex.

A block trade is an off-exchange-style match between two or more accounts that
clears via Paradex. The lifecycle is:

  1. Initiator creates a block with trade constraints (price/size bounds).
  2. Counterparties submit offers committing to fills within those bounds.
  3. Initiator selects accepted offers and executes the block.

Block trades are signed under SNIP-12 schema v2 (rev "1"). The signing happens
locally via the account helpers in `paradex_py.account.account`. None of these
tools require sharing your private key.
"""

import time
import uuid
from decimal import Decimal
from typing import Annotated, Any

from mcp.server.fastmcp.server import Context
from mcp.types import ToolAnnotations
from paradex_py.api.generated.requests import (
    BlockExecuteRequest,
    BlockOfferInfo,
    BlockOfferRequest,
    BlockTradeInfo,
    BlockTradeRequest,
)
from paradex_py.api.generated.responses import (
    BlockTradeConstraints,
    BlockTradeOrder,
)
from paradex_py.message.block_trades import (
    BlockTrade as BlockTradeMsg,
)
from paradex_py.message.block_trades import (
    BlockTradeOffer as BlockTradeOfferMsg,
)
from paradex_py.message.block_trades import (
    BlockTradeOrder as BlockTradeOrderMsg,
)
from paradex_py.message.block_trades import (
    Trade,
)
from pydantic import Field

from mcp_paradex.models import (
    BlockTrade,
    OrderSideEnum,
)
from mcp_paradex.server.server import server
from mcp_paradex.utils.ctx import ctx_info
from mcp_paradex.utils.errors import check_response
from mcp_paradex.utils.paradex_client import get_authenticated_paradex_client

_DEFAULT_EXPIRATION_MINUTES = 5


def _ms_from_now(minutes: int) -> int:
    return int(time.time() * 1000) + minutes * 60 * 1000


def _dec(value: float | str | None) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else Decimal(0)


@server.tool(
    name="paradex_block_trade_list",
    title="List Block Trades or Offers",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def list_block_trades(
    block_trade_id: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "If set, returns the offers submitted against this block trade. "
                "If None, returns the list of block trades matching status/market."
            ),
        ),
    ],
    status: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Filter blocks by status (CREATED, OFFER_COLLECTION, READY_TO_EXECUTE, "
                "EXECUTING, PENDING_SETTLEMENT, COMPLETED, FAILED, CANCELLED). "
                "Ignored when block_trade_id is set."
            ),
        ),
    ],
    market: Annotated[
        str | None,
        Field(
            default=None,
            description="Filter blocks by market symbol. Ignored when block_trade_id is set.",
        ),
    ],
    ctx: Context,
) -> dict[str, Any]:
    """
    List block trades or the offers attached to a specific block trade.

    - Pass nothing (or status/market filters) to list block trades.
    - Pass `block_trade_id` to list offers submitted against that block.

    Returns the raw paginated response from the corresponding endpoint.
    """
    client = await get_authenticated_paradex_client()
    if block_trade_id is not None:
        response = client.get_block_trade_offers(block_trade_id)
        return await check_response(ctx, response, path=f"block-trades/{block_trade_id}/offers")  # type: ignore[no-any-return]
    response = await check_response(
        ctx, client.list_block_trades(status=status, market=market), path="block-trades"
    )
    return response  # type: ignore[no-any-return]


@server.tool(
    name="paradex_block_trade_get",
    title="Get Block Trade",
    annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
)
async def get_block_trade(
    block_trade_id: Annotated[str, Field(description="Block trade ID (UUID).")],
    ctx: Context,
) -> BlockTrade:
    """
    Fetch full details for a block trade including its trades, signers, and signatures.
    """
    client = await get_authenticated_paradex_client()
    response = client.get_block_trade(block_trade_id)
    # The SDK returns the BlockTradeDetailFullResponse model directly; raw error envelopes
    # only come back from the underlying HTTP layer (handled by api_call).
    return response


@server.tool(
    name="paradex_block_trade_cancel",
    title="Cancel Block Trade",
    annotations=ToolAnnotations(destructiveHint=True),
)
async def cancel_block_trade(
    block_trade_id: Annotated[str, Field(description="Block trade ID to cancel.")],
    ctx: Context,
) -> dict[str, Any]:
    """
    Cancel a block trade you initiated. Only the initiator can cancel.
    """
    client = await get_authenticated_paradex_client()
    response = await check_response(
        ctx,
        client.cancel_block_trade(block_trade_id),
        path=f"block-trades/{block_trade_id}",
    )
    await ctx_info(
        ctx,
        f"Cancelled block trade {block_trade_id}",
        logger_name="paradex.block_trades",
    )
    return response  # type: ignore[no-any-return]


@server.tool(
    name="paradex_block_trade_cancel_offer",
    title="Cancel Block Trade Offer",
    annotations=ToolAnnotations(destructiveHint=True),
)
async def cancel_block_trade_offer(
    block_trade_id: Annotated[str, Field(description="Parent block trade ID.")],
    offer_id: Annotated[str, Field(description="Offer ID to cancel.")],
    ctx: Context,
) -> dict[str, Any]:
    """
    Cancel an offer you submitted against a block trade.
    """
    client = await get_authenticated_paradex_client()
    response = await check_response(
        ctx,
        client.cancel_block_trade_offer(block_trade_id, offer_id),
        path=f"block-trades/{block_trade_id}/offers/{offer_id}",
    )
    return response  # type: ignore[no-any-return]


@server.tool(
    name="paradex_block_trade_create_offer_based",
    title="Create Offer-Based Block Trade",
    annotations=ToolAnnotations(destructiveHint=True),
)
async def create_offer_based_block_trade(
    market_id: Annotated[str, Field(description="Market symbol, e.g. 'BTC-USD-PERP'.")],
    min_price: Annotated[str, Field(description="Minimum acceptable price (string decimal).")],
    max_price: Annotated[str, Field(description="Maximum acceptable price (string decimal).")],
    min_size: Annotated[str, Field(description="Minimum size offerers may fill.")],
    max_size: Annotated[str, Field(description="Maximum size offerers may fill.")],
    counterparty_accounts: Annotated[
        list[str],
        Field(
            description=(
                "Paradex account addresses that may submit offers. Use [] for an open block."
            ),
        ),
    ],
    expiration_minutes: Annotated[
        int,
        Field(
            default=_DEFAULT_EXPIRATION_MINUTES,
            description="Minutes from now until the block expires.",
            gt=0,
        ),
    ],
    ctx: Context,
) -> BlockTrade:
    """
    Create a new offer-based block trade (initiator-side).

    You commit to a price/size range; counterparties later submit offers and
    you execute the ones you accept. The block is signed locally with your
    Paradex account key — no private material leaves this process.

    Single-leg blocks only; multi-leg blocks require additional coordination
    outside this tool.
    """
    client = await get_authenticated_paradex_client()
    if client.account is None:
        raise ValueError("Block trades require a signing account; set PARADEX_ACCOUNT_PRIVATE_KEY.")

    nonce = str(time.time_ns())
    expiration_ms = _ms_from_now(expiration_minutes)
    trade_id = str(uuid.uuid4())

    # Build the on-chain Trade as a pure constraint (no fills yet — offerers add those).
    constraint_trade = Trade(
        market=market_id,
        min_size=_dec(min_size),
        max_size=_dec(max_size),
        min_price=_dec(min_price),
        max_price=_dec(max_price),
    )
    block_msg = BlockTradeMsg(
        nonce=nonce,
        expiration=expiration_ms,
        trades=[constraint_trade],
    )
    signature = client.account.build_block_trade_signature(block_msg)

    required_signers = [client.account.l2_address, *counterparty_accounts]
    request = BlockTradeRequest(
        block_expiration=expiration_ms,
        nonce=nonce,
        required_signers=required_signers,
        signatures={client.account.l2_address: signature},
        trades={
            trade_id: BlockTradeInfo(
                trade_constraints=BlockTradeConstraints(
                    max_price=max_price,
                    max_size=max_size,
                    min_price=min_price,
                    min_size=min_size,
                ),
            )
        },
    )
    response = client.create_block_trade(request)
    await ctx_info(
        ctx,
        f"Created block trade for {market_id} {min_size}-{max_size} @ {min_price}-{max_price}",
        logger_name="paradex.block_trades",
    )
    return response


@server.tool(
    name="paradex_block_trade_submit_offer",
    title="Submit Block Trade Offer",
    annotations=ToolAnnotations(destructiveHint=True),
)
async def submit_block_trade_offer(
    block_trade_id: Annotated[str, Field(description="Parent block trade ID.")],
    market_id: Annotated[str, Field(description="Market symbol of the offered fill.")],
    side: Annotated[OrderSideEnum, Field(description="Your side of the trade (BUY or SELL).")],
    price: Annotated[
        str, Field(description="Offered fill price (must respect block constraints).")
    ],
    size: Annotated[str, Field(description="Offered fill size.")],
    order_type: Annotated[
        str,
        Field(default="LIMIT", description="Order type for the offered leg (typically 'LIMIT')."),
    ],
    expiration_minutes: Annotated[
        int,
        Field(
            default=_DEFAULT_EXPIRATION_MINUTES,
            description="Minutes until the offer expires.",
            gt=0,
        ),
    ],
    ctx: Context,
) -> BlockTrade:
    """
    Submit an offer to an existing block trade as a counterparty.

    Your offer commits you to filling at the given price/size on the given
    side. The offer is signed locally and submitted; the initiator may then
    accept or ignore it.
    """
    client = await get_authenticated_paradex_client()
    if client.account is None:
        raise ValueError("Block-trade offers require a signing account.")

    nonce = str(time.time_ns())
    expiration_ms = _ms_from_now(expiration_minutes)
    offer_trade_id = str(uuid.uuid4())

    # The offerer signs a Trade where their side is the maker_order (server convention).
    maker_order_msg = BlockTradeOrderMsg(
        account=client.account.l2_address,
        side=str(side),
        order_type=order_type,
        size=_dec(size),
        price=_dec(price),
    )
    trade_msg = Trade.fill(
        market=market_id,
        price=_dec(price),
        size=_dec(size),
        maker_order=maker_order_msg,
        taker_order=BlockTradeOrderMsg(),  # initiator fills this side at execute time
    )
    offer_msg = BlockTradeOfferMsg(
        nonce=nonce,
        expiration=expiration_ms,
        block_trade_id=block_trade_id,
        trades=[trade_msg],
    )
    signature = client.account.build_block_trade_offer_signature(offer_msg)

    request = BlockOfferRequest(
        nonce=nonce,
        offering_account=client.account.l2_address,
        signature=signature,
        trades={
            offer_trade_id: BlockOfferInfo(
                offerer_order=BlockTradeOrder.model_validate(
                    {
                        "account": client.account.l2_address,
                        "side": str(side),
                        "type": order_type,
                        "size": size,
                        "price": price,
                        "client_id": "",
                        "flags": [],
                        "market": market_id,
                        "signature": signature.signature_data,
                        "signature_timestamp": int(time.time() * 1000),
                    }
                ),
                price=price,
                size=size,
            )
        },
    )
    response = client.create_block_trade_offer(block_trade_id, request)
    await ctx_info(
        ctx,
        f"Submitted offer on block {block_trade_id}: {side} {size} {market_id} @ {price}",
        logger_name="paradex.block_trades",
    )
    return response


@server.tool(
    name="paradex_block_trade_execute",
    title="Execute Block Trade",
    annotations=ToolAnnotations(destructiveHint=True),
)
async def execute_block_trade(
    block_trade_id: Annotated[str, Field(description="Block trade ID to execute.")],
    offer_ids: Annotated[
        list[str],
        Field(
            description=(
                "Offer IDs to accept and include in this execution. Pass [] for "
                "direct block trades that have no offers."
            ),
        ),
    ],
    expiration_minutes: Annotated[
        int,
        Field(
            default=_DEFAULT_EXPIRATION_MINUTES,
            description="Minutes the execution signature stays valid.",
            gt=0,
        ),
    ],
    ctx: Context,
) -> BlockTrade:
    """
    Execute a block trade as the initiator.

    For offer-based blocks, pass the IDs of offers you've decided to accept;
    each offer is fetched and the executor signature is built per offer. For
    direct block trades, pass an empty `offer_ids` list and the block itself
    is signed.
    """
    client = await get_authenticated_paradex_client()
    if client.account is None:
        raise ValueError("Block-trade execution requires a signing account.")

    nonce = str(time.time_ns())

    if offer_ids:
        offers = [client.get_block_trade_offer(block_trade_id, oid) for oid in offer_ids]
        signatures = client.account.build_executor_signatures_for_offers(
            offers, expiration_minutes=expiration_minutes
        )
        selected_offers: list[str] | None = list(offer_ids)
    else:
        block = client.get_block_trade(block_trade_id)
        signatures = client.account.build_executor_signature_for_block(
            block, expiration_minutes=expiration_minutes
        )
        selected_offers = None

    request = BlockExecuteRequest(
        execution_nonce=nonce,
        selected_offers=selected_offers,
        signatures=signatures,
    )
    response = client.execute_block_trade(block_trade_id, request)
    await ctx_info(
        ctx,
        f"Executed block trade {block_trade_id} with offers {offer_ids or 'direct'}",
        logger_name="paradex.block_trades",
    )
    return response
