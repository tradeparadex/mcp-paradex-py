# OAuth 2.1 / SIWE Auth + Subkey Trading for MCP Paradex Server

## Deployment Context

The remote MCP server runs at **https://mcp.paradex.trade/mcp** on AWS Lambda
via the `Dockerfile.aws` image (Lambda Web Adapter + uvicorn, stateless HTTP mode).

---

## Background: Paradex Subkeys

Paradex supports **subkeys** — StarkNet keypairs registered against a main account that
can trade (place/cancel orders) but **cannot transfer or withdraw funds**. This is the
right primitive for the shared remote server: even full server compromise only risks
trading positions, not funds.

Key technical detail: a subkey is a random StarkNet keypair — unlike the main L2 key,
the account address **cannot be derived** from the subkey private key. The main account
address must be carried separately and passed explicitly in API requests
(`PARADEX-STARKNET-ACCOUNT` header).

---

## Who Signs What and Where

| Action | Who signs | Where | Key used |
|--------|-----------|-------|----------|
| SIWE login | User | Browser / wallet | L1 Ethereum private key |
| Subkey registration | User | Browser / wallet (part of SIWE flow) | L1 key (same signing ceremony) |
| Order payloads | MCP server | Inside Lambda | Subkey private key |
| Subkey JWT (`/v1/auth`) | MCP server | Inside Lambda | Subkey private key |

The user's wallet is involved **once** — the initial SIWE login. Everything after that
is server-side using the subkey.

---

## How the Server Gets the Subkey Private Key

The server **generates** it — no key is ever sent from the user.

```python
import secrets
from starknet_py.net.signer.stark_curve_signer import StarkCurveSigner

subkey_private = hex(secrets.randbelow(StarkCurveSigner.CURVE.order))
subkey_public  = StarkCurveSigner(subkey_private).public_key
```

The private key is created inside the Lambda, stored in Secrets Manager, never transmitted.
The user only ever sees the public key.

---

## Subkey Registration: Why the Server Cannot Do It Alone

Registration must be signed by the user's main account key. The server holds neither
the user's L1 Ethereum key nor their L2 StarkNet key.

```
POST /v1/account/subkeys
Authorization: Bearer <jwt>
{
  "name":      "mcp-server",
  "public_key": subkey_public,
  "signature":  sign(registration_payload, user_main_key)  ← only user can provide
}
```

The `INVALID_STARKNET_SIGNATURE` error code on this endpoint confirms that a signature
from the user's main key is required beyond the Bearer JWT.

**Solution:** fold subkey registration into the OAuth authorization flow. The user signs
once with their wallet — that single signature covers both SIWE authentication and subkey
registration. No separate step, no elicitation.

---

## OAuth 2.1: One Login, No Re-auth Until Logout

Paradex currently issues JWTs expiring in 5 minutes with no refresh mechanism, requiring
wallet re-signing every ~3 minutes. OAuth 2.1 Authorization Code + PKCE with refresh
tokens solves this: the wallet signs once, a long-lived refresh token handles all
subsequent access token renewals silently.

---

## Full Flow

### Phase 1 — First-Time Login + Subkey Registration (one browser interaction)

The MCP server generates the subkey *before* redirecting. The AS includes the subkey
public key in the SIWE message the user signs, registering it in one ceremony.

```
MCP Client (Claude Desktop)
      │
      │  ① Discover AS:
      │    GET https://mcp.paradex.trade/.well-known/oauth-protected-resource
      │    ← { authorization_servers: ["https://auth.paradex.trade"] }
      │
      │  ② GET https://auth.paradex.trade/.well-known/oauth-authorization-server
      │    ← { authorization_endpoint, token_endpoint, jwks_uri, ... }
      │
      ▼
MCP Server  (pre-login hook)
      │
      │  ③ generate subkey keypair
      │     subkey_private → store in Secrets Manager immediately
      │     subkey_public  → include in authorization URL
      │
      │  ④ redirect client browser to:
      │     GET https://auth.paradex.trade/authorize
      │       ?client_id=mcp-paradex
      │       &redirect_uri=https://mcp.paradex.trade/callback
      │       &code_challenge=<PKCE>
      │       &subkey=<subkey_public>    ← AS will embed this in the SIWE message
      │
      ▼
Paradex Authorization Server  (user's browser)
      │
      │  ⑤ show login page: "Sign in and authorize MCP trading key"
      │     construct SIWE message including subkey_public in the payload
      │
      │  ⑥ user signs EIP-4361 with wallet  ← only wallet interaction ever
      │
      │  ⑦ AS validates SIWE signature
      │     registers { account_address, subkey_public } as subkey  ← done here
      │     issues authorization code
      │
      │  ⑧ redirect → https://mcp.paradex.trade/callback?code=...
      │
      ▼
MCP Server
      │
      │  ⑨ POST https://auth.paradex.trade/token
      │     { code, code_verifier }
      │     ← { access_token (5 min), refresh_token (long-lived) }
      │
      │  access_token delivered to MCP client
      │  refresh_token stored by client for silent renewal
      │  subkey_private already in Secrets Manager from step ③
      │
      └─ trading ready
```

---

### Phase 2 — Silent Token Refresh (every ~3 min, no user interaction)

```
MCP Client
      │  POST https://auth.paradex.trade/token
      │  { grant_type: refresh_token, refresh_token: <stored> }
      ▼
Paradex AS
      │  ← { access_token: <new>, refresh_token: <new> }  (old refresh token rotated)
      ▼
Client stores new tokens. User sees nothing.
```

---

### Phase 3 — Per-Request Read Operation

```
MCP Client
      │  POST https://mcp.paradex.trade/mcp
      │  Authorization: Bearer <access_token>
      │  tools/call: paradex_account_positions
      ▼
MCP Server
  validate access_token via JWKS → account_address
  subkey_jwt = get_subkey_jwt(account_address)   ← cache hit or re-auth (see below)
  client.set_token(subkey_jwt)
      │
      ▼
Paradex REST API  GET /v1/positions
Authorization: Bearer <subkey_jwt>
      │
      ▼
{ positions: [...] } → MCP response
```

---

### Phase 4 — Per-Request Order Placement

```
MCP Client
      │  POST https://mcp.paradex.trade/mcp
      │  Authorization: Bearer <access_token>
      │  tools/call: paradex_create_order  { market, side, size, price }
      ▼
MCP Server
  validate access_token via JWKS → account_address
  subkey_private = get_from_secrets_manager(account_address)
  subkey_jwt     = get_subkey_jwt(account_address)
  account = ParadexAccount(
      l1_address     = account_address,   ← main account; cannot be derived from subkey
      l2_private_key = subkey_private
  )
  client.init_account(account)
  client.create_order(params)
      │  sign order payload with subkey_private  ← inside Lambda
      ▼
Paradex REST API  POST /v1/orders
Authorization: Bearer <subkey_jwt>
Body: { ...params, signature: <subkey_signature> }
      │
  Paradex validates:
    subkey_jwt valid ✓  subkey registered to account ✓  signature from subkey ✓
    subkey cannot withdraw/transfer ✓
      ▼
{ order_id } → MCP response
```

---

### Phase 5 — Logout

```
MCP Client
      │  POST https://auth.paradex.trade/token/revoke
      │  { refresh_token: <stored> }
      ▼
Paradex AS  invalidates refresh_token — all future silent refreshes fail
      │
      ▼
Client clears stored tokens. Next use requires full SIWE login again.
```

---

## Two JWTs: Roles and Lifetimes

| Token | Issued by | Held by | Used for | Refresh |
|-------|-----------|---------|----------|---------|
| `access_token` | Paradex AS (OAuth) | MCP client | Identify user at MCP server boundary; **never forwarded to Paradex REST API** | Client calls `/token` with `refresh_token`; no wallet needed |
| `subkey_jwt` | Paradex REST API (`/v1/auth`) | MCP server | All Paradex REST API calls (reads + writes) | Server re-signs with `subkey_private`; cached 3 min per warm Lambda container |

The `access_token` is validated **locally** on the MCP server via JWKS — no Paradex API
call for validation.

---

## Subkey JWT: Server-Side Cache and Refresh

```python
@dataclass
class _JwtCacheEntry:
    jwt: str
    cached_at: float

_subkey_jwt_cache: dict[str, _JwtCacheEntry] = {}  # cleared on Lambda cold start

async def get_subkey_jwt(account_address: str) -> str:
    entry = _subkey_jwt_cache.get(account_address)
    if entry and time.monotonic() - entry.cached_at < 180:  # 3 min TTL
        return entry.jwt
    subkey_private = await secrets_manager_get(f"paradex-subkeys/{account_address}")
    jwt = await paradex_auth_with_subkey(account_address, subkey_private)
    _subkey_jwt_cache[account_address] = _JwtCacheEntry(jwt, time.monotonic())
    return jwt
```

Cold start cost: ~20ms Secrets Manager read + `/v1/auth` round-trip per account,
then cached for 3 min within the warm container.

---

## Key Storage (AWS Secrets Manager)

```
Key:   paradex-subkeys/{account_address}
Value: { "private_key": "0x..." }
```

IAM: Lambda execution role scoped to `secretsmanager:GetSecretValue` and
`secretsmanager:PutSecretValue` on `paradex-subkeys/*` only.

For development: `SUBKEY_STORAGE_BACKEND=memory` uses an in-process dict (lost on cold start).

---

## Security Properties

| Threat | Impact | Mitigation |
|--------|--------|------------|
| Lambda fully compromised | Attacker trades on all registered accounts | Subkeys cannot withdraw/transfer; fund loss impossible |
| Subkey private key exfiltrated | Attacker trades until revoked | User revokes at Paradex; no fund loss |
| `access_token` intercepted | Attacker calls MCP tools for up to 5 min | Short TTL; HTTPS only |
| `refresh_token` stolen | Attacker silently refreshes access tokens | Single-use rotation; revoked on logout |
| Forged `account_address` in token | Server looks up wrong subkey; Paradex rejects order | AS signs tokens; server validates via JWKS |
| Subkey registered to wrong account | Impossible — AS controls registration at login | AS binds subkey to authenticated account_address |

---

## What Paradex Needs to Build

### OAuth 2.1 Authorization Server (`auth.paradex.trade`)

- [ ] `GET  /authorize` — Authorization Code + PKCE; SIWE as authentication method;
      accept `subkey` parameter, embed it in SIWE message, register on sign
- [ ] `POST /token` — `authorization_code` and `refresh_token` grant types; rotate refresh tokens
- [ ] `POST /token/revoke` — RFC 7009
- [ ] `GET  /.well-known/oauth-authorization-server` — RFC 8414 metadata
- [ ] `GET  /.well-known/jwks.json` — public keys so MCP server can validate access tokens locally

### Paradex REST API clarification

- [ ] Confirm exact signature scheme for `POST /v1/account/subkeys`
      (if handled by AS at login, this endpoint may only be needed for re-registration /
      manual registration outside the OAuth flow)

---

## What the MCP Server Needs to Build (this repo)

- [ ] Pre-login hook: generate subkey, store in Secrets Manager, append `&subkey=` to `/authorize` redirect
- [ ] `GET /callback` — OAuth callback handler; exchange code for tokens
- [ ] `get_subkey_jwt(account_address)` — 3-min in-memory cache + auto re-auth
- [ ] `get_signing_paradex_client(account_address)` — subkey lookup + `ParadexAccount` construction
- [ ] `paradex_revoke_trading` tool — calls `DELETE /v1/account/subkeys/{public_key}`, removes from Secrets Manager
- [ ] JWT validation via JWKS (replace current "trust and forward" approach)
- [ ] `WWW-Authenticate` header on expired/invalid token errors

---

## What the MCP Server Already Has

| Feature | Status |
|---------|--------|
| `BearerAuthMiddleware` (extracts token → ContextVar) | ✅ Done |
| `OAuthResourceMetadataMiddleware` (RFC 9728) | ✅ Done |
| `_make_jwt_client()` — read tools work today | ✅ Done |
| `PARADEX_JWT_TOKEN` — static JWT for stdio/local use | ✅ Done |

---

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `PARADEX_ACCOUNT_PRIVATE_KEY` | L1 key — single-user stdio/local deployments | `0x...` |
| `PARADEX_JWT_TOKEN` | Static JWT — non-HTTP / stdio deployments | `eyJ...` |
| `MCP_SERVER_URL` | Canonical URL of this MCP server | `https://mcp.paradex.trade` |
| `PARADEX_AUTH_SERVER_URL` | Paradex OAuth AS base URL | `https://auth.paradex.trade` |
| `SUBKEY_STORAGE_BACKEND` | `secrets_manager` or `memory` | `secrets_manager` |

## Production Config (mcp.paradex.trade)

```bash
MCP_TRANSPORT=streamable-http
MCP_STATELESS=true
MCP_SERVER_URL=https://mcp.paradex.trade
PARADEX_AUTH_SERVER_URL=https://auth.paradex.trade
PARADEX_ENVIRONMENT=prod
SUBKEY_STORAGE_BACKEND=secrets_manager
```
