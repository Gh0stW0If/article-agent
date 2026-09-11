import hashlib
import json
import re
from pathlib import Path
from article_agent.evaluation import GoldStandardV2, evaluate_article
from article_agent.evaluation.registry import load_registry

ROOT=Path(__file__).resolve().parents[1]
GOLD=ROOT/"gold/2015-06/gold.json"

def load_gold():
    return GoldStandardV2.model_validate_json(GOLD.read_text(encoding="utf-8"))

def test_real_gold_topology_and_no_pseudo_articles():
    g=load_gold(); t=g.truth
    assert g.state=="DRAFT" and g.article_id=="2015-06"
    assert len(t.studies)==1 and len(t.arms)==3 and len(t.interventions)==3 and len(t.outcomes)==4
    assert all("2015-06-0" not in x for x in [a.arm_id for a in t.arms]+[o.outcome_id for o in t.outcomes])

def test_real_gold_conflicts_and_evidence():
    g=load_gold(); t=g.truth
    assert t.arms[0].randomized_n.value==35
    for arm in t.arms[1:]:
        assert arm.randomized_n.status.value=="SOURCE_CONFLICT"
        assert {c.value for c in arm.randomized_n.conflict_candidates}=={34,38}
        assert all(c.evidence_ids for c in arm.randomized_n.conflict_candidates)
    assert len(t.evidence)>0

def test_real_gold_outcomes_comparisons_and_p_mapping():
    g=load_gold(); t=g.truth
    assert [o.name.value for o in t.outcomes]==["Bladder balance","CIC frequency","Residual urine volume","Voided volume"]
    assert [c.arm_ids for c in t.comparisons]==[
        ["2015-06-S1-A01","2015-06-S1-A02"],["2015-06-S1-A01","2015-06-S1-A03"],["2015-06-S1-A02","2015-06-S1-A03"]]
    assert len(t.arm_results)>=21 and len(t.comparison_results)==18
    values=[r.p_value.value for r in t.comparison_results]
    assert 0.019 in values and 0.001 in values

def test_missingness_and_runtime_statuses():
    g=load_gold(); t=g.truth
    assert all(x.status.value not in {"UNRESOLVED","INSUFFICIENT_CONTEXT"}
               for group in ([t.article],t.studies,t.arms,t.interventions,t.outcomes,t.arm_results,t.comparisons,t.comparison_results)
               for item in group for _,x in item if hasattr(x,"status"))
    assert all(m.coverage_complete for m in g.missingness_assessments)
    assert len(g.missingness_assessments)>0

def test_self_evaluation_and_determinism(tmp_path):
    g=load_gold(); report=evaluate_article(g.truth,g,load_registry())
    assert report.metrics["hard_exact"]["rate"]==1.0
    assert report.metrics["production_coverage"]["rate"]==1.0
    assert report.metrics["supported_value_accuracy"]["rate"]==1.0
    assert report.metrics["conflicts"]["conflict_detection_rate"]["rate"]==1.0
    import runpy
    runpy.run_path(str(ROOT/"scripts/pr5c1_2015_06_acceptance.py"),run_name="__main__")
    out=ROOT/"outputs/pr5c1_2015_06"
    first=(out/"SUMMARY.json").read_bytes(),(out/"REPORT.md").read_bytes()
    runpy.run_path(str(ROOT/"scripts/pr5c1_2015_06_acceptance.py"),run_name="__main__")
    assert first==((out/"SUMMARY.json").read_bytes(),(out/"REPORT.md").read_bytes())

def test_all_table2_cells_and_baseline():
    t=load_gold().truth
    expected=[
        ["21 (60.0)","29 (85.29)","23 (60.5)"],
        ["1.7±0.14","0.35±0.07","1.35±0.21"],
        ["301.0±8.48","213.0±9.19","295.0±9.89"],
        ["271.5±12.06","375.5±10.06","276.5±9.09"],
        ["193.5±10.6","113.5±12.02","176.5±9.19"],
        ["360.0±14.14","471.0±10.4","382.5±10.2"],
    ]
    for row,values in enumerate(expected):
        for column,raw in enumerate(values):
            r=t.arm_results[row*3+column]
            assert r.arm_id==f"2015-06-S1-A{column+1:02}"
            assert r.source_table_id=="Table 2"
            assert r.raw_value.value==raw
            if row==0:
                assert r.event_count.value==int(raw.split()[0])
                assert r.denominator.status.value=="PRESENT"
                assert r.denominator.value==(35,34,38)[column]
            else:
                mean,sd=map(float,raw.split("±"))
                assert (r.value.value,r.standard_deviation.value)==(mean,sd)
    for r,raw in zip(t.arm_results[18:],["566.0±8.9","591.0±9.4","575.0±10.5"]):
        assert r.source_table_id=="Table 1" and r.timepoint.value=="baseline"
        assert r.outcome_id=="2015-06-S1-O03" and r.raw_value.value==raw

def test_source_hashes_when_local_sources_available():
    g=load_gold()
    sources=[ROOT/"datas/articles/2015/-2015-06.pdf",ROOT/"datas/label/2015-6篇.xlsx"]
    for document,path in zip(g.source_lineage.documents,sources):
        assert len(document.sha256)==64
        if path.exists():
            assert document.sha256==hashlib.sha256(path.read_bytes()).hexdigest()

def test_real_gold_rejects_missing_candidate_evidence_in_acceptance(monkeypatch):
    import runpy
    import pytest
    module=runpy.run_path(str(ROOT/"scripts/pr5c1_2015_06_acceptance.py"))
    g=load_gold()
    field=g.truth.arms[1].randomized_n
    # Simulate a structurally constructible omission: remove references and targets.
    removed=set(field.conflict_candidates[0].evidence_ids)
    field.conflict_candidates[0].evidence_ids=[]
    field.evidence_ids=[e for e in field.evidence_ids if e not in removed]
    g.truth.evidence=[e for e in g.truth.evidence if e.evidence_id not in removed]
    monkeypatch.setattr(GoldStandardV2,"model_validate_json",classmethod(lambda cls,text:g))
    with pytest.raises(AssertionError):
        module["validate"]()


def test_human_review_absences_have_complete_individual_assessments():
    g = load_gold()
    t = g.truth
    targets = [("Study", t.studies[0].study_id, t.studies[0], field) for field in (
        "practitioner_blinding", "outcome_assessor_blinding", "statistician_blinding")]
    targets += [("Intervention", i.intervention_id, i, "total_sessions")
                for i in t.interventions if i.intervention_id.endswith(("-I02", "-I03"))]
    for kind, results, id_field in (("ArmResult", t.arm_results, "arm_result_id"),
                                   ("ComparisonResult", t.comparison_results, "comparison_result_id")):
        bladder_results = [r for r in results if r.outcome_id == "2015-06-S1-O01"]
        assert len(bladder_results) == 3
        targets += [(kind, getattr(r, id_field), r, field) for r in bladder_results
                    for field in ("timepoint", "timepoint_value", "timepoint_unit")]
    assert len(targets) == 23
    assessments = {(m.entity_type, m.entity_id, m.field_id): m for m in g.missingness_assessments}
    assert len(assessments) == len(g.missingness_assessments)
    for kind, entity_id, item, field in targets:
        value = getattr(item, field)
        assert value.status.value == "NOT_REPORTED" and value.value is None
        assert value.raw_value is None and not value.conflict_candidates
        assert not value.evidence_ids  # No old inferred timepoint/session evidence.
        assessment = assessments[(kind, entity_id, field)]
        assert assessment.status == "NOT_REPORTED" and assessment.coverage_complete
        assert assessment.covered_sources == ["2015-06-article"]
        assert "Human-reviewed NOT_REPORTED" in assessment.rationale
        assert "pages 1–7" in assessment.rationale


def test_human_review_queue_preserves_only_undecided_fields():
    from article_agent.evaluation.entity_matcher import GROUPS, entities
    t = load_gold().truth
    pending = {(kind, entity_id, field)
               for kind in GROUPS for entity_id, item in entities(t, kind).items()
               for field, value in item
               if hasattr(value, "status") and value.status.value == "REVIEW_REQUIRED"}
    assert pending == {
        ("Study", "2015-06-S1", "centre_count"),
        ("Study", "2015-06-S1", "participant_blinding"),
    }
    assert load_gold().state == "DRAFT"


def test_countries_has_direct_address_and_reciprocal_evidence():
    g = load_gold()
    study = g.truth.studies[0]
    evidence = {e.evidence_id: e for e in g.truth.evidence}
    linked = [evidence[eid] for eid in study.countries.evidence_ids]
    assert study.countries.value == ["China"]
    assert any("Chinese patients" in e.quote for e in linked)
    address = [e for e in linked if "Jiaxing University, Jiaxing 314000, China" in e.quote]
    assert len(address) == 1
    e = address[0]
    assert e.page == 5 and e.section == "Correspondence" and e.support_type == "direct"
    assert e.source_id == "2015-06-article"
    assert any((target.entity_type, target.entity_id, target.field_id) ==
               ("Study", "2015-06-S1", "countries") for target in e.targets)


def test_review_document_records_accepted_baseline_and_reconciliation_only_sessions():
    g = load_gold()
    review = (GOLD.parent / "REVIEW.md").read_text(encoding="utf-8")
    assert "Baseline inclusion：accepted policy" in review
    assert "请确认 baseline inclusion policy" not in review
    assert any(note.startswith("Accepted policy:") for note in g.review_notes)
    for intervention in g.truth.interventions:
        assert intervention.total_sessions.value is None
        assert "90" not in intervention.total_sessions.model_dump_json()
        assert "90" not in intervention.legacy_fields["annotation_notes"]["total_sessions"]
    assert not any("90" in note for note in g.review_notes)
    assert all("reconciliation note" in line for line in review.splitlines()
               if re.search(r"\b90\b", line))  # Exclude evidence IDs such as E0090.
    assert "Denominator 最终人工裁决与 derivation policy" in review
    assert "deterministic derived" in review and "最终 REVIEW_REQUIRED 仅剩 2 项" in review
    queue = review.split("## REVIEW_REQUIRED 队列", 1)[1].split("## 已接受的人工审核决策", 1)[0]
    assert ".denominator" not in queue


def test_reviewed_draft_builder_reproduces_committed_annotation():
    import runpy
    import pytest
    module = runpy.run_path(str(GOLD.parent / "build_draft.py"))
    if not module["PDF"].exists() or not module["WORKBOOK"].exists():
        pytest.skip("Local primary sources are not distributed in Git")
    generated, queue = module["build"]()
    assert generated.model_dump_json(indent=2) + "\n" == GOLD.read_text(encoding="utf-8")
    assert len(queue) == 2


def test_acceptance_rejects_reintroduced_bladder_timepoint(monkeypatch):
    import runpy
    import pytest
    module = runpy.run_path(str(ROOT / "scripts/pr5c1_2015_06_acceptance.py"))
    g = load_gold()
    # Simulate bypassing model validation: acceptance must still reject drift.
    from article_agent.domain.models import FieldStatus
    g.truth.comparison_results[0].timepoint.status = FieldStatus.REVIEW_REQUIRED
    monkeypatch.setattr(GoldStandardV2, "model_validate_json", classmethod(lambda cls, text: g))
    with pytest.raises(AssertionError):
        module["validate"]()


def test_derived_bladder_denominators_keep_raw_cells_and_conflicts():
    from decimal import Decimal, ROUND_HALF_UP
    g = load_gold()
    t = g.truth
    evidence = {e.evidence_id: e for e in t.evidence}
    formulas = ("21 / 0.600 = 35", "29 / 0.8529 ≈ 34", "23 / 0.605 ≈ 38")
    for i, (value, raw, formula) in enumerate(zip(
            (35, 34, 38), ("21 (60.0)", "29 (85.29)", "23 (60.5)"), formulas), start=1):
        result = next(r for r in t.arm_results
                      if r.arm_id == f"2015-06-S1-A{i:02}" and r.outcome_id == "2015-06-S1-O01")
        field = result.denominator
        assert field.status.value == "PRESENT" and field.value == value and field.raw_value == raw
        count, percent = map(Decimal, raw.rstrip(")").split(" ("))
        assert int((count / (percent / 100)).to_integral_value(rounding=ROUND_HALF_UP)) == value
        assert (count * 100 / value).quantize(percent, rounding=ROUND_HALF_UP) == percent
        assert len(field.evidence_ids) == 1 and not field.conflict_candidates
        e = evidence[field.evidence_ids[0]]
        assert e.support_type == "derived" and formula in e.derivation
        assert (e.source_type, e.source_id, e.page, e.table_id, e.row_id, e.cell_refs, e.quote) == (
            "table", "2015-06-article", 4, "Table 2", "bladder-balance", [f"Group {i}"], raw)
        assert [(target.entity_type, target.entity_id, target.field_id) for target in e.targets] == [
            ("ArmResult", result.arm_result_id, "denominator")]
        disclaimer = "derived outcome denominator does not adjudicate randomized_n SOURCE_CONFLICT."
        assert disclaimer in e.derivation
        assert disclaimer in result.legacy_fields["annotation_notes"]["denominator"]
        assert not any(m.entity_type == "ArmResult" and m.entity_id == result.arm_result_id
                       and m.field_id == "denominator" for m in g.missingness_assessments)
    assert t.arms[0].randomized_n.value == 35
    for arm in t.arms[1:]:
        assert arm.randomized_n.status.value == "SOURCE_CONFLICT"
        assert {c.value for c in arm.randomized_n.conflict_candidates} == {34, 38}
        assert all(c.evidence_ids for c in arm.randomized_n.conflict_candidates)
    assert GoldStandardV2.model_validate_json(g.model_dump_json()) == g


def test_acceptance_rejects_source_reported_denominator_evidence(monkeypatch):
    import runpy
    import pytest
    module = runpy.run_path(str(ROOT / "scripts/pr5c1_2015_06_acceptance.py"))
    g = load_gold()
    eid = g.truth.arm_results[0].denominator.evidence_ids[0]
    evidence = next(e for e in g.truth.evidence if e.evidence_id == eid)
    evidence.support_type = "direct"
    evidence.derivation = None
    monkeypatch.setattr(GoldStandardV2, "model_validate_json", classmethod(lambda cls, text: g))
    with pytest.raises(AssertionError):
        module["validate"]()
