"""Idempotently creates the metadata_store dataset and 5 tables in BigQuery.

Run once before first use, or any time to verify tables exist.
"""

import sys

from google.cloud import bigquery
from google.cloud.bigquery import SchemaField

from app.config import get_settings


def _client() -> bigquery.Client:
    s = get_settings()
    return bigquery.Client(project=s.bq_metadata_project)


def _ensure_dataset(client: bigquery.Client, project: str, dataset_id: str) -> None:
    ref = bigquery.DatasetReference(project, dataset_id)
    dataset = bigquery.Dataset(ref)
    dataset.location = "US"
    client.create_dataset(dataset, exists_ok=True)
    print(f"  dataset {project}.{dataset_id} — ok")


# ---------------------------------------------------------------------------
# Table schemas
# ---------------------------------------------------------------------------

ASSETS_SCHEMA = [
    SchemaField("asset_id", "STRING", mode="REQUIRED"),
    SchemaField("source", "STRING", mode="REQUIRED"),
    SchemaField("kind", "STRING", mode="REQUIRED"),
    SchemaField("identifier", "STRING", mode="REQUIRED"),
    SchemaField("repo_url", "STRING"),
    SchemaField("branch", "STRING"),
    SchemaField("commit_sha", "STRING"),
    SchemaField("content_hash", "STRING", mode="REQUIRED"),
    SchemaField("size_bytes", "INT64"),
    SchemaField("raw_path", "STRING"),
    SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
    SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
]

CRAWL_RUNS_SCHEMA = [
    SchemaField("run_id", "STRING", mode="REQUIRED"),
    SchemaField("started_at", "TIMESTAMP"),
    SchemaField("finished_at", "TIMESTAMP"),
    SchemaField("sources", "STRING"),  # JSON
    SchemaField("stats", "STRING"),    # JSON
    SchemaField("status", "STRING"),
    SchemaField("error", "STRING"),
]

LINEAGE_JOBS_SCHEMA = [
    SchemaField("job_id", "STRING", mode="REQUIRED"),
    SchemaField("asset_id", "STRING"),
    SchemaField("status", "STRING"),
    SchemaField("schema_kind", "STRING"),
    SchemaField("llm_model", "STRING"),
    SchemaField("started_at", "TIMESTAMP"),
    SchemaField("finished_at", "TIMESTAMP"),
    SchemaField("error", "STRING"),
    SchemaField("input_hash", "STRING"),
]

LINEAGE_RESULTS_SCHEMA = [
    SchemaField("result_id", "STRING", mode="REQUIRED"),
    SchemaField("asset_id", "STRING"),
    SchemaField("job_id", "STRING"),
    SchemaField("schema_kind", "STRING"),
    SchemaField("payload", "STRING"),  # JSON
    SchemaField("created_at", "TIMESTAMP"),
]

LINEAGE_EDGES_SCHEMA = [
    SchemaField("edge_id", "STRING", mode="REQUIRED"),
    SchemaField("source_asset_id", "STRING"),
    SchemaField("target_table", "STRING"),
    SchemaField("target_column", "STRING"),
    SchemaField("source_table", "STRING"),
    SchemaField("source_column", "STRING"),
    SchemaField("transformation_type", "STRING"),
    SchemaField("transformation", "STRING"),
    SchemaField("depth", "INT64"),
    SchemaField("created_at", "TIMESTAMP"),
]

TABLES: list[tuple[str, list[SchemaField]]] = [
    ("assets", ASSETS_SCHEMA),
    ("crawl_runs", CRAWL_RUNS_SCHEMA),
    ("lineage_jobs", LINEAGE_JOBS_SCHEMA),
    ("lineage_results", LINEAGE_RESULTS_SCHEMA),
    ("lineage_edges", LINEAGE_EDGES_SCHEMA),
]


def _ensure_table(
    client: bigquery.Client,
    project: str,
    dataset_id: str,
    table_name: str,
    schema: list[SchemaField],
) -> None:
    table_ref = f"{project}.{dataset_id}.{table_name}"
    table = bigquery.Table(table_ref, schema=schema)
    client.create_table(table, exists_ok=True)
    print(f"  table {table_ref} — ok")


def init_tables() -> None:
    s = get_settings()
    project = s.bq_metadata_project
    dataset_id = s.bq_metadata_dataset

    if not project:
        print("ERROR: BQ_METADATA_PROJECT is not set in .env", file=sys.stderr)
        sys.exit(1)

    client = _client()
    print(f"Initialising metadata_store in {project}.{dataset_id} …")
    _ensure_dataset(client, project, dataset_id)
    for table_name, schema in TABLES:
        _ensure_table(client, project, dataset_id, table_name, schema)
    print("Done — all 5 tables ready.")


if __name__ == "__main__":
    init_tables()
