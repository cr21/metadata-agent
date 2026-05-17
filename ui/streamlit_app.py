"""Streamlit UI — Metadata Generator Agent."""

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
# Pages
# ---------------------------------------------------------------------------

if page == "Dashboard":
    st.title("Metadata Generator")
    st.markdown(
        "Crawl **BigQuery** tables, views, and stored procedures — "
        "plus **Git repositories** containing SQL, Airflow DAGs, and PySpark scripts — "
        "then browse column-level lineage in one place."
    )

    st.divider()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Assets", "—")
    col2.metric("Lineage Jobs", "—")
    col3.metric("Direct Edges", "—")
    col4.metric("Resolved Edges (depth 2)", "—")

    st.info("No data yet. Go to **Crawl** to index your first BigQuery project or Git repository.")

elif page == "Crawl":
    st.title("🕷️ Crawl")
    st.info("BigQuery crawler available in M3. Git crawler available in M4.")

elif page == "Assets":
    st.title("📁 Assets")
    st.info("Asset browser available after first crawl (M3+).")

elif page == "Preview":
    st.title("🔎 Lineage Preview")
    st.info("Select an asset from the Assets page to preview its column-level lineage.")
