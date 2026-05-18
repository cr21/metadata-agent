"""Lineage extractor — loads one asset, calls the LLM, stores results."""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.lineage.resolver import resolve_depth2
from app.llm.client import LLMClient
from app.llm.schemas import KIND_TO_SCHEMA_KIND
from app.storage import local_cache

logger = logging.getLogger(__name__)


def _get_bq_content(asset: dict) -> str:
    """Fetch BQ asset content live from BigQuery and format as SQL text for the LLM."""
    from app.crawlers import bigquery_crawler as bqc

    identifier = asset["identifier"]  # "project.dataset.resource"
    parts = identifier.split(".")
    if len(parts) != 3:
        raise ValueError(f"Cannot parse BQ identifier '{identifier}': expected project.dataset.resource")
    project_id, dataset_id, resource_id = parts
    kind = asset["kind"]

    if kind == "bq_routine":
        body = bqc.get_routine_definition(project_id, dataset_id, resource_id)
        if not body:
            raise ValueError(f"Empty routine body for {identifier}")
        return body

    if kind == "bq_view":
        view_query = bqc.get_view_query(project_id, dataset_id, resource_id)
        schema = bqc.get_table_schema(project_id, dataset_id, resource_id)
        schema_ddl = ", ".join(
            f"{c['name']} {c['type']}" for c in (schema or [])
        )
        view_sql = view_query or "-- view query unavailable"
        return (
            f"-- BigQuery view: {identifier}\n"
            f"-- Columns: {schema_ddl}\n"
            f"CREATE OR REPLACE VIEW `{identifier}` AS\n{view_sql}"
        )

    # bq_table — reconstruct a CREATE TABLE skeleton for the LLM
    schema = bqc.get_table_schema(project_id, dataset_id, resource_id)
    if not schema:
        raise ValueError(f"Empty schema for {identifier}")
    col_defs = "\n  ".join(f"{c['name']} {c['type']}," for c in schema)
    return (
        f"-- BigQuery table: {identifier}\n"
        f"CREATE TABLE `{identifier}` (\n  {col_defs}\n);"
    )


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _edge_id(source_asset_id: str, target_table: str, target_col: str,
             source_table: str, source_col: str, depth: int) -> str:
    key = f"{source_asset_id}|{target_table}|{target_col}|{source_table}|{source_col}|{depth}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def extract_lineage(
    asset_id: str,
    llm_client: LLMClient | None = None,
    db_path: Path = local_cache.DB_PATH,
) -> dict:
    """Run end-to-end lineage extraction for one asset.

    Returns a summary dict with result_id, schema_kind, and edge_count.
    Raises ValueError / FileNotFoundError on unrecoverable failures.
    """
    asset = local_cache.get_asset(asset_id, db_path=db_path)
    if asset is None:
        raise ValueError(f"Asset not found: {asset_id}")

    kind = asset["kind"]
    schema_kind = KIND_TO_SCHEMA_KIND.get(kind)
    if schema_kind is None:
        raise ValueError(f"Cannot extract lineage for kind '{kind}' (no schema registered)")

    identifier = asset.get("identifier", asset_id)
    raw_path = asset.get("raw_path")

    if asset.get("source") == "bigquery":
        content = _get_bq_content(asset)
    elif raw_path and Path(raw_path).exists():
        content = Path(raw_path).read_text(encoding="utf-8", errors="replace")
    else:
        raise FileNotFoundError(f"Raw content not found at '{raw_path}' for asset {asset_id}")

    client = llm_client or LLMClient()

    logger.info("Extracting lineage for asset %s (kind=%s)", asset_id, kind)
    payload = client.extract(kind=kind, path=identifier, content=content)

    result_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    now = _now()

    result_row = {
        "result_id": result_id,
        "asset_id": asset_id,
        "job_id": job_id,
        "schema_kind": schema_kind,
        "payload": json.dumps(payload),
        "created_at": now,
    }
    local_cache.upsert_lineage_result(result_row, db_path=db_path)

    edge_count = _explode_edges(asset_id, schema_kind, payload, db_path)
    depth2_count = resolve_depth2(db_path=db_path)

    logger.info(
        "Stored result %s with %d depth-1 + %d depth-2 edges for asset %s",
        result_id, edge_count, depth2_count, asset_id,
    )
    return {
        "result_id": result_id,
        "schema_kind": schema_kind,
        "edge_count": edge_count,
        "depth2_count": depth2_count,
    }


# ---------------------------------------------------------------------------
# Edge explosion helpers
# ---------------------------------------------------------------------------

def _explode_edges(
    source_asset_id: str,
    schema_kind: str,
    payload: dict,
    db_path: Path,
) -> int:
    if schema_kind == "stm":
        return _explode_stm_edges(source_asset_id, payload, db_path)
    if schema_kind == "pyspark_stm":
        return _explode_stm_edges(source_asset_id, payload, db_path)
    if schema_kind == "dag_spec":
        return _explode_dag_edges(source_asset_id, payload, db_path)
    return 0


def _explode_stm_edges(source_asset_id: str, payload: dict, db_path: Path) -> int:
    count = 0
    for entry in payload.get("stm_entries", []):
        target_table = entry.get("target_table", "")
        for col in entry.get("columns", []):
            target_col = col.get("column", "")
            transformation_type = col.get("transformation_type", "unknown")
            transformation = col.get("transformation", "")
            spark_function = col.get("spark_function", "")
            if spark_function and not transformation:
                transformation = spark_function

            for src in col.get("source_columns", []):
                source_table = src.get("table", "")
                source_col = src.get("column", "")
                if not source_table or not source_col:
                    continue

                edge = {
                    "edge_id": _edge_id(source_asset_id, target_table, target_col,
                                        source_table, source_col, 1),
                    "source_asset_id": source_asset_id,
                    "target_table": target_table,
                    "target_column": target_col,
                    "source_table": source_table,
                    "source_column": source_col,
                    "transformation_type": transformation_type,
                    "transformation": transformation,
                    "depth": 1,
                }
                local_cache.upsert_lineage_edge(edge, db_path=db_path)
                count += 1
    return count


def _explode_dag_edges(source_asset_id: str, payload: dict, db_path: Path) -> int:
    count = 0
    dag_id = payload.get("dag_id", "unknown_dag")
    for task in payload.get("tasks", []):
        task_id = task.get("task_id", "")
        target_table = f"{dag_id}.{task_id}"
        for reads in task.get("reads_hint", []):
            if not reads:
                continue
            edge = {
                "edge_id": _edge_id(source_asset_id, target_table, "task", reads, "data", 1),
                "source_asset_id": source_asset_id,
                "target_table": target_table,
                "target_column": "task",
                "source_table": reads,
                "source_column": "data",
                "transformation_type": "direct",
                "transformation": f"Airflow task {task_id} reads from {reads}",
                "depth": 1,
            }
            local_cache.upsert_lineage_edge(edge, db_path=db_path)
            count += 1
    return count
