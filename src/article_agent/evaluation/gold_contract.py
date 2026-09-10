from __future__ import annotations
import argparse, json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..domain.models import ArticleExtraction, CanonicalField, Evidence, FieldStatus

GOLD_STATUSES = {FieldStatus.PRESENT, FieldStatus.NOT_REPORTED, FieldStatus.NOT_APPLICABLE,
                 FieldStatus.SOURCE_CONFLICT, FieldStatus.REVIEW_REQUIRED}

class SourceDocument(BaseModel):
    model_config=ConfigDict(extra="forbid")
    source_id: str
    sha256: str|None=None
    role: str
class SourceLineage(BaseModel):
    model_config=ConfigDict(extra="forbid")
    documents: list[SourceDocument]
class MissingnessAssessment(BaseModel):
    model_config=ConfigDict(extra="forbid")
    entity_type: str; entity_id: str; field_id: str
    status: Literal["NOT_REPORTED","NOT_APPLICABLE"]
    coverage_complete: bool = False
    covered_sources: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
class EntityMatchAlias(BaseModel):
    model_config=ConfigDict(extra="forbid")
    entity_type: str; entity_id: str
    accepted_values: dict[str,list[str]] = Field(default_factory=dict)
    note: str = Field(min_length=1)
class GoldStandardV2(BaseModel):
    model_config=ConfigDict(extra="forbid")
    gold_version: Literal["GOLD_STANDARD/2.0.0"]
    article_schema_version: Literal["ARTICLE_EXTRACTION/2.0"]
    gold_id: str; article_id: str
    state: Literal["DRAFT","FROZEN"]
    source_lineage: SourceLineage
    truth: ArticleExtraction
    entity_aliases: list[EntityMatchAlias] = Field(default_factory=list)
    missingness_assessments: list[MissingnessAssessment] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    @model_validator(mode="after")
    def validate_gold(self):
        if self.truth.article.article_id != self.article_id: raise ValueError("Gold/article_id mismatch")
        evidence_by_id={e.evidence_id:e for e in self.truth.evidence}
        fields=[]
        for typ, items in (("Article",[self.truth.article]),("Study",self.truth.studies),("Intervention",self.truth.interventions),("Arm",self.truth.arms),("Outcome",self.truth.outcomes),("ArmResult",self.truth.arm_results),("Comparison",self.truth.comparisons),("ComparisonResult",self.truth.comparison_results)):
            for item in items:
                entity_id=getattr(item, {"Article":"article_id","Study":"study_id","Intervention":"intervention_id","Arm":"arm_id","Outcome":"outcome_id","ArmResult":"arm_result_id","Comparison":"comparison_id","ComparisonResult":"comparison_result_id"}[typ])
                for field,value in item:
                    if isinstance(value,CanonicalField):
                        if value.status not in GOLD_STATUSES: raise ValueError(f"runtime-only Gold status: {typ}.{field}")
                        if value.status==FieldStatus.NOT_REPORTED:
                            ma=[x for x in self.missingness_assessments if (x.entity_type,x.entity_id,x.field_id)==(typ,entity_id,field)]
                            if not ma or not ma[0].coverage_complete: raise ValueError(f"NOT_REPORTED needs complete assessment: {typ}.{field}")
                        if value.status==FieldStatus.SOURCE_CONFLICT and len(value.conflict_candidates)<2: raise ValueError("invalid Gold conflict")
                        for eid in value.evidence_ids+[x for c in value.conflict_candidates for x in c.evidence_ids]:
                            evidence=evidence_by_id.get(eid)
                            if evidence is None:
                                raise ValueError(f"referenced evidence does not exist: {eid}")
                            if not any(t.entity_type==typ and t.entity_id==entity_id and t.field_id==field for t in evidence.targets):
                                raise ValueError(f"missing reciprocal evidence target for {eid}")
        known={t.entity_id for e in self.truth.evidence for t in e.targets}
        entities={getattr(x, idf) for items,idf in (([self.truth.article],"article_id"),(self.truth.studies,"study_id"),(self.truth.interventions,"intervention_id"),(self.truth.arms,"arm_id"),(self.truth.outcomes,"outcome_id"),(self.truth.arm_results,"arm_result_id"),(self.truth.comparisons,"comparison_id"),(self.truth.comparison_results,"comparison_result_id")) for x in items}
        for alias in self.entity_aliases:
            if alias.entity_id not in entities: raise ValueError("alias target does not exist")
        return self

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("gold"); a=p.parse_args(argv)
    GoldStandardV2.model_validate_json(open(a.gold,encoding="utf-8").read()); print("valid GOLD_STANDARD/2.0.0"); return 0
if __name__=="__main__": raise SystemExit(main())
