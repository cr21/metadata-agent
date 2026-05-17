"""MCP server exposing BigQuery introspection tools (spec §8)."""

import json
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from app.crawlers import bigquery_crawler as bqc

logger = logging.getLogger(__name__)

server = Server("metadata-agent-bq")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_datasets",
            description="List all dataset IDs in a BigQuery project.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "GCP project ID"},
                },
                "required": ["project_id"],
            },
        ),
        Tool(
            name="list_tables",
            description="List tables and views in a BigQuery dataset with metadata.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "dataset_id": {"type": "string"},
                },
                "required": ["project_id", "dataset_id"],
            },
        ),
        Tool(
            name="get_table_schema",
            description="Return the column schema for a BigQuery table or view.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "dataset_id": {"type": "string"},
                    "table_id": {"type": "string"},
                },
                "required": ["project_id", "dataset_id", "table_id"],
            },
        ),
        Tool(
            name="get_routine_definition",
            description="Return the DDL body of a BigQuery stored procedure or UDF.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "dataset_id": {"type": "string"},
                    "routine_id": {"type": "string"},
                },
                "required": ["project_id", "dataset_id", "routine_id"],
            },
        ),
        Tool(
            name="query_information_schema",
            description=(
                "Query a named INFORMATION_SCHEMA view for a dataset "
                "(e.g. COLUMNS, TABLES, ROUTINES)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "dataset_id": {"type": "string"},
                    "view": {
                        "type": "string",
                        "description": "INFORMATION_SCHEMA view name, e.g. COLUMNS",
                    },
                },
                "required": ["project_id", "dataset_id", "view"],
            },
        ),
        Tool(
            name="dry_run_query",
            description=(
                "Dry-run a SQL query against BigQuery. "
                "Returns bytes_processed and referenced_tables."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "sql": {"type": "string", "description": "SQL query to dry-run"},
                },
                "required": ["project_id", "sql"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "list_datasets":
            result = bqc.list_datasets(arguments["project_id"])

        elif name == "list_tables":
            result = bqc.list_tables(
                arguments["project_id"], arguments["dataset_id"]
            )

        elif name == "get_table_schema":
            result = bqc.get_table_schema(
                arguments["project_id"],
                arguments["dataset_id"],
                arguments["table_id"],
            )

        elif name == "get_routine_definition":
            result = bqc.get_routine_definition(
                arguments["project_id"],
                arguments["dataset_id"],
                arguments["routine_id"],
            )

        elif name == "query_information_schema":
            result = bqc.query_information_schema(
                arguments["project_id"],
                arguments["dataset_id"],
                arguments["view"],
            )

        elif name == "dry_run_query":
            result = bqc.dry_run_query(
                arguments["project_id"],
                arguments["sql"],
            )

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [TextContent(type="text", text=json.dumps(result, default=str))]

    except Exception as exc:
        logger.exception("MCP tool %s failed", name)
        return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]


async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
