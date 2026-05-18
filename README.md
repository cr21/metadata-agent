# Metadata Generator Agent

Crawls BigQuery and Git repositories, extracts column-level lineage using OpenAI structured outputs, resolves transitive lineage up to depth 2, and exposes everything through a Streamlit UI.

---

## Quick start

### 1. Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- A Google Cloud project with BigQuery enabled (for BQ crawling)
- An OpenAI API key

### 2. Clone and install

```bash
git clone <repo-url>
cd metadata-agent
uv sync
```

### 3. Configure

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | Your OpenAI API key |
| `OPENAI_MODEL` | Model to use (default: `gpt-4o`) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Path to your GCP ADC JSON file |
| `BQ_METADATA_PROJECT` | GCP project that hosts the metadata store tables |
| `BQ_METADATA_DATASET` | BigQuery dataset name (default: `metadata_store`) |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` (default: `INFO`) |
| `LOG_FORMAT` | `text` (default) or `json` for machine-readable logs |
| `DEMO_FIXTURE_REPO` | Git repo to crawl in the demo (default: `https://github.com/cr21/agentic-test-data`) |
| `DEMO_FIXTURE_BRANCH` | Branch to crawl (default: `main`) |

### 4. Initialize BigQuery tables (first run only)

```bash
uv run python scripts/init_bq_tables.py
```

This creates the five `metadata_store` tables (`assets`, `crawl_runs`, `lineage_jobs`, `lineage_results`, `lineage_edges`) idempotently.

### 5. Start the API server

```bash
make api
```

The FastAPI server starts at `http://localhost:8000`. Verify with:

```bash
curl localhost:8000/health
```

### 6. Start the Streamlit UI

In a second terminal:

```bash
make ui
```

Open `http://localhost:8501` in your browser.

Or run both together with:

```bash
make dev
```

---

## Using the UI

### Dashboard

Landing page showing:
- Asset counts by kind
- Lineage job status (queued / running / succeeded / failed)
- Edge counts at depth 1 and depth 2
- Recent crawl runs and lineage jobs
- Build progress for all milestones

A red banner appears on the Dashboard if any lineage jobs failed — click through to the **Preview** page for error details.

### Crawl

Trigger a crawl against BigQuery or a Git repository:

- **BigQuery**: enter a GCP project ID and an optional dataset filter
- **Git**: enter a repo URL and branch (defaults to the demo fixture repo)

Crawl results return immediately with a `run_id`; lineage extraction runs in the background. Use the **Job Monitor** section at the bottom of the Crawl page to track progress.

### Assets

Filterable, sortable table of all crawled assets. Filter by `source` (bigquery / git) and `kind` (bq_table, sql_file, airflow_dag, etc.). Click **Open Preview →** to view lineage for a specific asset.

### Preview

Displays the extracted lineage for one asset:

- **STM** (SQL / BQ): per-target-table view of columns, source columns, transformation description, transformation type, and PII flag
- **DAG spec** (Airflow): task list with reads/writes hints and upstream dependency chain
- **PySpark STM**: like STM plus write mode, target location type, and Spark function used

A **Resolved (Depth 2)** panel shows transitive sources where they exist.

Use the **Re-run Lineage** button to force a fresh extraction regardless of the content hash.

---

## Running from the command line

### Crawl a Git repo

```bash
curl -s -X POST http://localhost:8000/api/crawl \
  -H "Content-Type: application/json" \
  -d '{"git": {"repo_url": "https://github.com/cr21/agentic-test-data", "branch": "main"}}' | jq .
```

### Crawl BigQuery

```bash
curl -s -X POST http://localhost:8000/api/crawl \
  -H "Content-Type: application/json" \
  -d '{"bigquery": {"project_id": "my-gcp-project"}}' | jq .
```

### List assets

```bash
curl -s "http://localhost:8000/api/assets?source=git&kind=sql_file" | jq .
```

### Trigger on-demand lineage extraction

```bash
curl -s -X POST http://localhost:8000/api/lineage/refresh/<asset_id> | jq .
```

### List lineage jobs

```bash
curl -s "http://localhost:8000/api/lineage/jobs?status=failed" | jq .
```

---

## Development

### Run tests

```bash
make test
```

Unit tests use mocked BQ clients and recorded LLM fixtures — no live API calls needed.

Integration tests (`tests/integration/`) require network access to clone `https://github.com/cr21/agentic-test-data` and use a mocked LLM client (no OpenAI calls).

```bash
# Integration tests only
pytest tests/integration/ -v
```

### Lint

```bash
make lint
```

Uses `ruff` — all checks must pass before committing.

### MCP server

The MCP server exposes BigQuery tooling for use with Claude Code and other MCP-compatible clients:

```bash
uv run python mcp_server/server.py
```

Tools: `list_datasets`, `list_tables`, `get_table_schema`, `get_routine_definition`, `query_information_schema`, `dry_run_query`.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Cannot reach API — is make api running?` | Start the API with `make api` in a separate terminal |
| BQ auth error | Run `gcloud auth application-default login` and set `GOOGLE_APPLICATION_CREDENTIALS` in `.env` |
| Lineage job stuck in `running` after restart | Jobs are auto-recovered to `failed` on the next server startup |
| `Schema validation failed after retry` in job error | The file content may be too large or ambiguous; check the asset's raw content |
| All lineage jobs show `stale` | Expected — the extractor skips assets whose content hash hasn't changed. Use **Re-run Lineage** to force re-extraction |
| `No assets yet` on Assets page | Run a crawl first from the **Crawl** page |

---

## Architecture overview

```
┌─────────────────┐    HTTP     ┌─────────────────────┐
│  Streamlit UI   │ ──────────► │   FastAPI (port 8000)│
│  port 8501      │             │                     │
└─────────────────┘             │  /api/crawl         │
                                │  /api/assets        │
                                │  /api/lineage/*     │
                                │  /api/milestones    │
                                └─────────┬───────────┘
                                          │
                    ┌─────────────────────┼──────────────┐
                    ▼                     ▼              ▼
             ┌────────────┐      ┌──────────────┐  ┌──────────┐
             │  Crawlers  │      │  Async Queue │  │  MCP     │
             │  BQ / Git  │      │  (asyncio)   │  │  Server  │
             └─────┬──────┘      └──────┬───────┘  └──────────┘
                   │                   │
                   ▼                   ▼
          ┌─────────────────┐   ┌─────────────────┐
          │  Local cache    │   │  LLM Extractor  │
          │  SQLite + files │   │  (OpenAI)       │
          └─────────────────┘   └─────────────────┘
                   │
                   ▼
          ┌─────────────────┐
          │  BigQuery store │
          │  (canonical)    │
          └─────────────────┘
```

Data flows: crawl → local cache (SQLite + raw files) → async queue → LLM extraction → `lineage_results` → edge explosion → `lineage_edges` → depth-2 resolver → UI.
