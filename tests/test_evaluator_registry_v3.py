import json, pytest
from article_agent.evaluation.registry import load_registry, EvaluatorRegistryV3
from article_agent.evaluation.registry_audit import audit
def test_registry_contract():
    r=load_registry(); assert r.registry_version=="EVALUATOR_FIELD_REGISTRY/3.0.0"; assert len(r.fields)>=70
    assert set(r.entities)=={"Article","Study","Arm","Intervention","Outcome","ArmResult","Comparison","ComparisonResult"}
def test_registry_ids_unique(): assert len({f.field_id for f in load_registry().fields})==len(load_registry().fields)
def test_registry_audit_clean():
    a=audit(); assert not a["hard_but_not_supported"]; assert not a["hard_without_comparator"]; assert not a["missing_entity_identity_rule"]
def test_hard_requires_supported_and_comparator():
    data=load_registry().model_dump(); data["fields"][0]["evaluation_tier"]="HARD";data["fields"][0]["support_status"]="PARTIAL"
    with pytest.raises(ValueError): EvaluatorRegistryV3.model_validate(data)
