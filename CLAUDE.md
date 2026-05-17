# CLAUDE.md — Operating Instructions for Claude Code

This file is your standing brief for the **Metadata Generator Agent** project. Read it at the start of every session.

## What this project is

A metadata generator that:
- Crawls BigQuery (datasets, tables, views, stored procedures) and Git repositories (SQL, Airflow DAGs, PySpark/Pandas).
- Extracts **column-level lineage** using OpenAI with structured JSON-schema outputs.
- Resolves transitive lineage up to **depth 2** (C → A → B should report C as B's effective source).
- Exposes everything through a Streamlit UI with a first-class Progress page for stakeholder demos.

Full design is in `METADATA_GENERATOR_SPEC.md`. Milestone list and live status is in `MILESTONES.md`.

## How to start every session

1. **Read `MILESTONES.md` first.** Find the milestone marked `🟡 in_progress`. If none, find the first one marked `⬜ pending`. That is your active milestone.
2. **Read `METADATA_GENERATOR_SPEC.md` §9 for that milestone's details.** Scope, deliverables, acceptance, preview command, commit message are all defined there.
3. **State your plan in one paragraph** before writing code: which milestone you're on, what you're about to build, what tests you'll add.
4. **Wait for the user to say "go"** before starting work on a fresh milestone. If you're resuming an in-progress milestone, continue without asking.

## Rules of engagement

1. **One milestone at a time.** Do not start M{n+1} until the user replies with explicit approval ("approved, move to M{n+1}" or similar).
2. **Show before you commit.** Print the preview command, paste any relevant output, and for UI work include a manual checklist. Wait for "approved" before `git commit`.
3. **Update `MILESTONES.md` as part of every milestone's commit.** Flip status, fill in commit SHA and date, check off acceptance items. This file is the single source of truth — there is no `app/milestones.py`.
4. **Tests must pass before commit.** Run `pytest` and `ruff check`. If anything is red, fix it or ask.
5. **Commit message format is defined in the spec.** Use it verbatim (e.g., `feat(m4): git crawler and classifier`).
6. **Save a Progress page screenshot** after each milestone to `docs/progress/m{n}.png` so the user can share with their manager.
7. **No silent scope creep.** If a milestone needs to grow, propose the change in chat and wait for sign-off before doing it.
8. **Secrets stay in `.env`.** The user's `GOOGLE_APPLICATION_CREDENTIALS` path is machine-specific — never commit it. `.env` is in `.gitignore`; `.env.example` shows the keys.
9. **OpenAI calls in tests use recorded fixtures** (VCR cassettes or saved JSON under `tests/fixtures/openai/`). No live API calls in CI.
10. **Idempotency everywhere.** Re-running a crawl or extraction must not duplicate rows. Test this explicitly.

## Tech stack (do not deviate without approval)

- Backend: **FastAPI** (Python 3.11+)
- UI: **Streamlit** (talks to FastAPI over HTTP)
- LLM: **OpenAI**, model from `OPENAI_MODEL` env var, structured outputs with `strict: true`
- Canonical store: **BigQuery** (`metadata_store` dataset, 5 tables — see spec §3)
- Local cache: **SQLite** at `./.cache/index.db` + raw files in `./.cache/`
- Async: **in-process asyncio queue** with bounded semaphore (no Celery/Redis in v1)
- Git: **GitPython**
- BigQuery: **google-cloud-bigquery**
- MCP: **`mcp` Python SDK**, server at `mcp_server/server.py`
- Tests: **pytest, pytest-asyncio**, VCR for OpenAI
- Lint/format: **ruff** + **ruff format**

## Environment

`.env` keys (the user's actual values stay local):

```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4o
GOOGLE_APPLICATION_CREDENTIALS=/Users/chiragtagadiya/.config/gcloud/application_default_credentials.json
BQ_METADATA_PROJECT=...
BQ_METADATA_DATASET=metadata_store
LOG_LEVEL=INFO
DEMO_FIXTURE_REPO=https://github.com/cr21/agentic-test-data
DEMO_FIXTURE_BRANCH=main
```

## Per-milestone workflow

For every milestone, follow this loop:

1. Mark the milestone `🟡 in_progress` in `MILESTONES.md` (commit this change separately as `chore: start mX`, or fold it into the milestone commit — your choice, but be consistent).
2. Write code + tests for the milestone's scope (spec §9).
3. Run `ruff check` and `pytest`. Both must be green.
4. Print the preview command from the spec and any relevant output to chat.
5. For UI work, list the manual checks the user should perform.
6. **Wait for user approval.**
7. On approval:
   - Update `MILESTONES.md`: status → `✅ done`, fill commit SHA (use `<pending>` placeholder, replace after commit), check off acceptance items.
   - Save Progress page screenshot to `docs/progress/m{n}.png` (UI milestones only; skip for pure-backend ones).
   - `git add -A && git commit -m "<message from spec>"`
   - Replace the `<pending>` SHA in `MILESTONES.md` with `git rev-parse --short HEAD`, amend the commit.
   - Push.
8. Announce completion in chat with the commit SHA. **Stop.** Wait for the user to greenlight the next milestone.

## When something goes wrong

- **Test fails after a change**: fix forward, don't disable. If the test was wrong, say so and propose a fix.
- **Acceptance criterion is ambiguous**: ask. Don't guess and proceed.
- **LLM returns invalid JSON despite `strict: true`**: retry once with a tightened system prompt; if still bad, log and surface as a job failure in `lineage_jobs`.
- **BigQuery quota or auth fails**: surface the error verbatim. Do not silently fall back to local-only mode.
- **You realize the milestone scope is wrong**: stop, write a short proposal to the user, wait for direction.

## Quick reference

- Active milestone tracker → `MILESTONES.md`
- Full design → `METADATA_GENERATOR_SPEC.md`
- Output schemas (verbatim) → spec §4, implemented in `app/llm/schemas.py`
- BigQuery table DDLs → spec §3, implemented in `scripts/init_bq_tables.py`
- MCP tools list → spec §8

## First-session checklist

If `MILESTONES.md` shows everything as `⬜ pending` and the working directory is empty, you're at the very start. Confirm with the user, then begin M1.
