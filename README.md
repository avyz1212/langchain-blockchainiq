# langchain-blockchainiq

LangChain tools for the [Blockchain IQ](https://www.blockchainiq.co/agents)
pay-per-call crypto data API — market briefs, event risk, macro indicators,
on-chain analytics and research that an agent buys **one call at a time**,
paid in USDC on Base with the open [x402](https://x402.org) standard.

No account. No API key. A wallet holding a little USDC is the only
credential.

Built for the
[Blockchain IQ x402 Build Bounties](https://blockchainiq.co/blog/x402-build-bounties)
(LangChain slot).

## The tools

| Tool | Resource | Price | Notes |
| --- | --- | --- | --- |
| `blockchainiq_catalog` | `GET /api/x402/v1` | free | Every resource, price and response shape |
| `blockchainiq_sample` | `GET /api/x402/v1/sample` | free | Bitcoin network activity, same envelope as paid data |
| `blockchainiq_brief` | `GET /api/x402/v1/brief` | **$0.01** | BTC/ETH/SOL/XRP brief, next-48h events, risk flags — **bounty-qualifying call** |
| `blockchainiq_event_risk` | `GET /api/x402/v1/event-risk` | **$0.05** | Market-moving events, `days` 1–90, `min_importance` 1–3 — **bounty-qualifying call** |
| `blockchainiq_get` | any `/api/x402/v1/*` path | per catalog | Generic access to all 26 resources (macro, dashboards, research, …) |

Paid calls return the data plus the **settlement proof** decoded from the
`PAYMENT-RESPONSE` header — payer, network and the on-chain transaction
hash — so an agent (or a bounty claim) can show exactly what was paid.

## Install

```bash
pip install -e .          # from this repository
# or, once published: pip install langchain-blockchainiq
```

Python 3.10+. Dependencies: `langchain-core`, `requests`, `eth-account`.

## Quickstart

```python
from blockchainiq_langchain import BlockchainIQClient, get_blockchainiq_tools

# Reads AGENT_PRIVATE_KEY / BIQ_MAX_PRICE_PER_CALL / BIQ_DRY_RUN from env.
tools = get_blockchainiq_tools()

# Bind to any LangChain chat model or agent executor:
#   model.bind_tools(tools)  /  create_agent(model, tools)
```

Or drive the client directly:

```python
client = BlockchainIQClient.from_env()
print(client.catalog().data)          # free
print(client.sample().data)           # free
result = client.brief()               # $0.01 via x402
print(result.data)
print(result.transaction_hash)        # settlement proof
```

### Wallet

Set `AGENT_PRIVATE_KEY` (the same variable name as Blockchain IQ's own
copy-paste example) to a **dedicated wallet holding a little USDC on
Base**. Settlement is gasless for the payer — the signature authorizes the
transfer and the server's facilitator submits it — so the wallet needs
USDC only, no ETH. Never use a main wallet.

### Dry-run mode (spend nothing)

```bash
BIQ_DRY_RUN=1 python examples/agent_demo.py
python examples/dry_run_demo.py
```

In dry-run mode a paid tool performs the (free) HTTP 402 probe, reads the
real price, builds the payment and verifies the signature locally — then
stops. The signed retry is never sent, so nothing can be charged. The
tool returns the payment preview instead: amount, asset, pay-to address
and network. This is the mode to demo, test or show a human before
approving spend. It works with no wallet at all (preview only, unsigned).

### Spend control

Every payment is checked against a per-call cap before signing
(`BIQ_MAX_PRICE_PER_CALL`, default **$0.60**, mirroring the spend control
in Blockchain IQ's own example). A resource priced above the cap is
refused with `SpendLimitError` and nothing is signed. HTTP 404 and other
error responses are never charged by the API.

### The real paid call

```bash
AGENT_PRIVATE_KEY=0x... python examples/paid_call.py --confirm
```

Makes exactly one paid call to `brief` ($0.01) and prints the settlement
proof including the transaction hash. The `--confirm` flag (or
`BIQ_CONFIRM_SPEND=1`) is required so the spend cannot happen by accident.

## How the payment works (protocol notes)

The client implements x402 protocol **version 2**, `exact` scheme, EVM:

1. `GET` the resource. A priced resource answers `402` with a
   `PAYMENT-REQUIRED` header: base64 JSON whose `accepts` array lists the
   price (`amount` in atomic units), the asset (USDC on Base,
   `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`), the `payTo` address and
   the token's EIP-712 domain hints (`extra.name`/`extra.version`).
2. The client selects the `eip155:*` exact requirement, checks the price
   against the spend cap, and signs an EIP-3009
   `transferWithAuthorization` EIP-712 message (domain taken from the
   server's own `extra` fields, chain id from the CAIP-2 network,
   verifying contract = the asset). Signing is local; nothing is
   broadcast by the client.
3. The request is retried with the payment in a `PAYMENT-SIGNATURE`
   header (base64 JSON: `x402Version`, the `accepted` requirement, and
   the `payload` with signature + authorization).
4. The `200` response carries a `PAYMENT-RESPONSE` header: base64 JSON
   with `success`, `transaction`, `network` and `payer` — the settlement
   proof this package decodes onto every paid result.

Solana rails offered by the API are skipped by this client (EVM only).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The suite runs fully offline against a fake transport that replays the
real 402 requirements document captured from the live server: payload
shape and signature recovery, the probe → sign → retry flow, dry-run
never sending, the spend cap refusing before signing, and 404s never
being retried or charged.

## Repository layout

```
src/blockchainiq_langchain/
    client.py    the x402 client (probe, pay, settle, dry-run, spend cap)
    payment.py   PAYMENT-REQUIRED parsing, EIP-3009 payload build/verify
    tools.py     the five LangChain tools
examples/
    dry_run_demo.py   full flow, zero spend (live free calls + signed preview)
    agent_demo.py     tools invoked through the LangChain interface
    paid_call.py      the one real $0.01 qualifying call, with proof output
tests/                offline pytest suite
```

## License

MIT. Market data and analysis from Blockchain IQ are not investment
advice; use of the API is covered by their
[terms](https://www.blockchainiq.co/terms).
