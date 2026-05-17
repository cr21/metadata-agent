# CLAUDE.md — Operating Instructions for Claude Code

This file is your standing brief for the **Metadata Generator Agent** project. Read it at the start of every session.

## What this project is

A metadata generator that:
- Crawls BigQuery (datasets, tables, views, stored procedures) and Git repositories (SQL, Airflow DAGs, PySpark/Pandas).
- Extracts **column-level lineage** using OpenAI with structured JSON-schema outputs.
- Resolves transitive lineage up to **depth 2** (C → A → B should report C as B's effective source).
- Exposes everything through a Streamlit UI — Dashboard, Crawl, Assets, and Preview pages — for end-user and stakeholder demos.

Full design is in `METADATA_GENERATOR_SPEC.md`. Milestone list and live status is in `MILESTONES.md`.

---

## How to start every session

1. **Read `MILESTONES.md` first.** Find the milestone marked `🟡 in_progress`. If none, find the first `⬜ pending`. That is your active milestone.
2. **Re-read the milestone's details in `METADATA_GENERATOR_SPEC.md` §9:** Goal, Deliverables, Out of scope, Acceptance criteria, preview command, commit message. If anything is ambiguous, **stop and ask** — do not guess and proceed.
3. **State your plan in one paragraph** before writing code: which milestone, what you're about to build, what tests you'll add.
4. **Wait for the user to say "go"** before starting a fresh milestone. If resuming an in-progress milestone, continue without asking.

---

## Per-milestone workflow

Follow this loop exactly for every milestone.

### 1 — Branch
Create a feature branch from an up-to-date `main`:
```bash
git checkout main
git pull origin main
git checkout -b feature/m<NUMBER>-<short-kebab-name>
```
Example: `feature/m2-storage-layer`

### 2 — Mark in progress
In `MILESTONES.md` flip `⬜ pending` → `🟡 in_progress`. Commit immediately:
```
chore(m<NUMBER>): start milestone
```

### 3 — Implement
Build only what is in this milestone's scope. If you discover something that belongs to a later milestone, add a note under that milestone in `MILESTONES.md` — do not implement it now.

### 4 — Test
Every acceptance criterion must have either a passing automated test (`pytest`) or a clearly described reproducible manual check. Run both before moving on:
```bash
make lint   # ruff check — must be clean
make test   # pytest — must be green
```

### 5 — Document
- Update `README.md` if the milestone adds a new setup step, env var, or run command.
- Add or update `docs/m<NUMBER>-<short-name>.md` with: what was built, how to run/verify it, known limitations.

### 6 — Commit frequently
Use **Conventional Commits** throughout the milestone (not just at the end):
- `feat(m<NUMBER>): <what>` — new capability
- `fix(m<NUMBER>): <what>` — bug fix
- `test(m<NUMBER>): <what>` — tests only
- `docs(m<NUMBER>): <what>` — docs only
- `chore(m<NUMBER>): <what>` — tooling / config

### 7 — Mark complete + final commit
In `MILESTONES.md` flip `🟡 in_progress` → `✅ done`, fill `Completed On` with today's date, check off every acceptance item. Commit:
```
chore(m<NUMBER>): complete milestone
```

### 8 — Push and open PR
```bash
git push -u origin feature/m<NUMBER>-<short-kebab-name>
gh pr create --title "M<NUMBER>: <Title>" --body <auto>
```

### 9 — Stop and report
Print exactly:
- Branch name
- PR URL
- What was built (2–4 bullets)
- Test results (`pytest` count, `ruff` status)
- Next milestone name

**Do not start the next milestone until the user explicitly confirms.**

---

## Definition of done

A milestone is done only when **all** of the following are true:

- [ ] Every *Deliverable* listed in the spec exists.
- [ ] Every *Acceptance criterion* has a passing test or a reproducible manual check.
- [ ] `MILESTONES.md` is updated (`✅ done`, date filled, acceptance items checked).
- [ ] PR is open.
- [ ] `make lint` and `make test` are both green on the feature branch.
- [ ] **The milestone's Streamlit page renders on a fresh checkout** and demonstrates the new capability without errors.

---

## Rules of engagement

1. **One milestone at a time.** Do not start M{n+1} until the user replies with explicit approval.
2. **Re-read before coding.** Always re-read the milestone's Goal, Deliverables, Out of scope, and Acceptance criteria before touching code. Stop and ask if anything is unclear.
3. **No silent scope creep.** If the milestone needs to grow, propose the change in chat and wait for sign-off before doing it.
4. **Tests must pass before any commit.** Run `make lint` and `make test`. Both must be green.
5. **Secrets stay in `.env`.** `GOOGLE_APPLICATION_CREDENTIALS` is machine-specific — never commit it. `.env` is in `.gitignore`; `.env.example` shows the keys.
6. **OpenAI calls in tests use recorded fixtures** (VCR cassettes or saved JSON under `tests/fixtures/openai/`). No live API calls in CI.
7. **Idempotency everywhere.** Re-running a crawl or extraction must not duplicate rows. Test this explicitly.

---

## Tech stack (do not deviate without approval)

- Backend: **FastAPI** (Python 3.12+)
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

---

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

---

## When something goes wrong

- **Test fails after a change**: fix forward, don't disable. If the test itself was wrong, say so and propose a fix.
- **Acceptance criterion is ambiguous**: stop and ask. Don't guess and proceed.
- **LLM returns invalid JSON despite `strict: true`**: retry once with a tightened system prompt; if still bad, log and surface as a job failure in `lineage_jobs`.
- **BigQuery quota or auth fails**: surface the error verbatim. Do not silently fall back to local-only mode.
- **Milestone scope feels wrong**: stop, write a short proposal, wait for direction.

---

## Quick reference

- Active milestone tracker → `MILESTONES.md`
- Full design → `METADATA_GENERATOR_SPEC.md`
- Output schemas (verbatim) → spec §4, implemented in `app/llm/schemas.py`
- BigQuery table DDLs → spec §3, implemented in `scripts/init_bq_tables.py`
- MCP tools list → spec §8
- Run commands → `Makefile` (`make api`, `make ui`, `make dev`, `make test`, `make lint`)
