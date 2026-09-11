import hashlib
import json
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
                assert r.denominator.status.value=="REVIEW_REQUIRED"
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
