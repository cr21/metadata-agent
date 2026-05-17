"""BigQuery canonical store — upsert-by-hash semantics for all 5 metadata tables."""

from datetime import UTC, datetime
from functools import lru_cache

from google.cloud import bigquery

from app.config import get_settings


def _now_ts() -> str:
    return datetime.now(UTC).isoformat()


@lru_cache(maxsize=1)
def _client() -> bigquery.Client:
    s = get_settings()
    return bigquery.Client(project=s.bq_metadata_project)


def _table(name: str) -> str:
    s = get_settings()
    return f"{s.bq_metadata_project}.{s.bq_metadata_dataset}.{name}"


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------

def upsert_asset(asset: dict, client: bigquery.Client | None = None) -> str:
    """MERGE asset into BQ. Returns 'inserted', 'updated', or 'skipped'."""
    bq = client or _client()
    table = _table("assets")

    # Check for existing row
    check_sql = f"SELECT content_hash FROM `{table}` WHERE asset_id = @asset_id"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("asset_id", "STRING", asset["asset_id"])]
    )
    rows = list(bq.query(check_sql, job_config=job_config).result())

    now = _now_ts()

    if not rows:
        asset_row = {**asset}
        asset_row.setdefault("created_at", now)
        asset_row.setdefault("updated_at", now)
        errors = bq.insert_rows_json(table, [asset_row])
        if errors:
            raise RuntimeError(f"BQ insert errors: {errors}")
        return "inserted"

    if rows[0]["content_hash"] == asset["content_hash"]:
        return "skipped"

    update_sql = f"""
        UPDATE `{table}`
        SET source=@source, kind=@kind, identifier=@identifier, repo_url=@repo_url,
            branch=@branch, commit_sha=@commit_sha, content_hash=@content_hash,
            size_bytes=@size_bytes, raw_path=@raw_path, updated_at=@updated_at
        WHERE asset_id=@asset_id
    """
    params = [
        bigquery.ScalarQueryParameter("source", "STRING", asset.get("source")),
        bigquery.ScalarQueryParameter("kind", "STRING", asset.get("kind")),
        bigquery.ScalarQueryParameter("identifier", "STRING", asset.get("identifier")),
        bigquery.ScalarQueryParameter("repo_url", "STRING", asset.get("repo_url")),
        bigquery.ScalarQueryParameter("branch", "STRING", asset.get("branch")),
        bigquery.ScalarQueryParameter("commit_sha", "STRING", asset.get("commit_sha")),
        bigquery.ScalarQueryParameter("content_hash", "STRING", asset.get("content_hash")),
        bigquery.ScalarQueryParameter("size_bytes", "INT64", asset.get("size_bytes")),
        bigquery.ScalarQueryParameter("raw_path", "STRING", asset.get("raw_path")),
        bigquery.ScalarQueryParameter("updated_at", "STRING", now),
        bigquery.ScalarQueryParameter("asset_id", "STRING", asset["asset_id"]),
    ]
    bq.query(update_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return "updated"


def get_asset(asset_id: str, client: bigquery.Client | None = None) -> dict | None:
    bq = client or _client()
    table = _table("assets")
    sql = f"SELECT * FROM `{table}` WHERE asset_id = @asset_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("asset_id", "STRING", asset_id)]
    )
    rows = list(bq.query(sql, job_config=job_config).result())
    return dict(rows[0]) if rows else None


def list_assets(filters: dict | None = None, client: bigquery.Client | None = None) -> list[dict]:
    bq = client or _client()
    table = _table("assets")
    filters = filters or {}
    sql = f"SELECT * FROM `{table}`"
    params = []
    if filters:
        clauses = [f"{k} = @{k}" for k in filters]
        sql += " WHERE " + " AND ".join(clauses)
        params = [bigquery.ScalarQueryParameter(k, "STRING", v) for k, v in filters.items()]
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    rows = list(bq.query(sql, job_config=job_config).result())
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# crawl_runs
# ---------------------------------------------------------------------------

def upsert_crawl_run(run: dict, client: bigquery.Client | None = None) -> None:
    bq = client or _client()
    table = _table("crawl_runs")
    check_sql = f"SELECT run_id FROM `{table}` WHERE run_id = @run_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run["run_id"])]
    )
    exists = list(bq.query(check_sql, job_config=job_config).result())

    if not exists:
        errors = bq.insert_rows_json(table, [run])
        if errors:
            raise RuntimeError(f"BQ insert errors: {errors}")
        return

    update_sql = f"""
        UPDATE `{table}`
        SET finished_at=@finished_at, sources=@sources, stats=@stats, status=@status, error=@error
        WHERE run_id=@run_id
    """
    params = [
        bigquery.ScalarQueryParameter("finished_at", "STRING", run.get("finished_at")),
        bigquery.ScalarQueryParameter("sources", "STRING", run.get("sources")),
        bigquery.ScalarQueryParameter("stats", "STRING", run.get("stats")),
        bigquery.ScalarQueryParameter("status", "STRING", run.get("status")),
        bigquery.ScalarQueryParameter("error", "STRING", run.get("error")),
        bigquery.ScalarQueryParameter("run_id", "STRING", run["run_id"]),
    ]
    bq.query(update_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


# ---------------------------------------------------------------------------
# lineage_jobs
# ---------------------------------------------------------------------------

def upsert_lineage_job(job: dict, client: bigquery.Client | None = None) -> None:
    bq = client or _client()
    table = _table("lineage_jobs")
    check_sql = f"SELECT job_id FROM `{table}` WHERE job_id = @job_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("job_id", "STRING", job["job_id"])]
    )
    exists = list(bq.query(check_sql, job_config=job_config).result())

    if not exists:
        errors = bq.insert_rows_json(table, [job])
        if errors:
            raise RuntimeError(f"BQ insert errors: {errors}")
        return

    update_sql = f"""
        UPDATE `{table}`
        SET asset_id=@asset_id, status=@status, schema_kind=@schema_kind, llm_model=@llm_model,
            started_at=@started_at, finished_at=@finished_at, error=@error, input_hash=@input_hash
        WHERE job_id=@job_id
    """
    params = [
        bigquery.ScalarQueryParameter("asset_id", "STRING", job.get("asset_id")),
        bigquery.ScalarQueryParameter("status", "STRING", job.get("status")),
        bigquery.ScalarQueryParameter("schema_kind", "STRING", job.get("schema_kind")),
        bigquery.ScalarQueryParameter("llm_model", "STRING", job.get("llm_model")),
        bigquery.ScalarQueryParameter("started_at", "STRING", job.get("started_at")),
        bigquery.ScalarQueryParameter("finished_at", "STRING", job.get("finished_at")),
        bigquery.ScalarQueryParameter("error", "STRING", job.get("error")),
        bigquery.ScalarQueryParameter("input_hash", "STRING", job.get("input_hash")),
        bigquery.ScalarQueryParameter("job_id", "STRING", job["job_id"]),
    ]
    bq.query(update_sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


# ---------------------------------------------------------------------------
# lineage_results
# ---------------------------------------------------------------------------

def upsert_lineage_result(result: dict, client: bigquery.Client | None = None) -> None:
    bq = client or _client()
    table = _table("lineage_results")
    result_row = {**result}
    result_row.setdefault("created_at", _now_ts())
    check_sql = f"SELECT result_id FROM `{table}` WHERE result_id = @result_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("result_id", "STRING", result["result_id"])]
    )
    exists = list(bq.query(check_sql, job_config=job_config).result())
    if exists:
        return  # lineage_results are immutable; re-runs produce new rows
    errors = bq.insert_rows_json(table, [result_row])
    if errors:
        raise RuntimeError(f"BQ insert errors: {errors}")


# ---------------------------------------------------------------------------
# lineage_edges
# ---------------------------------------------------------------------------

def upsert_lineage_edge(edge: dict, client: bigquery.Client | None = None) -> None:
    bq = client or _client()
    table = _table("lineage_edges")
    edge_row = {**edge}
    edge_row.setdefault("created_at", _now_ts())
    check_sql = f"SELECT edge_id FROM `{table}` WHERE edge_id = @edge_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("edge_id", "STRING", edge["edge_id"])]
    )
    exists = list(bq.query(check_sql, job_config=job_config).result())
    if exists:
        return  # idempotent — same edge_id means same edge
    errors = bq.insert_rows_json(table, [edge_row])
    if errors:
        raise RuntimeError(f"BQ insert errors: {errors}")
