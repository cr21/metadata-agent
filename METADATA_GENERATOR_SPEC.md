# Metadata Generator Agent — Build Spec for Claude Code

A milestone-driven specification for building a metadata generator that crawls BigQuery and Git repositories, extracts table-level metadata, end-to-end column metadata, and column-level lineage using an LLM, and exposes everything through a UI.

This document is structured so Claude Code can build it **one milestone at a time**, with a verification checkpoint, a Git commit, and a test run between each milestone. **Claude Code must not advance to the next milestone without explicit user approval.**

---

## 0. Goals and Non-Goals

**Goals**
- Crawl assets from BigQuery (datasets, tables, views, routines/stored procedures) and from a Git repository (SQL files, Airflow DAGs, PySpark/Pandas scripts).
- Store crawled assets in BigQuery (canonical store) and on the local filesystem (cache).
- Skip unchanged assets via content hash; update only what changed.
- Use OpenAI to extract column-level lineage in one of three structured formats: SQL/SP STM, Airflow DAG spec, or PySpark/Pandas STM.
- Resolve transitive lineage up to **depth 2** (e.g., C → A → B should report C → B as the effective source for B's columns).
- Expose a Streamlit UI for browsing crawled assets and previewing lineage in tabular form.
- Run lineage extraction in **both modes**: async-queued after a crawl, and on-demand refresh from the preview screen.
- Provide BigQuery tooling exposed via an MCP server where applicable.

**Non-goals (for v1)**
- Real-time streaming lineage.
- Authentication / multi-tenant access control.
- Visual graph rendering (table-format display is enough for v1; graph view is a stretch goal).
- Editing metadata in the UI (read-only display).

---

## 1. Tech Stack (locked)

| Layer | Choice |
|---|---|
| Backend API | FastAPI (Python 3.11+) |
| UI | Streamlit (talks to FastAPI over HTTP) |
| LLM | OpenAI (`gpt-4o` or `gpt-4.1`, configurable via env var) with **structured outputs** (`response_format` = JSON schema, `strict: true`) |
| Canonical store | BigQuery |
| Local cache | `./.cache/` (raw files) + SQLite at `./.cache/index.db` (hashes, status, job tracking) |
| Async queue | In-process `asyncio` task queue (no Celery/Redis for v1; revisit at scale) |
| Git access | `GitPython` |
| BigQuery client | `google-cloud-bigquery` |
| MCP server | Python MCP SDK (`mcp` package) exposing BigQuery tools |
| Tests | `pytest`, `pytest-asyncio`, with `vcrpy` or recorded fixtures for OpenAI calls |
| Lint/format | `ruff` + `ruff format` |

Environment variables (`.env`):
```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o
GOOGLE_APPLICATION_CREDENTIALS=/Users/chiragtagadiya/.config/gcloud/application_default_credentials.json
BQ_METADATA_PROJECT=...        # where the metadata tables live
BQ_METADATA_DATASET=metadata_store
LOG_LEVEL=INFO
DEMO_FIXTURE_REPO=https://github.com/cr21/agentic-test-data
DEMO_FIXTURE_BRANCH=main
```

**Auth model**: Application Default Credentials via the JSON path above (already on your machine). The BQ client picks this up automatically; no service-account JSON is committed to the repo.

---

## 2. Repository Layout

```
metadata-generator/
├── README.md
├── pyproject.toml
├── .env.example
├── app/
│   ├── api/                 # FastAPI routes
│   │   ├── crawl.py
│   │   ├── assets.py
│   │   └── lineage.py
│   ├── crawlers/
│   │   ├── bigquery_crawler.py
│   │   └── git_crawler.py
│   ├── classifier.py        # detect file kind: sql | sp | airflow_dag | pyspark | pandas | unknown
│   ├── llm/
│   │   ├── client.py
│   │   ├── prompts.py
│   │   └── schemas.py       # the three JSON schemas (verbatim from user)
│   ├── lineage/
│   │   ├── extractor.py     # orchestrates LLM calls per file kind
│   │   └── resolver.py      # depth-2 transitive resolution
│   ├── storage/
│   │   ├── bq_store.py
│   │   └── local_cache.py   # SQLite + filesystem
│   ├── queue.py             # asyncio task queue
│   ├── config.py
│   └── main.py              # FastAPI app entrypoint
├── ui/
│   └── streamlit_app.py
├── mcp_server/
│   └── server.py            # BigQuery MCP tools
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
└── scripts/
    └── init_bq_tables.py    # creates the metadata_store dataset and tables
```

---

## 3. Data Model (BigQuery `metadata_store` dataset)

Five tables. All timestamps UTC.

**`assets`** — one row per crawled object
| column | type | notes |
|---|---|---|
| asset_id | STRING (PK) | UUID |
| source | STRING | `bigquery` or `git` |
| kind | STRING | `bq_table`, `bq_view`, `bq_routine`, `sql_file`, `airflow_dag`, `pyspark_file`, `pandas_file`, `unknown` |
| identifier | STRING | `project.dataset.table` for BQ; repo-relative path for git |
| repo_url | STRING | nullable |
| branch | STRING | nullable |
| commit_sha | STRING | nullable, last commit that touched the file |
| content_hash | STRING | sha256 of the raw content |
| size_bytes | INT64 | |
| raw_path | STRING | local cache path |
| created_at | TIMESTAMP | |
| updated_at | TIMESTAMP | |

**`crawl_runs`** — one row per crawl invocation
| column | type |
|---|---|
| run_id | STRING (PK) |
| started_at | TIMESTAMP |
| finished_at | TIMESTAMP |
| sources | STRING (JSON: which sources were crawled) |
| stats | STRING (JSON: counts of added/updated/skipped) |
| status | STRING (`running`, `succeeded`, `failed`) |
| error | STRING |

**`lineage_jobs`** — async lineage extraction jobs
| column | type |
|---|---|
| job_id | STRING (PK) |
| asset_id | STRING |
| status | STRING (`queued`, `running`, `succeeded`, `failed`, `stale`) |
| schema_kind | STRING (`stm`, `dag_spec`, `pyspark_stm`) |
| llm_model | STRING |
| started_at | TIMESTAMP |
| finished_at | TIMESTAMP |
| error | STRING |
| input_hash | STRING | content_hash at the time of extraction; used to detect staleness |

**`lineage_results`** — the structured STM output
| column | type |
|---|---|
| result_id | STRING (PK) |
| asset_id | STRING |
| job_id | STRING |
| schema_kind | STRING |
| payload | STRING (JSON: the full STM result conforming to one of the three schemas) |
| created_at | TIMESTAMP |

**`lineage_edges`** — flattened column-level edges, derived from `lineage_results` (makes transitive resolution easy)
| column | type |
|---|---|
| edge_id | STRING (PK) |
| source_asset_id | STRING |
| target_table | STRING |
| target_column | STRING |
| source_table | STRING |
| source_column | STRING |
| transformation_type | STRING |
| transformation | STRING |
| depth | INT64 | 1 for direct edges; 2 for resolved transitive edges |
| created_at | TIMESTAMP |

The local SQLite cache mirrors `assets`, `crawl_runs`, and `lineage_jobs` for fast UI listing without hitting BigQuery on every page load.

---

## 4. LLM Output Schemas

The three schemas (`STM_SCHEMA`, `DAG_SPEC_SCHEMA`, `PYSPARK_STM_SCHEMA`) live verbatim in `app/llm/schemas.py` as defined in the original brief. The classifier decides which schema to request:

| File kind | Schema |
|---|---|
| `bq_table`, `bq_view`, `bq_routine`, `sql_file` | `STM_SCHEMA` |
| `airflow_dag` | `DAG_SPEC_SCHEMA` |
| `pyspark_file`, `pandas_file` | `PYSPARK_STM_SCHEMA` |

The OpenAI call uses `response_format={"type": "json_schema", "json_schema": <schema>}` with `strict: true`. On a schema-validation failure, retry once with a tightened system prompt that quotes the offending fields.

---

## 5. Lineage Extraction — How It Works

**Trigger paths**
1. **Async after crawl** — when a crawl run completes, every asset whose `content_hash` changed (or is new) is enqueued for extraction. Existing `lineage_jobs.input_hash` is compared to the current `content_hash`; if equal, the job is marked `stale → skipped`.
2. **On-demand from UI** — the preview page has a "Re-run lineage" button that enqueues a fresh job regardless of hash.

**Per-asset flow**
1. Load raw content from local cache.
2. Detect kind (classifier).
3. Build prompt: system message + raw file + (for SQL) referenced table schemas pulled from `assets`.
4. Call OpenAI with the matching JSON schema.
5. Validate against the schema (the OpenAI SDK does this; we also re-validate with `jsonschema` as a safety net).
6. Persist to `lineage_results`; explode into `lineage_edges` with `depth=1`.
7. Run `resolver` to compute `depth=2` edges (see §6).

**Concurrency**
- Bounded asyncio semaphore (default 4 concurrent LLM calls; configurable).
- Per-job timeout: 120s.
- Per-job retry: 2 attempts on transient errors, 1 attempt on schema-validation failure.

---

## 6. Transitive Lineage (Depth 2)

After all depth-1 edges for a crawl run are written, the resolver does:

```
for each target_column T in lineage_edges where depth = 1:
    for each (source_table S, source_column SC) of T:
        find depth-1 edges where target_table = S and target_column = SC
        if found:
            for each grandparent (G, GC):
                upsert edge (target = T, source = (G, GC), depth = 2)
```

We stop at depth 2 for v1. The UI's preview shows both direct (depth 1) and resolved (depth 2) sources side by side, so the user can see *"B.col is computed from A.col, which in turn comes from C.col"*.

A column may have multiple source columns; all combinations are expanded. Cycles are detected by tracking visited `(table, column)` pairs per traversal.

---

## 7. UI Behavior (Streamlit)

Four pages, navigated via a sidebar.

**Progress (demo view, default landing page)**
- Top banner: build version, last commit SHA, last commit message, current milestone.
- Milestone checklist — for each of M1–M9, show: name, scope one-liner, status (`pending` / `in_progress` / `done`), acceptance summary, commit SHA when done, link to preview command.
- "What this milestone proves" panel — a one-paragraph plain-English explanation per milestone, written for a non-engineer (your manager). Examples:
  - M2: *"We can remember what we've already seen, so re-crawling doesn't redo work."*
  - M5: *"We can ask the LLM to read one file and produce structured lineage that conforms to our schema — every time."*
  - M6: *"If table B comes from A which comes from C, we surface C as B's real source."*
- Live counters (read from BigQuery `assets`, `lineage_jobs`, `lineage_edges`): total assets, by kind, lineage jobs by status, edges at depth 1 vs depth 2.
- Recent activity feed: last 20 entries from `crawl_runs` and `lineage_jobs`.

Milestone state is read from a single source of truth: **`MILESTONES.md`** at the repo root. The FastAPI endpoint `GET /api/milestones` parses this file (status emoji + headings) and returns JSON; the Streamlit page renders from that endpoint. This means the page updates automatically as Claude Code edits `MILESTONES.md` during each milestone — no Python module to keep in sync.

**Crawl**
- Toggles: "Crawl BigQuery" / "Crawl Git" / both.
- BigQuery inputs: project_id (text), optional dataset filter (multi-select, populated after first connect).
- Git inputs: repo URL (defaults to `DEMO_FIXTURE_REPO`), branch (defaults to `DEMO_FIXTURE_BRANCH`), optional path prefix.
- "Start crawl" button → POSTs `/api/crawl`. Shows live status (polled).

**Assets**
- Filterable table: kind, source, last updated, lineage status.
- Click a row → Preview page.

**Preview (`/assets/{asset_id}`)**
- Header: identifier, kind, content_hash, last crawled, lineage job status.
- "Re-run lineage" button.
- Tabbed display based on `schema_kind`:
  - **STM** → per target table: a table with columns `column | datatype | source_columns | transformation | type | PII`.
  - **DAG spec** → task list with reads_hint/writes_hint, dependency chips.
  - **PySpark STM** → like STM plus `write_mode`, `target_location_type`, `spark_function` column.
- Below the direct STM: a "Resolved (depth 2)" panel showing transitive sources where they exist.

---

## 8. MCP Server — BigQuery Tools

Exposed at `mcp_server/server.py`. Tools:

| Tool | Args | Returns |
|---|---|---|
| `list_datasets` | `project_id` | array of dataset ids |
| `list_tables` | `project_id, dataset_id` | array of `{table_id, type, num_rows, last_modified}` |
| `get_table_schema` | `project_id, dataset_id, table_id` | INFORMATION_SCHEMA column list |
| `get_routine_definition` | `project_id, dataset_id, routine_id` | DDL body of the stored procedure/UDF |
| `query_information_schema` | `project_id, dataset_id, view` | rows from a named INFORMATION_SCHEMA view |
| `dry_run_query` | `project_id, sql` | bytes processed + referenced tables |

These tools are used both by the crawler internally and exposed via MCP so external agents (and the developer using Claude Code) can introspect BigQuery directly during development.

---

## 9. Milestones

Each milestone has: **scope**, **deliverables**, **acceptance tests**, **what gets committed**, and a **preview command**. After completing a milestone, Claude Code runs the test suite, prints the preview command, and **waits for explicit approval** ("approved, move to M{n+1}") before continuing.

### M1 — Project skeleton, config, and Progress page scaffold
**Scope**: repo layout, `pyproject.toml`, `.env.example` (with the real credentials path), `config.py`, logging, empty FastAPI app, Streamlit app with the **Progress page already wired up**, `pytest` wired up, `ruff` configured. `MILESTONES.md` and `CLAUDE.md` are present at repo root and committed in M1.
**Deliverables**:
- Repo boots: `uvicorn app.main:app` returns 200 on `/health`.
- `streamlit run ui/streamlit_app.py` opens on the Progress page showing all 9 milestones parsed from `MILESTONES.md`.
- `GET /api/milestones` returns the parsed milestone list (status, scope, acceptance, commit SHA).
- `pytest` runs 1 sanity test and passes.
**Acceptance**: both servers start; Progress page renders all 9 rows; tests green; `ruff check` clean.
**Preview**: `curl localhost:8000/health`, `curl localhost:8000/api/milestones`, visit Streamlit and screenshot for your manager.
**Commit**: `chore(m1): project skeleton + progress page`

### M2 — Storage layer
**Scope**: SQLite local cache schema, BigQuery dataset/tables created via `scripts/init_bq_tables.py`, `bq_store.py` and `local_cache.py` with upsert-by-hash semantics.
**Deliverables**:
- Running the init script idempotently creates the five BQ tables.
- Unit tests cover: insert new asset, update on hash change, no-op on hash match.
**Acceptance**: tests pass; BQ tables visible in the console; SQLite file created.
**Preview**: run init script; `python -c "from app.storage.local_cache import list_assets; print(list_assets())"`.
**Commit**: `feat(m2): storage layer (bq + sqlite)`

### M3 — BigQuery crawler + MCP tools
**Scope**: crawl datasets/tables/views/routines for a given project. Implement all six MCP tools. Wire the crawler to use the same internal functions the MCP tools expose.
**Deliverables**:
- `POST /api/crawl` with `{"bigquery": {"project_id": "..."}}` populates `assets` with rows for every table/view/routine.
- Hash for BQ assets is sha256 of the canonical JSON of `(schema + routine_body + view_query)`.
- MCP server starts and responds to `tools/list`.
**Acceptance**: integration test against a small sandbox project (or a mocked BQ client) returns expected counts; MCP server tool list matches §8.
**Preview**: crawl a real (small) project and inspect `assets` table.
**Commit**: `feat(m3): bigquery crawler and mcp server`

### M4 — Git crawler + file classifier
**Scope**: clone or pull a repo at a given branch, walk files, classify each, store with content hash. Skip unchanged.
**Fixture repo**: https://github.com/cr21/agentic-test-data (branch `main`). M4 integration tests run against a shallow clone of this repo.
**Deliverables**:
- Classifier rules:
  - `.sql` with `CREATE PROCEDURE`/`CREATE OR REPLACE PROCEDURE` → `bq_routine` (treated as SP)
  - other `.sql` → `sql_file`
  - `.py` importing `airflow` → `airflow_dag`
  - `.py` importing `pyspark` → `pyspark_file`
  - `.py` importing `pandas` (and not pyspark/airflow) → `pandas_file`
  - else → `unknown`
- Re-crawling the same branch with no changes produces zero updates.
- After M4 completes, the Progress page shows a "Demo repo crawled" stat with counts per file kind.
**Acceptance**: unit tests for each classifier rule; integration test against `cr21/agentic-test-data` produces the expected kind breakdown (Claude Code: lock the counts after first successful run).
**Preview**: crawl the fixture repo, verify `assets` rows and classifications, screenshot the Progress page.
**Commit**: `feat(m4): git crawler and classifier`

### M5 — LLM client + schemas + extractor (single asset)
**Scope**: OpenAI client with structured outputs, the three schemas verbatim, extractor that handles one asset end-to-end.
**Deliverables**:
- `POST /api/lineage/extract/{asset_id}` synchronously runs extraction and stores result.
- Recorded-fixture tests for one SQL file, one Airflow DAG, one PySpark file produce schema-valid output.
- Schema-validation retry path covered by a test that injects a bad first response.
**Acceptance**: tests pass; manual run on three real files produces sensible STMs.
**Preview**: hit the endpoint for three fixture assets and inspect `lineage_results`.
**Commit**: `feat(m5): llm lineage extractor`

### M6 — Edge explosion + depth-2 resolver
**Scope**: flatten `lineage_results.payload` into `lineage_edges` (depth 1), then compute depth-2 edges with cycle detection.
**Deliverables**:
- Unit tests for the resolver covering: simple A→B, chain C→A→B (expect depth-2 row C→B), diamond, cycle.
**Acceptance**: tests green; resolver runs in O(edges) per asset.
**Preview**: query `lineage_edges` for a chained fixture and verify depth-2 rows.
**Commit**: `feat(m6): edge resolver with depth-2 transitive lineage`

### M7 — Async job queue
**Scope**: in-process asyncio queue, semaphore-bounded workers, job lifecycle in `lineage_jobs`, automatic enqueue after crawl, on-demand enqueue endpoint.
**Deliverables**:
- `POST /api/crawl` returns immediately with a run_id; lineage jobs are enqueued for changed assets.
- `POST /api/lineage/refresh/{asset_id}` enqueues a fresh job.
- `GET /api/lineage/jobs?status=...` lists jobs.
- Staleness: if `input_hash == content_hash` and a non-failed result exists, skip.
**Acceptance**: tests verify concurrency limit, staleness skip, on-demand always runs.
**Preview**: crawl → watch jobs progress via the jobs endpoint.
**Commit**: `feat(m7): async lineage job queue`

### M8 — Streamlit UI
**Scope**: three pages per §7, polling status, preview tables per schema kind, depth-2 panel.
**Deliverables**:
- Crawl page kicks off a crawl and shows progress.
- Assets page filters and sorts.
- Preview page renders STM / DAG / PySpark variants in their own table layouts.
**Acceptance**: manual checklist (Claude Code writes it into `tests/ui_checklist.md`); no Python errors during a 5-minute click-through.
**Preview**: `streamlit run ui/streamlit_app.py` and run through the checklist.
**Commit**: `feat(m8): streamlit ui`

### M9 — End-to-end test + hardening
**Scope**: one integration test that crawls a fixture repo + mocked BQ project, runs the full pipeline, and asserts on `lineage_edges`. Add structured logging and error surfaces in the UI. Write `README.md` with quickstart.
**Deliverables**:
- `pytest tests/integration/test_end_to_end.py` passes.
- README explains: install, configure, run, troubleshoot.
**Acceptance**: clean pytest run; README walk-through works on a fresh machine.
**Commit**: `feat(m9): end-to-end test and docs`

---

## 10. Working Agreement with Claude Code

1. **One milestone at a time.** Do not begin Mn+1 until the user replies with explicit approval.
2. **Show before you commit.** Print the preview command and, for UI work, a short manual checklist. Wait for "approved" before running `git commit`.
3. **Tests must pass before commit.** If they don't, fix or ask.
4. **Commit messages follow the format shown in each milestone.**
5. **Update `MILESTONES.md` as part of each milestone's commit** — flip status emoji, fill in the commit SHA and completion date, check off acceptance items. The Progress page reads this file directly, so it must reflect reality after every commit.
6. **Take a screenshot of the Progress page** after each milestone and save it to `docs/progress/m{n}.png` so the user can share with their manager without re-running the app.
7. **No silent scope creep.** If a milestone needs to grow, propose the change and wait for sign-off.
8. **Secrets stay in `.env`.** Never commit credentials. The `GOOGLE_APPLICATION_CREDENTIALS` path is user-specific and stays out of git.
9. **OpenAI calls in tests are recorded fixtures** (VCR or a saved JSON) — no live calls in CI.
10. **Idempotency everywhere.** Re-running a crawl or an extraction must not duplicate rows.

---

## 11. Open Questions

- **Multi-project crawls**: v1 supports one BQ project per crawl request. Multi-project is a v2 item.
- **Graph view of lineage**: deferred. Tabular only in v1.

Resolved:
- ✅ Fixture repo: https://github.com/cr21/agentic-test-data (branch `main`).
- ✅ BigQuery auth: ADC via `~/.config/gcloud/application_default_credentials.json`.
- ✅ Progress visibility for manager demos: first-class Streamlit page, screenshots committed per milestone.
