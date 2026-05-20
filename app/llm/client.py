"""OpenAI LLM client — structured outputs with one retry on schema-validation failure."""

import json
import logging
import time
import uuid
from pathlib import Path

import jsonschema
from openai import OpenAI

from app.config import get_settings
from app.llm.pricing import compute_usd
from app.llm.prompts import build_prompts, build_retry_prompts
from app.llm.schemas import KIND_TO_SCHEMA
from app.storage import local_cache

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, client: OpenAI | None = None, db_path: Path = local_cache.DB_PATH) -> None:
        s = get_settings()
        self._client = client or OpenAI(api_key=s.openai_api_key)
        self._model = s.openai_model
        self._db_path = db_path

    def extract(
        self,
        kind: str,
        path: str,
        content: str,
        asset_id: str | None = None,
    ) -> dict:
        """Run structured-output extraction for the given asset kind.

        Returns the parsed payload dict. Raises ValueError if both attempts fail.
        """
        schema = KIND_TO_SCHEMA.get(kind)
        if schema is None:
            raise ValueError(f"No schema registered for kind '{kind}'")

        system, user = build_prompts(kind, path, content)
        raw, call_meta = self._call(system, user, schema)
        self._log(call_meta, asset_id=asset_id, kind=kind, attempt=1,
                  system=system, user=user, raw=raw)

        errors = self._validate(raw, schema["schema"])
        if errors:
            logger.warning("Schema validation failed on first attempt (%s), retrying…", errors)
            system2, user2 = build_retry_prompts(kind, path, content, errors)
            raw, call_meta2 = self._call(system2, user2, schema)
            self._log(call_meta2, asset_id=asset_id, kind=kind, attempt=2,
                      system=system2, user=user2, raw=raw)
            errors2 = self._validate(raw, schema["schema"])
            if errors2:
                raise ValueError(f"Schema validation failed after retry: {errors2}")

        return raw

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call(self, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        """Call the API and return (parsed_dict, call_metadata)."""
        s = get_settings()
        t0 = time.monotonic()
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_schema", "json_schema": schema},
            timeout=s.llm_timeout_seconds,
        )
        duration_ms = int((time.monotonic() - t0) * 1000)

        text = response.choices[0].message.content or "{}"
        parsed = json.loads(text)

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else None
        completion_tokens = usage.completion_tokens if usage else None
        total_tokens = usage.total_tokens if usage else None
        usd = compute_usd(self._model, prompt_tokens or 0, completion_tokens or 0)

        meta = {
            "model": self._model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "usd_cost": usd,
            "duration_ms": duration_ms,
            "raw_output": text,
        }
        return parsed, meta

    def _log(
        self,
        meta: dict,
        asset_id: str | None,
        kind: str,
        attempt: int,
        system: str,
        user: str,
        raw: dict,
    ) -> None:
        try:
            local_cache.log_llm_call(
                {
                    "call_id": str(uuid.uuid4()),
                    "asset_id": asset_id,
                    "kind": kind,
                    "model": meta["model"],
                    "attempt": attempt,
                    "system_prompt": system,
                    "user_prompt": user,
                    "raw_output": meta["raw_output"],
                    "prompt_tokens": meta["prompt_tokens"],
                    "completion_tokens": meta["completion_tokens"],
                    "total_tokens": meta["total_tokens"],
                    "usd_cost": meta["usd_cost"],
                    "duration_ms": meta["duration_ms"],
                },
                db_path=self._db_path,
            )
        except Exception:
            logger.exception("Failed to log LLM call — extraction continues")

    @staticmethod
    def _validate(payload: dict, schema: dict) -> str:
        """Return a short error string, or '' if valid."""
        validator = jsonschema.Draft7Validator(schema)
        errs = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if not errs:
            return ""
        return "; ".join(f"{list(e.path)}: {e.message}" for e in errs[:3])
