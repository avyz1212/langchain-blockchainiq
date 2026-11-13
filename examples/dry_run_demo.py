"""Dry-run demo: exercise the whole integration without spending a cent.

What happens here:

1. The free catalog is fetched live (no wallet involved).
2. The free sample is fetched live.
3. The $0.01 ``brief`` resource is probed: the server answers HTTP 402 with
   its price (that probe is free), the client builds the x402 payment and
   verifies the signature locally, and then *stops* — the paid retry is
   never sent, so nothing can be charged.

Run it:

    pip install -e .
    python examples/dry_run_demo.py

No private key is needed: in dry-run mode the client uses an ephemeral
throwaway key purely to demonstrate the signing step. Set AGENT_PRIVATE_KEY
to preview payments from a real wallet address instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eth_account import Account

from blockchainiq_langchain import BlockchainIQClient


def main() -> None:
    # Ephemeral key: generated in memory, holds nothing, never funded.
    # Used only so the signing step can be demonstrated end to end.
    ephemeral = Account.create()
    client = BlockchainIQClient(
        private_key=ephemeral.key.hex(), dry_run=True
    )

    print("== 1. Catalog (free) ==")
    catalog = client.catalog()
    resources = catalog.data.get("data", [])
    print(f"{len(resources)} resources listed. First three:")
    for entry in resources[:3]:
        print(f"  - {entry['id']}: {entry['path']} @ {entry['price']}")

    print("\n== 2. Sample (free) ==")
    sample = client.sample()
    data = sample.data.get("data", {})
    print(
        f"Bitcoin network, as of {data.get('asOf')}: "
        f"{data.get('transactions', {}).get('value')} transactions, "
        f"{data.get('activeAddresses', {}).get('value')} active addresses."
    )

    print("\n== 3. Brief (paid $0.01) — DRY RUN, nothing is sent ==")
    result = client.brief()
    preview = dict(result.payment_preview or {})
    print(json.dumps(preview, indent=2))
    assert preview.get("signature_valid") is True
    print(
        "\nSignature verified locally against the payer address "
        f"{client.payer_address}. The signed payment was NOT sent; "
        "no USDC moved. This is the exact point where a live run would "
        "retry with the PAYMENT-SIGNATURE header."
    )


if __name__ == "__main__":
    main()
