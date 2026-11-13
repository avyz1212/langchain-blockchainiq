from decimal import Decimal

import pytest

from blockchainiq_langchain.client import (
    APIError,
    BlockchainIQClient,
    SpendLimitError,
    WalletRequiredError,
)
from blockchainiq_langchain.payment import PaymentError
from conftest import (
    BRIEF_REQUIRED,
    FAKE_TX_HASH,
    TEST_PRIVATE_KEY,
    FakeResponse,
    FakeSession,
    make_402,
    make_paid_200,
)


def test_free_resource_passes_through_without_wallet():
    session = FakeSession([FakeResponse(200, json_body={"data": [1, 2]})])
    client = BlockchainIQClient(session=session)
    result = client.catalog()
    assert result.data == {"data": [1, 2]}
    assert result.settlement is None
    assert len(session.calls) == 1


def test_paid_call_probes_signs_and_retries_once():
    session = FakeSession([make_402(), make_paid_200({"data": {"coins": []}})])
    client = BlockchainIQClient(private_key=TEST_PRIVATE_KEY, session=session)
    result = client.brief()
    assert result.data == {"data": {"coins": []}}
    assert result.transaction_hash == FAKE_TX_HASH
    assert result.settlement["success"] is True
    assert len(session.calls) == 2
    retry_headers = session.calls[1]["headers"]
    assert "PAYMENT-SIGNATURE" in retry_headers
    assert result.payment_preview["amount_usd"] == "0.01"
    assert result.payment_preview["signature_valid"] is True


def test_dry_run_signs_but_never_sends():
    session = FakeSession([make_402()])
    client = BlockchainIQClient(
        private_key=TEST_PRIVATE_KEY, session=session, dry_run=True
    )
    result = client.brief()
    assert result.dry_run is True
    assert result.data is None
    assert result.payment_preview["amount_usd"] == "0.01"
    assert result.payment_preview["signature_valid"] is True
    # Exactly one request (the free probe); no paid retry left the process.
    assert len(session.calls) == 1
    assert "PAYMENT-SIGNATURE" not in session.calls[0]["headers"]


def test_dry_run_without_wallet_still_previews():
    session = FakeSession([make_402()])
    client = BlockchainIQClient(session=session, dry_run=True)
    result = client.brief()
    assert result.dry_run is True
    assert result.payment_preview["pay_to"].startswith("0x617d")


def test_paid_call_without_wallet_or_dry_run_raises():
    session = FakeSession([make_402()])
    client = BlockchainIQClient(session=session)
    with pytest.raises(WalletRequiredError):
        client.brief()


def test_spend_cap_refuses_before_signing():
    pricey = {
        "x402Version": 2,
        "resource": BRIEF_REQUIRED["resource"],
        "accepts": [
            dict(BRIEF_REQUIRED["accepts"][0], amount="2000000"),  # $2.00
            BRIEF_REQUIRED["accepts"][1],
        ],
    }
    session = FakeSession([make_402(pricey)])
    client = BlockchainIQClient(
        private_key=TEST_PRIVATE_KEY,
        session=session,
        max_price_usd=Decimal("0.60"),
    )
    with pytest.raises(SpendLimitError):
        client.brief()
    assert len(session.calls) == 1  # refused after the probe, before retry


def test_error_status_is_never_charged_or_retried():
    session = FakeSession([FakeResponse(404, json_body={"error": "nope"})])
    client = BlockchainIQClient(private_key=TEST_PRIVATE_KEY, session=session)
    with pytest.raises(APIError) as excinfo:
        client.get_json("/api/x402/v1/dashboards/nope/nope")
    assert excinfo.value.status_code == 404
    assert len(session.calls) == 1


def test_rejected_payment_raises():
    session = FakeSession([make_402(), make_402()])
    client = BlockchainIQClient(private_key=TEST_PRIVATE_KEY, session=session)
    with pytest.raises(PaymentError):
        client.brief()
