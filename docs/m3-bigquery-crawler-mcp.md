# M3 — BigQuery Crawler + MCP Tools

## What was built

- **`app/crawlers/bigquery_crawler.py`** — crawls all datasets, tables, views, and routines in a BigQuery project. Asset hash = sha256 of canonical JSON of `(schema, routine_body, view_query)`. Upserts to both BigQuery and SQLite with idempotent semantics.
- **`mcp_server/server.py`** — MCP server exposing all 6 tools from spec §8 (`list_datasets`, `list_tables`, `get_table_schema`, `get_routine_definition`, `query_information_schema`, `dry_run_query`). Tools are thin wrappers over the same crawler functions.
- **`app/api/crawl.py`** — `POST /api/crawl` accepts `{"bigquery": {"project_id": "...", "dataset_filter": [...]}}` and runs a synchronous crawl returning `run_id`, `status`, `datasets_crawled`, and `stats`.
- **`app/api/assets.py`** — `GET /api/assets` with optional `?source=&kind=` filters; `GET /api/assets/{asset_id}`.
- **`app/main.py`** — routes wired; `/api/milestones` added, parsing `MILESTONES.md` to JSON for the Streamlit progress page.

## How to verify manually

### 1. Start the API

```bash
make api
# → uvicorn on http://localhost:8000
```

### 2. Crawl your BigQuery project

```bash
curl -s -X POST http://localhost:8000/api/crawl \
  -H "Content-Type: application/json" \
  -d '{"bigquery": {"project_id": "project-5c016d48-80d5-4534-b69"}}' | python -m json.tool
```

Expected response shape:
```json
{
  "run_id": "<uuid>",
  "status": "succeeded",
  "datasets_crawled": ["metadata_store"],
  "stats": {"inserted": N, "updated": 0, "skipped": 0}
}
```

### 3. Inspect crawled assets

```bash
curl -s http://localhost:8000/api/assets | python -m json.tool
# Filter by kind:
curl -s "http://localhost:8000/api/assets?kind=bq_table" | python -m json.tool
```

### 4. Check crawl run history

```bash
curl -s http://localhost:8000/api/crawl/runs | python -m json.tool
```

### 5. Verify idempotency — re-run same crawl

```bash
curl -s -X POST http://localhost:8000/api/crawl \
  -H "Content-Type: application/json" \
  -d '{"bigquery": {"project_id": "project-5c016d48-80d5-4534-b69"}}' | python -m json.tool
# stats.skipped should equal previous stats.inserted
```

### 6. Run MCP server and check tools/list

```bash
# In a separate terminal:
uv run python mcp_server/server.py
# The server listens on stdio. You can also check the tool list via the test suite:
make test -k test_mcp
```

### 7. Check milestones endpoint (used by Streamlit)

```bash
curl -s http://localhost:8000/api/milestones | python -m json.tool
```

## Known limitations

- Crawl is synchronous (returns when done). Async queuing is M7.
- `raw_path` is null for BQ assets (no raw file download in this milestone).
- `query_information_schema` and `dry_run_query` MCP tools require live GCP credentials; they are not exercised by the unit test suite.
