"""Shared fixtures: a fake HTTP transport speaking real x402 v2 shapes.

The canned PAYMENT-REQUIRED payload below is the actual requirements
document the live Blockchain IQ server returns for /brief (captured from
an unpaid probe on 2026-11-13; only the bulky bazaar extension example
was trimmed). Tests therefore exercise the same bytes a live run sees.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from requests.structures import CaseInsensitiveDict

# Hardhat account #0 — a publicly known test key, used for signing tests.
TEST_PRIVATE_KEY = (
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
)
TEST_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
FAKE_TX_HASH = "0x" + "ab" * 32

BRIEF_REQUIRED = {
    "x402Version": 2,
    "error": "Payment Required",
    "resource": {
        "url": "https://www.blockchainiq.co/api/x402/v1/brief",
        "description": "Market brief in one parameter-free call.",
        "mimeType": "application/json",
    },
    "accepts": [
        {
            "scheme": "exact",
            "network": "eip155:8453",
            "amount": "10000",
            "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            "payTo": "0x617dA9383fbA67e86137BC4924b8b7E400fB7C9e",
            "maxTimeoutSeconds": 300,
            "extra": {"name": "USD Coin", "version": "2"},
        },
        {
            "scheme": "exact",
            "network": "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp",
            "amount": "10000",
            "asset": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            "payTo": "473o2o4QaubXvvAFr9jikTCEirA6xhpzMSBxJpbTocLf",
            "maxTimeoutSeconds": 300,
            "extra": {"feePayer": "BENrLoUbndxoNMUS5JXApGMtNykLjFXXixMtpDwDR9SP"},
        },
    ],
}

SETTLEMENT = {
    "success": True,
    "transaction": FAKE_TX_HASH,
    "network": "eip155:8453",
    "payer": TEST_ADDRESS,
}


def b64_json(obj) -> str:
    return base64.b64encode(json.dumps(obj).encode()).decode()


class FakeResponse:
    def __init__(self, status_code, json_body=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_body
        self.headers = CaseInsensitiveDict(headers or {})
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


def make_402(required=None) -> FakeResponse:
    required = BRIEF_REQUIRED if required is None else required
    return FakeResponse(
        402,
        json_body={"error": "Payment required.", "price": "$0.01"},
        headers={"PAYMENT-REQUIRED": b64_json(required)},
    )


def make_paid_200(data=None) -> FakeResponse:
    return FakeResponse(
        200,
        json_body=data if data is not None else {"data": {"ok": True}},
        headers={"PAYMENT-RESPONSE": b64_json(SETTLEMENT)},
    )


class FakeSession:
    """A requests.Session stand-in returning queued responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "params": params, "headers": headers or {}}
        )
        if not self._responses:
            raise AssertionError("FakeSession ran out of queued responses")
        return self._responses.pop(0)
