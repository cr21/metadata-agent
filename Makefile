.PHONY: api ui dev lint test install

api:
	uv run uvicorn app.main:app --reload --port 8000

ui:
	uv run streamlit run ui/streamlit_app.py

dev:
	make -j2 api ui

install:
	uv sync --extra dev

lint:
	uv run ruff check .

test:
	uv run pytest tests/ -v
