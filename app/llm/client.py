"""OpenAI LLM client — structured outputs with one retry on schema-validation failure."""

import json
import logging

import jsonschema
from openai import OpenAI

from app.config import get_settings
from app.llm.prompts import build_prompts, build_retry_prompts
from app.llm.schemas import KIND_TO_SCHEMA

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, client: OpenAI | None = None) -> None:
        s = get_settings()
        self._client = client or OpenAI(api_key=s.openai_api_key)
        self._model = s.openai_model

    def extract(self, kind: str, path: str, content: str) -> dict:
        """Run structured-output extraction for the given asset kind.

        Returns the parsed payload dict. Raises ValueError if both attempts fail.
        """
        schema = KIND_TO_SCHEMA.get(kind)
        if schema is None:
            raise ValueError(f"No schema registered for kind '{kind}'")

        system, user = build_prompts(kind, path, content)
        raw = self._call(system, user, schema)

        errors = self._validate(raw, schema["schema"])
        if errors:
            logger.warning("Schema validation failed on first attempt (%s), retrying…", errors)
            system2, user2 = build_retry_prompts(kind, path, content, errors)
            raw = self._call(system2, user2, schema)
            errors2 = self._validate(raw, schema["schema"])
            if errors2:
                raise ValueError(f"Schema validation failed after retry: {errors2}")

        return raw

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call(self, system: str, user: str, schema: dict) -> dict:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_schema", "json_schema": schema},
        )
        text = response.choices[0].message.content or "{}"
        return json.loads(text)

    @staticmethod
    def _validate(payload: dict, schema: dict) -> str:
        """Return a short error string, or '' if valid."""
        validator = jsonschema.Draft7Validator(schema)
        errs = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        if not errs:
            return ""
        return "; ".join(f"{list(e.path)}: {e.message}" for e in errs[:3])
