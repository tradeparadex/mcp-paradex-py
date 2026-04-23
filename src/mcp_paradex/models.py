"""
Pydantic models for the MCP Paradex application.

SDK-published models are re-exported under their legacy names so tool files
need no import changes. Custom/composite models with no SDK equivalent are
defined locally.
"""

from __future__ import annotations

from typing import Annotated, Any

from paradex_py.api.generated.responses import (
    AccountInfoResponse,
    ApiToken,
    Greeks,
    Subkey,
)
from paradex_py.api.generated.responses import (
    AccountSummaryResponse as AccountSummary,
)
from paradex_py.api.generated.responses import (
    BalanceResp as Balance,
)
from paradex_py.api.generated.responses import (
    BBOResp as BBO,  # noqa: N814
)
from paradex_py.api.generated.responses import (
    FillResult as Fill,
)
from paradex_py.api.generated.responses import (
    FundingDataResult as FundingData,
)
from paradex_py.api.generated.responses import (
    GetAccountMarginConfigsResp as AccountMarginConfig,
)
from paradex_py.api.generated.responses import (
    MarketResp as MarketDetails,
)
from paradex_py.api.generated.responses import (
    MarketSummaryResp as MarketSummary,
)
from paradex_py.api.generated.responses import (
    OrderInstruction as InstructionEnum,
)
from paradex_py.api.generated.responses import (
    OrderResp as OrderState,
)
from paradex_py.api.generated.responses import (
    OrderSide as OrderSideEnum,
)
from paradex_py.api.generated.responses import (
    OrderType as OrderTypeEnum,
)
from paradex_py.api.generated.responses import (
    PortfolioMarginParamsResp as PortfolioMarginAssetConfig,
)
from paradex_py.api.generated.responses import (
    PortfolioMarginScenarioResp as PortfolioMarginScenario,
)
from paradex_py.api.generated.responses import (
    PositionResp as Position,
)
from paradex_py.api.generated.responses import (
    Strategy as VaultStrategy,
)
from paradex_py.api.generated.responses import (
    TradeResult as Trade,
)
from paradex_py.api.generated.responses import (
    TransactionResponse as Transaction,
)
from paradex_py.api.generated.responses import (
    VaultAccountSummaryResp as VaultAccountSummary,
)
from paradex_py.api.generated.responses import (
    VaultResp as Vault,
)
from paradex_py.api.generated.responses import (
    VaultSummaryResp as VaultSummary,
)
from paradex_py.api.generated.responses import (
    VolShockParamsResp as PortfolioMarginVolShock,
)
from pydantic import BaseModel, Field


# System models
class SystemState(BaseModel):
    """Model representing the current state of the Paradex system."""

    status: str
    timestamp: int = Field(default=0)


class VaultBalance(BaseModel):
    """Model representing the balance of a vault."""

    token: Annotated[str, Field(description="Name of the token")]
    size: Annotated[str, Field(description="Balance amount of settlement token")]
    last_updated_at: Annotated[int, Field(description="Balance last updated time")]


# Paginated response models
class PagedMarketDetails(BaseModel):
    """Paginated list of market details."""

    results: list[MarketDetails]
    total: int
    limit: int
    offset: int


class PagedMarketSummaries(BaseModel):
    """Paginated list of market summaries."""

    results: list[MarketSummary]
    total: int
    limit: int
    offset: int


class PagedVaults(BaseModel):
    """Paginated list of vaults."""

    results: list[Vault]
    total: int
    limit: int
    offset: int


class PagedVaultSummaries(BaseModel):
    """Paginated list of vault summaries."""

    results: list[VaultSummary]
    total: int
    limit: int
    offset: int


class PagedOrderStates(BaseModel):
    """Paginated list of order states."""

    results: list[OrderState]
    total: int
    limit: int
    offset: int


# Account credential model (combines two SDK types)
class AccountCredentials(BaseModel):
    """All credentials registered for this account."""

    subkeys: list[Subkey] = Field(description="Paradex subkeys used for on-chain signing.")
    tokens: list[ApiToken] = Field(description="API tokens (JWTs / API keys) for REST access.")



class SystemConfigResult(BaseModel):
    """System configuration combined with portfolio margin parameters."""

    config: dict[str, Any]
    portfolio_margin: list[PortfolioMarginAssetConfig]


# Composite overview models
class AccountOverview(BaseModel):
    """Complete account snapshot with margin health, token balances, and open positions."""

    summary: AccountSummary
    balances: list[Balance]
    positions: list[Position]
    info: AccountInfo | None = Field(
        default=None, description="Account fees, kind, and isolation mode."
    )
    margin: AccountMarginConfig | None = Field(
        default=None, description="Margin methodology and per-market leverage config."
    )


class VaultOverview(BaseModel):
    """Complete vault operational snapshot with token balances, open positions, and account health."""

    balances: list[VaultBalance]
    positions: list[Position]
    account_summary: list[VaultAccountSummary]


class PreTradeMarketConstraints(BaseModel):
    """Market-level trading constraints relevant to a pre-trade check."""

    min_notional: float
    order_size_increment: str
    position_limit: float
    price_tick_size: float


class PreTradeBBO(BaseModel):
    """Best bid/offer snapshot used to estimate entry price and slippage."""

    bid: str
    ask: str
    mark_price: str
    funding_rate: str


class PreTradeEstimates(BaseModel):
    """Estimated financial impact of the proposed order.

    All monetary values are in USDC. Fee and funding estimates are approximations
    — actual fees depend on the account's volume-based fee tier.
    """

    estimated_entry_price: float = Field(
        description="Best available execution price (ask for BUY, bid for SELL)"
    )
    estimated_fee_usdc: float = Field(
        description="Estimated taker fee in USDC assuming default 0.05% taker rate"
    )
    slippage_bps: float = Field(
        description="Half-spread slippage from mid price, in basis points (1 bps = 0.01%)"
    )
    daily_funding_cost_usdc: float = Field(
        description=(
            "Estimated daily funding payment in USDC at the current 8h funding rate "
            "(negative = cost for longs / revenue for shorts when funding is positive)"
        )
    )
    break_even_price_change_pct: float = Field(
        description=("Minimum price move required to cover round-trip taker fees, as a percentage")
    )
    existing_unrealized_pnl_usdc: float | None = Field(
        default=None,
        description="Unrealized PnL of the existing position in this market (trading + funding)",
    )


class PreTradeCheckResult(BaseModel):
    """Result of a pre-trade readiness check for a specific market and order size."""

    market_id: str
    side: str
    size: float
    account_status: str
    free_collateral: str
    current_position: Position | None
    bbo: PreTradeBBO
    market_constraints: PreTradeMarketConstraints
    estimates: PreTradeEstimates
    ready_to_trade: bool
    not_ready_reasons: list[str]


class GeneratedSubkey(BaseModel):
    """Result of a locally generated Paradex subkey."""

    name: str = Field(description="Label for the generated key")
    public_key: str = Field(description="Paradex public key in hex format (0x...)")


# Type alias for backward-compat in tool files
AccountInfo = AccountInfoResponse
