"""Optional BAML-backed structured extraction with a strict compatibility path.

BAML generated clients are intentionally loaded at runtime.  This keeps the
project installable in a CPU-only Agent environment while making the chosen
structured-extraction backend explicit in manifests.  If a generated BAML
client is supplied, its function output is validated by the same Pydantic model
used by the current MinerU experiment; otherwise the existing OpenAI-compatible
JSON request is used with identical evidence/validation semantics.
"""

from __future__ import annotations

import importlib
import importlib.util
import hashlib
import json
import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


def _normalize_baml_payload(value: Any) -> Any:
    """Normalize generated enum member names to the Pydantic wire values."""

    if isinstance(value, list):
        return [_normalize_baml_payload(item) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {key: _normalize_baml_payload(item) for key, item in value.items()}
    if "field_id" in normalized and "quote" in normalized:
        source = normalized.get("source")
        support_type = normalized.get("support_type")
        if isinstance(source, str):
            normalized["source"] = source.lower()
        if isinstance(support_type, str):
            normalized["support_type"] = support_type.lower()
    return normalized


class BamlExtractor:
    """Small adapter for generated BAML functions or an API-compatible fallback."""

    FUNCTION_ALIASES = {
        "metadata": ("ExtractMetadata", "extract_metadata"),
        "acupuncture": ("ExtractAcupuncture", "extract_acupuncture", "ExtractProtocol"),
        "risk_of_bias": ("ExtractRiskOfBias", "extract_risk_of_bias", "ExtractRisk"),
        "outcomes": ("ExtractClinicalOutcomes", "extract_clinical_outcomes", "ExtractOutcomes"),
    }

    def __init__(
        self,
        client: Any | None = None,
        raw_dir: Path | None = None,
        generated_client: Any | None = None,
        retries: int = 2,
    ):
        self.client = client
        self.raw_dir = Path(raw_dir) if raw_dir else None
        if self.raw_dir:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.retries = max(0, int(retries))
        self.generated_client = generated_client or self._load_generated_client()

    @staticmethod
    def _load_generated_client() -> Any | None:
        configured_module = os.getenv("ARTICLE_AGENT_BAML_CLIENT_MODULE", "").strip()
        backend = os.getenv("ARTICLE_AGENT_STRUCTURED_BACKEND", "auto").strip().lower()
        # Installing/generating a client must not silently change existing API
        # runs.  BAML is selected explicitly by backend or module configuration.
        if not configured_module and backend != "baml":
            return None
        module_name = configured_module or "baml_client"
        if importlib.util.find_spec(module_name) is None:
            return None
        try:
            module = importlib.import_module(module_name)
            # Current Python generators export the async client as ``b`` from
            # the package root.  This adapter is synchronous, so prefer the
            # generated sync client when it exists.
            try:
                sync_module = importlib.import_module(f"{module_name}.sync_client")
                sync_client = getattr(sync_module, "b", None)
                if sync_client is not None:
                    return sync_client
            except (ImportError, AttributeError):
                pass
            return getattr(module, "b_sync", None) or getattr(module, "Client", None) or module
        except Exception:
            return None

    @property
    def backend_name(self) -> str:
        return (
            "baml-with-openai-compatible-pydantic-fallback"
            if self.generated_client is not None and self.client is not None
            else "baml"
            if self.generated_client is not None
            else "openai-compatible-pydantic-fallback"
        )

    def _function(self, name: str):
        if self.generated_client is None:
            return None
        for alias in self.FUNCTION_ALIASES.get(name, ()):
            function = getattr(self.generated_client, alias, None)
            if callable(function):
                return function
        return None

    def _baml_extract(self, name: str, context: str) -> Any | None:
        function = self._function(name)
        if function is None:
            return None
        # Generated BAML clients differ in whether they accept a plain string
        # or a named input.  Try the named form first, then the plain form.
        try:
            return function(source_context=context)
        except TypeError:
            return function(context)

    def extract(self, name: str, model: type[T], context: str, prompt_spec: dict[str, Any]) -> T:
        # Outcome extraction is invoked once per table shard.  Include the
        # source context identity so an empty/partial shard can never be reused
        # as the result for a different table or row range.
        artifact_stem = name
        if name == "outcomes":
            digest = hashlib.sha256(context.encode("utf-8")).hexdigest()[:12]
            artifact_stem = f"{name}.{digest}"
        cache_path = self.raw_dir / f"{artifact_stem}.baml.json" if self.raw_dir else None
        if cache_path and cache_path.exists():
            try:
                return model.model_validate_json(cache_path.read_text(encoding="utf-8"))
            except (ValidationError, ValueError):
                pass

        try:
            baml_value = self._baml_extract(name, context)
        except Exception as exc:
            # BAML uses its own HTTP runtime.  A provider TLS/parser failure
            # must not discard the already configured, serial curl/failover
            # path that enforces the same Pydantic contract.
            baml_value = None
            if self.raw_dir:
                (self.raw_dir / f"{artifact_stem}.baml.error.txt").write_text(
                    f"{type(exc).__name__}: {exc}", encoding="utf-8"
                )
        if baml_value is not None:
            payload = baml_value.model_dump(mode="json") if isinstance(baml_value, BaseModel) else baml_value
            payload = _normalize_baml_payload(payload)
            if self.raw_dir:
                (self.raw_dir / f"{artifact_stem}.baml.raw.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
                )
            try:
                result = model.model_validate(payload)
            except ValidationError as exc:
                if self.raw_dir:
                    (self.raw_dir / f"{artifact_stem}.baml.validation-error.txt").write_text(
                        str(exc), encoding="utf-8"
                    )
            else:
                outcome_rows = getattr(result, "outcomes", None)
                if name == "outcomes" and not outcome_rows and "[ROW " in context:
                    if self.raw_dir:
                        (self.raw_dir / f"{artifact_stem}.baml.empty-fallback.txt").write_text(
                            "BAML returned no outcomes for a selected table shard; rerouted to the full Pydantic prompt.",
                            encoding="utf-8",
                        )
                else:
                    if cache_path:
                        cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                    return result

        if self.client is None:
            raise RuntimeError("No generated BAML client or API client is configured")
        schema = model.model_json_schema()
        feedback = ""
        for attempt in range(self.retries + 1):
            prompt = {
                "module": name,
                "role_definition": prompt_spec.get("role_definition", "evidence-first clinical extraction expert"),
                "task_description": prompt_spec.get("task_description", "Return strict JSON."),
                "field_definitions": {
                    "semantic_boundaries": prompt_spec.get("field_boundaries", {}),
                    "pydantic_json_schema": schema,
                },
                "json_template": prompt_spec.get("json_template", {}),
                "validation_feedback": feedback,
                "source_context": context,
            }
            response = self.client.chat_json([
                {"role": "system", "content": "You are an evidence-first clinical trial extraction expert. Return JSON only."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ])
            if self.raw_dir:
                (self.raw_dir / f"{artifact_stem}.baml-fallback.attempt-{attempt + 1}.json").write_text(
                    json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            try:
                result = model.model_validate(response)
                if cache_path:
                    cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
                return result
            except ValidationError as exc:
                feedback = str(exc)
                if attempt >= self.retries:
                    raise RuntimeError(f"{name} failed structured validation after {attempt + 1} attempts: {exc}") from exc
        raise RuntimeError(f"{name} structured extraction failed")
