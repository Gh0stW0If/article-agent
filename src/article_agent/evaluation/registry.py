from __future__ import annotations
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator

COMPARATORS={"EXACT_VALUE","NORMALIZED_STRING","NORMALIZED_NUMERIC","SET_EQUALITY","ORDERED_LIST","UNORDERED_LIST","SEMANTIC_CODE","STATUS_ONLY","EVIDENCE_GROUNDED"}
SUPPORT={"SUPPORTED","PARTIAL","UNSUPPORTED"}; TIERS={"HARD","SOFT","AUDIT"}
class EntityRule(BaseModel):
    model_config=ConfigDict(extra="forbid")
    identity: str
    fallback: list[str]=Field(default_factory=list)
    forbidden: list[str]=Field(default_factory=list)
class RegistryField(BaseModel):
    model_config=ConfigDict(extra="forbid")
    field_id: str; entity_type: str; field_path: str; value_type: str
    support_status: str; evaluation_tier: str; required: bool=False
    comparator: dict|None=None; normalization: list[str]=Field(default_factory=list)
    gold_allowed_statuses: list[str]; runtime_allowed_statuses: list[str]
    evidence_policy: str; missingness_policy: str; source_conflict_policy: str
    notes: str|None=None; enabled: bool=True
    @model_validator(mode="after")
    def check(self):
        if self.support_status not in SUPPORT or self.evaluation_tier not in TIERS: raise ValueError("invalid registry enum")
        if self.comparator and self.comparator.get("type") not in COMPARATORS: raise ValueError("invalid comparator")
        if self.evaluation_tier=="HARD" and (self.support_status!="SUPPORTED" or not self.comparator): raise ValueError("HARD requires supported comparator")
        return self
class EvaluatorRegistryV3(BaseModel):
    model_config=ConfigDict(extra="forbid")
    registry_version: str; article_schema_version: str
    entities: dict[str,EntityRule]; fields: list[RegistryField]
    @model_validator(mode="after")
    def unique(self):
        if len({x.field_id for x in self.fields}) != len(self.fields): raise ValueError("duplicate field_id")
        return self
def load_registry(path: Path|str="schemas/evaluator-field-registry-v3.json"):
    return EvaluatorRegistryV3.model_validate_json(Path(path).read_text(encoding="utf-8"))
