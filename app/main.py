import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import assets, crawl, lineage, llm_calls
from app.config import configure_logging, get_settings

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app import queue as job_queue
    settings = get_settings()
    job_queue.startup(concurrency=settings.llm_concurrency, num_workers=settings.llm_concurrency)
    yield
    job_queue.shutdown()


app = FastAPI(title="Metadata Generator Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(crawl.router)
app.include_router(assets.router)
app.include_router(lineage.router)
app.include_router(llm_calls.router)


@app.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "model": settings.openai_model}


# ---------------------------------------------------------------------------
# Milestones endpoint — parses MILESTONES.md so the Streamlit page stays in
# sync with the file automatically.
# ---------------------------------------------------------------------------

_MILESTONES_PATH = Path(__file__).parent.parent / "MILESTONES.md"

_STATUS_MAP = {
    "✅": "done",
    "🟡": "in_progress",
    "⬜": "pending",
    "❌": "blocked",
}


def _parse_milestones() -> list[dict]:
    text = _MILESTONES_PATH.read_text(encoding="utf-8")
    milestones: list[dict] = []
    # Split on top-level H2 headings that start with M<digit>
    sections = re.split(r"\n## (M\d+ —[^\n]+)", text)
    # sections: [preamble, title1, body1, title2, body2, ...]
    for i in range(1, len(sections), 2):
        title = sections[i].strip()
        body = sections[i + 1] if i + 1 < len(sections) else ""

        status_raw = "pending"
        commit_sha = None
        completed = None
        what_proves = None

        for emoji, label in _STATUS_MAP.items():
            if emoji in body:
                status_raw = label
                break

        sha_match = re.search(r"\*\*Commit SHA\*\*:\s*([a-f0-9]{7,40}|—)", body)
        if sha_match:
            val = sha_match.group(1)
            commit_sha = val if val != "—" else None

        completed_match = re.search(r"\*\*Completed\*\*:\s*(\d{4}-\d{2}-\d{2}|—)", body)
        if completed_match:
            val = completed_match.group(1)
            completed = val if val != "—" else None

        proves_match = re.search(r'\*"(.+?)"\*', body)
        if proves_match:
            what_proves = proves_match.group(1)

        # Parse acceptance items
        acceptance = re.findall(r"- \[([ xX])\] (.+)", body)
        acceptance_items = [
            {"checked": chk.lower() == "x", "text": txt.strip()}
            for chk, txt in acceptance
        ]

        milestones.append(
            {
                "id": title.split(" — ")[0],
                "title": title,
                "status": status_raw,
                "commit_sha": commit_sha,
                "completed": completed,
                "what_proves": what_proves,
                "acceptance": acceptance_items,
            }
        )

    return milestones


@app.get("/api/milestones")
async def get_milestones() -> list[dict]:
    return _parse_milestones()
