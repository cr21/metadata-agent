# M8 UI Checklist — 5-Minute Click-Through

Run both servers before starting:
```bash
make api   # terminal 1
make ui    # terminal 2
```

---

## 1. Dashboard page

- [ ] Page loads without Python errors in the terminal.
- [ ] Asset counters show `—` (or 0) since the cache is empty.
- [ ] Build Progress section lists all 9 milestones with correct status icons (✅ / 🟡 / ⬜).
- [ ] M8 shows 🟡 in_progress.

---

## 2. Crawl page — Git repository

- [ ] Navigate to **Crawl**. Default URL is pre-filled (`https://github.com/cr21/agentic-test-data`, branch `main`).
- [ ] Click **Start Git Crawl**. Spinner appears while cloning.
- [ ] After crawl: success banner shows run ID.
- [ ] Metrics show Inserted > 0, Skipped = 0.
- [ ] "Files by kind" table appears with at least `sql_file`, `airflow_dag`, `pyspark_file`, `pandas_file`.
- [ ] "Jobs Enqueued" metric shows a positive number.
- [ ] Info banner appears: "X lineage jobs enqueued — check the Job Monitor below."
- [ ] **Recent Crawl Runs** table shows the run with status `done`.
- [ ] **Job Monitor** shows jobs with status `pending` or `running` or `done`.
- [ ] Click **Refresh Jobs** — job statuses update.

---

## 3. Dashboard page — after crawl

- [ ] Navigate back to **Dashboard**.
- [ ] Total Assets > 0.
- [ ] "Demo Repo — File Kinds" section visible with non-zero counts.
- [ ] "Lineage Jobs" section visible with counts by status.
- [ ] "Recent Activity" feed shows both crawl and lineage entries.

---

## 4. Assets page

- [ ] Navigate to **Assets**. Table lists crawled files.
- [ ] `lineage_status` column shows job status (`done`, `pending`, `failed`, or `—`).
- [ ] Filter by **Source = git** — BQ assets disappear, only git assets remain.
- [ ] Filter by **Kind = airflow_dag** — only Airflow files show.
- [ ] Reset filters to `all`. Change **Sort by = kind** — rows reorder.
- [ ] Select an asset from the dropdown, click **Open Preview →** — navigates to Preview page.

---

## 5. Preview page — STM asset (sql_file / bq_routine)

- [ ] Asset header shows identifier, kind, source, lineage job status, last crawled date.
- [ ] If job is `done`: STM table renders with columns `Column | Datatype | Source Columns | Transformation | Type | PII`.
- [ ] If PII column exists: shows "🔴 Yes" for flagged columns.
- [ ] If depth-2 transitive edges exist: "Resolved (Depth 2)" panel is visible with edge rows.
- [ ] If no depth-2 edges: expander shows "No transitive (depth-2) edges found."
- [ ] **Job History** expander shows the job(s) for this asset.

---

## 6. Preview page — DAG spec asset (airflow_dag)

- [ ] Navigate to an `airflow_dag` asset (via Assets → Open Preview).
- [ ] Header shows kind = `airflow_dag`.
- [ ] DAG ID and description are shown.
- [ ] Each task renders in a collapsible expander with:  
  - Reads from / Writes to lists.
  - Upstream chain (if dependencies exist).

---

## 7. Preview page — PySpark STM asset (pyspark_file / pandas_file)

- [ ] Navigate to a `pyspark_file` or `pandas_file` asset.
- [ ] Header shows kind = `pyspark_file` (or `pandas_file`).
- [ ] Tabs per target table; each tab shows **Write Mode** and **Target Location** metrics.
- [ ] Table includes `Spark Function` column in addition to the STM columns.

---

## 8. Re-run Lineage button

- [ ] On any Preview page, click **Re-run Lineage**.
- [ ] Success message shows new job ID.
- [ ] Page reruns; Job History expander shows the new job.

---

## 9. Error handling

- [ ] Stop the API server (`Ctrl+C` in terminal 1).
- [ ] Reload Dashboard — warning banner "Cannot reach API — is `make api` running?" appears, no Python traceback.
- [ ] Restart the API. Dashboard recovers on next load.

---

## Pass criteria

All boxes checked with **zero Python tracebacks** in either terminal during the click-through.
