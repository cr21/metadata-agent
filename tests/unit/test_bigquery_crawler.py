"""Unit tests for BigQuery crawler — uses mocked BQ client, no live API calls."""

import hashlib
import json
from unittest.mock import MagicMock, patch

from app.crawlers import bigquery_crawler as bqc

# ---------------------------------------------------------------------------
# Helpers for building mock BQ objects
# ---------------------------------------------------------------------------

def _mock_table(table_id: str, table_type: str = "TABLE", num_rows: int = 100):
    t = MagicMock()
    t.table_id = table_id
    t.table_type = table_type
    t.num_rows = num_rows
    t.modified = None
    return t


def _mock_bq_table_resource(
    table_id: str,
    table_type: str = "TABLE",
    schema_fields: list[dict] | None = None,
    view_query: str | None = None,
    mview_query: str | None = None,
):
    """Mock for what bq.get_table() returns."""
    t = MagicMock()
    t.table_id = table_id
    t.table_type = table_type
    t.view_query = view_query
    t.mview_query = mview_query

    fields = []
    for f in (schema_fields or []):
        field = MagicMock()
        field.name = f["name"]
        field.field_type = f["type"]
        field.mode = f.get("mode", "NULLABLE")
        field.description = f.get("description")
        fields.append(field)
    t.schema = fields
    return t


def _mock_routine(routine_id: str, body: str = "SELECT 1"):
    r = MagicMock()
    r.routine_id = routine_id
    r.body = body
    return r


def _mock_dataset(dataset_id: str):
    ds = MagicMock()
    ds.dataset_id = dataset_id
    return ds


# ---------------------------------------------------------------------------
# _compute_asset_hash
# ---------------------------------------------------------------------------

def test_hash_is_sha256_of_canonical_json():
    schema = [{"name": "id", "type": "INTEGER", "mode": "REQUIRED", "description": None}]
    payload = json.dumps(
        {"schema": schema, "routine_body": None, "view_query": None},
        sort_keys=True,
        default=str,
    )
    expected = hashlib.sha256(payload.encode()).hexdigest()
    assert bqc._compute_asset_hash(schema, None, None) == expected


def test_hash_differs_on_schema_change():
    schema_v1 = [{"name": "id", "type": "INTEGER", "mode": "NULLABLE", "description": None}]
    schema_v2 = [{"name": "id", "type": "STRING", "mode": "NULLABLE", "description": None}]
    assert bqc._compute_asset_hash(schema_v1, None, None) != bqc._compute_asset_hash(schema_v2, None, None)


def test_hash_stable_for_same_input():
    schema = [{"name": "col", "type": "STRING", "mode": "NULLABLE", "description": None}]
    h1 = bqc._compute_asset_hash(schema, None, None)
    h2 = bqc._compute_asset_hash(schema, None, None)
    assert h1 == h2


# ---------------------------------------------------------------------------
# list_datasets
# ---------------------------------------------------------------------------

def test_list_datasets_returns_ids():
    client = MagicMock()
    client.list_datasets.return_value = [_mock_dataset("ds1"), _mock_dataset("ds2")]
    result = bqc.list_datasets("my-project", client=client)
    assert result == ["ds1", "ds2"]
    client.list_datasets.assert_called_once_with(project="my-project")


# ---------------------------------------------------------------------------
# list_tables
# ---------------------------------------------------------------------------

def test_list_tables_returns_metadata():
    client = MagicMock()
    client.list_tables.return_value = [
        _mock_table("orders", "TABLE", 500),
        _mock_table("vw_orders", "VIEW", 0),
    ]
    result = bqc.list_tables("proj", "ds", client=client)
    assert len(result) == 2
    assert result[0]["table_id"] == "orders"
    assert result[0]["type"] == "TABLE"
    assert result[1]["table_id"] == "vw_orders"
    assert result[1]["type"] == "VIEW"


# ---------------------------------------------------------------------------
# get_table_schema
# ---------------------------------------------------------------------------

def test_get_table_schema_returns_columns():
    client = MagicMock()
    client.get_table.return_value = _mock_bq_table_resource(
        "orders",
        schema_fields=[
            {"name": "id", "type": "INTEGER", "mode": "REQUIRED"},
            {"name": "total", "type": "FLOAT", "mode": "NULLABLE"},
        ],
    )
    result = bqc.get_table_schema("proj", "ds", "orders", client=client)
    assert len(result) == 2
    assert result[0]["name"] == "id"
    assert result[1]["name"] == "total"


# ---------------------------------------------------------------------------
# get_view_query
# ---------------------------------------------------------------------------

def test_get_view_query_returns_sql():
    client = MagicMock()
    client.get_table.return_value = _mock_bq_table_resource(
        "vw_orders", table_type="VIEW", view_query="SELECT * FROM orders"
    )
    result = bqc.get_view_query("proj", "ds", "vw_orders", client=client)
    assert result == "SELECT * FROM orders"


def test_get_view_query_returns_none_for_table():
    client = MagicMock()
    client.get_table.return_value = _mock_bq_table_resource("orders", table_type="TABLE")
    result = bqc.get_view_query("proj", "ds", "orders", client=client)
    assert result is None


# ---------------------------------------------------------------------------
# get_routine_definition
# ---------------------------------------------------------------------------

def test_get_routine_definition_returns_body():
    client = MagicMock()
    client.get_routine.return_value = _mock_routine("sp_calc", "BEGIN SELECT 1; END")
    result = bqc.get_routine_definition("proj", "ds", "sp_calc", client=client)
    assert result == "BEGIN SELECT 1; END"


def test_get_routine_definition_returns_none_on_error():
    client = MagicMock()
    client.get_routine.side_effect = Exception("not found")
    result = bqc.get_routine_definition("proj", "ds", "sp_missing", client=client)
    assert result is None


# ---------------------------------------------------------------------------
# dry_run_query
# ---------------------------------------------------------------------------

def test_dry_run_query_returns_bytes_and_tables():
    client = MagicMock()
    job = MagicMock()
    job.total_bytes_processed = 1024
    tbl = MagicMock()
    tbl.project = "proj"
    tbl.dataset_id = "ds"
    tbl.table_id = "orders"
    job.referenced_tables = [tbl]
    client.query.return_value = job

    result = bqc.dry_run_query("proj", "SELECT * FROM ds.orders", client=client)
    assert result["bytes_processed"] == 1024
    assert result["referenced_tables"] == ["proj.ds.orders"]


# ---------------------------------------------------------------------------
# crawl_project — integration with mocked BQ + storage
# ---------------------------------------------------------------------------

def _build_crawl_client(
    datasets=("sales",),
    tables=None,
    routines=None,
):
    """Build a mock BQ client that simulates a small project."""
    if tables is None:
        tables = [("orders", "TABLE"), ("vw_orders", "VIEW")]
    if routines is None:
        routines = [("sp_calc", "BEGIN SELECT 1; END")]

    client = MagicMock()

    # list_datasets
    client.list_datasets.return_value = [_mock_dataset(d) for d in datasets]

    # list_tables
    client.list_tables.return_value = [_mock_table(tid, ttype) for tid, ttype in tables]

    # get_table (called by get_table_schema and get_view_query)
    def _get_table(ref):
        tid = ref.table_id if hasattr(ref, "table_id") else str(ref).split(".")[-1]
        for name, ttype in tables:
            if name == tid:
                vq = "SELECT * FROM orders" if ttype == "VIEW" else None
                return _mock_bq_table_resource(
                    tid,
                    table_type=ttype,
                    schema_fields=[{"name": "id", "type": "INTEGER", "mode": "NULLABLE"}],
                    view_query=vq,
                )
        return _mock_bq_table_resource(tid)

    client.get_table.side_effect = _get_table

    # list_routines
    client.list_routines.return_value = [_mock_routine(rid, body) for rid, body in routines]

    # get_routine
    def _get_routine(ref):
        rid = ref.routine_id if hasattr(ref, "routine_id") else str(ref).split(".")[-1]
        for name, body in routines:
            if name == rid:
                return _mock_routine(rid, body)
        raise Exception("not found")

    client.get_routine.side_effect = _get_routine
    return client


def test_crawl_project_populates_assets(tmp_path):
    """End-to-end crawl with mocked BQ and SQLite cache — verifies asset counts."""
    introspect_client = _build_crawl_client(
        datasets=["sales"],
        tables=[("orders", "TABLE"), ("vw_orders", "VIEW")],
        routines=[("sp_calc", "BEGIN SELECT 1; END")],
    )

    # Mock both BQ write client and crawl_run upserts
    write_client = MagicMock()
    write_client.query.return_value = MagicMock(result=MagicMock(return_value=[]))
    write_client.insert_rows_json.return_value = []

    db_path = tmp_path / "index.db"

    with (
        patch("app.crawlers.bigquery_crawler.bq_store.upsert_asset", return_value="inserted"),
        patch("app.crawlers.bigquery_crawler.bq_store.upsert_crawl_run"),
        patch("app.crawlers.bigquery_crawler.bq_store._client", return_value=write_client),
        patch("app.storage.local_cache.DB_PATH", db_path),
    ):
        result = bqc.crawl_project(
            project_id="test-proj",
            bq_client=introspect_client,
            store_client=write_client,
        )

    assert result["status"] == "succeeded"
    assert "sales" in result["datasets_crawled"]
    # 2 tables + 1 routine = 3 assets
    assert result["stats"]["inserted"] == 3


def test_crawl_project_idempotent(tmp_path):
    """Second crawl with same content → all skipped."""
    introspect_client = _build_crawl_client(
        datasets=["ds"],
        tables=[("t1", "TABLE")],
        routines=[],
    )
    write_client = MagicMock()
    write_client.query.return_value = MagicMock(result=MagicMock(return_value=[]))
    write_client.insert_rows_json.return_value = []

    db_path = tmp_path / "index.db"

    with (
        patch("app.crawlers.bigquery_crawler.bq_store.upsert_asset", return_value="skipped"),
        patch("app.crawlers.bigquery_crawler.bq_store.upsert_crawl_run"),
        patch("app.crawlers.bigquery_crawler.bq_store._client", return_value=write_client),
        patch("app.storage.local_cache.DB_PATH", db_path),
    ):
        result = bqc.crawl_project(
            project_id="test-proj",
            bq_client=introspect_client,
            store_client=write_client,
        )

    assert result["stats"]["skipped"] == 1
    assert result["stats"].get("inserted", 0) == 0


def test_crawl_project_dataset_filter(tmp_path):
    """dataset_filter restricts which datasets are crawled."""
    introspect_client = _build_crawl_client(
        datasets=["ds_a", "ds_b"],
        tables=[("t1", "TABLE")],
        routines=[],
    )
    write_client = MagicMock()
    write_client.query.return_value = MagicMock(result=MagicMock(return_value=[]))
    write_client.insert_rows_json.return_value = []

    db_path = tmp_path / "index.db"

    with (
        patch("app.crawlers.bigquery_crawler.bq_store.upsert_asset", return_value="inserted"),
        patch("app.crawlers.bigquery_crawler.bq_store.upsert_crawl_run"),
        patch("app.crawlers.bigquery_crawler.bq_store._client", return_value=write_client),
        patch("app.storage.local_cache.DB_PATH", db_path),
    ):
        result = bqc.crawl_project(
            project_id="test-proj",
            dataset_filter=["ds_a"],
            bq_client=introspect_client,
            store_client=write_client,
        )

    assert result["datasets_crawled"] == ["ds_a"]
    assert result["stats"]["inserted"] == 1  # only ds_a.t1
