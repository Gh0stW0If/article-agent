import json, pytest
from article_agent.evaluation.registry import load_registry, EvaluatorRegistryV3
from article_agent.evaluation.registry_audit import audit
def test_registry_contract():
    r=load_registry(); assert r.registry_version=="EVALUATOR_FIELD_REGISTRY/3.0.0"; assert len(r.fields)>=70
    assert set(r.entities)=={"Article","Study","Arm","Intervention","Outcome","ArmResult","Comparison","ComparisonResult"}
def test_registry_ids_unique(): assert len({f.field_id for f in load_registry().fields})==len(load_registry().fields)
def test_registry_audit_clean():
    a=audit()
    assert a["ok"]
    assert a["total_canonical_fields"] == a["registered_fields"] == 73
    for key in ("unregistered_fields", "invalid_field_paths", "value_type_mismatches",
                "comparator_type_mismatches", "hard_but_not_supported",
                "hard_without_comparator", "missing_entity_identity_rule"):
        assert not a[key]
    assert a["support_counts"] == {"SUPPORTED":24,"PARTIAL":49,"UNSUPPORTED":0}
    assert a["tier_counts"] == {"HARD":24,"SOFT":49,"AUDIT":0}
def test_hard_requires_supported_and_comparator():
    data=load_registry().model_dump(); data["fields"][0]["evaluation_tier"]="HARD";data["fields"][0]["support_status"]="PARTIAL"
    with pytest.raises(ValueError): EvaluatorRegistryV3.model_validate(data)


@pytest.mark.parametrize("field_id, comparator", [
    ("article.journal", "NORMALIZED_NUMERIC"),
    ("outcome.scale_min", "NORMALIZED_STRING"),
    ("article.authors", "NORMALIZED_STRING"),
    ("study.random_sequence_code", "ORDERED_LIST"),
    ("article.journal", "STATUS_ONLY"),
    ("article.journal", "EVIDENCE_GROUNDED"),
])
def test_incompatible_comparator_fails_audit(tmp_path, field_id, comparator):
    data=load_registry().model_dump()
    field=next(f for f in data["fields"] if f["field_id"]==field_id)
    field["comparator"]={"type":comparator}
    path=tmp_path/"registry.json"
    path.write_text(json.dumps(data),encoding="utf-8")
    result=audit(path)
    assert not result["ok"]
    assert [x["field_id"] for x in result["comparator_type_mismatches"]] == [field_id]


@pytest.mark.parametrize("field_id, comparator", [
    ("article.journal", "NORMALIZED_STRING"),
    ("article.journal", "EXACT_VALUE"),
    ("article.language", "SEMANTIC_CODE"),
    ("study.random_sequence_code", "SEMANTIC_CODE"),
    ("outcome.scale_min", "NORMALIZED_NUMERIC"),
    ("outcome.scale_min", "EXACT_VALUE"),
    ("article.authors", "ORDERED_LIST"),
    ("article.correspondence", "UNORDERED_LIST"),
    ("study.countries", "SET_EQUALITY"),
])
def test_compatible_comparator_passes_audit(tmp_path, field_id, comparator):
    data=load_registry().model_dump()
    next(f for f in data["fields"] if f["field_id"]==field_id)["comparator"]={"type":comparator}
    path=tmp_path/"registry.json"
    path.write_text(json.dumps(data),encoding="utf-8")
    assert audit(path)["ok"]


def test_semantic_comparator_choices():
    fields={f.field_id:f for f in load_registry().fields}
    expected={
        "article.authors":"ORDERED_LIST",  # Author order is meaningful.
        "study.countries":"SET_EQUALITY",  # Country membership, not order/count.
        "article.correspondence":"UNORDERED_LIST",  # Preserve repeated entries.
        "intervention.components":"UNORDERED_LIST",  # Not treatment sequence.
        "study.random_sequence_code":"EXACT_VALUE",  # Codes have no tolerance.
        "study.allocation_concealment_code":"EXACT_VALUE",
    }
    for field_id, comparator in expected.items():
        assert fields[field_id].comparator["type"] == comparator


def test_domain_type_cannot_be_hidden_by_registry_type(tmp_path):
    data=load_registry().model_dump()
    field=next(f for f in data["fields"] if f["field_id"]=="article.journal")
    field.update(value_type="number",comparator={"type":"NORMALIZED_NUMERIC"})
    path=tmp_path/"registry.json"
    path.write_text(json.dumps(data),encoding="utf-8")
    result=audit(path)
    assert not result["ok"]
    assert result["value_type_mismatches"]
    assert result["comparator_type_mismatches"]


def test_audit_cli_exits_nonzero_on_mismatch(tmp_path, monkeypatch):
    from article_agent.evaluation import registry_audit
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(registry_audit,"audit",lambda:{"ok":False})
    assert registry_audit.main() == 1


def test_missing_entity_identity_rule_fails_audit_and_cli(tmp_path):
    import subprocess
    import sys

    data = load_registry().model_dump()
    del data["entities"]["Outcome"]
    schema_dir = tmp_path / "schemas"
    schema_dir.mkdir()
    path = schema_dir / "evaluator-field-registry-v3.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    result = audit(path)
    assert result["missing_entity_identity_rule"] == ["Outcome"]
    assert result["ok"] is False
    completed = subprocess.run(
        [sys.executable, "-m", "article_agent.evaluation.registry_audit"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert completed.returncode == 1, completed.stderr
    assert json.loads(completed.stdout) == result


@pytest.mark.parametrize("defect", ["duplicate_field_ids", "hard_but_not_supported", "hard_without_comparator"])
def test_ok_includes_diagnostics_normally_rejected_by_loader(monkeypatch, defect):
    from article_agent.evaluation import registry_audit

    registry = load_registry().model_copy(deep=True)
    # Isolate aggregation: production loading rejects these malformed models.
    if defect == "duplicate_field_ids":
        registry.fields.append(registry.fields[0].model_copy())
    else:
        field = next(f for f in registry.fields if f.evaluation_tier == "HARD")
        if defect == "hard_but_not_supported":
            field.support_status = "PARTIAL"
        else:
            field.comparator = None
    monkeypatch.setattr(registry_audit, "load_registry", lambda path: registry)
    result = registry_audit.audit()
    assert result[defect]
    assert result["ok"] is False
