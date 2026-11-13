import base64
import json
from decimal import Decimal

import pytest
from eth_account import Account

from blockchainiq_langchain.payment import (
    PaymentError,
    build_payment_payload,
    recover_signer,
    select_evm_requirement,
)
from conftest import BRIEF_REQUIRED, TEST_ADDRESS, TEST_PRIVATE_KEY


def test_selects_base_usdc_requirement():
    req = select_evm_requirement(BRIEF_REQUIRED)
    assert req.scheme == "exact"
    assert req.network == "eip155:8453"
    assert req.chain_id == 8453
    assert req.amount_atomic == 10000
    assert req.amount_usd == Decimal("0.01")
    assert req.asset == "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    assert req.pay_to == "0x617dA9383fbA67e86137BC4924b8b7E400fB7C9e"
    assert req.token_name == "USD Coin"
    assert req.token_version == "2"


def test_solana_only_requirements_are_rejected():
    solana_only = {
        "x402Version": 2,
        "accepts": [BRIEF_REQUIRED["accepts"][1]],
    }
    with pytest.raises(PaymentError):
        select_evm_requirement(solana_only)


def test_built_payload_matches_x402_v2_shape_and_signs_for_payer():
    account = Account.from_key(TEST_PRIVATE_KEY)
    req = select_evm_requirement(BRIEF_REQUIRED)
    header_value, payload = build_payment_payload(
        BRIEF_REQUIRED, req, account, now=1_800_000_000, nonce=b"\x01" * 32
    )
    # The header is exactly the base64 of the payload dict.
    assert json.loads(base64.b64decode(header_value)) == payload

    assert payload["x402Version"] == 2
    assert payload["accepted"] == BRIEF_REQUIRED["accepts"][0]
    assert payload["resource"]["url"].endswith("/api/x402/v1/brief")

    inner = payload["payload"]
    auth = inner["authorization"]
    assert auth["from"] == TEST_ADDRESS
    assert auth["to"] == req.pay_to
    assert auth["value"] == "10000"
    assert auth["nonce"] == "0x" + "01" * 32
    assert int(auth["validBefore"]) - int(auth["validAfter"]) == 360
    assert inner["signature"].startswith("0x") and len(inner["signature"]) == 132

    # The signature is a genuine EIP-712 signature by the payer over the
    # USDC-on-Base TransferWithAuthorization message.
    assert recover_signer(req, payload) == TEST_ADDRESS
