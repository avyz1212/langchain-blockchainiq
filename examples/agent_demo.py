"""LangChain demo: the five tools, invoked through the LangChain interface.

No LLM key is needed — the tools are called directly with ``.invoke()``,
exactly as an agent executor would call them. The paid tools run in
dry-run mode here, so the demo spends nothing: they return the payment
preview an agent would show its user before paying for real.

    pip install -e .
    python examples/agent_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from blockchainiq_langchain import BlockchainIQClient, get_blockchainiq_tools


def main() -> None:
    # Dry-run client: free tools hit the live API; paid tools preview.
    client = BlockchainIQClient(dry_run=True)
    tools = get_blockchainiq_tools(client)
    by_name = {tool.name: tool for tool in tools}

    print("Tools registered with the agent:")
    for tool in tools:
        print(f"  - {tool.name}")

    print("\n== blockchainiq_sample (free, live) ==")
    print(by_name["blockchainiq_sample"].invoke({})[:400], "...")

    print("\n== blockchainiq_brief (paid $0.01, dry-run preview) ==")
    print(by_name["blockchainiq_brief"].invoke({}))

    print("\n== blockchainiq_event_risk (paid $0.05, dry-run preview) ==")
    print(
        by_name["blockchainiq_event_risk"].invoke(
            {"days": 7, "min_importance": 2}
        )
    )

    print(
        "\nBind these tools to any LangChain chat model with "
        "model.bind_tools(tools) or pass them to create_agent — the "
        "payment behaviour travels with the client."
    )


if __name__ == "__main__":
    main()
