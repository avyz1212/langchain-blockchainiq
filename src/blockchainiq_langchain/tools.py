"""LangChain tools for the Blockchain IQ x402 data API.

Five tools expose the API to any LangChain agent:

==============  ============================  ==========================
Tool            Resource                      Price
==============  ============================  ==========================
catalog         GET /api/x402/v1              free
sample          GET /api/x402/v1/sample       free
brief           GET /api/x402/v1/brief        $0.01 (bounty-qualifying)
event_risk      GET /api/x402/v1/event-risk   $0.05 (bounty-qualifying)
get             any /api/x402/v1/* path       per the catalog
==============  ============================  ==========================

Paid tools pay in USDC on Base through x402 (see :mod:`.client`). With
``dry_run`` enabled — or no wallet configured — a paid tool returns the
payment preview instead of data, so an agent can show a human exactly what
a call would cost before any money moves. Errors are returned as text so
the agent can react to them instead of crashing the chain.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from .client import (
    API_PREFIX,
    BlockchainIQClient,
    BlockchainIQError,
    CallResult,
)


def _render(result: CallResult) -> str:
    """Render a CallResult as the JSON string a tool returns."""
    if result.dry_run:
        return json.dumps(
            {
                "dry_run": True,
                "note": (
                    "Payment preview only: the 402 price was probed and the "
                    "payment verified locally, but nothing was sent and "
                    "nothing was charged."
                ),
                "payment": result.payment_preview,
            },
            indent=2,
        )
    out: dict[str, Any] = {"data": result.data}
    if result.settlement:
        out["settlement"] = result.settlement
    if result.payment_preview:
        out["payment"] = result.payment_preview
    return json.dumps(out, indent=2, default=str)


class _ClientTool(BaseTool):
    """Base class carrying the shared client (not an LLM-visible arg)."""

    client: BlockchainIQClient = Field(exclude=True)
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def _call(self, fn) -> str:
        try:
            return _render(fn())
        except BlockchainIQError as exc:
            return f"Error: {exc}"
        except Exception as exc:  # network errors etc. — report, don't crash
            return f"Error: {type(exc).__name__}: {exc}"


class _NoArgs(BaseModel):
    pass


class BlockchainIQCatalogTool(_ClientTool):
    """Free catalog of every Blockchain IQ resource and price."""

    name: str = "blockchainiq_catalog"
    description: str = (
        "List every Blockchain IQ data resource with its price and response "
        "shape. Free, no payment. Call this first to discover what can be "
        "bought and what each resource costs."
    )
    args_schema: Type[BaseModel] = _NoArgs

    def _run(self) -> str:
        return self._call(self.client.catalog)


class BlockchainIQSampleTool(_ClientTool):
    """Free Bitcoin network-activity sample in the paid envelope."""

    name: str = "blockchainiq_sample"
    description: str = (
        "Free sample of Blockchain IQ data: Bitcoin network activity "
        "(transactions, active addresses, fees) in the same JSON envelope "
        "as the paid resources. No payment. Useful to test parsing."
    )
    args_schema: Type[BaseModel] = _NoArgs

    def _run(self) -> str:
        return self._call(self.client.sample)


class BlockchainIQBriefTool(_ClientTool):
    """The $0.01 market brief — a bounty-qualifying paid call."""

    name: str = "blockchainiq_brief"
    description: str = (
        "Buy the Blockchain IQ market brief for $0.01 in USDC on Base via "
        "x402: BTC, ETH, SOL and XRP prices with 24h/7d/30d moves and rank, "
        "scheduled macro and crypto events in the next 48 hours, and short "
        "risk flags. Refreshed every minute. No API key; the wallet pays "
        "per call. In dry-run mode (or with no wallet) returns the payment "
        "preview instead and charges nothing."
    )
    args_schema: Type[BaseModel] = _NoArgs

    def _run(self) -> str:
        return self._call(self.client.brief)


class EventRiskArgs(BaseModel):
    days: int = Field(
        default=7, ge=1, le=90, description="Window length in days (1-90)."
    )
    min_importance: int = Field(
        default=1,
        ge=1,
        le=3,
        description="Lowest importance to include: 1 = everything, 3 = only major.",
    )


class BlockchainIQEventRiskTool(_ClientTool):
    """The $0.05 event-risk calendar — a bounty-qualifying paid call."""

    name: str = "blockchainiq_event_risk"
    description: str = (
        "Buy Blockchain IQ event risk for $0.05 in USDC on Base via x402: "
        "scheduled market-moving events (US data releases with times, FOMC, "
        "ECB and Bank of Japan decisions, Treasury auctions, crypto and "
        "regulatory milestones), each with importance 1-3 and its official "
        "source. In dry-run mode (or with no wallet) returns the payment "
        "preview instead and charges nothing."
    )
    args_schema: Type[BaseModel] = EventRiskArgs

    def _run(self, days: int = 7, min_importance: int = 1) -> str:
        return self._call(lambda: self.client.event_risk(days, min_importance))


class ResourceArgs(BaseModel):
    path: str = Field(
        description=(
            "Resource path under /api/x402/v1, e.g. /api/x402/v1/macro or "
            "/api/x402/v1/dashboards/bitcoin-network. Prices are in the "
            "blockchainiq_catalog output."
        )
    )
    query: Optional[dict[str, Any]] = Field(
        default=None, description="Optional query parameters as an object."
    )


class BlockchainIQResourceTool(_ClientTool):
    """Generic access to any catalog resource, free or paid."""

    name: str = "blockchainiq_get"
    description: str = (
        "GET any Blockchain IQ resource by its catalog path (must start "
        "with /api/x402/v1). Free resources return data directly; priced "
        "resources are paid in USDC on Base via x402, subject to the "
        "client's per-call spend cap. Use blockchainiq_catalog to see "
        "paths and prices. In dry-run mode (or with no wallet) a priced "
        "resource returns its payment preview instead and charges nothing."
    )
    args_schema: Type[BaseModel] = ResourceArgs

    def _run(self, path: str, query: Optional[dict[str, Any]] = None) -> str:
        if not path.startswith(API_PREFIX):
            return f"Error: path must start with {API_PREFIX}: {path!r}"
        return self._call(lambda: self.client.get_json(path, params=query))


def get_blockchainiq_tools(
    client: Optional[BlockchainIQClient] = None,
) -> list[BaseTool]:
    """Return the five Blockchain IQ tools bound to one client.

    With no argument the client is built from the environment
    (``AGENT_PRIVATE_KEY``, ``BIQ_MAX_PRICE_PER_CALL``, ``BIQ_DRY_RUN``).
    """
    client = client or BlockchainIQClient.from_env()
    return [
        BlockchainIQCatalogTool(client=client),
        BlockchainIQSampleTool(client=client),
        BlockchainIQBriefTool(client=client),
        BlockchainIQEventRiskTool(client=client),
        BlockchainIQResourceTool(client=client),
    ]
