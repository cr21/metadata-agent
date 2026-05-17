"""Streamlit UI — Metadata Generator Agent."""

import httpx
import streamlit as st

FASTAPI_BASE = "http://localhost:8000"

st.set_page_config(
    page_title="Metadata Generator",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Sidebar ---
with st.sidebar:
    st.title("🔍 Metadata Generator")
    page = st.radio(
        "Navigate",
        ["Dashboard", "Crawl", "Assets", "Preview"],
        index=0,
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _api(path: str, method: str = "GET", json: dict | None = None):
    try:
        if method == "POST":
            r = httpx.post(f"{FASTAPI_BASE}{path}", json=json, timeout=300)
        else:
            r = httpx.get(f"{FASTAPI_BASE}{path}", timeout=30)
        r.raise_for_status()
        return r.json(), None
    except httpx.ConnectError:
        return None, "Cannot reach API — is `make api` running?"
    except httpx.HTTPStatusError as e:
        return None, e.response.json().get("detail", str(e))
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

if page == "Dashboard":
    st.title("Metadata Generator — Dashboard")

    # Live counters from API
    assets_data, err = _api("/api/assets")
    milestones_data, _ = _api("/api/milestones")

    if err:
        st.warning(f"API not reachable: {err}")
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

        if total == 0:
            st.info("No assets yet. Go to **Crawl** to index your first BigQuery project.")

    # Milestone progress
    if milestones_data:
        st.divider()
        st.subheader("Build Progress")
        for m in milestones_data:
            status = m.get("status", "pending")
            icon = {"done": "✅", "in_progress": "🟡", "pending": "⬜", "blocked": "❌"}.get(status, "⬜")
            with st.expander(f"{icon} {m.get('title', '')}"):
                if m.get("what_proves"):
                    st.markdown(f"*{m['what_proves']}*")
                if m.get("completed"):
                    st.caption(f"Completed: {m['completed']}  |  SHA: {m.get('commit_sha', '—')}")
                items = m.get("acceptance", [])
                for item in items:
                    chk = "✅" if item["checked"] else "☐"
                    st.markdown(f"  {chk} {item['text']}")

elif page == "Crawl":
    st.title("🕷️ Crawl BigQuery")

    with st.form("crawl_form"):
        project_id = st.text_input(
            "GCP Project ID",
            placeholder="project-5c016d48-80d5-4534-b69",
        )
        dataset_filter_raw = st.text_input(
            "Dataset filter (optional — comma-separated)",
            placeholder="dataset1, dataset2",
        )
        submitted = st.form_submit_button("Start Crawl")

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

            with st.spinner("Crawling... (this may take a minute)"):
                result, err = _api("/api/crawl", method="POST", json=payload)

            if err:
                st.error(f"Crawl failed: {err}")
            else:
                st.success(f"Crawl completed — run ID: `{result['run_id']}`")
                stats = result.get("stats", {})
                c1, c2, c3 = st.columns(3)
                c1.metric("Inserted", stats.get("inserted", 0))
                c2.metric("Updated", stats.get("updated", 0))
                c3.metric("Skipped", stats.get("skipped", 0))
                st.caption(f"Datasets crawled: {', '.join(result.get('datasets_crawled', []))}")

    # Crawl run history
    st.divider()
    st.subheader("Recent Crawl Runs")
    runs, err = _api("/api/crawl/runs")
    if err:
        st.warning(err)
    elif not runs:
        st.info("No crawl runs yet.")
    else:
        import pandas as pd
        df = pd.DataFrame(runs)[["run_id", "status", "started_at", "finished_at", "stats"]]
        st.dataframe(df, use_container_width=True)

elif page == "Assets":
    st.title("📁 Assets")

    col_src, col_kind, _ = st.columns([1, 1, 3])
    source_filter = col_src.selectbox("Source", ["all", "bigquery", "git"])
    kind_filter = col_kind.selectbox(
        "Kind", ["all", "bq_table", "bq_view", "bq_routine",
                 "sql_file", "airflow_dag", "pyspark_file", "pandas_file", "unknown"]
    )

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
        import pandas as pd
        df = pd.DataFrame(assets)
        display_cols = [c for c in ["identifier", "kind", "source", "content_hash", "updated_at"] if c in df.columns]
        st.dataframe(df[display_cols], use_container_width=True)
        st.caption(f"{len(assets)} assets total")

elif page == "Preview":
    st.title("🔎 Lineage Preview")
    st.info("Lineage extraction is M5. Select an asset from Assets page — preview will be available after M5.")
