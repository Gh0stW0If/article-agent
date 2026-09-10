import json
from pathlib import Path
from typing import get_args, get_origin
from .registry import load_registry
from ..domain.models import Article, Study, Arm, Intervention, Outcome, ArmResult, Comparison, ComparisonResult, CanonicalField

ENTITIES={"Article":Article,"Study":Study,"Arm":Arm,"Intervention":Intervention,"Outcome":Outcome,"ArmResult":ArmResult,"Comparison":Comparison,"ComparisonResult":ComparisonResult}
def _canonical_fields():
    out={}
    for entity, model in ENTITIES.items():
        for name, field in model.model_fields.items():
            if (get_origin(field.annotation) is CanonicalField or (isinstance(field.annotation,type) and issubclass(field.annotation, CanonicalField))):
                meta=getattr(field.annotation,"__pydantic_generic_metadata__",{})
                inner=(meta.get("args") or get_args(field.annotation) or (object,))[0]
                typ="string" if inner is str else "integer" if inner is int else "number" if inner is float else "list[string]" if get_origin(inner) is list else "code"
                out[f"{entity[0].lower()+entity[1:]}.{name}"]=(typ,name)
    return out
def audit(path="schemas/evaluator-field-registry-v3.json"):
    registry=load_registry(path); canonical=_canonical_fields(); entries={f.field_id:f for f in registry.fields}
    registered=set(entries)&set(canonical); disabled={f.field_id for f in registry.fields if not f.enabled}; unregistered=sorted(set(canonical)-registered-disabled)
    invalid=[]; mismatches=[]; comp=[]
    for f in registry.fields:
        expected=canonical.get(f.field_id)
        if expected:
            if f.value_type!=expected[0]: mismatches.append({"field_id":f.field_id,"expected":expected[0],"actual":f.value_type})
            if f.field_path.split(".")[-1]!=expected[1]: invalid.append(f.field_id)
            if f.enabled and f.comparator is None: comp.append(f.field_id)
        elif f.enabled: invalid.append(f.field_id)
    counts={k:sum(f.support_status==k for f in registry.fields) for k in ("SUPPORTED","PARTIAL","UNSUPPORTED")}
    tiers={k:sum(f.evaluation_tier==k for f in registry.fields) for k in ("HARD","SOFT","AUDIT")}
    return {"registry_version":registry.registry_version,"total_fields":len(registry.fields),"total_canonical_fields":len(canonical),"registered_fields":len(registered),"explicitly_disabled_fields":sorted(disabled),"unregistered_fields":unregistered,"invalid_field_paths":invalid,"value_type_mismatches":mismatches,"comparator_type_mismatches":comp,"duplicate_field_ids":len(entries)!=len(registry.fields),"support_counts":counts,"tier_counts":tiers,"hard_but_not_supported":[f.field_id for f in registry.fields if f.evaluation_tier=="HARD" and f.support_status!="SUPPORTED"],"hard_without_comparator":[f.field_id for f in registry.fields if f.evaluation_tier=="HARD" and not f.comparator],"missing_entity_identity_rule":[e for e in ENTITIES if e not in registry.entities],"ok":not(unregistered or invalid or mismatches or comp)}
def main():
    result=audit(); out=Path("outputs/pr5a_contract_acceptance"); out.mkdir(parents=True,exist_ok=True); (out/"REGISTRY_COVERAGE.json").write_text(json.dumps(result,indent=2),encoding="utf-8"); print(json.dumps(result,indent=2)); return 0
if __name__=="__main__": raise SystemExit(main())
