"""Make the real, qualifying paid call: the $0.01 market brief.

This performs one working paid call through x402 to
``GET /api/x402/v1/brief`` — one of the two resources that qualify an
integration for the Blockchain IQ x402 Build Bounties (the other is
``event-risk`` at $0.05) — and prints the settlement proof decoded from
the ``PAYMENT-RESPONSE`` header, including the transaction hash you need
for the bounty claim email.

Safety rails:

* Requires a dedicated wallet in ``AGENT_PRIVATE_KEY`` holding at least
  $0.01 USDC on Base. Settlement is gasless for the payer, so no ETH is
  needed. Never use a main wallet.
* Requires the explicit ``--confirm`` flag (or ``BIQ_CONFIRM_SPEND=1``)
  so the spend can never happen by accident.
* The client's per-call cap (``BIQ_MAX_PRICE_PER_CALL``, default $0.60)
  still applies.

Usage:

    AGENT_PRIVATE_KEY=0x... python examples/paid_call.py --confirm
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blockchainiq_langchain import BlockchainIQClient


def main() -> None:
    confirmed = "--confirm" in sys.argv or os.environ.get(
        "BIQ_CONFIRM_SPEND"
    ) in ("1", "true")
    if not os.environ.get("AGENT_PRIVATE_KEY"):
        sys.exit("Set AGENT_PRIVATE_KEY to a dedicated wallet holding USDC on Base.")
    if not confirmed:
        sys.exit(
            "This makes a real $0.01 payment. Re-run with --confirm "
            "(or BIQ_CONFIRM_SPEND=1) to proceed."
        )

    client = BlockchainIQClient.from_env()
    print(f"Payer: {client.payer_address}")
    result = client.brief()
    print("Brief data:")
    print(json.dumps(result.data, indent=2)[:1000])
    print("\nSettlement proof (from the PAYMENT-RESPONSE header):")
    print(json.dumps(result.settlement, indent=2))
    print(f"\nTransaction hash: {result.transaction_hash}")
    print(
        "Keep this hash: the bounty claim is an email to "
        "partnerships@blockchainiq.co with the repository link and this "
        "settlement transaction hash."
    )


if __name__ == "__main__":
    main()
