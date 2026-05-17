"""Unit tests for BigQuery store — uses a mock BQ client, no live API calls."""

from unittest.mock import MagicMock

from app.storage import bq_store  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(existing_hash: str | None = None) -> MagicMock:
    """Return a mock BQ client. existing_hash simulates a pre-existing asset row."""
    client = MagicMock()

    def _query(sql: str, job_config=None):
        job = MagicMock()
        # For SELECT queries that check existence, return a row if existing_hash set
        if "SELECT content_hash" in sql:
            job.result.return_value = (
                [MagicMock(**{"__getitem__": lambda self, k: existing_hash})]
                if existing_hash
                else []
            )
        elif "SELECT run_id" in sql or "SELECT job_id" in sql or "SELECT result_id" in sql or "SELECT edge_id" in sql:
            job.result.return_value = []
        else:
            job.result.return_value = []
        return job

    client.query.side_effect = _query
    client.insert_rows_json.return_value = []  # no errors
    return client


def _asset(asset_id: str = "a1", content_hash: str = "hash_v1") -> dict:
    return {
        "asset_id": asset_id,
        "source": "git",
        "kind": "sql_file",
        "identifier": "sql/query.sql",
        "repo_url": None,
        "branch": "main",
        "commit_sha": "abc",
        "content_hash": content_hash,
        "size_bytes": 100,
        "raw_path": ".cache/a1.sql",
    }


# ---------------------------------------------------------------------------
# upsert_asset
# ---------------------------------------------------------------------------

def test_bq_insert_new_asset():
    """New asset (no existing row) → INSERT → returns 'inserted'."""
    client = _make_client(existing_hash=None)
    result = bq_store.upsert_asset(_asset(), client=client)
    assert result == "inserted"
    client.insert_rows_json.assert_called_once()


def test_bq_noop_on_hash_match():
    """Existing asset with same hash → returns 'skipped', no INSERT/UPDATE."""
    client = _make_client(existing_hash="hash_v1")
    result = bq_store.upsert_asset(_asset(content_hash="hash_v1"), client=client)
    assert result == "skipped"
    client.insert_rows_json.assert_not_called()


def test_bq_update_on_hash_change():
    """Existing asset with different hash → UPDATE → returns 'updated'."""
    client = _make_client(existing_hash="hash_v1")

    # The query mock needs to know: first call checks hash, second call is UPDATE
    call_count = 0

    def _query(sql: str, job_config=None):
        nonlocal call_count
        call_count += 1
        job = MagicMock()
        if call_count == 1 and "SELECT content_hash" in sql:
            row = MagicMock()
            row.__getitem__ = lambda self, k: "hash_v1"
            job.result.return_value = [row]
        else:
            job.result.return_value = []
        return job

    client.query.side_effect = _query
    result = bq_store.upsert_asset(_asset(content_hash="hash_v2"), client=client)
    assert result == "updated"
    client.insert_rows_json.assert_not_called()


# ---------------------------------------------------------------------------
# upsert_crawl_run
# ---------------------------------------------------------------------------

def test_bq_upsert_crawl_run_inserts_new():
    client = _make_client()
    run = {
        "run_id": "r1", "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": None, "sources": '["git"]', "stats": "{}",
        "status": "running", "error": None,
    }
    bq_store.upsert_crawl_run(run, client=client)
    client.insert_rows_json.assert_called_once()


# ---------------------------------------------------------------------------
# upsert_lineage_job
# ---------------------------------------------------------------------------

def test_bq_upsert_lineage_job_inserts_new():
    client = _make_client()
    job = {
        "job_id": "j1", "asset_id": "a1", "status": "queued",
        "schema_kind": "stm", "llm_model": "gpt-4o",
        "started_at": None, "finished_at": None, "error": None, "input_hash": "h1",
    }
    bq_store.upsert_lineage_job(job, client=client)
    client.insert_rows_json.assert_called_once()


# ---------------------------------------------------------------------------
# upsert_lineage_result / upsert_lineage_edge (idempotent inserts)
# ---------------------------------------------------------------------------

def test_bq_upsert_lineage_result_inserts_new():
    client = _make_client()
    result = {
        "result_id": "res1", "asset_id": "a1", "job_id": "j1",
        "schema_kind": "stm", "payload": "{}",
    }
    bq_store.upsert_lineage_result(result, client=client)
    client.insert_rows_json.assert_called_once()


def test_bq_upsert_lineage_edge_inserts_new():
    client = _make_client()
    edge = {
        "edge_id": "e1", "source_asset_id": "a1",
        "target_table": "orders", "target_column": "total",
        "source_table": "order_items", "source_column": "amount",
        "transformation_type": "aggregation", "transformation": "SUM",
        "depth": 1,
    }
    bq_store.upsert_lineage_edge(edge, client=client)
    client.insert_rows_json.assert_called_once()
