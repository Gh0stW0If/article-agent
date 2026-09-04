from __future__ import annotations

import json
import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from article_agent.models import OpenAICompatibleClient
from article_agent.baml_adapter import BamlExtractor

from .canonical import build_canonical_outcome_dataset
from .prompts import (
    FLOW_PROMPT_SPEC,
    OUTCOME_POSTPROCESS_PROMPT_SPEC,
    OUTCOME_SEMANTIC_PROMPT_SPEC,
    ROLE_DEFINITION,
    TABLE_CLASSIFICATION_PROMPT_SPEC,
    TABLE_OUTCOME_PROMPT_SPEC,
)
from .schemas import (
    EvidenceQuote,
    GoldOutcomeConflict,
    OutcomeArm,
    OutcomeComparison,
    OutcomeExtraction,
    OutcomePostProcessBatch,
    OutcomePostProcessDecision,
    OutcomePostProcessRecord,
    OutcomePostProcessing,
    OutcomeStatistic,
    TableClassification,
)
from .table_parser import OutcomeTableBlock, apply_table_classification, prepare_outcome_table_block


T = TypeVar("T", bound=BaseModel)


SYSTEM = ROLE_DEFINITION


class ValidatedExtractor:
    def __init__(self, client: OpenAICompatibleClient, raw_dir: Path, retries: int = 2):
        self.client = client
        self.raw_dir = raw_dir
        self.retries = retries
        raw_dir.mkdir(parents=True, exist_ok=True)
        # Prefer a generated BAML client when explicitly installed/configured.
        # The legacy request path remains the compatibility fallback and keeps
        # the existing raw attempt filenames stable for resumable runs.
        self.baml = BamlExtractor(client=client, raw_dir=raw_dir, retries=retries)

    def extract(self, name: str, model: type[T], context: str, prompt_spec: dict) -> T:
        if self.baml.generated_client is not None:
            return self.baml.extract(name, model, context, prompt_spec)
        schema = model.model_json_schema()
        # Some OpenAI-compatible gateways (including the currently selected
        # gpt-5.6-sol route) return HTTP 502 when a full Pydantic schema is
        # embedded in an otherwise valid JSON request.  The field boundaries
        # and template still constrain the model, while local Pydantic
        # validation below remains authoritative.  Keep this opt-in so other
        # models retain the richer schema prompt by default.
        omit_schema = os.getenv("ARTICLE_AGENT_OMIT_PYDANTIC_SCHEMA", "0").strip().lower() in {
            "1", "true", "yes",
        }
        schema_fields = {"semantic_boundaries": prompt_spec["field_boundaries"]}
        if not omit_schema:
            schema_fields["pydantic_json_schema"] = schema
        else:
            # Keep the small, high-value part of the schema that models most
            # often omit or rename when the full schema is unavailable.  This
            # avoids gateway 502s while preserving the evidence contract used
            # by local Pydantic validation.
            schema_fields["compact_output_contract"] = {
                "top_level_fields": list(schema.get("properties", {})),
                "evidence_item": {
                    "field_id": "exact top-level field name",
                    "quote": "exact continuous source substring",
                    "page": "integer or null",
                    "source": "markdown|table|figure|crossref",
                    "support_type": "direct|derived",
                    "derivation": "string or null",
                },
            }
        feedback = ""
        disable_cache = os.getenv("ARTICLE_AGENT_DISABLE_STRUCTURED_CACHE", "0").strip().lower() in {
            "1", "true", "yes",
        }
        if not disable_cache:
            cached = sorted(self.raw_dir.glob(f"{name}.attempt-*.json"), reverse=True)
            for path in cached:
                try:
                    return model.model_validate_json(path.read_text(encoding="utf-8"))
                except (ValidationError, ValueError):
                    continue
        for attempt in range(self.retries + 1):
            prompt = {
                "module": name,
                "role_definition": ROLE_DEFINITION,
                "task_description": prompt_spec["task_description"],
                "field_definitions": schema_fields,
                "json_template": prompt_spec["json_template"],
                "validation_feedback": feedback,
                "source_context": context,
            }
            try:
                response = self.client.chat_json([
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ])
            except RuntimeError as exc:
                feedback = f"Transport error on prior attempt; retry the same extraction: {exc}"
                if attempt == self.retries:
                    raise
                continue
            (self.raw_dir / f"{name}.attempt-{attempt + 1}.json").write_text(
                json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            try:
                return model.model_validate(response)
            except ValidationError as exc:
                feedback = str(exc)
        raise RuntimeError(f"{name} failed Pydantic validation after {self.retries + 1} attempts: {feedback}")


def extract_flow(client: OpenAICompatibleClient, image_path: Path, article_id: str) -> dict:
    from .schemas import ConsortFlowExtraction

    prompt = json.dumps({
        **FLOW_PROMPT_SPEC,
        "article_id": article_id,
        "field_definitions": {
            "semantic_boundaries": FLOW_PROMPT_SPEC["field_boundaries"],
            "pydantic_json_schema": ConsortFlowExtraction.model_json_schema(),
        },
    }, ensure_ascii=False)
    return client.chat_vision_json(prompt, image_path.read_bytes())


def _float_or_none(value):
    try:
        return float(value) if value not in (None, "", "NR") else None
    except (TypeError, ValueError):
        return None


def _numeric_or_none(value):
    """Read a scalar numeric value from a compact source-value token."""

    parsed = _float_or_none(value)
    if parsed is not None:
        return parsed
    text = str(value or "").replace("−", "-").replace("–", "-")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return _float_or_none(match.group(0)) if match else None


def _interval_bounds(value) -> tuple[float | None, float | None]:
    """Parse a compact CI value without changing the supplied source text."""

    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return _float_or_none(value[0]), _float_or_none(value[1])
    if isinstance(value, dict):
        return (
            _float_or_none(value.get("lower") if value.get("lower") is not None else value.get("l")),
            _float_or_none(value.get("upper") if value.get("upper") is not None else value.get("u")),
        )
    text = str(value or "")
    numbers = re.findall(r"[-−–]?\s*\d+(?:\.\d+)?", text)
    if len(numbers) >= 2:
        return _float_or_none(numbers[0].replace("−", "-").replace("–", "-")), _float_or_none(numbers[1].replace("−", "-").replace("–", "-"))
    return None, None


def _int_or_none(value):
    number = _float_or_none(value)
    return int(number) if number is not None and number >= 0 else None


def _item_value(item: dict, *names: str):
    for name in names:
        if name in item:
            return item[name]
    return None


def _source_table_id(context: str, fallback: str = "NR") -> str:
    match = re.search(r"(?im)^SOURCE_TABLE_ID:\s*([^\n]+)", context)
    if match:
        return match.group(1).strip()
    match = re.search(r"(?im)^TABLE_ID:\s*([^\n]+)", context)
    if match:
        value = match.group(1).strip()
        return value.split("#part-", 1)[0]
    return fallback


def _row_id_from_quote(context: str, quote: str, table_id: str) -> str:
    """Recover the stable source row marker when a model omits ``row_id``."""

    quote = str(quote or "").strip()
    if not quote:
        return "NR"
    normalized_quote = " ".join(quote.split()).lower()
    for line in context.splitlines():
        match = re.search(r"\[ROW\s+(\d+)\]\s*(.*?)\s+ROW_ID=([^\s]+)\s*$", line, re.I)
        if not match:
            continue
        rendered = " ".join(match.group(2).split()).lower()
        if normalized_quote in rendered or rendered in normalized_quote:
            return match.group(3)
    marker = re.search(r"ROW_ID\s*[=:]\s*([^\s,;]+)", quote, re.I)
    if marker:
        return marker.group(1)
    return "NR"


def _canonical_row_id(value: object) -> str:
    return re.sub(r"#part-[^:]+", "", str(value or "")).strip()


def _row_quote_from_context(context: str, row_id: str) -> str:
    """Return the complete rendered source row for a stable row ID."""

    target = _canonical_row_id(row_id)
    for line in context.splitlines():
        match = re.search(r"\[ROW\s+\d+\]\s*(.*?)\s+ROW_ID=([^\s]+)\s*$", line, re.I)
        if not match:
            continue
        if _canonical_row_id(match.group(2)) == target:
            return match.group(1).strip()
    return ""


def _source_values_from_row_quote(quote: str) -> list[str]:
    """Deterministically retain raw cell tokens when a model omits them.

    This is only a provenance fallback: it never assigns a token to a
    statistic field.  The column map remains the sole source for numeric
    projections, while the complete row cells stay available for audit.
    """

    text = str(quote or "").strip()
    if not text:
        return []
    # Rendered Markdown/HTML row quotes use pipes as cell boundaries.  Strip
    # only presentation tags and row markers; preserve each cell's original
    # textual value and order.
    text = re.sub(r"\[/?(?:ROW|CELL)\s*[^\]]*\]", "", text, flags=re.I)
    text = re.sub(r"<\/?(?:td|th|tr)[^>]*>", "|", text, flags=re.I)
    parts = [re.sub(r"\s+", " ", part).strip() for part in text.split("|")]
    return [part for part in parts if part]


def _context_column_map(context: str) -> list[dict]:
    """Read the complete deterministic column map embedded in a table prompt."""

    marker = re.search(r"TABLE_COLUMN_MAP[^\n]*:\s*\n", str(context or ""), re.I)
    if not marker:
        return []
    tail = str(context)[marker.end():]
    # The map is emitted as one JSON array followed by the next TABLE_* line.
    # Decode the first balanced array rather than using a character budget.
    start = tail.find("[")
    if start < 0:
        return []
    depth = 0
    in_string = False
    escaped = False
    end = None
    for index in range(start, len(tail)):
        char = tail[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end is None:
        return []
    try:
        parsed = json.loads(tail[start:end])
    except (TypeError, ValueError):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _context_row_cells(context: str, row_id: str, quote: str = "") -> list[str]:
    """Return the complete rendered cells for one stable row marker."""

    row_quote = _row_quote_from_context(context, row_id)
    if not row_quote:
        row_quote = quote
    return _source_values_from_row_quote(row_quote)


def _parse_numeric_cell(value: object) -> float | None:
    """Parse a single explicit numeric cell, rejecting mixed text."""

    text = str(value or "").strip().replace("−", "-").replace("–", "-")
    if not text:
        return None
    match = re.fullmatch(r"(?:<|<=|>|>=)?\s*(-?\d+(?:\.\d+)?)", text)
    return _float_or_none(match.group(1)) if match else None


def _parse_p_cell(value: object) -> tuple[float | None, str]:
    """Parse one explicit P-value cell without borrowing another column."""

    text = str(value or "").strip().replace("≤", "<=").replace("≥", ">=")
    match = re.fullmatch(r"p?\s*(<=|>=|<|>|=)?\s*(0?\.\d+|\d+(?:\.\d+)?)", text, re.I)
    if not match:
        return None, "NR"
    return _float_or_none(match.group(2)), match.group(1) or "="


def _parse_mean_sd_cell(value: object) -> tuple[float | None, float | None]:
    text = str(value or "").replace("−", "-").replace("–", "-")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:±|\+/-|\+\s*/\s*-|\(\s*)\s*(-?\d+(?:\.\d+)?)", text)
    if not match:
        return None, None
    return _float_or_none(match.group(1)), _float_or_none(match.group(2))


def _parse_cell_interval(value: object) -> tuple[float | None, float | None]:
    text = str(value or "").replace("−", "-").replace("–", "-")
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:to|–|-|,)\s*(-?\d+(?:\.\d+)?)", text, re.I)
    if not match:
        return None, None
    return _float_or_none(match.group(1)), _float_or_none(match.group(2))


def _deterministic_row_projection(
    context: str,
    row_id: str,
    quote: str,
    arms: list[OutcomeArm],
) -> tuple[list[OutcomeArm], list[dict], list[dict]]:
    """Fill only unambiguous arm/statistic cells from the parsed header map.

    The model remains responsible for semantic outcome identity and arm roles.
    This helper only aligns an explicit row cell with its deterministic header
    column and never overwrites a non-null model value.
    """

    column_map = _context_column_map(context)
    cells = _context_row_cells(context, row_id, quote)
    if not column_map or not cells:
        return arms, [], []
    source_cells: list[dict] = []
    p_cells: list[dict] = []
    if not arms:
        seen_labels: set[str] = set()
        for item in column_map:
            label = str(item.get("arm_label") or "NR").strip()
            key = re.sub(r"\s+", " ", label).lower()
            if not label or key in {"", "nr"} or key in seen_labels:
                continue
            seen_labels.add(key)
            arm_id = re.sub(r"[^a-z0-9]+", "-", key).strip("-") or "NR"
            arms.append(OutcomeArm(arm_id=arm_id, arm_label=label, role="NR"))
    arm_by_label: dict[str, OutcomeArm] = {}
    for arm in arms:
        label = re.sub(r"\s+", " ", str(arm.arm_label or "NR")).strip().lower()
        if label and label != "nr":
            arm_by_label[label] = arm
    for item in column_map:
        try:
            index = int(item.get("column_index"))
        except (TypeError, ValueError):
            continue
        if index >= len(cells):
            continue
        raw_value = cells[index]
        header_path = item.get("header_path") if isinstance(item.get("header_path"), list) else []
        arm_label = str(item.get("arm_label") or "NR").strip()
        statistic = str(item.get("statistic") or "value")
        source_cells.append({
            "column_index": index,
            "header_path": [str(value) for value in header_path],
            "arm_label": arm_label,
            "timepoint_raw": str(item.get("timepoint_raw") or "NR"),
            "statistic": statistic,
            "analysis_set": str(item.get("analysis_set") or "NR"),
            "raw_value": raw_value,
        })
        if statistic == "p_value":
            number, comparator = _parse_p_cell(str(raw_value))
            p_cells.append({
                "column_index": index,
                "header_path": [str(value) for value in header_path],
                "raw_value": raw_value,
                "value": number,
                "comparator": comparator,
            })
        if arm_label.lower() == "nr":
            continue
        key = re.sub(r"\s+", " ", arm_label).strip().lower()
        arm = arm_by_label.get(key)
        if arm is None:
            continue
        if statistic in {"mean_sd", "mean_or_median"}:
            value, spread = _parse_mean_sd_cell(raw_value)
            if value is not None:
                if arm.estimate is None:
                    arm.estimate = value
                if arm.value is None:
                    arm.value = value
            if spread is not None and arm.sd is None:
                arm.sd = abs(spread)
        elif statistic in {"value", "effect"}:
            value = _parse_numeric_cell(raw_value)
            if value is not None:
                if arm.estimate is None:
                    arm.estimate = value
                if arm.value is None:
                    arm.value = value
        elif statistic == "n":
            # Only a plain integer in an explicit n column is a sample size;
            # values such as ``1.7±0.14`` stay in the estimate field.
            value = _parse_numeric_cell(raw_value)
            if value is not None and value >= 0 and float(value).is_integer() and arm.n is None:
                arm.n = int(value)
        elif statistic == "confidence_interval":
            lower, upper = _parse_cell_interval(raw_value)
            if arm.lower is None:
                arm.lower = lower
            if arm.upper is None:
                arm.upper = upper
    return arms, source_cells, p_cells


def _source_evidence_unit(source_context: str, source: dict) -> str:
    """Route one source record to its complete table/paragraph evidence unit."""

    context = str(source_context or "")
    quotes = []
    for key in ("source_evidence", "quote", "row_quote"):
        value = source.get(key) if isinstance(source, dict) else None
        if value not in (None, "", "NR"):
            quotes.append(" ".join(str(value).split()).lower())
    evidence = source.get("evidence") if isinstance(source, dict) else None
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and item.get("quote") not in (None, "", "NR"):
                quotes.append(" ".join(str(item["quote"]).split()).lower())
    for match in re.finditer(r"<table\b.*?</table>", context, flags=re.I | re.S):
        table_text = match.group(0)
        normalized = " ".join(re.sub(r"<[^>]+>", " ", table_text).split()).lower()
        if quotes and any(quote in normalized for quote in quotes):
            return table_text
    for paragraph in re.split(r"\n\s*\n", context):
        normalized = " ".join(paragraph.split()).lower()
        if quotes and any(quote in normalized for quote in quotes):
            return paragraph
    return context if not quotes else str(source.get("source_evidence") or "NR")


def _normalize_arm_items(raw_arm) -> list[OutcomeArm]:
    if raw_arm in (None, "", "NR"):
        return []
    if isinstance(raw_arm, dict):
        raw_arm = [raw_arm]
    elif isinstance(raw_arm, str):
        # Preserve a textual arm label without inventing its role.  Structured
        # arm objects are preferred, but an LLM may return a concise label.
        return [OutcomeArm(arm_label=raw_arm.strip() or "NR")]
    if not isinstance(raw_arm, list):
        return []
    result: list[OutcomeArm] = []
    for item in raw_arm:
        if isinstance(item, str):
            result.append(OutcomeArm(arm_label=item.strip() or "NR"))
            continue
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("arm_role") or "NR").strip()
        role_aliases = {
            "treatment": "intervention",
            "treatment_group": "intervention",
            "experimental": "intervention",
            "reference": "control",
            "control_group": "control",
            "comparator_group": "comparator",
        }
        role = role_aliases.get(role.lower(), role)
        if role not in {"intervention", "control", "comparator", "other", "NR"}:
            role = "other"
        value_raw = item.get("value")
        change_raw = item.get("change")
        estimate_raw = item.get("estimate")
        if estimate_raw is None:
            estimate_raw = value_raw
        if estimate_raw is None:
            # The semantic wire contract calls the change-from-baseline
            # scalar ``change``.  It is still the explicitly reported arm
            # estimate, so preserve it in the legacy estimate slot.
            estimate_raw = change_raw
        sd_raw = item.get("sd")
        if sd_raw is None:
            sd_raw = item.get("standard_deviation")
        lower_raw = item.get("lower") if item.get("lower") is not None else item.get("ci_lower")
        upper_raw = item.get("upper") if item.get("upper") is not None else item.get("ci_upper")
        if lower_raw is None and upper_raw is None:
            lower_raw, upper_raw = _interval_bounds(item.get("confidence_interval"))
        n_raw = item.get("n")
        if n_raw is None:
            n_raw = item.get("sample_size")
        event_raw = item.get("event_count")
        if event_raw is None:
            event_raw = item.get("events")
        result.append(OutcomeArm(
            arm_id=str(item.get("arm_id") or item.get("id") or "NR"),
            arm_label=str(item.get("arm_label") or item.get("label") or item.get("name") or "NR"),
            role=role,
            n=_int_or_none(n_raw),
            value=_float_or_none(value_raw),
            sd=_float_or_none(sd_raw),
            change=_float_or_none(change_raw),
            estimate=_float_or_none(estimate_raw),
            lower=_float_or_none(lower_raw),
            upper=_float_or_none(upper_raw),
            event_count=_int_or_none(event_raw),
        ))
    return result


def _arm_registry_items(arm_registry: tuple[str, ...] | list[str] | None) -> list[OutcomeArm]:
    """Materialize only explicitly parsed header arm labels and n values."""

    result: list[OutcomeArm] = []
    for token in arm_registry or ():
        text = str(token).strip()
        match = re.match(r"(.+?)\s*\(\s*n\s*=\s*(\d+)\s*\)$", text, re.I)
        label = (match.group(1) if match else text).strip()
        n = int(match.group(2)) if match else None
        arm_id = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "NR"
        result.append(OutcomeArm(arm_id=arm_id, arm_label=label or "NR", role="NR", n=n))
    return result


def _analysis_set_from_context(context: str) -> str:
    caption_match = re.search(r"(?im)^TABLE_CAPTION:\s*([^\n]+)", context)
    header_match = re.search(r"(?im)^TABLE_HEADER_ROWS.*?(?=^TABLE_DATA_ROWS|\Z)", context, re.S)
    search_context = "\n".join(part for part in (caption_match.group(1) if caption_match else "", header_match.group(0) if header_match else "") if part)
    if not search_context:
        # This is a semantic fallback for legacy/non-table callers.  Keep the
        # complete supplied context; row/table partitioning happens at the
        # request boundary and must never be implemented as a character cap.
        search_context = context
    labels: list[str] = []
    patterns = (
        (r"\bfull\s+analysis\s+set\b|\bFAS\b", "FAS"),
        (r"\bper\s+protocol\b|\bPPS\b", "PPS"),
        (r"\bLOCF\b|last\s+observation\s+carried\s+forward", "LOCF"),
        (r"\bMMRM\b|mixed\s+model\s+for\s+repeated\s+measures", "MMRM"),
        (r"\bintention[- ]to[- ]treat\b|\bITT\b", "ITT"),
        (r"\bavailable[- ]case\b", "available_case"),
    )
    for pattern, label in patterns:
        if re.search(pattern, search_context, re.I) and label not in labels:
            labels.append(label)
    return "/".join(labels) if labels else "NR"


def _normalize_comparison(raw_comparison) -> OutcomeComparison:
    if raw_comparison in (None, "", "NR"):
        return OutcomeComparison()
    if isinstance(raw_comparison, str):
        return OutcomeComparison(contrast=raw_comparison.strip() or "NR")
    if not isinstance(raw_comparison, dict):
        return OutcomeComparison()
    relation = str(raw_comparison.get("relation") or raw_comparison.get("type") or "NR").strip()
    relation_aliases = {
        "intervention vs control": "intervention_vs_control",
        "intervention versus control": "intervention_vs_control",
        "treatment vs control": "intervention_vs_control",
        "treatment versus control": "intervention_vs_control",
        "arm vs arm": "arm_vs_arm",
        "arm versus arm": "arm_vs_arm",
        "multi arm": "multi_arm",
        "multi-arm": "multi_arm",
        "within arm": "within_arm",
        "within-arm": "within_arm",
        "not applicable": "not_applicable",
        "not-applicable": "not_applicable",
    }
    relation = relation_aliases.get(relation.lower(), relation)
    allowed = {"intervention_vs_control", "arm_vs_arm", "multi_arm", "within_arm", "overall", "not_applicable", "NR"}
    if relation not in allowed:
        relation = "NR"
    ids = raw_comparison.get("comparator_arm_ids") or raw_comparison.get("comparatorArms") or []
    if not isinstance(ids, list):
        ids = [ids]
    return OutcomeComparison(
        relation=relation,
        intervention_arm_id=str(raw_comparison.get("intervention_arm_id") or raw_comparison.get("interventionArm") or "NR"),
        control_arm_id=str(raw_comparison.get("control_arm_id") or raw_comparison.get("controlArm") or "NR"),
        comparator_arm_ids=[str(value) for value in ids if value not in (None, "")],
        contrast=str(raw_comparison.get("contrast") or raw_comparison.get("description") or "NR"),
    )


def _default_record_role(context: str) -> str:
    match = re.search(r"(?im)^TABLE_CATEGORY:\s*([^\n]+)", context)
    category = match.group(1).strip().lower() if match else ""
    if re.search(r"\bprimary\b", context, re.I):
        return "primary"
    return {
        "outcome": "secondary",
        "safety": "safety",
        "subgroup": "subgroup",
        "sensitivity": "sensitivity",
        "baseline": "baseline",
        "flow": "administrative",
    }.get(category, "NR")


def _sleep_before_request(request_delay_seconds: float) -> None:
    """Throttle shard requests without delaying cache-only work."""
    try:
        delay = max(0.0, float(request_delay_seconds))
    except (TypeError, ValueError):
        delay = 0.0
    if delay:
        time.sleep(delay)


def _normalize_outcome_items(
    raw: dict | None,
    context: str,
    source: str = "markdown",
    table_id: str | None = None,
    arm_registry: tuple[str, ...] | list[str] | None = None,
) -> OutcomeExtraction:
    """Normalize a table response and attach stable source identities."""
    raw = raw or {}
    items = raw.get("outcomes")
    if items is None:
        items = raw.get("rows", [])
    if not isinstance(items, list):
        items = []

    allowed_statistic = {"continuous", "binary", "ordinal", "other"}
    allowed_population = {"ITT", "mITT", "PP", "available_case", "other", "NR"}
    allowed_measure = {"MD", "SMD", "OR", "RR", "RD", "HR", "percent_change", "other", "NR"}
    allowed_comparator = {"=", "<", "<=", ">", ">=", "NR"}
    source_table = table_id or _source_table_id(context)
    default_role = _default_record_role(context)
    outcomes = []
    for item in items:
        if not isinstance(item, dict):
            continue
        outcome_name = str(_item_value(item, "outcome_name", "outcomeName") or "").strip()
        if not outcome_name:
            # A table-level classifier may explicitly mark a non-outcome row.
            # Such rows are intentionally not forced into the outcome schema.
            continue
        quote = str(_item_value(item, "quote", "row_quote", "evidence_quote", "source_evidence") or "").strip()
        # Prefer a verbatim row rendered by the request context when the
        # model returns an abbreviated/non-matching quote.  This keeps
        # provenance checkable and gives the evaluator the exact cells that
        # produced the record without inventing evidence.
        raw_item_row_id = _item_value(item, "row_id", "rowId", "source_row_id", "sourceRowId")
        context_quote = _row_quote_from_context(context, str(raw_item_row_id or "")) if raw_item_row_id else ""
        if context_quote and (not quote or quote not in context):
            quote = context_quote
        evidence = []
        if quote and quote in context:
            evidence.append(EvidenceQuote(
                field_id="outcome_name", quote=quote, source=source, support_type="direct"
            ))
        statistic = _item_value(item, "statistic_type", "statisticType")
        population = _item_value(item, "analysis_population", "analysisPopulation")
        measure = _item_value(item, "between_group_measure", "betweenGroupMeasure")
        comparator = _item_value(item, "p_comparator", "p_value_comparator", "outcome_p_value_comparator", "pComparator")
        unit = _int_or_none(_item_value(item, "timepoint_unit", "outcome_observation_timepoint_unit", "timepointUnit"))
        raw_item_table_id = _item_value(item, "table_id", "tableId", "source_table_id", "sourceTableId")
        item_table_id = str(raw_item_table_id or source_table or "NR").split("#part-", 1)[0]
        raw_row_id = raw_item_row_id
        row_id = str(raw_row_id).strip() if raw_row_id not in (None, "") else _row_id_from_quote(context, quote, item_table_id)
        if row_id not in ("NR", ""):
            # Stable IDs emitted by the semantic pass may already carry their
            # source namespace (for example ``narrative-results:r013`` or
            # ``table-003:r007``).  Do not prefix those IDs with the chunk's
            # synthetic table id; doing so makes a valid response look
            # uncovered during the lossless row-id check and drops its
            # normalized record.  Only bare row labels need the table prefix.
            if ":" not in row_id:
                row_id = f"{item_table_id}:{row_id.lstrip(':')}"
        raw_analysis_set = _item_value(item, "analysis_set", "analysisSet", "analysis_label", "analysisLabel")
        analysis_set = str(raw_analysis_set or "NR").strip() or "NR"
        if analysis_set == "NR":
            analysis_set = _analysis_set_from_context(context)
        raw_role = str(_item_value(item, "record_role", "recordRole", "role") or default_role)
        allowed_roles = {"primary", "secondary", "safety", "subgroup", "sensitivity", "baseline", "administrative", "other", "NR"}
        record_role = raw_role if raw_role in allowed_roles else "other"
        arms = _normalize_arm_items(_item_value(item, "arm", "arms", "arm_structure", "armStructure"))
        if not arms and arm_registry:
            arms = _arm_registry_items(arm_registry)
        arms, deterministic_source_cells, deterministic_p_value_cells = _deterministic_row_projection(
            context, row_id, quote, arms
        )
        comparison = _normalize_comparison(_item_value(item, "comparison", "comparison_structure", "comparisonStructure"))
        # If the compact scalar fields are absent but structured arm values are
        # present, copy only the explicitly labelled intervention/control arms.
        intervention_arm = next((arm for arm in arms if arm.role == "intervention"), None)
        control_arm = next((arm for arm in arms if arm.role == "control"), None)
        intervention_n = _int_or_none(_item_value(item, "intervention_n", "interventionN"))
        control_n = _int_or_none(_item_value(item, "control_n", "controlN"))
        intervention_estimate = _numeric_or_none(_item_value(item, "intervention_estimate", "interventionEstimate"))
        control_estimate = _numeric_or_none(_item_value(item, "control_estimate", "controlEstimate"))
        if intervention_arm is not None:
            intervention_n = intervention_n if intervention_n is not None else intervention_arm.n
            intervention_estimate = intervention_estimate if intervention_estimate is not None else intervention_arm.estimate
        if control_arm is not None:
            control_n = control_n if control_n is not None else control_arm.n
            control_estimate = control_estimate if control_estimate is not None else control_arm.estimate
        source_values = _item_value(item, "source_values", "sourceValues")
        if not isinstance(source_values, list):
            source_values = [source_values] if source_values not in (None, "", "NR") else []
        # Keep the exact source cells in the normalized Pydantic record.  The
        # raw response is still written unchanged to disk, but downstream
        # post-processing/evaluation must not depend on reparsing a shortened
        # quote or on a legacy scalar projection.
        source_values = [str(value) for value in source_values if value not in (None, "")]
        quote_values = _source_values_from_row_quote(quote)
        # Preserve an explicitly returned source_values list byte-for-byte.
        # The deterministic projection above carries every rendered cell and
        # coordinate, so expanding/replacing this legacy list from a row
        # quote would overwrite an original model value (and can prepend the
        # outcome-label cell).  Only synthesize the list when the model did
        # not provide one at all.
        if not source_values and quote:
            source_values = quote_values
        source_evidence = str(
            _item_value(item, "source_evidence", "sourceEvidence", "quote", "row_quote", "evidence_quote")
            or quote
            or "NR"
        ).strip() or "NR"
        derived_raw = _item_value(item, "derived", "is_derived", "isDerived")
        if isinstance(derived_raw, str):
            derived = derived_raw.strip().lower() in {"1", "true", "yes", "derived"}
        else:
            derived = bool(derived_raw) if derived_raw is not None else False
        derivation_raw = _item_value(item, "derivation", "derivation_note", "derivationNote")
        derivation = str(derivation_raw).strip() if derivation_raw not in (None, "", "NR") else None
        conflict_group_raw = _item_value(item, "conflict_group_id", "conflictGroupId")
        conflict_group_id = str(conflict_group_raw).strip() if conflict_group_raw not in (None, "", "NR") else None
        p_value_raw = _item_value(item, "p_value", "outcome_p_value", "pValue")
        p_value = _numeric_or_none(p_value_raw)
        p_comparator = comparator
        if p_value is None:
            for token in [*source_values, quote]:
                match = re.search(r"p\s*(?:value)?\s*(<=|>=|<|>|=)?\s*([0-9]+(?:\.[0-9]+)?)", str(token), re.I)
                if match:
                    p_value = _float_or_none(match.group(2))
                    p_comparator = match.group(1) or "="
                    break
        ci_value = _item_value(item, "confidence_interval", "confidenceInterval", "ci")
        ci_lower, ci_upper = _interval_bounds(ci_value)
        between_lower = _numeric_or_none(_item_value(item, "between_group_lower", "outcome_between_group_lower", "betweenGroupLower"))
        between_upper = _numeric_or_none(_item_value(item, "between_group_upper", "outcome_between_group_upper", "betweenGroupUpper"))
        if between_lower is None:
            between_lower = ci_lower
        if between_upper is None:
            between_upper = ci_upper
        if population not in allowed_population:
            population = analysis_set if analysis_set in {"ITT", "mITT", "PP"} else "NR"
        outcomes.append(OutcomeStatistic(
            table_id=item_table_id,
            row_id=row_id or "NR",
            outcome_name=outcome_name,
            measurement_instrument=str(_item_value(item, "instrument", "measurement_instrument", "measurementInstrument") or "NR"),
            outcome_observation_timepoint_raw=str(_item_value(item, "timepoint_raw", "timepoint", "outcome_observation_timepoint_raw", "timepointRaw") or "NR"),
            outcome_observation_timepoint_value=_float_or_none(_item_value(item, "timepoint_value", "outcome_observation_timepoint_value", "timepointValue")),
            outcome_observation_timepoint_unit=unit if unit in {1, 2, 3, 4, 5} else None,
            statistic_type=statistic if statistic in allowed_statistic else "other",
            analysis_population=population if population in allowed_population else "NR",
            intervention_estimate=intervention_estimate,
            intervention_variance_lower=_float_or_none(_item_value(item, "intervention_variance_lower", "interventionLower", "intervention_ci_lower")),
            intervention_variance_upper=_float_or_none(_item_value(item, "intervention_variance_upper", "interventionUpper", "intervention_ci_upper")),
            intervention_n=intervention_n,
            control_estimate=control_estimate,
            control_variance_lower=_float_or_none(_item_value(item, "control_variance_lower", "controlLower", "control_ci_lower")),
            control_variance_upper=_float_or_none(_item_value(item, "control_variance_upper", "controlUpper", "control_ci_upper")),
            control_n=control_n,
            between_group_measure=measure if measure in allowed_measure else "NR",
            outcome_between_group_estimate=_numeric_or_none(_item_value(item, "between_group_estimate", "effect_estimate", "outcome_between_group_estimate", "betweenGroupEstimate")),
            outcome_between_group_lower=between_lower,
            outcome_between_group_upper=between_upper,
            outcome_p_value=p_value,
            outcome_p_value_comparator=p_comparator if p_comparator in allowed_comparator else "NR",
            effect_size_name=str(_item_value(item, "effect_size_name", "effectSizeName") or "NR"),
            arm=arms,
            comparison=comparison,
            analysis_set=analysis_set,
            record_role=record_role,
            source_values=source_values,
            source_evidence=source_evidence,
            source_cells=deterministic_source_cells,
            p_value_cells=deterministic_p_value_cells,
            derived=derived,
            derivation=derivation,
            conflict_group_id=conflict_group_id,
            evidence=evidence,
        ))
    return OutcomeExtraction(outcomes=outcomes)


def _deduplicate_outcomes(outcomes: list[OutcomeStatistic]) -> list[OutcomeStatistic]:
    """Legacy exact de-duplication helper.

    New extraction runs must retain every source row so semantic duplicates and
    disagreements can be assigned to conflict groups downstream.  This helper
    remains available for explicit legacy callers only.
    """
    result: list[OutcomeStatistic] = []
    seen: set[tuple] = set()
    for outcome in outcomes:
        key = (
            outcome.outcome_name.strip().lower(),
            outcome.measurement_instrument.strip().lower(),
            outcome.outcome_observation_timepoint_raw.strip().lower(),
            outcome.analysis_population,
            outcome.intervention_estimate,
            outcome.control_estimate,
            outcome.outcome_between_group_estimate,
            outcome.outcome_p_value,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(outcome)
    return result


def merge_outcome_extractions(
    *extractions: OutcomeExtraction,
    deduplicate: bool = False,
) -> OutcomeExtraction:
    """Merge table responses while retaining source rows by default."""
    outcomes: list[OutcomeStatistic] = []
    for extraction in extractions:
        outcomes.extend(extraction.outcomes)
    return OutcomeExtraction(outcomes=_deduplicate_outcomes(outcomes) if deduplicate else outcomes)


def extract_outcomes_from_table(
    client: OpenAICompatibleClient,
    context: str,
    cache_path: Path,
    retries: int = 2,
    source: str = "markdown",
    request_delay_seconds: float = 0.01,
    table_id: str | None = None,
    arm_registry: tuple[str, ...] | list[str] | None = None,
) -> OutcomeExtraction:
    """Extract all outcome rows in one supplied table/context.

    The caller is expected to pass one table block (or a bounded row batch)
    and the response is normalized without a document-wide row limit.
    """
    disable_cache = os.getenv("ARTICLE_AGENT_DISABLE_OUTCOME_CACHE", "0").strip().lower() in {
        "1", "true", "yes",
    }
    if cache_path.exists() and not disable_cache:
        try:
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = None
    else:
        raw = None
    # Keep the complete source context and stable row markers lossless, but
    # use the semantic-first wire contract for each shard.  The authoritative
    # full Excel/Pydantic field registry remains in TABLE_OUTCOME_PROMPT_SPEC;
    # this pass asks the model only for semantic labels and exact source
    # values, while normalization deterministically maps them into every
    # registry field.  The compact contract avoids gateway failures caused by
    # asking the model to regenerate a large nested schema for every row.
    semantic_pass = os.getenv("ARTICLE_AGENT_OUTCOME_SEMANTIC_PASS", "1").strip().lower() in {
        "1", "true", "yes",
    }
    wire_spec = OUTCOME_SEMANTIC_PROMPT_SPEC if semantic_pass else {
        "role_definition": ROLE_DEFINITION,
        "task_description": TABLE_OUTCOME_PROMPT_SPEC["task_description"],
        "field_boundaries": TABLE_OUTCOME_PROMPT_SPEC["field_boundaries"],
        "json_template": TABLE_OUTCOME_PROMPT_SPEC["json_template"],
    }
    prompt = {
        "role_definition": wire_spec["role_definition"],
        "task_description": wire_spec["task_description"],
        "field_definitions": wire_spec["field_boundaries"],
        "json_template": wire_spec["json_template"],
        "source_context": context,
        "lossless_input": True,
    }
    if raw is None:
        last_error = None
        for _ in range(retries + 1):
            try:
                _sleep_before_request(request_delay_seconds)
                baml = BamlExtractor(client=client, raw_dir=cache_path.parent, retries=0)
                baml_outcomes_enabled = os.getenv("ARTICLE_AGENT_BAML_OUTCOMES", "0").strip().lower() in {
                    "1", "true", "yes",
                }
                if (
                    baml.generated_client is not None
                    and baml_outcomes_enabled
                    and os.getenv("ARTICLE_AGENT_STRUCTURED_BACKEND", "auto").strip().lower() != "legacy"
                ):
                    structured = baml.extract("outcomes", OutcomeExtraction, context, TABLE_OUTCOME_PROMPT_SPEC)
                    raw = structured.model_dump(mode="json")
                else:
                    raw = client.chat_json([
                        {"role": "system", "content": wire_spec["role_definition"]},
                        {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                    ])
                cache_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                break
            except RuntimeError as exc:
                last_error = exc
        else:
            raise RuntimeError(f"Table outcome extraction failed: {last_error}")

    return _normalize_outcome_items(
        raw,
        context,
        source=source,
        table_id=table_id,
        arm_registry=arm_registry,
    )


def extract_compact_outcomes(
    client: OpenAICompatibleClient,
    context: str,
    cache_path: Path,
    retries: int = 2,
    source: str = "markdown",
    request_delay_seconds: float = 0.01,
    table_id: str | None = None,
    arm_registry: tuple[str, ...] | list[str] | None = None,
) -> OutcomeExtraction:
    """Backward-compatible alias for the table-wise extractor."""
    return extract_outcomes_from_table(
        client,
        context,
        cache_path,
        retries=retries,
        source=source,
        request_delay_seconds=request_delay_seconds,
        table_id=table_id,
        arm_registry=arm_registry,
    )


_TABLE_CATEGORIES = {
    "outcome", "safety", "subgroup", "sensitivity", "baseline", "flow", "other", "unknown",
}


def _compact_api_prompts_enabled() -> bool:
    return os.getenv("ARTICLE_AGENT_COMPACT_API_PROMPTS", "0").strip().lower() in {"1", "true", "yes"}


def _compact_table_wire_context(context: str, max_chars: int = 700) -> str:
    """Return the complete table context.

    The old implementation silently kept only the last two rows and clipped
    the final row to a character budget.  That made valid outcome values
    disappear before the model saw them.  ``max_chars`` remains in the
    signature for compatibility, but transport partitioning is now handled by
    ``extract_outcomes_by_table`` and this function never truncates content.
    """

    del max_chars
    return context


def _compact_outcome_wire_prompt(context: str) -> dict:
    """Small schema contract for a row-wise retry request."""

    return {
        "task": "Extract the clinical outcome represented by this one selected table row. Return JSON only; never guess or combine rows.",
        "required_keys": (
            "outcomes[{table_id,row_id,outcome_name,measurement_instrument,"
            "outcome_observation_timepoint_raw,arm,comparison,analysis_set,record_role,"
            "analysis_population,intervention_estimate,intervention_n,control_estimate,control_n,"
            "between_group_measure,outcome_between_group_estimate,outcome_between_group_lower,"
            "outcome_between_group_upper,outcome_p_value,outcome_p_value_comparator,quote}]"
        ),
        "rules": "Copy TABLE_ID/ROW_ID and numeric cells from the row. Missing evidence is null or NR. quote must be a verbatim row fragment.",
        "source_context": _compact_table_wire_context(context),
    }


def _relevant_results_narrative(block: OutcomeTableBlock, narrative_hint: str) -> str:
    """Route complete Results evidence units relevant to one table.

    The complete Results section remains in ``routed_context.json`` and is
    used by the independent narrative pass.  Repeating that entire section
    on every table-row request, however, creates oversized gateway payloads
    and timeouts.  This helper selects whole paragraphs that explicitly name
    the table/caption or a row label; it never slices a paragraph or applies a
    character/record prefix.  When no direct match exists, the table itself
    is the only evidence unit and the routing decision is stated explicitly.
    """

    text = str(narrative_hint or "")
    if not text.strip():
        return ""
    prose = re.sub(r"<table\b.*?</table>", "\n", text, flags=re.I | re.S)
    paragraphs: list[str] = []
    for raw in re.split(r"\n\s*\n", prose):
        cleaned = re.sub(r"<[^>]+>", " ", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned and not (cleaned.startswith("|") and cleaned.endswith("|")):
            paragraphs.append(cleaned)
    if not paragraphs:
        return "No directly matched Results narrative paragraph; use the supplied table evidence only."

    caption = re.sub(r"<[^>]+>", " ", str(block.caption or ""))
    row_texts = list(block.target_rows or block.source_data_rows or block.rows)
    row_labels: list[str] = []
    for row in row_texts:
        cells = re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", str(row), re.I | re.S)
        rendered = " ".join(cells) if cells else str(row)
        rendered = re.sub(r"<[^>]+>", " ", rendered)
        rendered = re.sub(r"\s+", " ", rendered).strip()
        if rendered:
            # The first label cell is the stable semantic anchor; numeric
            # cells are deliberately excluded from routing keywords.
            first = re.split(r"\s*\|\s*", rendered, maxsplit=1)[0]
            row_labels.append(first)
    stop = {
        "table", "the", "and", "group", "groups", "mean", "sd", "value",
        "baseline", "follow", "treatment", "control", "after", "from",
        "with", "for", "were", "was", "this", "that", "data", "change",
        "difference", "score", "total", "number", "patients", "participants",
    }
    # Use complete row-label phrases rather than individual caption tokens.
    # Single words such as ``treatment``/``data`` occur throughout a Results
    # section and previously pulled the entire article into each request.
    row_phrases: list[str] = []
    for label in row_labels:
        normalized = re.sub(r"[^A-Za-z0-9%/_ -]", " ", label)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        words = [word for word in normalized.split() if word not in stop]
        phrase = " ".join(words)
        if len(phrase) >= 5 and phrase not in row_phrases:
            row_phrases.append(phrase)
    # Prefer explicit table number/caption matches, then exact row-label
    # phrases.  All returned matches remain whole paragraphs.
    caption_needles = [item.lower() for item in re.findall(r"(?:table\s*\d+|fig(?:ure)?\s*\d+)", caption, re.I)]
    matches: list[str] = []
    for paragraph in paragraphs:
        low = paragraph.lower()
        if any(needle in low for needle in caption_needles) or any(needle in low for needle in row_phrases):
            matches.append(paragraph)
    # Short evidence sections are safe to send in full; for larger sections,
    # a no-match result is represented explicitly rather than silently
    # dropping an unbounded prefix.
    if not matches and len(text) <= 12000:
        return "\n\n".join(paragraphs)
    if not matches:
        return "No directly matched Results narrative paragraph; use the supplied table evidence only."
    # De-duplicate while retaining source order; every selected unit is whole.
    return "\n\n".join(dict.fromkeys(matches))


def _bounded_table_classification_context(block: OutcomeTableBlock, narrative_hint: str) -> tuple[str, bool, int]:
    """Return a complete semantic-routing payload without clipping rows."""

    context = block.classification_prompt_text(_relevant_results_narrative(block, narrative_hint))
    return context, False, len(context)


def _normalize_table_classification(raw: dict | None) -> TableClassification:
    """Normalize a compact classifier response without applying heuristics."""

    payload = raw if isinstance(raw, dict) else {}
    nested = payload.get("table_classification") or payload.get("classification")
    if isinstance(nested, dict):
        payload = nested
    category = payload.get("table_category") or payload.get("category") or payload.get("table_type") or "unknown"
    category = str(category).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "clinical_outcome": "outcome",
        "clinical_outcomes": "outcome",
        "results": "outcome",
        "endpoint": "outcome",
        "adverse_event": "safety",
        "adverse_events": "safety",
        "participant_characteristics": "baseline",
        "baseline_characteristics": "baseline",
        "participant_flow": "flow",
        "consort_flow": "flow",
        "administrative": "other",
    }
    category = aliases.get(category, category)
    if category not in _TABLE_CATEGORIES:
        category = "unknown"
    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw) if confidence_raw not in (None, "", "NR") else None
    except (TypeError, ValueError):
        confidence = None
    if confidence is not None and not 0.0 <= confidence <= 1.0:
        confidence = None
    rationale = payload.get("rationale") or payload.get("reason") or payload.get("explanation") or "NR"
    return TableClassification(
        table_category=category,
        confidence=confidence,
        rationale=str(rationale).strip() or "NR",
    )


def classify_outcome_tables_with_llm(
    client: OpenAICompatibleClient,
    table_blocks: list[OutcomeTableBlock],
    raw_dir: Path,
    *,
    narrative_hint: str = "",
    retries: int = 1,
    request_delay_seconds: float = 0.01,
) -> tuple[list[OutcomeTableBlock], list[dict]]:
    """Classify each table semantically before deterministic row selection.

    The classifier is intentionally one-table-per-request and serial.  It sees
    all source rows, while the subsequent ``apply_table_classification`` call
    performs only structural header/row filtering.  A failed classifier is
    fail-closed to ``unknown`` and never fabricates an outcome table.
    """

    raw_dir.mkdir(parents=True, exist_ok=True)
    model_name = str(getattr(client, "model", "unknown"))
    try:
        retries = max(0, min(int(retries), 5))
    except (TypeError, ValueError):
        retries = 1
    classified_blocks: list[OutcomeTableBlock] = []
    manifest: list[dict] = []
    for table_index, block in enumerate(table_blocks, start=1):
        cache_path = raw_dir / f"outcomes.table-classification-{table_index:03d}.json"
        error_path = raw_dir / f"outcomes.table-classification-{table_index:03d}.error.txt"
        classification: TableClassification | None = None
        status = "pending"
        last_error = ""
        classification_context_truncated = False
        classification_source_chars = None
        disable_cache = os.getenv("ARTICLE_AGENT_DISABLE_TABLE_CLASSIFICATION_CACHE", "0").strip().lower() in {
            "1", "true", "yes",
        }
        if cache_path.exists() and not disable_cache:
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                classification = _normalize_table_classification(cached)
                status = "cached"
            except (OSError, ValueError, TypeError):
                classification = None
        if classification is None:
            for attempt in range(retries + 1):
                _sleep_before_request(request_delay_seconds)
                classification_context, classification_context_truncated, classification_source_chars = _bounded_table_classification_context(
                    block, narrative_hint
                )
                payload = {
                    "role_definition": TABLE_CLASSIFICATION_PROMPT_SPEC["role_definition"],
                    "task_description": TABLE_CLASSIFICATION_PROMPT_SPEC["task_description"],
                    "field_definitions": TABLE_CLASSIFICATION_PROMPT_SPEC["field_boundaries"],
                    "json_template": TABLE_CLASSIFICATION_PROMPT_SPEC["json_template"],
                    "table_context": classification_context,
                    "lossless_input": True,
                }
                try:
                    raw = client.chat_json([
                        {"role": "system", "content": TABLE_CLASSIFICATION_PROMPT_SPEC["role_definition"]},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ])
                    cache_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
                    classification = _normalize_table_classification(raw)
                    status = "success"
                    break
                except (RuntimeError, OSError, TypeError, ValueError) as exc:
                    last_error = str(exc)
                    if attempt == retries:
                        break
            if classification is None:
                status = "failed"
                classification = TableClassification(
                    table_category="unknown",
                    confidence=0.0,
                    rationale="LLM table classification failed; no target rows selected.",
                )
                error_path.write_text(last_error or "unknown classifier error", encoding="utf-8")

        classified = apply_table_classification(
            block,
            classification.table_category,
            classification.rationale,
            confidence=classification.confidence,
            model=model_name,
        )
        classified_blocks.append(classified)
        manifest.append({
            "table_id": block.table_id,
            "caption": block.caption,
            "classification_model": model_name,
            "classification_context_chars": classification_source_chars,
                    "classification_context_truncated": False,
                    "lossless_input": True,
            "table_category": classification.table_category,
            "confidence": classification.confidence,
            "rationale": classification.rationale,
            "source_data_row_count": len(block.source_data_rows),
            "selected_row_count": len(classified.selected_rows or ()),
            "status": status,
            "cache": cache_path.name,
            **({"error": last_error} if status == "failed" else {}),
        })
    return classified_blocks, manifest


def _response_row_ids(raw: dict | None, extraction: OutcomeExtraction | None = None) -> set[str]:
    """Collect every source row acknowledged by a model response.

    ``row_decisions``/``non_outcome_row_ids`` allow a model to explicitly say
    that a row is administrative rather than leaving the coverage ambiguous.
    Outcome IDs from a normalized extraction are included as a compatibility
    fallback for older response shapes.
    """

    found: set[str] = set()
    def canonical_row_id(value: object) -> str:
        return re.sub(r"#part-[^:]+", "", str(value))
    payload = raw if isinstance(raw, dict) else {}
    items = payload.get("outcomes") or payload.get("rows") or []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            value = _item_value(item, "row_id", "rowId", "source_row_id", "sourceRowId")
            if value not in (None, "", "NR"):
                found.add(canonical_row_id(value))
    for key in ("row_decisions", "row_status", "row_annotations"):
        decisions = payload.get(key)
        if isinstance(decisions, list):
            for item in decisions:
                if isinstance(item, dict):
                    value = _item_value(item, "row_id", "rowId", "source_row_id", "sourceRowId")
                    if value not in (None, "", "NR"):
                        found.add(canonical_row_id(value))
    for key in ("non_outcome_row_ids", "skipped_row_ids", "acknowledged_row_ids"):
        values = payload.get(key)
        if isinstance(values, list):
            found.update(canonical_row_id(value) for value in values if value not in (None, "", "NR"))
    if extraction is not None:
        found.update(str(item.row_id) for item in extraction.outcomes if item.row_id not in (None, "", "NR"))
    return found


def _request_hash(context: str) -> str:
    return hashlib.sha256(context.encode("utf-8")).hexdigest()


def extract_outcomes_by_table(
    client: OpenAICompatibleClient,
    table_blocks: list[OutcomeTableBlock],
    raw_dir: Path,
    narrative_hint: str = "",
    retries: int = 2,
    max_rows_per_request: int = 3,
    max_workers: int = 1,
    request_delay_seconds: float = 0.01,
    whole_table_first: bool = False,
    whole_table_timeout: int | None = None,
    request_id_prefix: str = "table",
) -> tuple[OutcomeExtraction, list[dict]]:
    """Extract every selected row with a lossless whole-table fallback plan.

    Production calls set ``whole_table_first=True``.  A complete table is
    attempted first; an API/JSON/coverage failure automatically retries only
    missing rows with the complete header and column map.  The default remains
    the historical bounded-chunk behaviour for direct legacy callers/tests.
    """

    raw_dir.mkdir(parents=True, exist_ok=True)
    # Large whole-table responses are deliberately attempted first, but a
    # gateway can spend minutes generating a response that will ultimately be
    # rejected for partial row coverage.  Use a short, independently cloned
    # client for that probe when requested; row-level retries keep the normal
    # extraction timeout.  Test doubles and custom clients that cannot be
    # cloned simply use the caller's client for both modes.
    whole_table_client = client
    if whole_table_first and whole_table_timeout not in (None, 0):
        try:
            whole_table_client = type(client)(
                api_key=getattr(client, "api_key", None),
                base_url=getattr(client, "base_url", None),
                model=getattr(client, "model", None),
                timeout=max(10, int(whole_table_timeout)),
            )
        except Exception:
            whole_table_client = client
    hint = narrative_hint
    max_rows_per_request = max(1, int(max_rows_per_request))
    max_workers = max(1, min(int(max_workers), 8))
    skip_existing_errors = os.getenv("ARTICLE_AGENT_SKIP_EXISTING_ERRORS", "0").strip().lower() in {"1", "true", "yes"}
    manifest: list[dict] = []
    tasks: list[tuple[int, int, OutcomeTableBlock, tuple[str, ...], tuple[str, ...], Path, str, str, str | None]] = []
    try:
        # Zero is the lossless default: attempt the complete table regardless
        # of row count.  Deployments may opt into a preflight guard explicitly
        # when a provider imposes a request-size limit; that guard only changes
        # the transport partition and never drops source rows.
        whole_max_rows = int(os.getenv("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_MAX_ROWS", "0"))
    except ValueError:
        whole_max_rows = 0
    try:
        whole_max_chars = int(os.getenv("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_MAX_CHARS", "0"))
    except ValueError:
        whole_max_chars = 0
    # ``0`` means no row-count guard: attempt the complete table first and
    # fall back only when the full prompt exceeds the explicit character
    # budget or the response fails coverage validation.  This preserves the
    # lossless two-level strategy without introducing a hidden row cap.
    whole_max_rows = max(0, whole_max_rows)
    whole_max_chars = max(0, whole_max_chars)

    for index, block in enumerate(table_blocks, start=1):
        prepared = (
            prepare_outcome_table_block(block.table_id, block.caption, block.raw_table, block.rows, block.source)
            if block.selected_rows is None else block
        )
        # Route whole Results paragraphs per table so row requests remain
        # lossless at the evidence-unit level without repeating an entire
        # article-sized section on every request.
        hint = _relevant_results_narrative(prepared, narrative_hint)
        headers = tuple(prepared.header_rows)
        data_rows = list(prepared.target_rows)
        data_row_ids = list(prepared.target_row_ids)
        base_entry = {
            "table_id": prepared.table_id,
            "caption": prepared.caption,
            "source": prepared.source,
            "table_category": prepared.table_category,
            "selection_reason": prepared.selection_reason,
            "row_count": prepared.row_count,
            "selected_row_count": len(data_rows),
            "header_row_count": len(headers),
            "column_labels": list(prepared.column_labels),
            "column_map": list(prepared.column_map),
            "arm_registry": list(prepared.arm_registry),
            "timepoint_labels": list(prepared.timepoint_labels),
            "statistic_columns": list(prepared.statistic_columns),
            "lossless": True,
        }
        if not data_rows:
            manifest.append({**base_entry, "part_count": 0, "parts": [], "status": "skipped", "outcome_count": 0})
            continue
        # A gateway may keep streaming an oversized whole-table response even
        # after the socket timeout, tying up the serial worker for many
        # minutes.  For such tables, enter the same lossless row fallback
        # directly and record the explicit preflight reason.  No source row is
        # omitted; the complete header/column map is repeated on every row.
        whole_prompt_chars = len(prepared.prompt_text(hint)) if whole_table_first else 0
        attempt_whole = bool(
            whole_table_first
            and (whole_max_rows == 0 or len(data_rows) <= whole_max_rows)
            and (whole_max_chars == 0 or whole_prompt_chars <= whole_max_chars)
        )
        preflight_reason = None
        if whole_table_first and not attempt_whole:
            reasons = []
            if whole_max_rows and len(data_rows) > whole_max_rows:
                reasons.append(f"row_count>{whole_max_rows}")
            if whole_max_chars and whole_prompt_chars > whole_max_chars:
                reasons.append(f"prompt_chars>{whole_max_chars}")
            preflight_reason = "whole_table_preflight_guard:" + ",".join(reasons or ["gateway_safe_mode"])
        if attempt_whole:
            chunks = [tuple(data_rows)]
            id_chunks = [tuple(data_row_ids)]
        else:
            chunks = [tuple(data_rows[offset:offset + max_rows_per_request]) for offset in range(0, len(data_rows), max_rows_per_request)]
            id_chunks = [tuple(data_row_ids[offset:offset + max_rows_per_request]) for offset in range(0, len(data_row_ids), max_rows_per_request)]
        manifest.append({
            **base_entry,
            "part_count": len(chunks),
            "whole_table_first": bool(whole_table_first),
            "whole_table_attempted": attempt_whole,
            "whole_table_preflight_reason": preflight_reason,
            "parts": [
                {
                    "part": part_index,
                    "row_count": len(rows),
                    "row_ids": list(id_chunks[part_index - 1]),
                    "cache": f"outcomes.table-{index:03d}.part-{part_index:02d}.json",
                    "status": "pending",
                    "request_mode": "whole_table" if attempt_whole else "row_block",
                }
                for part_index, rows in enumerate(chunks, start=1)
            ],
        })
        for part_index, rows in enumerate(chunks, start=1):
            row_ids = id_chunks[part_index - 1]
            chunk_block = OutcomeTableBlock(
                table_id=f"{prepared.table_id}#part-{part_index:02d}",
                caption=prepared.caption,
                raw_table=prepared.raw_table,
                rows=rows,
                source=prepared.source,
                header_rows=headers,
                selected_rows=rows,
                selected_row_ids=row_ids,
                table_category=prepared.table_category,
                selection_reason=prepared.selection_reason,
                column_labels=prepared.column_labels,
                arm_registry=prepared.arm_registry,
                timepoint_labels=prepared.timepoint_labels,
                statistic_columns=prepared.statistic_columns,
                column_map=prepared.column_map,
            )
            cache_path = raw_dir / f"outcomes.table-{index:03d}.part-{part_index:02d}.json"
            tasks.append((index, part_index, chunk_block, rows, headers, cache_path, hint, "whole_table" if attempt_whole else "row_block", preflight_reason))

    def make_row_block(chunk_block: OutcomeTableBlock, row: str, row_id: str) -> OutcomeTableBlock:
        return OutcomeTableBlock(
            table_id=chunk_block.table_id,
            caption=chunk_block.caption,
            raw_table=chunk_block.raw_table,
            rows=(row,),
            source=chunk_block.source,
            header_rows=chunk_block.header_rows,
            selected_rows=(row,),
            selected_row_ids=(row_id,),
            table_category=chunk_block.table_category,
            selection_reason=chunk_block.selection_reason,
            column_labels=chunk_block.column_labels,
            arm_registry=chunk_block.arm_registry,
            timepoint_labels=chunk_block.timepoint_labels,
            statistic_columns=chunk_block.statistic_columns,
            column_map=chunk_block.column_map,
        )

    def run_part(task):
        index, part_index, chunk_block, rows, _headers, cache_path, _hint, request_mode, preflight_reason = task
        expected_ids = [str(value) for value in chunk_block.selected_row_ids]
        existing_error = cache_path.with_suffix(".error.txt")
        if skip_existing_errors and existing_error.exists() and not cache_path.exists():
            error = existing_error.read_text(encoding="utf-8", errors="replace")
            return index, part_index, OutcomeExtraction(outcomes=[]), {
                "status": "failed_cached", "error": error, "outcome_count": 0,
                "cache_reused": True, "request_mode": request_mode,
                "covered_row_ids": [], "missing_row_ids": expected_ids,
                "request_records": [{
                    "run_id": os.getenv("ARTICLE_AGENT_RUN_ID") or "NR",
                    "request_id": f"{request_id_prefix}-{index:03d}-part-{part_index:02d}",
                    "table_id": chunk_block.table_id.split("#part-", 1)[0],
                    "row_ids": expected_ids, "request_mode": request_mode,
                    "input_sha256": _request_hash(chunk_block.prompt_text(_hint)),
                    "lossless": True, "attempt": 0, "fallback_reason": "cached_error",
                    "response_status": "failed",
                }],
            }

        merged_outcomes: list[OutcomeStatistic] = []
        merged_raw_items: list[dict] = []
        request_records: list[dict] = []
        missing_ids = list(expected_ids)
        completed_ids: set[str] = set()
        fallback_reason = preflight_reason

        def request_context(block: OutcomeTableBlock) -> str:
            return block.prompt_text(_hint)

        def run_single(block: OutcomeTableBlock, path: Path, mode: str, row_id_list: list[str], reason: str | None = None):
            context = request_context(block)
            request_id = f"{request_id_prefix}-{index:03d}-part-{part_index:02d}-{mode}-{len(request_records) + 1:02d}"
            record = {
                "run_id": os.getenv("ARTICLE_AGENT_RUN_ID") or "NR",
                "request_id": request_id,
                "table_id": block.table_id.split("#part-", 1)[0],
                "row_ids": list(row_id_list),
                "request_mode": mode,
                "input_sha256": _request_hash(context),
                "lossless": True,
                "attempt": 1,
                "fallback_reason": reason,
                "response_status": "pending",
            }
            request_records.append(record)
            try:
                # Reuse a previously stored *complete* response only when it
                # contains every requested row and the current source quote is
                # present.  This lets a resumed run normalize an older raw
                # response with the new source-layer schema without treating a
                # partial/mismatched cache as successful coverage.  The origin
                # is recorded explicitly for audit; no value is synthesized.
                if mode == "row_block" or mode == "row":
                    expected_cached = {_canonical_row_id(value) for value in row_id_list}
                    def verified_payload(candidate: Path):
                        try:
                            payload = json.loads(candidate.read_text(encoding="utf-8"))
                        except (OSError, ValueError, TypeError):
                            return None
                        if not isinstance(payload, dict):
                            return None
                        candidate_ids = _response_row_ids(payload)
                        if candidate_ids != expected_cached:
                            return None
                        source_rows = []
                        for item in payload.get("outcomes", []) if isinstance(payload.get("outcomes"), list) else []:
                            if not isinstance(item, dict):
                                continue
                            value = _canonical_row_id(_item_value(item, "row_id", "rowId", "source_row_id", "sourceRowId"))
                            if value not in expected_cached:
                                continue
                            quote = str(_item_value(item, "quote", "source_evidence", "row_quote", "evidence_quote") or "")
                            expected_quote = _row_quote_from_context(context, value)
                            if expected_quote and quote and quote not in context and expected_quote not in quote:
                                return None
                            source_rows.append(item)
                        decisions = [
                            item for item in payload.get("row_decisions", [])
                            if isinstance(item, dict)
                            and _canonical_row_id(_item_value(item, "row_id", "rowId", "source_row_id", "sourceRowId")) in expected_cached
                        ]
                        returned_ids = _response_row_ids({"outcomes": source_rows, "row_decisions": decisions})
                        if returned_ids != expected_cached:
                            return None
                        return {"outcomes": source_rows, "row_decisions": decisions}

                    current_verified = verified_payload(path) if path.exists() else None
                    if current_verified is None:
                        siblings = sorted(
                            raw_dir.glob(f"outcomes.table-{index:03d}.part-*.json"),
                            key=lambda item: item.stat().st_mtime,
                            reverse=True,
                        )
                        for sibling in siblings:
                            if sibling == path or ".stale" in sibling.name:
                                continue
                            current_verified = verified_payload(sibling)
                            if current_verified is not None:
                                path.write_text(json.dumps(current_verified, ensure_ascii=False, indent=2), encoding="utf-8")
                                record["cache_reused_from"] = sibling.name
                                break
                # A row-level cache is reusable only when it explicitly
                # acknowledges the exact row set for this request.  Older
                # batches may have used different header parsing and stable
                # row IDs; never let such a cache suppress a required retry.
                if mode == "row" and path.exists():
                    try:
                        cached_payload = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, ValueError, TypeError):
                        cached_payload = {}
                    cached_ids = _response_row_ids(cached_payload)
                    expected_cached_ids = {_canonical_row_id(value) for value in row_id_list}
                    if cached_ids != expected_cached_ids:
                        stale_path = path.with_suffix(".stale.json")
                        suffix = 2
                        while stale_path.exists():
                            stale_path = path.with_name(f"{path.stem}.stale-{suffix}.json")
                            suffix += 1
                        path.replace(stale_path)
                extraction = extract_outcomes_from_table(
                    whole_table_client if mode == "whole_table" else client,
                    context,
                    path,
                    # The whole-table call is a coverage probe.  Retrying the
                    # same oversized payload multiplies gateway timeout cost;
                    # once it fails, the manifest-driven row fallback is the
                    # retry.  Row requests retain the configured API retry
                    # count for transient failures.
                    retries=0 if mode == "whole_table" else retries,
                    source="table",
                    request_delay_seconds=request_delay_seconds,
                    table_id=block.table_id, arm_registry=block.arm_registry,
                )
                try:
                    raw_response = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    raw_response = {}
                # A resumed cache may have been produced before a header
                # re-parse changed the stable row IDs.  Keep only records
                # belonging to this request's declared row set; otherwise an
                # old row would be duplicated into the new dataset while
                # falsely satisfying coverage.
                allowed_rows = {_canonical_row_id(value) for value in row_id_list}
                if isinstance(raw_response.get("outcomes"), list):
                    raw_response["outcomes"] = [
                        item for item in raw_response["outcomes"]
                        if isinstance(item, dict)
                        and _canonical_row_id(_item_value(item, "row_id", "rowId", "source_row_id", "sourceRowId")) in allowed_rows
                    ]
                if extraction is not None:
                    extraction = OutcomeExtraction(outcomes=[
                        outcome for outcome in extraction.outcomes
                        if _canonical_row_id(outcome.row_id) in allowed_rows
                    ])
                covered = _response_row_ids(raw_response, extraction)
                record["covered_row_ids"] = sorted(covered.intersection(row_id_list))
                record["missing_row_ids"] = sorted(set(row_id_list) - covered)
                record["response_status"] = "success" if not record["missing_row_ids"] else "partial"
                return extraction, raw_response, covered
            except RuntimeError as exc:
                record["response_status"] = "failed"
                record["error"] = str(exc)
                # Keep an explicit per-row retry marker.  Without this file a
                # failed fallback row could look like an ordinary absent
                # cache until the final manifest is assembled.
                path.with_suffix(".error.txt").write_text(str(exc), encoding="utf-8")
                return None, {}, set()

        whole_context = request_context(chunk_block)
        try:
            if request_mode == "whole_table":
                extraction, raw_response, covered = run_single(chunk_block, cache_path, "whole_table", expected_ids)
                if extraction is not None:
                    completed_ids.update(value for value in expected_ids if value in covered)
                    merged_outcomes.extend(extraction.outcomes)
                    if isinstance(raw_response.get("outcomes"), list):
                        merged_raw_items.extend(item for item in raw_response["outcomes"] if isinstance(item, dict))
                    missing_ids = [row_id for row_id in expected_ids if row_id not in covered]
                    if missing_ids:
                        fallback_reason = "whole_table_partial_row_coverage"
                else:
                    fallback_reason = "whole_table_request_failed"
            else:
                extraction, raw_response, covered = run_single(
                    chunk_block, cache_path, "row_block", expected_ids, preflight_reason
                )
                if extraction is not None:
                    completed_ids.update(value for value in expected_ids if value in covered)
                    merged_outcomes.extend(extraction.outcomes)
                    if isinstance(raw_response.get("outcomes"), list):
                        merged_raw_items.extend(item for item in raw_response["outcomes"] if isinstance(item, dict))
                    missing_ids = [row_id for row_id in expected_ids if row_id not in covered]
                    if missing_ids:
                        fallback_reason = "row_block_partial_row_coverage"
                else:
                    fallback_reason = "row_block_request_failed"

            # In production the whole-table response is accepted only when it
            # acknowledges every input row.  Missing rows are retried one at a
            # time with the same complete header/column map; no source row is
            # silently dropped.  Legacy bounded callers retain their old
            # single-block behaviour unless explicitly opting into the
            # lossless fallback.
            if request_mode == "whole_table" and missing_ids:
                for row_index, row_id in enumerate(expected_ids, start=1):
                    if row_id not in missing_ids:
                        continue
                    row_offset = expected_ids.index(row_id)
                    row_block = make_row_block(chunk_block, rows[row_offset], row_id)
                    row_cache = cache_path.with_name(f"{cache_path.stem}.row-{row_index:03d}.json")
                    row_extraction, row_raw, _ = run_single(row_block, row_cache, "row", [row_id], fallback_reason)
                    if row_extraction is None:
                        continue
                    # A valid row request may correctly return zero outcome
                    # records (for example an administrative row).  The
                    # request itself acknowledges coverage, so it must not
                    # remain in the missing-row set.
                    completed_ids.add(row_id)
                    merged_outcomes.extend(row_extraction.outcomes)
                    if isinstance(row_raw.get("outcomes"), list):
                        merged_raw_items.extend(item for item in row_raw["outcomes"] if isinstance(item, dict))
                # Persist the merged response so a resumed run is complete and
                # the original whole-table response remains traceable in the
                # per-row cache files.
                covered_after_fallback = _response_row_ids(
                    {"outcomes": merged_raw_items}, OutcomeExtraction(outcomes=merged_outcomes)
                ) | completed_ids
                missing_ids = [row_id for row_id in expected_ids if row_id not in covered_after_fallback]
                # Only acknowledge rows that were actually returned or
                # explicitly completed by a valid row request.  Writing a
                # decision for every expected ID here would turn a failed row
                # into a false cache hit on resume and violate lossless
                # coverage guarantees.
                cache_path.write_text(json.dumps({
                    "outcomes": merged_raw_items,
                    "row_decisions": [
                        {"row_id": value, "status": "covered"}
                        for value in expected_ids
                        if value in covered_after_fallback
                    ],
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            elif request_mode != "whole_table" and missing_ids and whole_table_first:
                # Row-block callers (including a resumed cache whose row IDs
                # no longer match after header re-parsing) use the same
                # lossless per-row recovery.  A partial row-block response is
                # never accepted as complete and never silently cached.
                for row_index, row_id in enumerate(expected_ids, start=1):
                    if row_id not in missing_ids:
                        continue
                    row_offset = expected_ids.index(row_id)
                    row_block = make_row_block(chunk_block, rows[row_offset], row_id)
                    row_cache = cache_path.with_name(f"{cache_path.stem}.row-{row_index:03d}.json")
                    row_extraction, row_raw, _ = run_single(
                        row_block, row_cache, "row", [row_id], "row_block_partial_row_coverage"
                    )
                    if row_extraction is None:
                        continue
                    completed_ids.add(row_id)
                    merged_outcomes.extend(row_extraction.outcomes)
                    if isinstance(row_raw.get("outcomes"), list):
                        merged_raw_items.extend(item for item in row_raw["outcomes"] if isinstance(item, dict))
                covered_after_fallback = _response_row_ids(
                    {"outcomes": merged_raw_items}, OutcomeExtraction(outcomes=merged_outcomes)
                ) | completed_ids
                missing_ids = [row_id for row_id in expected_ids if row_id not in covered_after_fallback]
                cache_path.write_text(json.dumps({
                    "outcomes": merged_raw_items,
                    "row_decisions": [
                        {"row_id": value, "status": "covered"}
                        for value in expected_ids
                        if value in covered_after_fallback
                    ],
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            elif request_mode != "whole_table" and not cache_path.exists() and merged_raw_items:
                cache_path.write_text(json.dumps({"outcomes": merged_raw_items}, ensure_ascii=False, indent=2), encoding="utf-8")

            if missing_ids:
                status = "partial"
            else:
                status = "success"
            return index, part_index, OutcomeExtraction(outcomes=merged_outcomes), {
                "status": status,
                "outcome_count": len(merged_outcomes),
                "request_mode": (
                    "whole_table_then_row" if request_mode == "whole_table" and fallback_reason
                    else "row_block_preflight" if request_mode != "whole_table" and preflight_reason
                    else request_mode
                ),
                "whole_table_attempted": request_mode == "whole_table",
                "fallback_reason": fallback_reason,
                "covered_row_ids": [value for value in expected_ids if value not in missing_ids],
                "missing_row_ids": missing_ids,
                "request_records": request_records,
            }
        except Exception as exc:
            error_path = raw_dir / f"outcomes.table-{index:03d}.part-{part_index:02d}.error.txt"
            error_path.write_text(str(exc), encoding="utf-8")
            return index, part_index, OutcomeExtraction(outcomes=merged_outcomes), {
                "status": "failed", "error": str(exc), "outcome_count": len(merged_outcomes),
                "request_mode": request_mode, "missing_row_ids": missing_ids,
                "request_records": request_records,
            }

    extraction_by_part: dict[tuple[int, int], OutcomeExtraction] = {}
    request_manifest: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_part, task) for task in tasks]
        for future in as_completed(futures):
            index, part_index, extraction, result = future.result()
            extraction_by_part[(index, part_index)] = extraction
            manifest[index - 1]["parts"][part_index - 1].update({key: value for key, value in result.items() if key != "request_records"})
            request_manifest.extend(result.get("request_records", []))

    for item in manifest:
        if item.get("status") == "skipped":
            continue
        item["status"] = "success" if all(part.get("status") == "success" for part in item["parts"]) else "partial"
        item["outcome_count"] = sum(part.get("outcome_count", 0) for part in item["parts"])
        item["covered_row_ids"] = [row_id for part in item["parts"] for row_id in part.get("covered_row_ids", [])]
        item["missing_row_ids"] = [row_id for part in item["parts"] for row_id in part.get("missing_row_ids", [])]
    all_outcomes: list[OutcomeStatistic] = []
    for key in sorted(extraction_by_part):
        all_outcomes.extend(extraction_by_part[key].outcomes)
    request_manifest.sort(key=lambda item: str(item.get("request_id", "")))
    (raw_dir / "request_manifest.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in request_manifest), encoding="utf-8"
    )
    return OutcomeExtraction(outcomes=all_outcomes), manifest


def extract_outcomes_from_results_narrative(
    client: OpenAICompatibleClient,
    results_context: str,
    raw_dir: Path,
    *,
    retries: int = 2,
    request_delay_seconds: float = 0.01,
    only_row_ids: set[str] | None = None,
    request_id_prefix: str = "narrative",
) -> tuple[OutcomeExtraction, list[dict]]:
    """Extract numerical outcomes reported in Results prose.

    Tables are removed only because they have their own lossless table pass;
    every remaining Results paragraph receives a stable narrative row ID.
    The same whole-text/row fallback planner is then used, so prose outcomes
    are never limited to a fixed number of records.
    """

    raw_dir.mkdir(parents=True, exist_ok=True)
    narrative = re.sub(r"<table\b.*?</table>", "\n", results_context, flags=re.I | re.S)
    lines = narrative.splitlines()
    paragraphs: list[str] = []
    buffer: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Drop pipe-table rows and separator lines; the dedicated table pass
        # owns those cells, while headings and prose remain source evidence.
        if stripped.startswith("|") and stripped.endswith("|"):
            if buffer:
                paragraphs.append(" ".join(buffer).strip())
                buffer = []
            continue
        if not stripped:
            if buffer:
                paragraphs.append(" ".join(buffer).strip())
                buffer = []
            continue
        buffer.append(stripped)
    if buffer:
        paragraphs.append(" ".join(buffer).strip())
    paragraphs = [paragraph for paragraph in paragraphs if paragraph]
    if not paragraphs:
        return OutcomeExtraction(outcomes=[]), []

    # Prose without any numeric/statistical signal cannot contain a
    # reportable arm estimate, CI or P value.  Keep such paragraphs in an
    # explicit skipped list (rather than silently deleting them) and send all
    # potentially outcome-bearing paragraphs in complete chunks.  This is a
    # deterministic transport optimization, not a semantic table classifier;
    # the LLM still decides whether each retained paragraph is an outcome.
    narrative_signal = re.compile(
        r"(?:\d|%|p\s*[<=>]|confidence\s+interval|standard\s+deviation|mean|median|"
        r"significant|difference|improv|primary\s+outcome|secondary\s+outcome|pain|score|scale)",
        re.I,
    )
    skipped_paragraphs = [
        {
            "row_id": f"narrative-results:r{index:03d}",
            "status": "skipped",
            "reason": "paragraph contains no numeric/statistical outcome signal; retained locally and not sent as an outcome candidate",
        }
        for index, paragraph in enumerate(paragraphs, start=1)
        if not narrative_signal.search(paragraph)
    ]
    candidates = [
        (index, paragraph)
        for index, paragraph in enumerate(paragraphs, start=1)
        if narrative_signal.search(paragraph)
    ]
    # Recovery callers may provide the exact stable narrative row IDs that
    # remain uncovered in the request manifest.  Filter only at paragraph
    # boundaries while retaining the original paragraph index in every row
    # ID; no characters are removed from a selected paragraph and all
    # non-selected paragraphs remain represented by the authoritative
    # manifest.  This prevents a retry from re-sending already successful
    # prose shards or changing row identity after an append-only repair.
    if only_row_ids:
        wanted = {
            str(value).strip()
            for value in only_row_ids
            if value not in (None, "", "NR")
        }
        candidates = [
            (index, paragraph)
            for index, paragraph in candidates
            if f"narrative-results:r{index:03d}" in wanted
        ]
    force_fresh = os.getenv("ARTICLE_AGENT_NARRATIVE_FORCE_FRESH", "1").strip().lower() in {
        "1", "true", "yes",
    }
    if not candidates:
        manifest = [{"source_mode": "results_narrative", "status": "skipped", "skipped_paragraphs": skipped_paragraphs}]
        (raw_dir / "outcomes.narrative.manifest.json").write_text(
            json.dumps({
                "strategy": "lossless_results_narrative_paragraph_signal_routing",
                "lossless": True,
                "cache_policy": "forced_fresh" if force_fresh else "reuse_allowed",
                "paragraph_count": len(paragraphs),
                "candidate_paragraph_count": 0,
                "skipped_paragraphs": skipped_paragraphs,
                "manifest": manifest,
            }, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return OutcomeExtraction(outcomes=[]), manifest

    # A complete Results narrative can be larger than the gateway's response
    # budget even though it contains no truncatable structure.  Partition it
    # only at paragraph boundaries; each chunk still contains every character
    # of its paragraphs and carries the original stable row IDs.  This keeps
    # transport lossless while avoiding a pathological one-request/one-hour
    # fallback over every prose paragraph after a giant request times out.
    try:
        paragraphs_per_request = int(os.getenv("ARTICLE_AGENT_NARRATIVE_PARAGRAPHS_PER_REQUEST", "8"))
    except ValueError:
        paragraphs_per_request = 8
    paragraphs_per_request = max(1, min(paragraphs_per_request, 24))
    blocks: list[OutcomeTableBlock] = []
    for offset in range(0, len(candidates), paragraphs_per_request):
        candidate_chunk = candidates[offset:offset + paragraphs_per_request]
        chunk = tuple(paragraph for _index, paragraph in candidate_chunk)
        first = candidate_chunk[0][0]
        last = candidate_chunk[-1][0]
        blocks.append(OutcomeTableBlock(
            table_id="narrative-results" if len(candidates) <= paragraphs_per_request else f"narrative-results:p{first:03d}-p{last:03d}",
            caption="Results narrative outcomes",
            # Keep the full narrative in the audit object.  ``prompt_text``
            # renders only the selected complete paragraphs for this request.
            raw_table=narrative,
            rows=chunk,
            source="markdown",
            header_rows=(),
            selected_rows=chunk,
            selected_row_ids=tuple(f"narrative-results:r{index:03d}" for index, _paragraph in candidate_chunk),
            table_category="outcome",
            selection_reason="Results prose pass; tables handled separately; complete paragraph chunk",
        ))
    try:
        whole_table_timeout = int(os.getenv("ARTICLE_AGENT_OUTCOME_WHOLE_TABLE_TIMEOUT", "30"))
    except ValueError:
        whole_table_timeout = 30
    whole_table_timeout = max(10, whole_table_timeout)
    # Narrative cache files historically shared the ``outcomes.table-*``
    # namespace with an older table-only pass.  A valid-looking empty
    # response from that pass can therefore satisfy the row-coverage check
    # while silently suppressing the Results prose extraction.  Narrative
    # extraction is a distinct evidence source, so its current run is always
    # sent to the API unless the caller explicitly opts out.  The previous
    # value is restored immediately after the serial call, keeping table
    # cache policy independent.
    previous_outcome_cache_flag = os.environ.get("ARTICLE_AGENT_DISABLE_OUTCOME_CACHE")
    if force_fresh:
        os.environ["ARTICLE_AGENT_DISABLE_OUTCOME_CACHE"] = "1"
    try:
        extraction, manifest = extract_outcomes_by_table(
            client,
            blocks,
            raw_dir,
            narrative_hint="",
            retries=retries,
            max_rows_per_request=paragraphs_per_request,
            max_workers=1,
            request_delay_seconds=request_delay_seconds,
            whole_table_first=True,
            whole_table_timeout=whole_table_timeout,
            request_id_prefix=request_id_prefix,
        )
    finally:
        if force_fresh:
            if previous_outcome_cache_flag is None:
                os.environ.pop("ARTICLE_AGENT_DISABLE_OUTCOME_CACHE", None)
            else:
                os.environ["ARTICLE_AGENT_DISABLE_OUTCOME_CACHE"] = previous_outcome_cache_flag
    for item in manifest:
        item["source_mode"] = "results_narrative"
    (raw_dir / "outcomes.narrative.manifest.json").write_text(
        json.dumps({
            "strategy": "lossless_results_narrative_whole_text_then_paragraph_fallback",
            "lossless": True,
            "cache_policy": "forced_fresh" if force_fresh else "reuse_allowed",
            "paragraph_count": len(paragraphs),
            "candidate_paragraph_count": len(candidates),
            "paragraphs_per_request": paragraphs_per_request,
            "chunk_count": len(blocks),
            "skipped_paragraphs": skipped_paragraphs,
            "manifest": manifest,
        }, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return extraction, manifest


def _normalize_postprocess_payload(raw: dict | None) -> dict:
    """Accept a small set of harmless aliases while keeping the output strict."""
    raw = raw or {}
    source_records = raw.get("records")
    if source_records is None:
        source_records = raw.get("outcomes", [])
    if not isinstance(source_records, list):
        source_records = []
    records = []
    allowed_status = {"none", "conflict", "unresolved", "not_checked"}
    status_aliases = {"gold_conflict": "conflict", "no_conflict": "none", "unknown": "unresolved"}
    for item in source_records:
        if not isinstance(item, dict):
            continue
        source_index = _item_value(item, "source_index", "sourceIndex", "index")
        try:
            source_index = int(source_index)
        except (TypeError, ValueError):
            continue
        status = str(_item_value(item, "annotation_status", "annotationStatus", "conflict_status", "conflictStatus", "status") or "unresolved")
        status = status_aliases.get(status, status)
        if status not in allowed_status:
            status = "unresolved"
        gold_ids = _item_value(item, "gold_row_ids", "goldRowIds", "gold_ids") or []
        if not isinstance(gold_ids, list):
            gold_ids = [gold_ids]
        conflict_fields = _item_value(item, "conflict_fields", "conflictFields") or []
        if not isinstance(conflict_fields, list):
            conflict_fields = [conflict_fields]
        duplicate_group = _item_value(item, "duplicate_group", "duplicateGroup")
        if duplicate_group not in (None, ""):
            duplicate_group = str(duplicate_group)
        records.append({
            "source_index": source_index,
            "normalized_outcome_name": str(_item_value(item, "normalized_outcome_name", "normalizedOutcomeName", "outcome_name") or "NR"),
            "normalized_measurement_instrument": str(_item_value(item, "normalized_measurement_instrument", "normalizedMeasurementInstrument", "measurement_instrument", "instrument") or "NR"),
            "normalized_timepoint": str(_item_value(item, "normalized_timepoint", "normalizedTimepoint", "timepoint") or "NR"),
            "comparison_relation": str(_item_value(item, "comparison_relation", "comparisonRelation", "comparison") or "NR"),
            "duplicate_group": duplicate_group,
            "gold_row_ids": [str(value) for value in gold_ids if value not in (None, "")],
            "conflict_status": status,
            "annotation_status": status,
            "conflict_fields": [str(value) for value in conflict_fields if value not in (None, "")],
            "conflict_reason": str(_item_value(item, "conflict_reason", "conflictReason", "reason") or ""),
        })
    notes = raw.get("notes", [])
    if not isinstance(notes, list):
        notes = [notes]
    return {"records": records, "notes": [str(note) for note in notes if note not in (None, "")]} 


def _compact_postprocess_source(item: dict) -> dict:
    """Return the complete source record for annotation.

    The name is kept for compatibility with older callers, but no fields or
    arms are projected away.  Evidence and all numeric columns are required to
    make a source-first conflict decision.
    """

    return dict(item) if isinstance(item, dict) else {}


def _compact_postprocess_gold(rows: list[dict], max_chars: int = 220) -> list[dict]:
    """Return all Gold rows and columns; ``max_chars`` is compatibility-only."""

    del max_chars
    return [dict(row) for row in rows if isinstance(row, dict)]


def postprocess_outcomes_with_llm(
    client: OpenAICompatibleClient,
    outcomes: OutcomeExtraction,
    gold_rows: list[dict],
    source_context: str,
    raw_dir: Path,
    retries: int = 2,
    batch_size: int = 1,
    max_workers: int = 1,
    request_delay_seconds: float = 0.01,
) -> tuple[OutcomePostProcessing, list[dict]]:
    """Annotate extracted outcomes without replacing any source values.

    This is deliberately a post-extraction operation.  The gold rows are sent
    only to this comparator, never to the table-wise extraction requests.  Each
    output record contains a copy of the original ``OutcomeStatistic`` and a
    ``source_index``; conflicts are annotations, not corrections.  An
    evidence-only canonical dataset is built after annotation and does not
    read or apply gold values.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    batch_size = max(1, min(int(batch_size), 100))
    max_workers = max(1, min(int(max_workers), 8))
    skip_existing_errors = os.getenv("ARTICLE_AGENT_SKIP_EXISTING_POSTPROCESS_ERRORS", "0").strip().lower() in {
        "1", "true", "yes",
    }
    source_items = [item.model_dump(mode="json") for item in outcomes.outcomes]
    if not source_items:
        canonical_dataset = build_canonical_outcome_dataset([])
        result = OutcomePostProcessing(
            status="success",
            source_outcome_count=0,
            processed_outcome_count=0,
            conflict_count=0,
            duplicate_group_count=0,
            gold_comparison="provided" if gold_rows else "unavailable",
            gold_rows=gold_rows,
            records=[],
            gold_conflicts=[],
            canonical_dataset=canonical_dataset,
            notes=["没有可供后处理的结局记录；原始抽取结果保持为空。"],
        )
        return result, []

    # A repaired extraction is append-only: source indices that were already
    # annotated successfully in this same run remain valid even when new
    # narrative/table rows extend the dataset.  Build an index-level cache
    # rather than assuming that every run used the same batch size or part
    # numbering.  A different run_id is never reused, which prevents old
    # batch scores from leaking into a fresh evaluation.
    reusable_cache_records: dict[int, OutcomePostProcessDecision] = {}
    cache_disabled = os.getenv("ARTICLE_AGENT_DISABLE_POSTPROCESS_CACHE", "0").strip().lower() in {
        "1", "true", "yes",
    }
    current_run_id = str(os.getenv("ARTICLE_AGENT_RUN_ID") or "").strip()
    manifest_path = raw_dir / "outcomes.postprocess.manifest.json"
    prior_manifest = {}
    if not cache_disabled and manifest_path.exists():
        try:
            prior_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            prior_manifest = {}
        prior_run_id = str(prior_manifest.get("run_id") or "").strip() if isinstance(prior_manifest, dict) else ""
        if not current_run_id or not prior_run_id or prior_run_id != current_run_id:
            prior_manifest = {}
    if isinstance(prior_manifest, dict) and prior_manifest:
        for cache_path in sorted(raw_dir.glob("outcomes.postprocess.part-*.json")):
            try:
                raw_cache = json.loads(cache_path.read_text(encoding="utf-8"))
                normalized_cache = _normalize_postprocess_payload(raw_cache)
                batch_cache = OutcomePostProcessBatch.model_validate(normalized_cache)
            except (OSError, ValueError, TypeError):
                continue
            for decision in batch_cache.records:
                if 0 <= decision.source_index < len(source_items):
                    reusable_cache_records.setdefault(decision.source_index, decision)

    batches = [
        list(range(start, min(start + batch_size, len(source_items))))
        for start in range(0, len(source_items), batch_size)
    ]
    manifest = [
        {
            "part": part_index,
            "source_indices": indices,
            "row_count": len(indices),
            "cache": f"outcomes.postprocess.part-{part_index:03d}.json",
            "status": "pending",
        }
        for part_index, indices in enumerate(batches, start=1)
    ]

    def run_batch(item: tuple[int, list[int]]):
        part_index, indices = item
        cache_path = raw_dir / f"outcomes.postprocess.part-{part_index:03d}.json"
        existing_error = cache_path.with_suffix(".error.txt")
        if skip_existing_errors and existing_error.exists() and not cache_path.exists():
            return part_index, None, {
                "status": "failed_cached",
                "error": existing_error.read_text(encoding="utf-8", errors="replace"),
                "decision_count": 0,
                "cache_reused": True,
            }
        if not cache_disabled and reusable_cache_records and all(
            index in reusable_cache_records for index in indices
        ):
            # The current batch boundaries may differ from the historical
            # files.  Reuse only the exact source_index decisions and keep the
            # current manifest's part numbering deterministic.
            return part_index, [reusable_cache_records[index] for index in indices], {
                "status": "success",
                "decision_count": len(indices),
                "cache_reused": True,
                "cache_reused_by_source_index": True,
            }
        evidence_units: list[dict] = []
        evidence_index: dict[tuple[str, str], int] = {}
        for index in indices:
            source_item = source_items[index]
            table_key = str(source_item.get("table_id") or "NR")
            row_key = str(source_item.get("row_id") or "NR")
            context_unit = _source_evidence_unit(source_context, source_item)
            # A table can be shared by many rows in one postprocess shard.  A
            # single complete table unit plus its row mapping is lossless and
            # avoids duplicating the same 40-KB table eight times.
            unit_key = (table_key, context_unit)
            unit_index = evidence_index.get(unit_key)
            if unit_index is None:
                unit_index = len(evidence_units)
                evidence_index[unit_key] = unit_index
                evidence_units.append({
                    "unit_id": f"unit-{unit_index + 1:02d}",
                    "table_id": table_key,
                    "row_ids": [],
                    "source_indices": [],
                    "context": context_unit,
                })
            evidence_units[unit_index]["row_ids"].append(row_key)
            evidence_units[unit_index]["source_indices"].append(index)
        prompt = {
            "role_definition": OUTCOME_POSTPROCESS_PROMPT_SPEC["role_definition"],
            "task_description": OUTCOME_POSTPROCESS_PROMPT_SPEC["task_description"],
            "field_definitions": OUTCOME_POSTPROCESS_PROMPT_SPEC["field_boundaries"],
            "gold_reference_legend": OUTCOME_POSTPROCESS_PROMPT_SPEC["gold_reference_legend"],
            "json_template": OUTCOME_POSTPROCESS_PROMPT_SPEC["json_template"],
            "post_extraction_only": True,
            "lossless_input": True,
            "source_outcomes": [
                {"source_index": index, "outcome": _compact_postprocess_source(source_items[index])}
                for index in indices
            ],
            # Carry the complete source unit for each record, not the same
            # full Results document duplicated in every batch.  A table row
            # resolves to its complete table; a narrative row resolves to its
            # complete paragraph.  No characters are clipped or synthesized.
            "source_evidence_units": evidence_units,
            "source_evidence_units_rule": "Each unit is complete; source_indices/row_ids map the unit to records. Do not infer values from a different unit.",
            "gold_reference_rows": _compact_postprocess_gold(gold_rows),
        }
        valid_indices = set(indices)

        def validate_response(raw_response: dict | None):
            normalized = _normalize_postprocess_payload(raw_response)
            batch = OutcomePostProcessBatch.model_validate(normalized)
            decisions = [decision for decision in batch.records if decision.source_index in valid_indices]
            decision_indices = {decision.source_index for decision in decisions}
            if decision_indices != valid_indices:
                missing = sorted(valid_indices - decision_indices)
                raise ValueError(f"post-processing response omitted source_index values: {missing}")
            return batch, decisions

        raw = None
        disable_cache = os.getenv("ARTICLE_AGENT_DISABLE_POSTPROCESS_CACHE", "0").strip().lower() in {
            "1", "true", "yes",
        }
        if cache_path.exists() and not disable_cache:
            try:
                raw = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raw = None
        # A valid cache is reused; malformed/partial caches are ignored and
        # repaired by a fresh LLM request instead of permanently poisoning a
        # source index on subsequent runs.
        if raw is not None:
            try:
                normalized_cache = _normalize_postprocess_payload(raw)
                cached_indices = {item.get("source_index") for item in normalized_cache["records"]}
                # Cache files are keyed by part number for backwards
                # compatibility.  Reject a cache from a different batch
                # size/range instead of silently treating its decisions as
                # valid for unrelated source rows.
                if cached_indices != valid_indices:
                    raise ValueError("cached source_index set does not match this batch")
                batch, decisions = validate_response(raw)
                return part_index, decisions, {
                    "status": "success" if len(decisions) == len(indices) else "partial",
                    "decision_count": len(decisions),
                    "notes": batch.notes,
                    "cache_reused": True,
                }
            except (TypeError, ValueError):
                raw = None

        last_error = None
        for _ in range(retries + 1):
            raw = None
            try:
                _sleep_before_request(request_delay_seconds)
                raw = client.chat_json([
                    {"role": "system", "content": OUTCOME_POSTPROCESS_PROMPT_SPEC["role_definition"]},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ])
            except RuntimeError as exc:
                last_error = exc
                continue
            try:
                batch, decisions = validate_response(raw)
            except (TypeError, ValueError) as exc:
                last_error = RuntimeError(f"post-processing response validation failed: {exc}")
                continue
            cache_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            return part_index, decisions, {
                "status": "success" if len(decisions) == len(indices) else "partial",
                "decision_count": len(decisions),
                "notes": batch.notes,
            }
        # If a large post-processing shard repeatedly times out or omits an
        # index, retry the same source records one at a time.  This is a
        # lossless fallback: each request still carries the complete source
        # record, evidence, and Gold reference, and a missing index remains
        # explicitly unresolved rather than silently dropped.
        fail_fast_unavailable = os.getenv("ARTICLE_AGENT_POSTPROCESS_FAIL_FAST_ON_MODEL_UNAVAILABLE", "0").strip().lower() in {
            "1", "true", "yes",
        }
        fail_fast_timeout = os.getenv("ARTICLE_AGENT_POSTPROCESS_FAIL_FAST_ON_TIMEOUT", "0").strip().lower() in {
            "1", "true", "yes",
        }
        if fail_fast_unavailable and last_error and any(
            marker in str(last_error).lower()
            for marker in ("model_not_found", "no available channel", "all base urls")
        ):
            error = str(last_error)
            (raw_dir / f"outcomes.postprocess.part-{part_index:03d}.error.txt").write_text(error, encoding="utf-8")
            return part_index, None, {
                "status": "failed_model_unavailable",
                "error": error,
                "decision_count": 0,
                "fallback_mode": "deferred_retry",
            }
        if fail_fast_timeout and last_error and any(
            marker in str(last_error).lower()
            for marker in ("timed out", "timeout", "read operation timed out")
        ):
            error = str(last_error)
            (raw_dir / f"outcomes.postprocess.part-{part_index:03d}.error.txt").write_text(error, encoding="utf-8")
            return part_index, None, {
                "status": "failed_timeout",
                "error": error,
                "decision_count": 0,
                "fallback_mode": "deferred_retry",
            }

        fallback_decisions: list = []
        fallback_errors: list[str] = []
        for index in indices:
            one_prompt = dict(prompt)
            one_prompt["source_outcomes"] = [{
                "source_index": index,
                "outcome": _compact_postprocess_source(source_items[index]),
            }]
            one_prompt["fallback_mode"] = "one_source_index_after_shard_failure"
            one_decision = None
            for _ in range(max(1, retries + 1)):
                try:
                    _sleep_before_request(request_delay_seconds)
                    one_raw = client.chat_json([
                        {"role": "system", "content": OUTCOME_POSTPROCESS_PROMPT_SPEC["role_definition"]},
                        {"role": "user", "content": json.dumps(one_prompt, ensure_ascii=False)},
                    ])
                    one_batch, one_records = validate_response(one_raw)
                    if one_records:
                        one_decision = one_records[0]
                        break
                except (RuntimeError, TypeError, ValueError) as exc:
                    fallback_errors.append(f"source_index={index}: {exc}")
            if one_decision is not None:
                fallback_decisions.append(one_decision)
        if len(fallback_decisions) == len(indices):
            combined = {"records": [decision.model_dump(mode="json") for decision in fallback_decisions], "notes": [
                "large postprocess shard failed; all source_index values recovered by one-record fallback",
            ]}
            cache_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
            return part_index, fallback_decisions, {
                "status": "success",
                "decision_count": len(fallback_decisions),
                "fallback_mode": "one_source_index",
                "notes": combined["notes"],
            }
        error = str(last_error or "unknown post-processing error")
        if fallback_errors:
            error += " | fallback: " + " ; ".join(fallback_errors[-4:])
        (raw_dir / f"outcomes.postprocess.part-{part_index:03d}.error.txt").write_text(error, encoding="utf-8")
        return part_index, None, {"status": "failed", "error": error, "decision_count": 0}

    decisions_by_index = {}
    batch_notes: list[str] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(run_batch, (part_index, indices)) for part_index, indices in enumerate(batches, start=1)]
        for future in as_completed(futures):
            part_index, decisions, result = future.result()
            manifest[part_index - 1].update(result)
            if decisions:
                for decision in decisions:
                    decisions_by_index.setdefault(decision.source_index, decision)
            batch_notes.extend(result.get("notes", []))

    records: list[OutcomePostProcessRecord] = []
    for index, outcome in enumerate(outcomes.outcomes):
        decision = decisions_by_index.get(index)
        if decision is None:
            missing_status = "unresolved" if gold_rows else "not_checked"
            records.append(OutcomePostProcessRecord(
                source_index=index,
                source_outcome=outcome,
                normalized_outcome_name="NR",
                normalized_measurement_instrument="NR",
                normalized_timepoint="NR",
                comparison_relation="NR",
                conflict_status=missing_status,
                annotation_status=missing_status,
                conflict_reason=(
                    "LLM 后处理未返回该 source_index；原始结局记录保留且未被修改。"
                    if gold_rows else
                    "未提供金标准且 LLM 后处理未返回该 source_index；原始结局记录保留且未被修改。"
                ),
                processing_status="not_processed",
                value_preserved=True,
            ))
            continue
        decision_status = decision.conflict_status
        decision_reason = decision.conflict_reason
        if gold_rows and decision_status == "not_checked":
            decision_status = "unresolved"
            decision_reason = (
                f"LLM 返回 not_checked，但本次提供了金标准；改标为 unresolved，需人工回查。"
                + (f" {decision_reason}" if decision_reason else "")
            )
        elif not gold_rows and decision_status != "not_checked":
            decision_status = "not_checked"
            decision_reason = (
                f"本次未提供金标准，忽略 LLM 的 {decision.conflict_status} 判断。"
                + (f" {decision_reason}" if decision_reason else "")
            )
        records.append(OutcomePostProcessRecord(
            source_index=index,
            source_outcome=outcome,
            normalized_outcome_name=decision.normalized_outcome_name,
            normalized_measurement_instrument=decision.normalized_measurement_instrument,
            normalized_timepoint=decision.normalized_timepoint,
            comparison_relation=decision.comparison_relation,
            duplicate_group=decision.duplicate_group,
            gold_row_ids=decision.gold_row_ids,
            conflict_status=decision_status,
            annotation_status=decision_status,
            conflict_fields=decision.conflict_fields,
            conflict_reason=decision_reason,
            processing_status="processed",
            value_preserved=True,
        ))

    gold_ids = []
    gold_id_aliases: dict[str, str] = {}
    for index, row in enumerate(gold_rows, start=1):
        gold_id = str(row.get("gold_row_id") or row.get("column_1") or f"gold-row-{index:03d}")
        gold_ids.append((gold_id, row))
        # Models occasionally return the human-facing article ID (column_1)
        # or STUDYID instead of the stable row ID.  Treat these as aliases
        # for matching only; the record still preserves the model annotation.
        for alias_key in ("gold_row_id", "column_1", "STUDYID"):
            alias = row.get(alias_key)
            if alias not in (None, ""):
                gold_id_aliases[str(alias)] = gold_id
    matched_ids = {
        gold_id_aliases.get(str(gold_id), str(gold_id))
        for record in records
        for gold_id in record.gold_row_ids
    }
    gold_conflicts: list[GoldOutcomeConflict] = []
    all_batches_succeeded = all(item.get("status") == "success" for item in manifest)
    for gold_id, row in gold_ids:
        if gold_id in matched_ids:
            continue
        gold_conflicts.append(GoldOutcomeConflict(
            gold_row_id=gold_id,
            conflict_status="conflict" if all_batches_succeeded else "unresolved",
            source_indices=[],
            conflict_fields=["record_missing"],
            reason=(
                "没有候选记录被 LLM 明确匹配到该金标准行；保留金标准行并标记为冲突，需人工回查。"
                if all_batches_succeeded else
                "后处理分片未全部完成，暂不能判断该金标准行是否缺失；原始候选记录保留。"
            ),
        ))

    duplicate_groups = {
        record.duplicate_group
        for record in records
        if record.duplicate_group
    }
    successful_parts = sum(item.get("status") == "success" for item in manifest)
    status = "success" if successful_parts == len(manifest) else "partial" if successful_parts else "failed"
    notes = [
        "后处理只增加规范化和冲突标记；source_outcome 保存原始抽取值，value_preserved=true。",
        "金标准仅在抽取完成后用于比较，不参与逐表逐行抽取请求。",
        *[note for note in batch_notes if note],
    ]
    canonical_dataset = build_canonical_outcome_dataset(records)
    group_by_source = {
        source_index: group.conflict_group_id
        for group in canonical_dataset.conflict_groups
        for source_index in group.source_indices
    }
    if group_by_source:
        records = [record.model_copy(update={"conflict_group_id": group_by_source.get(record.source_index)}) for record in records]
        # Rebuild after adding the per-record group annotation; source values
        # remain unchanged and the identity grouping is deterministic.
        canonical_dataset = build_canonical_outcome_dataset(records)
    result = OutcomePostProcessing(
        status=status,
        source_outcome_count=len(outcomes.outcomes),
        processed_outcome_count=sum(record.processing_status == "processed" for record in records),
        conflict_count=sum(record.conflict_status == "conflict" for record in records) + len(gold_conflicts),
        duplicate_group_count=len(duplicate_groups),
        gold_comparison="provided" if gold_rows else "unavailable",
        gold_rows=gold_rows,
        records=records,
        gold_conflicts=gold_conflicts,
        canonical_dataset=canonical_dataset,
        notes=notes,
    )
    return result, manifest
