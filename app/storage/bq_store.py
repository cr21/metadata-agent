"""BigQuery canonical store — upsert-by-hash semantics for all 5 metadata tables.

All writes use DML INSERT (not the streaming API) so that rows can be immediately
updated or deleted by subsequent DML statements. The streaming buffer would block
UPDATE/DELETE for up to 90 minutes after an insert_rows_json call.
"""

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


def _dml_insert(
    bq: bigquery.Client,
    table: str,
    row: dict,
    str_cols: list[str],
    int_cols: list[str] | None = None,
) -> None:
    """Execute a DML INSERT for `row` into `table`.

    Uses named query parameters (not streaming API) so rows are immediately
    accessible to subsequent DML UPDATE/DELETE statements.
    """
    int_cols = int_cols or []
    cols = list(row.keys())
    placeholders = ", ".join(f"@{c}" for c in cols)
    col_list = ", ".join(f"`{c}`" for c in cols)
    sql = f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders})"

    params = []
    for c in cols:
        v = row[c]
        if c in int_cols:
            params.append(bigquery.ScalarQueryParameter(c, "INT64", v))
        else:
            params.append(bigquery.ScalarQueryParameter(c, "STRING", str(v) if v is not None else None))

    bq.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


# ---------------------------------------------------------------------------
# assets
# ---------------------------------------------------------------------------

_ASSET_STR_COLS = [
    "asset_id", "source", "kind", "identifier", "repo_url", "branch",
    "commit_sha", "content_hash", "raw_path", "created_at", "updated_at",
]
_ASSET_INT_COLS = ["size_bytes"]


def upsert_asset(asset: dict, client: bigquery.Client | None = None) -> str:
    """DML-upsert an asset. Returns 'inserted', 'updated', or 'skipped'."""
    bq = client or _client()
    table = _table("assets")

    check_sql = f"SELECT content_hash FROM `{table}` WHERE asset_id = @asset_id"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("asset_id", "STRING", asset["asset_id"])]
    )
    rows = list(bq.query(check_sql, job_config=job_config).result())

    now = _now_ts()

    if not rows:
        row = {**asset}
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        _dml_insert(bq, table, row, _ASSET_STR_COLS, _ASSET_INT_COLS)
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

_CRAWL_RUN_COLS = ["run_id", "started_at", "finished_at", "sources", "stats", "status", "error"]


def upsert_crawl_run(run: dict, client: bigquery.Client | None = None) -> None:
    bq = client or _client()
    table = _table("crawl_runs")
    check_sql = f"SELECT run_id FROM `{table}` WHERE run_id = @run_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run["run_id"])]
    )
    exists = list(bq.query(check_sql, job_config=job_config).result())

    if not exists:
        row = {k: run.get(k) for k in _CRAWL_RUN_COLS}
        _dml_insert(bq, table, row, _CRAWL_RUN_COLS)
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

_LINEAGE_JOB_COLS = [
    "job_id", "asset_id", "status", "schema_kind", "llm_model",
    "started_at", "finished_at", "error", "input_hash",
]


def upsert_lineage_job(job: dict, client: bigquery.Client | None = None) -> None:
    bq = client or _client()
    table = _table("lineage_jobs")
    check_sql = f"SELECT job_id FROM `{table}` WHERE job_id = @job_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("job_id", "STRING", job["job_id"])]
    )
    exists = list(bq.query(check_sql, job_config=job_config).result())

    if not exists:
        row = {k: job.get(k) for k in _LINEAGE_JOB_COLS}
        _dml_insert(bq, table, row, _LINEAGE_JOB_COLS)
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

_LINEAGE_RESULT_COLS = ["result_id", "asset_id", "job_id", "schema_kind", "payload", "created_at"]


def upsert_lineage_result(result: dict, client: bigquery.Client | None = None) -> None:
    bq = client or _client()
    table = _table("lineage_results")
    row = {**result}
    row.setdefault("created_at", _now_ts())

    check_sql = f"SELECT result_id FROM `{table}` WHERE result_id = @result_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("result_id", "STRING", result["result_id"])]
    )
    exists = list(bq.query(check_sql, job_config=job_config).result())
    if exists:
        return  # lineage_results are immutable; re-runs produce new rows

    insert_row = {k: row.get(k) for k in _LINEAGE_RESULT_COLS}
    _dml_insert(bq, table, insert_row, _LINEAGE_RESULT_COLS)


# ---------------------------------------------------------------------------
# lineage_edges
# ---------------------------------------------------------------------------

_LINEAGE_EDGE_STR_COLS = [
    "edge_id", "source_asset_id", "target_table", "target_column",
    "source_table", "source_column", "transformation_type", "transformation", "created_at",
]
_LINEAGE_EDGE_INT_COLS = ["depth"]


def upsert_lineage_edge(edge: dict, client: bigquery.Client | None = None) -> None:
    bq = client or _client()
    table = _table("lineage_edges")
    row = {**edge}
    row.setdefault("created_at", _now_ts())

    check_sql = f"SELECT edge_id FROM `{table}` WHERE edge_id = @edge_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("edge_id", "STRING", edge["edge_id"])]
    )
    exists = list(bq.query(check_sql, job_config=job_config).result())
    if exists:
        return  # idempotent — same edge_id means same edge

    all_cols = _LINEAGE_EDGE_STR_COLS + _LINEAGE_EDGE_INT_COLS
    insert_row = {k: row.get(k) for k in all_cols}
    _dml_insert(bq, table, insert_row, _LINEAGE_EDGE_STR_COLS, _LINEAGE_EDGE_INT_COLS)
