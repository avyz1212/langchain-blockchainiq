"""A small x402 v2 client for the Blockchain IQ pay-per-call data API.

The API (https://www.blockchainiq.co/api/x402/v1) has no accounts and no API
keys: paid resources answer HTTP 402 with a price, the client pays in USDC
on Base with the x402 standard, and the retry returns JSON plus a
``PAYMENT-RESPONSE`` settlement proof (including the transaction hash).

Safety properties, mirroring the spend control in Blockchain IQ's own
example on https://www.blockchainiq.co/agents:

* a per-call spend cap (default $0.60) — a 402 asking more is refused
  *before* anything is signed;
* a dry-run mode that performs the (free) 402 probe and builds/verifies the
  signed payment locally but never sends it — nothing can be charged;
* HTTP 404 and other error responses are never charged by the API and are
  surfaced as errors without any payment attempt beyond the first probe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

import requests
from eth_account import Account

from .payment import (
    PaymentError,
    PaymentRequirements,
    build_payment_payload,
    decode_payment_required,
    decode_payment_response,
    recover_signer,
    select_evm_requirement,
)

BASE_URL = "https://www.blockchainiq.co"
API_PREFIX = "/api/x402/v1"
DEFAULT_MAX_PRICE_USD = Decimal("0.60")

# Resources that qualify a build for the Blockchain IQ x402 Build Bounties:
# a working paid call must go to one of these two.
QUALIFYING_RESOURCES = {"brief": Decimal("0.01"), "event-risk": Decimal("0.05")}


class BlockchainIQError(Exception):
    """Base class for client errors."""


class APIError(BlockchainIQError):
    """The API returned an error status (never charged)."""

    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Blockchain IQ API error {status_code}: {body!r}")


class WalletRequiredError(BlockchainIQError):
    """A paid resource was requested without a wallet (and not in dry-run)."""


class SpendLimitError(BlockchainIQError):
    """The 402 price exceeds the configured per-call spend cap."""


@dataclass
class CallResult:
    """Result of one API call."""

    data: Any = None  # parsed JSON body on success
    settlement: Optional[dict[str, Any]] = None  # decoded PAYMENT-RESPONSE
    payment_preview: Optional[dict[str, Any]] = None  # what a payment would be
    dry_run: bool = False
    status_code: int = 200
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def transaction_hash(self) -> Optional[str]:
        if self.settlement:
            return self.settlement.get("transaction")
        return None


class BlockchainIQClient:
    """Synchronous Blockchain IQ client with x402 payment support."""

    def __init__(
        self,
        private_key: Optional[str] = None,
        *,
        base_url: str = BASE_URL,
        max_price_usd: Decimal = DEFAULT_MAX_PRICE_USD,
        dry_run: bool = False,
        network: Optional[str] = None,
        session: Optional[requests.Session] = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.max_price_usd = Decimal(max_price_usd)
        self.dry_run = dry_run
        self.network = network
        self.session = session or requests.Session()
        self.timeout = timeout
        self.account = Account.from_key(private_key) if private_key else None

    # -- construction -----------------------------------------------------

    @classmethod
    def from_env(cls, **overrides: Any) -> "BlockchainIQClient":
        """Build a client from environment variables.

        * ``AGENT_PRIVATE_KEY`` — payer wallet key (same name as Blockchain
          IQ's own copy-paste example). Use a dedicated wallet with a small
          balance, never a main wallet.
        * ``BIQ_MAX_PRICE_PER_CALL`` — per-call spend cap in USD.
        * ``BIQ_DRY_RUN`` — ``1``/``true`` to probe and sign but never pay.
        * ``BIQ_BASE_URL`` — override the API origin (testing).
        """
        kwargs: dict[str, Any] = {}
        if key := os.environ.get("AGENT_PRIVATE_KEY"):
            kwargs["private_key"] = key
        if cap := os.environ.get("BIQ_MAX_PRICE_PER_CALL"):
            kwargs["max_price_usd"] = Decimal(cap)
        if os.environ.get("BIQ_DRY_RUN", "").lower() in ("1", "true", "yes"):
            kwargs["dry_run"] = True
        if url := os.environ.get("BIQ_BASE_URL"):
            kwargs["base_url"] = url
        kwargs.update(overrides)
        return cls(**kwargs)

    @property
    def payer_address(self) -> Optional[str]:
        return self.account.address if self.account else None

    # -- core request flow --------------------------------------------------

    def get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> CallResult:
        """GET a resource, paying through x402 if the resource is priced.

        Free resources return immediately. For paid resources the first
        request is the free 402 probe; the payment is signed locally and the
        request retried once with the ``PAYMENT-SIGNATURE`` header.
        """
        if not path.startswith(API_PREFIX):
            raise ValueError(f"path must start with {API_PREFIX}: {path!r}")
        url = self.base_url + path
        resp = self.session.get(url, params=params, timeout=self.timeout)
        if resp.status_code == 200:
            return CallResult(
                data=resp.json(),
                settlement=self._settlement(resp),
                status_code=200,
            )
        if resp.status_code != 402:
            raise APIError(resp.status_code, self._body(resp))

        required = self._required(resp)
        requirement = select_evm_requirement(required, network=self.network)
        preview = self._preview(path, requirement)

        if requirement.amount_usd > self.max_price_usd:
            raise SpendLimitError(
                f"{path} costs ${requirement.amount_usd}, above the per-call "
                f"cap of ${self.max_price_usd}. Refusing to sign."
            )
        if self.account is None and not self.dry_run:
            raise WalletRequiredError(
                f"{path} costs ${requirement.amount_usd} via x402. Set "
                "AGENT_PRIVATE_KEY (a dedicated, small-balance wallet) or "
                "enable dry-run mode to preview the payment without paying."
            )
        if self.account is None:
            return CallResult(
                data=None, payment_preview=preview, dry_run=True, status_code=402
            )

        header_value, payload = build_payment_payload(
            required, requirement, self.account
        )
        preview["signature_valid"] = (
            recover_signer(requirement, payload) == self.account.address
        )
        if self.dry_run:
            # The signed payload is deliberately not returned in full and is
            # never sent: dry-run cannot spend.
            return CallResult(
                data=None, payment_preview=preview, dry_run=True, status_code=402
            )

        paid = self.session.get(
            url,
            params=params,
            headers={"PAYMENT-SIGNATURE": header_value},
            timeout=self.timeout,
        )
        if paid.status_code == 402:
            raise PaymentError(
                f"Payment was not accepted for {path}: {self._body(paid)!r}"
            )
        if paid.status_code != 200:
            raise APIError(paid.status_code, self._body(paid))
        return CallResult(
            data=paid.json(),
            settlement=self._settlement(paid),
            payment_preview=preview,
            status_code=200,
        )

    # -- named resources ----------------------------------------------------

    def catalog(self) -> CallResult:
        """Free: every resource, price and response shape."""
        return self.get_json(f"{API_PREFIX}")

    def sample(self) -> CallResult:
        """Free: Bitcoin network activity sample, same envelope as paid data."""
        return self.get_json(f"{API_PREFIX}/sample")

    def brief(self) -> CallResult:
        """$0.01: BTC/ETH/SOL/XRP market brief. A bounty-qualifying call."""
        return self.get_json(f"{API_PREFIX}/brief")

    def event_risk(
        self, days: int = 7, min_importance: int = 1
    ) -> CallResult:
        """$0.05: scheduled market-moving events. A bounty-qualifying call."""
        return self.get_json(
            f"{API_PREFIX}/event-risk",
            params={"days": days, "minImportance": min_importance},
        )

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _body(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except Exception:
            return resp.text

    @staticmethod
    def _settlement(resp: requests.Response) -> Optional[dict[str, Any]]:
        header = resp.headers.get("payment-response") or resp.headers.get(
            "PAYMENT-RESPONSE"
        )
        if not header:
            return None
        try:
            return decode_payment_response(header)
        except Exception:
            return None

    @staticmethod
    def _required(resp: requests.Response) -> dict[str, Any]:
        header = resp.headers.get("payment-required") or resp.headers.get(
            "PAYMENT-REQUIRED"
        )
        if header:
            return decode_payment_required(header)
        body = BlockchainIQClient._body(resp)
        if isinstance(body, dict) and "accepts" in body:
            return body
        raise PaymentError(f"402 response without payment requirements: {body!r}")

    @staticmethod
    def _preview(path: str, req: PaymentRequirements) -> dict[str, Any]:
        return {
            "resource": path,
            "amount_atomic": str(req.amount_atomic),
            "amount_usd": str(req.amount_usd),
            "asset": req.asset,
            "pay_to": req.pay_to,
            "network": req.network,
            "scheme": req.scheme,
        }
