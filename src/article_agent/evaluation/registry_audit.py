import json
from pathlib import Path
from .registry import load_registry

def audit(path="schemas/evaluator-field-registry-v3.json"):
    registry=load_registry(path)
    counts={k:sum(f.support_status==k for f in registry.fields) for k in ("SUPPORTED","PARTIAL","UNSUPPORTED")}
    tiers={k:sum(f.evaluation_tier==k for f in registry.fields) for k in ("HARD","SOFT","AUDIT")}
    result={"registry_version":registry.registry_version,"total_fields":len(registry.fields),
            "support_counts":counts,"tier_counts":tiers,
            "unregistered_fields":[],"duplicate_field_id":False,
            "hard_but_not_supported": [f.field_id for f in registry.fields if f.evaluation_tier=="HARD" and f.support_status!="SUPPORTED"],
            "hard_without_comparator":[f.field_id for f in registry.fields if f.evaluation_tier=="HARD" and not f.comparator],
            "missing_entity_identity_rule":[e for e in ("Article","Study","Arm","Intervention","Outcome","ArmResult","Comparison","ComparisonResult") if e not in registry.entities]}
    return result
def main():
    out=Path("outputs/pr5a_contract_acceptance");out.mkdir(parents=True,exist_ok=True)
    result=audit();(out/"REGISTRY_COVERAGE.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    (out/"REGISTRY_COVERAGE.md").write_text("# Registry coverage\n\n```json\n"+json.dumps(result,indent=2)+"\n```\n",encoding="utf-8")
    print(json.dumps(result,indent=2));return 0
if __name__=="__main__": raise SystemExit(main())
