"""Semantic overlay: an exact whitelist, never edits Registry V3 assignments."""
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .models import HybridModel

WHITELIST = frozenset("""
study.design study.condition study.random_sequence_method study.allocation_concealment
study.participant_blinding study.practitioner_blinding study.outcome_assessor_blinding
study.statistician_blinding study.primary_analysis_set study.missing_data_method
intervention.name intervention.kind intervention.description intervention.components
intervention.frequency_raw intervention.duration_raw arm.label arm.role
outcome.name outcome.instrument outcome.role outcome.direction
armResult.timepoint armResult.analysis_set armResult.value_kind
comparison.relation comparison.contrast comparisonResult.timepoint
comparisonResult.analysis_set comparisonResult.effect_measure
""".split())


class SemanticFieldSpec(HybridModel):
    field_id: str
    mode: Literal["SEMANTIC"] = "SEMANTIC"
    definition: str = Field(min_length=1)
    judge_focus: list[str] = Field(min_length=1)
    identity_role: bool


class SemanticRegistryV1(HybridModel):
    registry_version: Literal["HYBRID_SEMANTIC_REGISTRY/1.0.0"]
    fields: list[SemanticFieldSpec]

    @model_validator(mode="after")
    def frozen_scope(self):
        ids = [f.field_id for f in self.fields]
        if len(ids) != len(set(ids)) or set(ids) != WHITELIST:
            raise ValueError("Semantic V1 must contain exactly the frozen whitelist")
        return self

    def by_id(self):
        return {field.field_id: field for field in self.fields}


def load_semantic_registry(path="schemas/hybrid-semantic-registry-v1.json"):
    return SemanticRegistryV1.model_validate_json(Path(path).read_text(encoding="utf-8"))
