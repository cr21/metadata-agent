# MILESTONES.md — Live Build Tracker

**Single source of truth for milestone status.** Claude Code updates this file as part of every milestone's commit. Streamlit Progress page reads from this file.

## Status legend

- ⬜ `pending` — not started
- 🟡 `in_progress` — actively being worked on
- ✅ `done` — committed and approved
- ❌ `blocked` — needs user input

## Active milestone

> **M5** — LLM client + schemas + extractor (single asset)

---

## M1 — Project skeleton + Progress page scaffold

- **Status**: ✅ done
- **Commit SHA**: df25e80
- **Completed**: 2026-05-17
- **What this proves (for manager)**: *"The app boots, the demo page is wired up, and we have a place to track everything from here."*

**Scope**: repo layout, `pyproject.toml`, `.env.example`, `config.py`, logging, empty FastAPI app, Streamlit app with Dashboard/Crawl/Assets/Preview pages, `pytest`, `ruff`, `Makefile`.

**Acceptance**:
- [x] `uvicorn app.main:app` returns 200 on `/health`
- [x] `streamlit run ui/streamlit_app.py` opens on Dashboard page with 4-page sidebar
- [x] `pytest` green
- [x] `ruff check` clean
- [x] `Makefile` shortcuts wired (`make api`, `make ui`, `make dev`, `make test`, `make lint`)

**Preview**: `curl localhost:8000/health` · `curl localhost:8000/api/milestones` · open Streamlit, screenshot for manager

**Commit message**: `chore(m1): project skeleton + progress page`

---

## M2 — Storage layer (BigQuery + SQLite)

- **Status**: ✅ done
- **Commit SHA**: —
- **Completed**: 2026-05-17
- **What this proves (for manager)**: *"We can remember what we've already seen, so re-crawling doesn't redo work."*

**Scope**: SQLite cache schema, BQ tables created via `scripts/init_bq_tables.py`, `bq_store.py` and `local_cache.py` with upsert-by-hash semantics.

**Acceptance**:
- [x] Running init script idempotently creates the 5 BQ tables
- [x] Unit test: insert new asset
- [x] Unit test: update on hash change
- [x] Unit test: no-op on hash match
- [x] `ruff check` clean

**Preview**: run init script · `python -c "from app.storage.local_cache import list_assets; print(list_assets())"`

**Commit message**: `feat(m2): storage layer (bq + sqlite)`

---

## M3 — BigQuery crawler + MCP tools

- **Status**: ✅ done
- **Commit SHA**: d9d4dda
- **Completed**: 2026-05-17
- **What this proves (for manager)**: *"Point the tool at a BigQuery project and it inventories every table, view, and stored procedure — plus other agents can introspect BQ through our MCP server."*

**Scope**: crawl datasets/tables/views/routines for a given project. Implement all 6 MCP tools (spec §8). Wire crawler to use the same internal functions the MCP tools expose.

**Acceptance**:
- [x] `POST /api/crawl` with `{"bigquery": {"project_id": "..."}}` populates `assets`
- [x] BQ asset hash = sha256 of canonical JSON of `(schema + routine_body + view_query)`
- [x] MCP server `tools/list` returns all 6 tools per spec §8
- [x] Integration test against mocked BQ client passes

**Preview**: crawl a real small project; inspect `assets` table; run MCP `tools/list`

**Commit message**: `feat(m3): bigquery crawler and mcp server`

---

## M4 — Git crawler + file classifier

- **Status**: ✅ done
- **Commit SHA**: 9c18c6f
- **Completed**: 2026-05-17
- **What this proves (for manager)**: *"We can pull a repo and correctly identify SQL files, stored procedures, Airflow DAGs, and PySpark scripts — each gets the right downstream treatment."*

**Scope**: clone/pull repo at given branch, walk files, classify, store with content hash. Skip unchanged. Test against `https://github.com/cr21/agentic-test-data` (branch `main`).

**Classifier rules**:
- `.sql` with `CREATE [OR REPLACE] PROCEDURE` → `bq_routine`
- other `.sql` → `sql_file`
- `.py` importing `airflow` → `airflow_dag`
- `.py` importing `pyspark` → `pyspark_file`
- `.py` importing `pandas` (and not pyspark/airflow) → `pandas_file`
- else → `unknown`

**Acceptance**:
- [x] Unit test for each classifier rule
- [x] Integration test against `cr21/agentic-test-data` produces expected kind breakdown (lock counts after first run)
- [x] Re-crawling same branch with no changes produces zero updates
- [x] Progress page shows "Demo repo crawled" stats per kind

**Preview**: crawl fixture repo; verify `assets` rows; screenshot Progress page

**Commit message**: `feat(m4): git crawler and classifier`

---

## M5 — LLM client + schemas + extractor (single asset)

- **Status**: 🟡 in_progress
- **Commit SHA**: —
- **Completed**: —
- **What this proves (for manager)**: *"We can ask the LLM to read one file and produce structured lineage that conforms to our schema — every time."*

**Scope**: OpenAI client with structured outputs (`strict: true`), three schemas verbatim in `app/llm/schemas.py`, extractor handling one asset end-to-end.

**Acceptance**:
- [ ] `POST /api/lineage/extract/{asset_id}` synchronously runs and stores result
- [ ] Recorded-fixture test: one SQL file produces schema-valid STM
- [ ] Recorded-fixture test: one Airflow DAG produces schema-valid DAG spec
- [ ] Recorded-fixture test: one PySpark file produces schema-valid PySpark STM
- [ ] Schema-validation retry path covered by test (inject bad first response)

**Preview**: hit endpoint for 3 fixture assets; inspect `lineage_results`

**Commit message**: `feat(m5): llm lineage extractor`

---

## M6 — Edge explosion + depth-2 resolver

- **Status**: ⬜ pending
- **Commit SHA**: —
- **Completed**: —
- **What this proves (for manager)**: *"If table B comes from A, which comes from C, we surface C as B's real source — even when the pipeline spans multiple files."*

**Scope**: flatten `lineage_results.payload` into `lineage_edges` (depth 1), compute depth-2 edges with cycle detection.

**Acceptance**:
- [ ] Unit test: simple A→B
- [ ] Unit test: chain C→A→B produces depth-2 row C→B
- [ ] Unit test: diamond shape resolves correctly
- [ ] Unit test: cycle does not loop forever
- [ ] Runs in O(edges) per asset

**Preview**: query `lineage_edges` for a chained fixture; verify depth-2 rows

**Commit message**: `feat(m6): edge resolver with depth-2 transitive lineage`

---

## M7 — Async job queue

- **Status**: ⬜ pending
- **Commit SHA**: —
- **Completed**: —
- **What this proves (for manager)**: *"Crawls return instantly, lineage runs in the background, and users can re-trigger any asset on demand without waiting on others."*

**Scope**: in-process asyncio queue, semaphore-bounded workers, job lifecycle in `lineage_jobs`, auto-enqueue after crawl, on-demand endpoint.

**Acceptance**:
- [ ] `POST /api/crawl` returns immediately with run_id; jobs enqueued for changed assets
- [ ] `POST /api/lineage/refresh/{asset_id}` enqueues fresh job
- [ ] `GET /api/lineage/jobs?status=...` lists jobs
- [ ] Staleness: skip if `input_hash == content_hash` and non-failed result exists
- [ ] Test: concurrency limit honored
- [ ] Test: staleness skip works
- [ ] Test: on-demand always runs (bypasses staleness)

**Preview**: crawl; watch jobs progress via jobs endpoint

**Commit message**: `feat(m7): async lineage job queue`

---

## M8 — Streamlit UI (full)

- **Status**: ⬜ pending
- **Commit SHA**: —
- **Completed**: —
- **What this proves (for manager)**: *"The whole thing is usable end-to-end through a UI — crawl, browse, preview lineage in a table, drill into transitive sources."*

**Scope**: four pages per spec §7 — Progress (already exists, enhanced), Crawl, Assets, Preview. Polling status; STM/DAG/PySpark variant table layouts; depth-2 panel on Preview.

**Acceptance**:
- [ ] Crawl page kicks off crawl and shows progress
- [ ] Assets page filters and sorts
- [ ] Preview page renders STM variant correctly
- [ ] Preview page renders DAG spec variant correctly
- [ ] Preview page renders PySpark STM variant correctly
- [ ] Preview page shows depth-2 panel where transitive edges exist
- [ ] `tests/ui_checklist.md` written and passes 5-minute click-through with no Python errors

**Preview**: `streamlit run ui/streamlit_app.py`; run through checklist

**Commit message**: `feat(m8): streamlit ui`

---

## M9 — End-to-end test + hardening + docs

- **Status**: ⬜ pending
- **Commit SHA**: —
- **Completed**: —
- **What this proves (for manager)**: *"The whole pipeline works on a fresh machine following a README — and we have a single test that proves it."*

**Scope**: integration test crawling fixture repo + mocked BQ project, running full pipeline, asserting on `lineage_edges`. Structured logging. UI error surfaces. `README.md` quickstart.

**Acceptance**:
- [ ] `pytest tests/integration/test_end_to_end.py` passes
- [ ] README quickstart works on a fresh machine
- [ ] Errors in lineage jobs are visible in UI
- [ ] All milestones above show ✅ done

**Preview**: clean pytest run; README walk-through on a clean clone

**Commit message**: `feat(m9): end-to-end test and docs`

---

## Notes

- **Update procedure**: when starting a milestone, flip ⬜ → 🟡. When committing, flip 🟡 → ✅, fill `Commit SHA` (use `git rev-parse --short HEAD` after committing, then `git commit --amend`), fill `Completed` with `YYYY-MM-DD`, check off acceptance boxes.
- **The "Active milestone" line at the top is updated alongside the status flips** — keep it in sync.
- **If blocked**, flip to ❌ and write the blocker under that milestone's section.
