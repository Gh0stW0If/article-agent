import importlib.util
import json
from pathlib import Path
import socket
import pytest
from article_agent.domain.models import ArticleExtraction
from article_agent.evaluation import evaluate_article, EvaluationReportV2, GoldStandardV2
from article_agent.evaluation.registry import load_registry

_spec=importlib.util.spec_from_file_location("synthetic_pr5b",Path(__file__).resolve().parents[1]/"scripts/pr5b_synthetic_acceptance.py")
synthetic=importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(synthetic)


def replay(p,g):
    synthetic.add_evidence(p)
    return evaluate_article(ArticleExtraction.model_validate(p),g,load_registry())


def test_acceptance_all_scenarios_and_determinism():
    first=synthetic.acceptance()
    assert len(first)==13
    assert all(r["passed"] for r in first.values())
    assert first==synthetic.acceptance()


def test_immutable_serializable_and_offline_cli(tmp_path,monkeypatch):
    from article_agent.evaluation.engine import main
    def forbidden(*args,**kwargs): raise AssertionError("Network forbidden")
    monkeypatch.setattr(socket,"socket",forbidden)
    monkeypatch.setattr(socket,"create_connection",forbidden)
    g=synthetic.synthetic_gold(); p=g.truth.model_copy(deep=True); r=load_registry()
    before=[x.model_dump_json() for x in (p,g,r)]
    report=evaluate_article(p,g,r)
    assert report==EvaluationReportV2.model_validate_json(report.model_dump_json())
    assert before==[x.model_dump_json() for x in (p,g,r)]
    for name,obj in (("p",p),("g",g),("r",r)):
        (tmp_path/f"{name}.json").write_text(obj.model_dump_json(),encoding="utf-8")
    out=tmp_path/"out.json"
    assert main(["--prediction",str(tmp_path/"p.json"),"--gold",str(tmp_path/"g.json"),"--registry",str(tmp_path/"r.json"),"--output",str(out)])==0
    assert EvaluationReportV2.model_validate_json(out.read_text(encoding="utf-8"))==report


@pytest.mark.parametrize("status,value,expected",[
    ("PRESENT",35,"EXACT"),("PRESENT",9,"VALUE_WRONG"),
    ("NOT_REPORTED",None,"FALSE_NR"),("UNRESOLVED",None,"NOT_EXTRACTED"),
    ("INSUFFICIENT_CONTEXT",None,"NOT_EXTRACTED"),("NOT_APPLICABLE",None,"STATUS_WRONG"),
    ("REVIEW_REQUIRED",None,"STATUS_WRONG"),("SOURCE_CONFLICT",None,"SOURCE_CONFLICT_SPURIOUS"),
])
def test_present_status_table(status,value,expected):
    g=synthetic.synthetic_gold(); p=g.truth.model_dump(mode="json")
    p["arms"][0]["randomized_n"]=synthetic.conflict() if status=="SOURCE_CONFLICT" else {"status":status,"value":value}
    result=replay(p,g)
    field=next(f for f in result.field_results if f.gold_entity_id==g.truth.arms[0].arm_id and f.field_id=="arm.randomized_n")
    assert field.classification==expected


@pytest.mark.parametrize("gold_status,pred_status,expected",[
    ("NOT_REPORTED","NOT_REPORTED","EXACT"),("NOT_REPORTED","PRESENT","FALSE_PRESENT"),
    ("NOT_REPORTED","UNRESOLVED","NOT_EXTRACTED"),("NOT_REPORTED","NOT_APPLICABLE","STATUS_WRONG"),
    ("NOT_APPLICABLE","NOT_APPLICABLE","EXACT"),("NOT_APPLICABLE","PRESENT","FALSE_PRESENT"),
    ("NOT_APPLICABLE","NOT_REPORTED","STATUS_WRONG"),("NOT_APPLICABLE","INSUFFICIENT_CONTEXT","NOT_EXTRACTED"),
])
def test_absence_status_table(gold_status,pred_status,expected):
    d=synthetic.synthetic_gold().model_dump(mode="json")
    d["truth"]["arms"][0]["randomized_n"]={"status":gold_status}
    if gold_status=="NOT_REPORTED":
        d["missingness_assessments"]=[{"entity_type":"Arm","entity_id":d["truth"]["arms"][0]["arm_id"],"field_id":"randomized_n","status":"NOT_REPORTED","coverage_complete":True,"rationale":"Synthetic absence"}]
    synthetic.add_evidence(d["truth"]); g=GoldStandardV2.model_validate(d)
    p=g.truth.model_dump(mode="json"); p["arms"][0]["randomized_n"]={"status":pred_status,"value":35 if pred_status=="PRESENT" else None}
    r=replay(p,g)
    assert next(f for f in r.field_results if f.gold_entity_id==g.truth.arms[0].arm_id and f.field_id=="arm.randomized_n").classification==expected


def test_conflict_candidate_mismatch():
    g=synthetic.synthetic_gold(); p=g.truth.model_dump(mode="json")
    p["arms"][1]["randomized_n"]=synthetic.conflict((38,36))
    r=replay(p,g)
    assert r.conflict_results[0]["candidate_set_match"] is False
    assert r.metrics["conflicts"]["conflict_detected"]==1


@pytest.mark.parametrize("defect",["article_id","schema","registry_version","field_path","comparator","normalization"])
def test_contract_errors(defect):
    g=synthetic.synthetic_gold(); p=g.truth.model_copy(deep=True); r=load_registry()
    if defect=="article_id": p.article.article_id="wrong"
    elif defect=="schema": p=p.model_copy(update={"schema_version":"wrong"})
    elif defect=="registry_version": r.registry_version="wrong"
    elif defect=="field_path": r.fields[0].field_path="not.exists.title"
    elif defect=="comparator": r.fields[0].comparator={"type":"unknown"}
    else: r.fields[0].normalization=["guess"]
    with pytest.raises(ValueError): evaluate_article(p,g,r)


def test_legacy_exports_remain():
    from article_agent.evaluation import EVALUATION_HEADERS,build_evaluation_rows,compute_evaluation_summary,write_evaluation_summary
    assert EVALUATION_HEADERS
    assert all(callable(x) for x in (build_evaluation_rows,compute_evaluation_summary,write_evaluation_summary))


def test_published_fixtures_reproduce_generator():
    directory=Path(__file__).parent/"fixtures/evaluator"
    assert GoldStandardV2.model_validate_json((directory/"synthetic_gold.json").read_text(encoding="utf-8"))==synthetic.synthetic_gold()
    names={"perfect":"exact_prediction","wrong_value":"wrong_value_prediction","missing_entity":"missing_entity_prediction","source_conflict_detected":"conflict_prediction"}
    for name,_,prediction in synthetic.scenarios():
        if name in names:
            assert ArticleExtraction.model_validate_json((directory/(names[name]+".json")).read_text(encoding="utf-8"))==prediction


def test_ci_p_values_and_conflict_grounding_are_retained():
    g=synthetic.synthetic_gold(); r=replay(g.truth.model_dump(mode="json"),g)
    values={f.field_id:f for f in r.field_results if f.entity_type=="ComparisonResult"}
    for field,value in (("estimate",-2),("confidence_interval_lower",-3),("confidence_interval_upper",-1),("p_value",.02)):
        f=values["comparisonResult."+field]
        assert f.gold_value==f.prediction_value==value
        assert f.classification=="EXACT" and f.evidence_grounded
    assert all(c["evidence_ids"] for c in r.conflict_results[0]["prediction_candidates"])


def test_frozen_gold_supported():
    g=synthetic.synthetic_gold().model_copy(update={"state":"FROZEN"})
    r=evaluate_article(g.truth,g,load_registry())
    assert r.gold_state=="FROZEN" and r.metrics["hard_exact"]["rate"]==1
