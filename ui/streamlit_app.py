"""Streamlit UI — Metadata Generator Agent."""

from __future__ import annotations

import json

import httpx
import pandas as pd
import streamlit as st

FASTAPI_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Metadata Generator",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Session-state defaults
# ---------------------------------------------------------------------------

if "nav_page" not in st.session_state:
    st.session_state["nav_page"] = "Dashboard"
if "preview_asset_id" not in st.session_state:
    st.session_state["preview_asset_id"] = ""

# ---------------------------------------------------------------------------
# Sidebar navigation — index driven by session state so code can redirect
# ---------------------------------------------------------------------------

PAGES = ["Dashboard", "Crawl", "Assets", "Preview"]

with st.sidebar:
    st.title("🔍 Metadata Generator")
    current_idx = PAGES.index(st.session_state["nav_page"]) if st.session_state["nav_page"] in PAGES else 0
    page = st.radio("Navigate", PAGES, index=current_idx)
    # Sync selection back so programmatic changes also show as selected
    if page != st.session_state["nav_page"]:
        st.session_state["nav_page"] = page


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api(path: str, method: str = "GET", json_body: dict | None = None):
    try:
        if method == "POST":
            r = httpx.post(f"{FASTAPI_BASE}{path}", json=json_body, timeout=300)
        else:
            r = httpx.get(f"{FASTAPI_BASE}{path}", timeout=30)
        r.raise_for_status()
        return r.json(), None
    except httpx.ConnectError:
        return None, "Cannot reach API — is `make api` running?"
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json().get("detail", str(e))
        except Exception:
            detail = str(e)
        return None, detail
    except Exception as e:
        return None, str(e)


def _nav_to(target_page: str, asset_id: str = "") -> None:
    """Redirect to another page, optionally pre-loading an asset."""
    st.session_state["nav_page"] = target_page
    if asset_id:
        st.session_state["preview_asset_id"] = asset_id
    st.rerun()


# ---------------------------------------------------------------------------
# Lineage render helpers
# ---------------------------------------------------------------------------

def _render_stm(payload: dict) -> None:
    entries = payload.get("stm_entries", [])
    if not entries:
        st.info("No STM entries in this result.")
        return
    tab_labels = [e.get("target_table", f"Table {i}") for i, e in enumerate(entries)]
    tabs = st.tabs(tab_labels)
    for tab, entry in zip(tabs, entries):
        with tab:
            cols = entry.get("columns", [])
            if not cols:
                st.info("No columns.")
                continue
            rows = []
            for c in cols:
                src = ", ".join(
                    f"{s['table']}.{s['column']}" for s in c.get("source_columns", [])
                )
                rows.append(
                    {
                        "Column": c.get("column", ""),
                        "Datatype": c.get("datatype", ""),
                        "Source Columns": src or "—",
                        "Transformation": c.get("transformation", ""),
                        "Type": c.get("transformation_type", ""),
                        "PII": "🔴 Yes" if c.get("is_pii") else "No",
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_dag_spec(payload: dict) -> None:
    dag_id = payload.get("dag_id", "—")
    description = payload.get("description", "")
    tasks = payload.get("tasks", [])
    st.markdown(f"**DAG ID:** `{dag_id}`")
    if description:
        st.markdown(f"**Description:** {description}")
    st.divider()
    if not tasks:
        st.info("No tasks found.")
        return
    for task in tasks:
        with st.expander(
            f"📌 `{task.get('task_id', '')}` — {task.get('operator', '')}",
            expanded=False,
        ):
            if task.get("description"):
                st.caption(task["description"])
            col_r, col_w = st.columns(2)
            with col_r:
                reads = task.get("reads_hint", [])
                st.markdown("**Reads from**")
                if reads:
                    for r in reads:
                        st.markdown(f"- `{r}`")
                else:
                    st.markdown("_none_")
            with col_w:
                writes = task.get("writes_hint", [])
                st.markdown("**Writes to**")
                if writes:
                    for w in writes:
                        st.markdown(f"- `{w}`")
                else:
                    st.markdown("_none_")
            deps = task.get("dependencies", [])
            if deps:
                chain = " → ".join(deps + [task.get("task_id", "")])
                st.markdown(f"**Upstream chain:** `{chain}`")


def _render_pyspark_stm(payload: dict) -> None:
    entries = payload.get("stm_entries", [])
    if not entries:
        st.info("No STM entries in this result.")
        return
    tab_labels = [e.get("target_table", f"Table {i}") for i, e in enumerate(entries)]
    tabs = st.tabs(tab_labels)
    for tab, entry in zip(tabs, entries):
        with tab:
            m1, m2 = st.columns(2)
            m1.metric("Write Mode", entry.get("write_mode", "—"))
            m2.metric("Target Location", entry.get("target_location_type", "—"))
            cols = entry.get("columns", [])
            if not cols:
                st.info("No columns.")
                continue
            rows = []
            for c in cols:
                src = ", ".join(
                    f"{s['table']}.{s['column']}" for s in c.get("source_columns", [])
                )
                rows.append(
                    {
                        "Column": c.get("column", ""),
                        "Datatype": c.get("datatype", ""),
                        "Source Columns": src or "—",
                        "Transformation": c.get("transformation", ""),
                        "Type": c.get("transformation_type", ""),
                        "Spark Function": c.get("spark_function", "—"),
                        "PII": "🔴 Yes" if c.get("is_pii") else "No",
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

# ── Dashboard ───────────────────────────────────────────────────────────────
if page == "Dashboard":
    st.title("Metadata Generator — Dashboard")

    assets_data, err = _api("/api/assets")
    jobs_data, _ = _api("/api/lineage/jobs")
    edges_data, _ = _api("/api/lineage/edges")
    runs_data, _ = _api("/api/crawl/runs")
    milestones_data, _ = _api("/api/milestones")

    if err:
        st.warning(f"API not reachable: {err}")
        for label in ["Total Assets", "BQ Tables", "BQ Views", "BQ Routines"]:
            pass
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Assets", "—")
        col2.metric("BQ Tables", "—")
        col3.metric("BQ Views", "—")
        col4.metric("BQ Routines", "—")
    else:
        assets = assets_data or []
        total = len(assets)

        bq_tables = sum(1 for a in assets if a.get("kind") == "bq_table")
        bq_views = sum(1 for a in assets if a.get("kind") == "bq_view")
        bq_routines = sum(1 for a in assets if a.get("kind") == "bq_routine")

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total Assets", total)
        col2.metric("BQ Tables", bq_tables)
        col3.metric("BQ Views", bq_views)
        col4.metric("BQ Routines", bq_routines)

        sql_files = sum(1 for a in assets if a.get("kind") == "sql_file")
        git_routines = sum(
            1 for a in assets if a.get("kind") == "bq_routine" and a.get("source") == "git"
        )
        airflow_dags = sum(1 for a in assets if a.get("kind") == "airflow_dag")
        pyspark_files = sum(1 for a in assets if a.get("kind") == "pyspark_file")
        pandas_files = sum(1 for a in assets if a.get("kind") == "pandas_file")
        git_total = sum(1 for a in assets if a.get("source") == "git")

        if git_total > 0:
            st.divider()
            st.subheader("Demo Repo — File Kinds")
            gc1, gc2, gc3, gc4, gc5 = st.columns(5)
            gc1.metric("SQL Files", sql_files)
            gc2.metric("Git Routines (SP)", git_routines)
            gc3.metric("Airflow DAGs", airflow_dags)
            gc4.metric("PySpark Files", pyspark_files)
            gc5.metric("Pandas Files", pandas_files)

        if total == 0:
            st.info("No assets yet. Go to **Crawl** to index your first source.")

    # Lineage job counters
    jobs = jobs_data or []
    if jobs:
        st.divider()
        st.subheader("Lineage Jobs")
        jc1, jc2, jc3, jc4 = st.columns(4)
        jc1.metric("Pending", sum(1 for j in jobs if j.get("status") == "pending"))
        jc2.metric("Running", sum(1 for j in jobs if j.get("status") == "running"))
        jc3.metric("Done", sum(1 for j in jobs if j.get("status") == "done"))
        jc4.metric("Failed", sum(1 for j in jobs if j.get("status") == "failed"))

    # Edge counters
    edges = edges_data or []
    if edges:
        st.divider()
        ec1, ec2 = st.columns(2)
        ec1.metric("Lineage Edges (depth 1)", sum(1 for e in edges if e.get("depth") == 1))
        ec2.metric("Transitive Edges (depth 2)", sum(1 for e in edges if e.get("depth") == 2))

    # Recent activity feed
    runs = runs_data or []
    if jobs or runs:
        st.divider()
        st.subheader("Recent Activity (last 20)")
        activities = []
        for r in runs[:10]:
            activities.append(
                {
                    "type": "crawl",
                    "id": r.get("run_id", "")[:12],
                    "status": r.get("status", ""),
                    "started_at": r.get("started_at", ""),
                    "detail": str(r.get("stats", "")),
                }
            )
        for j in jobs[:20]:
            activities.append(
                {
                    "type": "lineage",
                    "id": j.get("job_id", "")[:12],
                    "status": j.get("status", ""),
                    "started_at": j.get("started_at", "") or "",
                    "detail": j.get("schema_kind", "") or j.get("error", "") or "",
                }
            )
        activities.sort(key=lambda x: x.get("started_at") or "", reverse=True)
        st.dataframe(
            pd.DataFrame(activities[:20]),
            use_container_width=True,
            hide_index=True,
        )

    # Milestone progress
    if milestones_data:
        st.divider()
        st.subheader("Build Progress")
        for m in milestones_data:
            status = m.get("status", "pending")
            icon = {"done": "✅", "in_progress": "🟡", "pending": "⬜", "blocked": "❌"}.get(
                status, "⬜"
            )
            with st.expander(f"{icon} {m.get('title', '')}"):
                if m.get("what_proves"):
                    st.markdown(f"*{m['what_proves']}*")
                if m.get("completed"):
                    st.caption(
                        f"Completed: {m['completed']}  |  SHA: {m.get('commit_sha', '—')}"
                    )
                for item in m.get("acceptance", []):
                    chk = "✅" if item["checked"] else "☐"
                    st.markdown(f"  {chk} {item['text']}")

# ── Crawl ────────────────────────────────────────────────────────────────────
elif page == "Crawl":
    st.title("🕷️ Crawl")

    crawl_type = st.radio("Crawl source", ["BigQuery", "Git repository"], horizontal=True)

    if crawl_type == "BigQuery":
        with st.form("crawl_bq_form"):
            project_id = st.text_input("GCP Project ID", placeholder="my-gcp-project")
            dataset_filter_raw = st.text_input(
                "Dataset filter (optional — comma-separated)", placeholder="dataset1, dataset2"
            )
            submitted = st.form_submit_button("Start BigQuery Crawl")

        if submitted:
            if not project_id.strip():
                st.error("Project ID is required.")
            else:
                dataset_filter = (
                    [d.strip() for d in dataset_filter_raw.split(",") if d.strip()]
                    if dataset_filter_raw.strip()
                    else None
                )
                payload: dict = {"bigquery": {"project_id": project_id.strip()}}
                if dataset_filter:
                    payload["bigquery"]["dataset_filter"] = dataset_filter

                with st.spinner("Crawling BigQuery… (this may take a minute)"):
                    result, err = _api("/api/crawl", method="POST", json_body=payload)

                if err:
                    st.error(f"Crawl failed: {err}")
                else:
                    st.success(f"Crawl completed — run ID: `{result['run_id']}`")
                    stats = result.get("stats", {})
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Inserted", stats.get("inserted", 0))
                    c2.metric("Updated", stats.get("updated", 0))
                    c3.metric("Skipped", stats.get("skipped", 0))
                    c4.metric("Jobs Enqueued", result.get("jobs_enqueued", 0))
                    st.caption(
                        f"Datasets crawled: {', '.join(result.get('datasets_crawled', []))}"
                    )
                    if result.get("jobs_enqueued", 0):
                        st.info(
                            f"🔄 {result['jobs_enqueued']} lineage jobs enqueued — check the Job Monitor below."
                        )

    else:  # Git repository
        with st.form("crawl_git_form"):
            repo_url = st.text_input(
                "Repository URL", value="https://github.com/cr21/agentic-test-data"
            )
            branch = st.text_input("Branch", value="main")
            path_prefix = st.text_input(
                "Path prefix (optional)", placeholder="dags/"
            )
            submitted_git = st.form_submit_button("Start Git Crawl")

        if submitted_git:
            if not repo_url.strip():
                st.error("Repository URL is required.")
            else:
                payload_git: dict = {
                    "git": {
                        "repo_url": repo_url.strip(),
                        "branch": branch.strip() or "main",
                    }
                }
                if path_prefix.strip():
                    payload_git["git"]["path_prefix"] = path_prefix.strip()

                with st.spinner("Cloning / pulling repo and classifying files…"):
                    result, err = _api("/api/crawl", method="POST", json_body=payload_git)

                if err:
                    st.error(f"Git crawl failed: {err}")
                else:
                    st.success(f"Git crawl completed — run ID: `{result['run_id']}`")
                    stats = result.get("stats", {})
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Inserted", stats.get("inserted", 0))
                    c2.metric("Updated", stats.get("updated", 0))
                    c3.metric("Skipped", stats.get("skipped", 0))
                    c4.metric("Jobs Enqueued", result.get("jobs_enqueued", 0))

                    kind_counts = result.get("kind_counts") or {}
                    if kind_counts:
                        st.subheader("Files by kind")
                        kc_df = pd.DataFrame(
                            list(kind_counts.items()), columns=["Kind", "Count"]
                        ).sort_values("Count", ascending=False)
                        st.dataframe(kc_df, use_container_width=True, hide_index=True)

                    if result.get("jobs_enqueued", 0):
                        st.info(
                            f"🔄 {result['jobs_enqueued']} lineage jobs enqueued — check the Job Monitor below."
                        )

    # Recent crawl runs
    st.divider()
    st.subheader("Recent Crawl Runs")
    runs, run_err = _api("/api/crawl/runs")
    if run_err:
        st.warning(run_err)
    elif not runs:
        st.info("No crawl runs yet.")
    else:
        runs_df = pd.DataFrame(runs)
        show_cols = [c for c in ["run_id", "status", "started_at", "finished_at", "stats"] if c in runs_df.columns]
        st.dataframe(runs_df[show_cols], use_container_width=True, hide_index=True)

    # Job monitor
    st.divider()
    st.subheader("Job Monitor")
    col_refresh, _ = st.columns([1, 5])
    if col_refresh.button("🔄 Refresh Jobs"):
        st.rerun()

    jobs, jobs_err = _api("/api/lineage/jobs")
    if jobs_err:
        st.warning(jobs_err)
    elif not jobs:
        st.info("No lineage jobs yet. Run a crawl first.")
    else:
        jobs_df = pd.DataFrame(jobs)
        show_j = [c for c in ["job_id", "asset_id", "status", "schema_kind", "started_at", "finished_at", "error"] if c in jobs_df.columns]
        st.dataframe(jobs_df[show_j], use_container_width=True, hide_index=True)

# ── Assets ────────────────────────────────────────────────────────────────────
elif page == "Assets":
    st.title("📁 Assets")

    col_src, col_kind, col_sort, _ = st.columns([1, 1, 1, 2])
    source_filter = col_src.selectbox("Source", ["all", "bigquery", "git"])
    kind_filter = col_kind.selectbox(
        "Kind",
        [
            "all", "bq_table", "bq_view", "bq_routine",
            "sql_file", "airflow_dag", "pyspark_file", "pandas_file", "unknown",
        ],
    )
    sort_by = col_sort.selectbox("Sort by", ["updated_at", "kind", "source", "identifier"])

    params = ""
    if source_filter != "all":
        params += f"?source={source_filter}"
    if kind_filter != "all":
        params += ("&" if params else "?") + f"kind={kind_filter}"

    assets, err = _api(f"/api/assets{params}")
    if err:
        st.error(err)
    elif not assets:
        st.info("No assets found. Run a crawl first.")
    else:
        # Enrich with latest lineage job status
        jobs, _ = _api("/api/lineage/jobs")
        latest_job_status: dict[str, str] = {}
        if jobs:
            for j in sorted(jobs, key=lambda x: x.get("started_at") or "", reverse=True):
                aid = j.get("asset_id")
                if aid and aid not in latest_job_status:
                    latest_job_status[aid] = j.get("status", "—")

        df = pd.DataFrame(assets)

        if sort_by in df.columns:
            asc = sort_by != "updated_at"
            df = df.sort_values(sort_by, ascending=asc)

        df["lineage_status"] = df["asset_id"].map(latest_job_status).fillna("—")

        display_cols = [
            c for c in
            ["identifier", "kind", "source", "content_hash", "updated_at", "lineage_status"]
            if c in df.columns
        ]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
        st.caption(f"{len(assets)} assets total")

        st.divider()
        st.subheader("Open in Preview")
        id_options = [""] + df["asset_id"].tolist()
        label_map = {row["asset_id"]: row.get("identifier", row["asset_id"]) for row in assets}

        selected_id = st.selectbox(
            "Select asset",
            id_options,
            format_func=lambda x: label_map.get(x, x) if x else "— select an asset —",
        )
        if selected_id and st.button("Open Preview →"):
            _nav_to("Preview", asset_id=selected_id)

# ── Preview ────────────────────────────────────────────────────────────────────
elif page == "Preview":
    st.title("🔎 Lineage Preview")

    # Asset ID input — pre-populated from Assets page click-through
    asset_id_input = st.text_input(
        "Asset ID",
        value=st.session_state.get("preview_asset_id", ""),
        placeholder="Paste an asset_id or select one from the Assets page",
    )
    if asset_id_input != st.session_state.get("preview_asset_id", ""):
        st.session_state["preview_asset_id"] = asset_id_input

    asset_id = st.session_state.get("preview_asset_id", "").strip()

    if not asset_id:
        st.info("Select an asset from the **Assets** page or paste an asset ID above.")
        st.stop()

    # Fetch asset metadata
    asset, asset_err = _api(f"/api/assets/{asset_id}")
    if asset_err:
        st.error(f"Asset not found: {asset_err}")
        st.stop()

    # ── Header ──────────────────────────────────────────────────────────────
    # Latest job status for this asset
    jobs, _ = _api("/api/lineage/jobs")
    asset_jobs = sorted(
        [j for j in (jobs or []) if j.get("asset_id") == asset_id],
        key=lambda j: j.get("started_at") or "",
        reverse=True,
    )
    latest_job = asset_jobs[0] if asset_jobs else None
    job_status = latest_job.get("status", "—") if latest_job else "no jobs"

    status_color = {
        "done": "🟢",
        "running": "🟡",
        "pending": "⚪",
        "failed": "🔴",
    }.get(job_status, "⚪")

    st.subheader(asset.get("identifier", asset_id))
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Kind", asset.get("kind", "—"))
    h2.metric("Source", asset.get("source", "—"))
    h3.metric("Lineage Job", f"{status_color} {job_status}")
    h4.metric("Last Crawled", (asset.get("updated_at") or "—")[:10])
    st.caption(f"Asset ID: `{asset_id}`  |  Hash: `{asset.get('content_hash', '—')[:16]}…`")

    # ── Re-run lineage ───────────────────────────────────────────────────────
    st.divider()
    col_btn, col_info = st.columns([1, 4])
    if col_btn.button("🔄 Re-run Lineage"):
        res, rerun_err = _api(f"/api/lineage/refresh/{asset_id}", method="POST")
        if rerun_err:
            st.error(f"Failed to enqueue: {rerun_err}")
        else:
            st.success(f"Job enqueued — ID: `{res['job_id']}`")
            st.rerun()

    if latest_job and latest_job.get("error"):
        col_info.error(f"Last job error: {latest_job['error']}")
    elif latest_job and latest_job.get("schema_kind"):
        col_info.info(f"Schema kind: **{latest_job['schema_kind']}**  |  Model: {latest_job.get('llm_model', '—')}")

    # ── Lineage result ───────────────────────────────────────────────────────
    results, res_err = _api(f"/api/lineage/results/{asset_id}")
    if res_err:
        st.warning(f"Could not load results: {res_err}")
    elif not results:
        st.info("No lineage results yet. Click **Re-run Lineage** to extract.")
    else:
        latest = results[0]
        schema_kind = latest.get("schema_kind", "stm")
        try:
            payload = json.loads(latest["payload"])
        except Exception:
            st.error("Could not parse lineage payload.")
            st.stop()

        st.subheader(f"Direct Lineage — {schema_kind.upper()}")

        if schema_kind == "stm":
            _render_stm(payload)
        elif schema_kind == "dag_spec":
            _render_dag_spec(payload)
        elif schema_kind == "pyspark_stm":
            _render_pyspark_stm(payload)
        else:
            st.json(payload)

        # ── Depth-2 transitive sources ───────────────────────────────────────
        edges, edges_err = _api(f"/api/lineage/edges/{asset_id}")
        if not edges_err:
            depth2 = [e for e in (edges or []) if e.get("depth") == 2]
            if depth2:
                st.divider()
                st.subheader("Resolved (Depth 2) — Transitive Sources")
                d2_cols = [
                    c for c in
                    ["target_table", "target_column", "source_table", "source_column", "transformation_type"]
                    if c in depth2[0]
                ]
                st.dataframe(
                    pd.DataFrame(depth2)[d2_cols],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                with st.expander("Depth-2 Transitive Sources"):
                    st.info("No transitive (depth-2) edges found for this asset.")

    # ── Job history ──────────────────────────────────────────────────────────
    if asset_jobs:
        st.divider()
        with st.expander("Job History", expanded=False):
            jh_cols = [c for c in ["job_id", "status", "schema_kind", "started_at", "finished_at", "error"] if c in asset_jobs[0]]
            st.dataframe(
                pd.DataFrame(asset_jobs)[jh_cols],
                use_container_width=True,
                hide_index=True,
            )
