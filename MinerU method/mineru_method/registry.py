from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel


def load_bindings(project_root: Path) -> dict[str, list[dict]]:
    bindings: dict[str, list[dict]] = {}
    for sheet in ("sheet1", "sheet2", "sheet3"):
        path = project_root / "registry" / "legacy-excel" / f"{sheet}-mapping.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        bindings[sheet] = data["columns"]
    return bindings


def canonical_ids(bindings: dict[str, list[dict]]) -> set[str]:
    return {
        item["canonicalFieldId"]
        for columns in bindings.values()
        for item in columns
        if item.get("canonicalFieldId")
    }


def model_field_ids(models: Iterable[type[BaseModel]]) -> set[str]:
    ignored = {
        "evidence", "outcomes", "statistic_type", "intervention_estimate",
        "intervention_variance_lower", "intervention_variance_upper", "intervention_n",
        "control_estimate", "control_variance_lower", "control_variance_upper", "control_n",
        "between_group_measure", "effect_size_name",
        "analysis_population", "outcome_p_value_comparator",
        "control_type_components", "practitioner_experience_raw", "practitioner_experience_comparator",
        # Outcome provenance/identity fields are not legacy Excel columns; they
        # are retained in the evidence and canonical JSON layers.
        "table_id", "row_id", "arm", "comparison", "analysis_set", "record_role",
        "source_values", "source_evidence", "source_cells", "p_value_cells",
        "derived", "derivation", "conflict_group_id",
    }
    return {name for model in models for name in model.model_fields if name not in ignored}


def relevant_bindings(bindings: dict[str, list[dict]], ids: set[str]) -> list[dict]:
    result: list[dict] = []
    for sheet, columns in bindings.items():
        for item in columns:
            if item.get("canonicalFieldId") in ids:
                result.append({"sheet": sheet.capitalize(), **item})
    return result
