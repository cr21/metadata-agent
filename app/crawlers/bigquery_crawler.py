"""BigQuery crawler — inventories datasets, tables, views, and routines for a project."""

import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery

from app.storage import bq_store, local_cache

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BQ client factory (injectable for tests)
# ---------------------------------------------------------------------------

def _bq_client(project_id: str) -> bigquery.Client:
    return bigquery.Client(project=project_id)


# ---------------------------------------------------------------------------
# Core introspection helpers — used by both crawler and MCP tools
# ---------------------------------------------------------------------------

def list_datasets(project_id: str, client: bigquery.Client | None = None) -> list[str]:
    """Return list of dataset IDs in the given project."""
    bq = client or _bq_client(project_id)
    return [ds.dataset_id for ds in bq.list_datasets(project=project_id)]


def list_tables(
    project_id: str,
    dataset_id: str,
    client: bigquery.Client | None = None,
) -> list[dict[str, Any]]:
    """Return table metadata for all tables/views in a dataset."""
    bq = client or _bq_client(project_id)
    dataset_ref = bigquery.DatasetReference(project_id, dataset_id)
    results = []
    for tbl in bq.list_tables(dataset_ref):
        results.append(
            {
                "table_id": tbl.table_id,
                "type": tbl.table_type,
                "num_rows": getattr(tbl, "num_rows", None),
                "last_modified": (
                    tbl.modified.isoformat() if getattr(tbl, "modified", None) else None
                ),
            }
        )
    return results


def get_table_schema(
    project_id: str,
    dataset_id: str,
    table_id: str,
    client: bigquery.Client | None = None,
) -> list[dict[str, Any]]:
    """Return column schema for a table/view as a list of dicts."""
    bq = client or _bq_client(project_id)
    table_ref = bigquery.TableReference(
        bigquery.DatasetReference(project_id, dataset_id), table_id
    )
    table = bq.get_table(table_ref)
    return [
        {
            "name": field.name,
            "type": field.field_type,
            "mode": field.mode,
            "description": field.description,
        }
        for field in table.schema
    ]


def get_view_query(
    project_id: str,
    dataset_id: str,
    table_id: str,
    client: bigquery.Client | None = None,
) -> str | None:
    """Return the view definition SQL, or None if not a view."""
    bq = client or _bq_client(project_id)
    table_ref = bigquery.TableReference(
        bigquery.DatasetReference(project_id, dataset_id), table_id
    )
    table = bq.get_table(table_ref)
    if table.table_type == "VIEW":
        return table.view_query
    if table.table_type == "MATERIALIZED_VIEW":
        return table.mview_query
    return None


def get_routine_definition(
    project_id: str,
    dataset_id: str,
    routine_id: str,
    client: bigquery.Client | None = None,
) -> str | None:
    """Return the DDL body of a stored procedure/UDF."""
    bq = client or _bq_client(project_id)
    routine_ref = bigquery.RoutineReference.from_string(
        f"{project_id}.{dataset_id}.{routine_id}"
    )
    try:
        routine = bq.get_routine(routine_ref)
        return routine.body
    except Exception:
        return None


def query_information_schema(
    project_id: str,
    dataset_id: str,
    view: str,
    client: bigquery.Client | None = None,
) -> list[dict[str, Any]]:
    """Query a named INFORMATION_SCHEMA view and return rows as dicts."""
    bq = client or _bq_client(project_id)
    sql = f"SELECT * FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.{view}`"
    rows = list(bq.query(sql).result())
    return [dict(r) for r in rows]


def dry_run_query(
    project_id: str,
    sql: str,
    client: bigquery.Client | None = None,
) -> dict[str, Any]:
    """Dry-run a SQL query; return bytes processed and referenced tables."""
    bq = client or _bq_client(project_id)
    job_config = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    job = bq.query(sql, job_config=job_config)
    referenced = [
        f"{t.project}.{t.dataset_id}.{t.table_id}"
        for t in (job.referenced_tables or [])
    ]
    return {
        "bytes_processed": job.total_bytes_processed,
        "referenced_tables": referenced,
    }


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

def _compute_asset_hash(
    schema: list[dict[str, Any]] | None,
    routine_body: str | None,
    view_query: str | None,
) -> str:
    """sha256 of canonical JSON of (schema, routine_body, view_query)."""
    payload = json.dumps(
        {"schema": schema, "routine_body": routine_body, "view_query": view_query},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Crawl a single dataset
# ---------------------------------------------------------------------------

def _crawl_dataset(
    project_id: str,
    dataset_id: str,
    client: bigquery.Client,
) -> tuple[dict[str, int], list[str]]:
    """Crawl all tables/views/routines in one dataset.

    Returns (stats, changed_asset_ids).
    """
    stats: dict[str, int] = {"inserted": 0, "updated": 0, "skipped": 0}
    changed_asset_ids: list[str] = []
    now = datetime.now(UTC).isoformat()

    # Tables and views
    for tbl in list_tables(project_id, dataset_id, client=client):
        table_id = tbl["table_id"]
        table_type = tbl["type"]

        if table_type in ("TABLE", "VIEW", "MATERIALIZED_VIEW"):
            schema = get_table_schema(project_id, dataset_id, table_id, client=client)
            view_query = (
                get_view_query(project_id, dataset_id, table_id, client=client)
                if table_type in ("VIEW", "MATERIALIZED_VIEW")
                else None
            )
            content_hash = _compute_asset_hash(schema, None, view_query)
            kind = "bq_view" if table_type in ("VIEW", "MATERIALIZED_VIEW") else "bq_table"
            identifier = f"{project_id}.{dataset_id}.{table_id}"
            asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identifier))

            asset = {
                "asset_id": asset_id,
                "source": "bigquery",
                "kind": kind,
                "identifier": identifier,
                "repo_url": None,
                "branch": None,
                "commit_sha": None,
                "content_hash": content_hash,
                "size_bytes": len(json.dumps(schema).encode()),
                "raw_path": None,
                "created_at": now,
                "updated_at": now,
            }

            result_bq = bq_store.upsert_asset(asset, client=client)
            local_cache.upsert_asset(asset)
            stats[result_bq] = stats.get(result_bq, 0) + 1
            if result_bq in ("inserted", "updated"):
                changed_asset_ids.append(asset_id)
            logger.debug("Asset %s → %s", identifier, result_bq)

    # Routines (stored procedures / UDFs)
    dataset_ref = bigquery.DatasetReference(project_id, dataset_id)
    for routine in client.list_routines(dataset_ref):
        routine_id = routine.routine_id
        body = get_routine_definition(project_id, dataset_id, routine_id, client=client)
        content_hash = _compute_asset_hash(None, body, None)
        identifier = f"{project_id}.{dataset_id}.{routine_id}"
        asset_id = str(uuid.uuid5(uuid.NAMESPACE_URL, identifier))

        asset = {
            "asset_id": asset_id,
            "source": "bigquery",
            "kind": "bq_routine",
            "identifier": identifier,
            "repo_url": None,
            "branch": None,
            "commit_sha": None,
            "content_hash": content_hash,
            "size_bytes": len((body or "").encode()),
            "raw_path": None,
            "created_at": now,
            "updated_at": now,
        }

        result_bq = bq_store.upsert_asset(asset, client=client)
        local_cache.upsert_asset(asset)
        stats[result_bq] = stats.get(result_bq, 0) + 1
        if result_bq in ("inserted", "updated"):
            changed_asset_ids.append(asset_id)
        logger.debug("Routine %s → %s", identifier, result_bq)

    return stats, changed_asset_ids


# ---------------------------------------------------------------------------
# Top-level crawl entry point
# ---------------------------------------------------------------------------

def crawl_project(
    project_id: str,
    dataset_filter: list[str] | None = None,
    bq_client: bigquery.Client | None = None,
    store_client: bigquery.Client | None = None,
) -> dict[str, Any]:
    """
    Crawl all datasets (or a filtered subset) in a BQ project.

    Args:
        project_id: GCP project to crawl.
        dataset_filter: if set, only crawl these dataset IDs.
        bq_client: BQ client for introspection (injectable for tests).
        store_client: BQ client for writing to metadata_store (injectable for tests).

    Returns:
        dict with run_id, stats (inserted/updated/skipped totals), and datasets crawled.
    """
    introspect = bq_client or _bq_client(project_id)
    write_client = store_client or bq_store._client()

    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC).isoformat()

    run_record = {
        "run_id": run_id,
        "started_at": started_at,
        "finished_at": None,
        "sources": json.dumps({"bigquery": project_id}),
        "stats": "{}",
        "status": "running",
        "error": None,
    }
    bq_store.upsert_crawl_run(run_record, client=write_client)
    local_cache.upsert_crawl_run(run_record)

    totals: dict[str, int] = {"inserted": 0, "updated": 0, "skipped": 0}
    datasets_crawled: list[str] = []
    all_changed: list[str] = []

    try:
        all_datasets = list_datasets(project_id, client=introspect)
        target_datasets = (
            [d for d in all_datasets if d in dataset_filter]
            if dataset_filter
            else all_datasets
        )
        logger.info(
            "Crawling project %s — %d datasets", project_id, len(target_datasets)
        )

        for ds_id in target_datasets:
            logger.info("Crawling dataset %s.%s", project_id, ds_id)
            ds_stats, changed = _crawl_dataset(project_id, ds_id, client=introspect)
            for k, v in ds_stats.items():
                totals[k] = totals.get(k, 0) + v
            all_changed.extend(changed)
            datasets_crawled.append(ds_id)

        finished_at = datetime.now(UTC).isoformat()
        run_record.update(
            {
                "finished_at": finished_at,
                "stats": json.dumps(totals),
                "status": "succeeded",
            }
        )
        bq_store.upsert_crawl_run(run_record, client=write_client)
        local_cache.upsert_crawl_run(run_record)

        logger.info("Crawl %s complete: %s", run_id, totals)
        return {
            "run_id": run_id,
            "status": "succeeded",
            "datasets_crawled": datasets_crawled,
            "stats": totals,
            "changed_asset_ids": all_changed,
        }

    except Exception as exc:
        logger.exception("Crawl %s failed", run_id)
        finished_at = datetime.now(UTC).isoformat()
        run_record.update(
            {
                "finished_at": finished_at,
                "stats": json.dumps(totals),
                "status": "failed",
                "error": str(exc),
            }
        )
        bq_store.upsert_crawl_run(run_record, client=write_client)
        local_cache.upsert_crawl_run(run_record)
        raise
