"""Unit tests for MCP server — verifies tool list matches spec §8."""

import pytest

from mcp_server.server import handle_list_tools

EXPECTED_TOOLS = {
    "list_datasets",
    "list_tables",
    "get_table_schema",
    "get_routine_definition",
    "query_information_schema",
    "dry_run_query",
}


@pytest.mark.asyncio
async def test_mcp_tools_list_contains_all_six():
    tools = await handle_list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS, f"Missing tools: {EXPECTED_TOOLS - names}"


@pytest.mark.asyncio
async def test_mcp_tools_have_input_schemas():
    tools = await handle_list_tools()
    for tool in tools:
        assert tool.inputSchema is not None, f"{tool.name} missing inputSchema"
        assert "properties" in tool.inputSchema, f"{tool.name} inputSchema missing properties"


@pytest.mark.asyncio
async def test_mcp_tools_have_descriptions():
    tools = await handle_list_tools()
    for tool in tools:
        assert tool.description, f"{tool.name} missing description"
