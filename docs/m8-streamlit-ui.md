# M8 — Streamlit UI (full)

## What was built

Four fully-wired Streamlit pages replacing the earlier skeleton:

| Page | What's new |
|---|---|
| **Dashboard** | Lineage job counters (pending/running/done/failed), depth-1/2 edge counts, 20-entry recent activity feed |
| **Crawl** | `jobs_enqueued` metric after crawl, Job Monitor table with Refresh button |
| **Assets** | Sort control, `lineage_status` column enriched from latest job, asset selector → navigate to Preview |
| **Preview** | Full build: asset header, Re-run Lineage button, STM/DAG/PySpark tabbed layouts, depth-2 transitive panel, job history |

## How to run

```bash
make api   # starts FastAPI on :8000
make ui    # starts Streamlit on :8501
```

Then open http://localhost:8501.

## Page-by-page details

### Dashboard
- Reads `/api/assets`, `/api/lineage/jobs`, `/api/lineage/edges`, `/api/crawl/runs`, `/api/milestones`.
- Shows live counters and a merged activity feed sorted by `started_at`.

### Crawl
- BigQuery and Git forms unchanged; result block now shows `jobs_enqueued`.
- Job Monitor section polls `/api/lineage/jobs`; "Refresh Jobs" button reruns the page.

### Assets
- Filters (source, kind) + sort (updated_at / kind / source / identifier).
- `lineage_status` column: latest job status per asset, fetched from `/api/lineage/jobs`.
- "Open Preview →" sets `st.session_state["preview_asset_id"]` and redirects.

### Preview
- Asset ID pre-loaded from session state (set by Assets page) or manually entered.
- Header: identifier, kind, source, job status badge, last-crawled date, hash.
- **STM** tab: per-target-table tabs → `Column | Datatype | Source Columns | Transformation | Type | PII`.
- **DAG spec** tab: task expanders with reads/writes lists and upstream chain.
- **PySpark STM** tab: like STM + Write Mode / Target Location metrics + `Spark Function` column.
- **Depth-2 panel**: `lineage_edges` rows with `depth=2` for the asset; collapsed expander if none.
- **Job History** expander: all jobs for the asset sorted newest-first.

## Navigation
Cross-page navigation uses `st.session_state["nav_page"]` and `st.rerun()`.  
The sidebar radio is index-driven from session state so programmatic redirects are reflected instantly.

## Known limitations
- No real-time auto-refresh; user clicks "Refresh Jobs" manually.
- Preview page requires the API to be running; no offline fallback.
- Streamlit has no native row-click on dataframes; asset selection uses a selectbox below the table.
