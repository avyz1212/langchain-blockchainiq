import json

from blockchainiq_langchain import BlockchainIQClient, get_blockchainiq_tools
from conftest import (
    FAKE_TX_HASH,
    TEST_PRIVATE_KEY,
    FakeResponse,
    FakeSession,
    make_402,
    make_paid_200,
)


def _tools(session, **client_kwargs):
    client = BlockchainIQClient(session=session, **client_kwargs)
    return {t.name: t for t in get_blockchainiq_tools(client)}


def test_tool_names_and_order():
    tools = get_blockchainiq_tools(BlockchainIQClient(session=FakeSession([])))
    assert [t.name for t in tools] == [
        "blockchainiq_catalog",
        "blockchainiq_sample",
        "blockchainiq_brief",
        "blockchainiq_event_risk",
        "blockchainiq_get",
    ]


def test_brief_tool_returns_data_and_settlement_proof():
    session = FakeSession([make_402(), make_paid_200({"data": {"coins": [1]}})])
    tools = _tools(session, private_key=TEST_PRIVATE_KEY)
    out = json.loads(tools["blockchainiq_brief"].invoke({}))
    assert out["data"] == {"data": {"coins": [1]}}
    assert out["settlement"]["transaction"] == FAKE_TX_HASH


def test_event_risk_tool_passes_query_params():
    session = FakeSession([make_402(), make_paid_200()])
    tools = _tools(session, private_key=TEST_PRIVATE_KEY)
    tools["blockchainiq_event_risk"].invoke({"days": 7, "min_importance": 2})
    # The API spells the parameter minImportance (see its OpenAPI schema).
    assert session.calls[0]["params"] == {"days": 7, "minImportance": 2}


def test_paid_tool_without_wallet_reports_error_as_text():
    session = FakeSession([make_402()])
    tools = _tools(session)
    out = tools["blockchainiq_brief"].invoke({})
    assert out.startswith("Error:")
    assert "AGENT_PRIVATE_KEY" in out


def test_resource_tool_rejects_paths_outside_the_api():
    tools = _tools(FakeSession([]))
    out = tools["blockchainiq_get"].invoke({"path": "/admin"})
    assert out.startswith("Error:")


def test_catalog_tool_is_free_without_wallet():
    session = FakeSession([FakeResponse(200, json_body={"data": []})])
    tools = _tools(session)
    out = json.loads(tools["blockchainiq_catalog"].invoke({}))
    assert out["data"] == {"data": []}
