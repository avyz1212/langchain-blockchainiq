"""x402 v2 "exact" EVM payment payloads for the Blockchain IQ API.

This module implements the client side of the x402 protocol version 2
(https://x402.org) for EVM chains, as spoken by https://www.blockchainiq.co:

1. An unpaid request returns HTTP 402 with a ``PAYMENT-REQUIRED`` header:
   base64-encoded JSON ``{"x402Version": 2, "resource": {...},
   "accepts": [PaymentRequirements, ...], ...}``.
2. The client picks an acceptable requirement (here: scheme ``exact`` on an
   EIP-155 network), builds an EIP-3009 ``transferWithAuthorization`` EIP-712
   signature over the token contract named by ``accepts[].asset``, and
3. retries the request with a ``PAYMENT-SIGNATURE`` header carrying the
   base64-encoded payment payload built here.
4. A successful response carries a ``PAYMENT-RESPONSE`` header: base64 JSON
   with the settlement proof (``success``, ``transaction``, ``network``,
   ``payer``).

Settlement is gasless for the payer: the signature authorizes the transfer
and the server's facilitator submits it on chain.
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from eth_account import Account
from eth_account.messages import encode_typed_data

# USDC on every chain Blockchain IQ accepts has 6 decimals.
USDC_DECIMALS = 6

TRANSFER_WITH_AUTHORIZATION_TYPES: dict[str, list[dict[str, str]]] = {
    "TransferWithAuthorization": [
        {"name": "from", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"},
        {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"},
        {"name": "nonce", "type": "bytes32"},
    ]
}


class PaymentError(Exception):
    """Raised when a 402 response cannot be turned into a payment."""


@dataclass(frozen=True)
class PaymentRequirements:
    """One entry of the ``accepts`` array of a 402 PAYMENT-REQUIRED payload."""

    scheme: str
    network: str  # CAIP-2, e.g. "eip155:8453" for Base
    amount_atomic: int  # smallest unit of the asset (USDC: 1e-6 dollar)
    asset: str  # token contract address (EVM)
    pay_to: str
    max_timeout_seconds: int = 300
    token_name: Optional[str] = None  # EIP-712 domain name, from `extra`
    token_version: Optional[str] = None  # EIP-712 domain version, from `extra`
    raw: Optional[dict[str, Any]] = None  # the requirement object, verbatim

    @property
    def chain_id(self) -> int:
        return int(self.network.split(":")[1])

    @property
    def amount_usd(self) -> Decimal:
        return Decimal(self.amount_atomic) / (Decimal(10) ** USDC_DECIMALS)

    @classmethod
    def from_dict(cls, entry: dict[str, Any]) -> "PaymentRequirements":
        extra = entry.get("extra") or {}
        return cls(
            scheme=entry["scheme"],
            network=entry["network"],
            amount_atomic=int(entry["amount"]),
            asset=entry["asset"],
            pay_to=entry["payTo"],
            max_timeout_seconds=int(entry.get("maxTimeoutSeconds", 300)),
            token_name=extra.get("name"),
            token_version=extra.get("version"),
            raw=entry,
        )


def decode_payment_required(header_value: str) -> dict[str, Any]:
    """Decode a base64 ``PAYMENT-REQUIRED`` header into its JSON object."""
    try:
        return json.loads(base64.b64decode(header_value))
    except Exception as exc:  # pragma: no cover - defensive
        raise PaymentError(f"Undecodable PAYMENT-REQUIRED header: {exc}") from exc


def decode_payment_response(header_value: str) -> dict[str, Any]:
    """Decode a base64 ``PAYMENT-RESPONSE`` settlement-proof header."""
    return json.loads(base64.b64decode(header_value))


def select_evm_requirement(
    required: dict[str, Any], *, network: Optional[str] = None
) -> PaymentRequirements:
    """Pick the first ``exact`` EVM requirement from a decoded 402 payload.

    Blockchain IQ offers Base (``eip155:8453``) and Solana rails; this client
    pays on EVM, so non-EIP-155 entries are skipped.
    """
    accepts = required.get("accepts") or []
    for entry in accepts:
        if entry.get("scheme") != "exact":
            continue
        if not str(entry.get("network", "")).startswith("eip155:"):
            continue
        if network is not None and entry["network"] != network:
            continue
        return PaymentRequirements.from_dict(entry)
    raise PaymentError(
        "No supported payment requirement: need scheme 'exact' on an "
        f"eip155:* network, got networks "
        f"{[a.get('network') for a in accepts] or 'none'}."
    )


def build_payment_payload(
    required: dict[str, Any],
    requirement: PaymentRequirements,
    account: Account,
    *,
    now: Optional[int] = None,
    nonce: Optional[bytes] = None,
) -> tuple[str, dict[str, Any]]:
    """Sign an EIP-3009 authorization and return (header_value, payload_dict).

    The signature is over the token's EIP-712 domain: the domain name and
    version are taken from the server's own ``extra`` fields (Blockchain IQ
    sends ``{"name": "USD Coin", "version": "2"}`` for USDC), the chain id
    from the CAIP-2 network, and the verifying contract is the asset itself.

    Nothing is broadcast by signing: the returned header only *authorizes*
    the transfer when a server chooses to settle it.
    """
    now = int(time.time()) if now is None else now
    nonce = secrets.token_bytes(32) if nonce is None else nonce
    valid_after = now - 60  # small clock-skew allowance
    valid_before = now + requirement.max_timeout_seconds

    authorization = {
        "from": account.address,
        "to": requirement.pay_to,
        "value": str(requirement.amount_atomic),
        "validAfter": str(valid_after),
        "validBefore": str(valid_before),
        "nonce": "0x" + nonce.hex(),
    }
    domain = {
        "name": requirement.token_name or "USD Coin",
        "version": requirement.token_version or "2",
        "chainId": requirement.chain_id,
        "verifyingContract": requirement.asset,
    }
    message = {
        "from": account.address,
        "to": requirement.pay_to,
        "value": requirement.amount_atomic,
        "validAfter": valid_after,
        "validBefore": valid_before,
        "nonce": nonce,
    }
    signable = encode_typed_data(
        domain_data=domain,
        message_types=TRANSFER_WITH_AUTHORIZATION_TYPES,
        message_data=message,
    )
    signed = account.sign_message(signable)
    signature = signed.signature.hex()
    if not signature.startswith("0x"):
        signature = "0x" + signature

    payload: dict[str, Any] = {
        "x402Version": 2,
        "accepted": requirement.raw,
        "payload": {"signature": signature, "authorization": authorization},
    }
    if required.get("resource") is not None:
        payload["resource"] = required["resource"]
    header_value = base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).decode()
    return header_value, payload


def recover_signer(
    requirement: PaymentRequirements, payload: dict[str, Any]
) -> str:
    """Recover the signer of a built payload (local sanity check)."""
    inner = payload["payload"]
    auth = inner["authorization"]
    domain = {
        "name": requirement.token_name or "USD Coin",
        "version": requirement.token_version or "2",
        "chainId": requirement.chain_id,
        "verifyingContract": requirement.asset,
    }
    message = {
        "from": auth["from"],
        "to": auth["to"],
        "value": int(auth["value"]),
        "validAfter": int(auth["validAfter"]),
        "validBefore": int(auth["validBefore"]),
        "nonce": bytes.fromhex(auth["nonce"][2:]),
    }
    signable = encode_typed_data(
        domain_data=domain,
        message_types=TRANSFER_WITH_AUTHORIZATION_TYPES,
        message_data=message,
    )
    return Account.recover_message(signable, signature=inner["signature"])
