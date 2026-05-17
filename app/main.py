from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import configure_logging, get_settings

configure_logging()

app = FastAPI(title="Metadata Generator Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "model": settings.openai_model}
