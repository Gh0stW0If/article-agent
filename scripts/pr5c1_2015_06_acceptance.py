"""Offline acceptance for the 2015-06 Gold DRAFT."""
from __future__ import annotations
import hashlib
import json
from collections import Counter
from pathlib import Path
from article_agent.domain.models import FieldStatus
from article_agent.evaluation import GoldStandardV2, evaluate_article
from article_agent.evaluation.registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
GOLD_PATH = ROOT / "gold/2015-06/gold.json"


def validate():
    gold = GoldStandardV2.model_validate_json(GOLD_PATH.read_text(encoding="utf-8"))
    t = gold.truth
    assert gold.state == "DRAFT"
    assert gold.article_id == "2015-06"
    assert t.article.article_id == "2015-06"
    assert [s.study_id for s in t.studies] == ["2015-06-S1"]
    assert [a.arm_id for a in t.arms] == [f"2015-06-S1-A{i:02}" for i in (1,2,3)]
    assert len(t.interventions) == 3 and len(t.outcomes) == 4
    assert len(t.arm_results) >= 18 and len(t.comparisons) == 3
    assert len(t.comparison_results) == 18
    assert [a.label.value for a in t.arms] == [
        "CIC treatment", "EA combined with CIC treatment", "sham acupuncture combined with CIC treatment"]
    assert [a.intervention_ids for a in t.arms] == [
        ["2015-06-S1-I01"], ["2015-06-S1-I02","2015-06-S1-I01"],
        ["2015-06-S1-I03","2015-06-S1-I01"]]
    assert sum(r.source_table_id=="Table 2" for r in t.arm_results)==18
    expected_p = [
        ["0.019","0.963","0.019"],["<0.001","<0.01","<0.001"],
        ["<0.001","0.018","<0.001"],["<0.001","0.107","<0.001"],
        ["<0.001"]*3,["<0.001"]*3]
    expected_outcomes = [1,2,3,4,3,4]
    for row, values in enumerate(expected_p):
        for column, raw in enumerate(values):
            result=t.comparison_results[row*3+column]
            assert result.comparison_id==f"2015-06-S1-C{column+1:02}"
            assert result.outcome_id==f"2015-06-S1-O{expected_outcomes[row]:02}"
            assert result.p_value.value==float(raw.lstrip("<"))
            assert result.p_value_comparator.value==("<" if raw.startswith("<") else "=")
            assert result.raw_value.value==raw
    assert [c.arm_ids for c in t.comparisons] == [
        ["2015-06-S1-A01","2015-06-S1-A02"],
        ["2015-06-S1-A01","2015-06-S1-A03"],
        ["2015-06-S1-A02","2015-06-S1-A03"],
    ]
    assert t.arms[0].randomized_n.value == 35
    for arm, expected in zip(t.arms[1:], ({34,38},{34,38})):
        assert arm.randomized_n.status == FieldStatus.SOURCE_CONFLICT
        assert {c.value for c in arm.randomized_n.conflict_candidates} == set(expected)
        assert all(c.evidence_ids for c in arm.randomized_n.conflict_candidates)
    assert all(a.arm_id not in {"2015-06-01","2015-06-02"} for a in t.arms)
    assert all(o.outcome_id not in {"2015-06-01","2015-06-02"} for o in t.outcomes)
    assert all(x.status not in {FieldStatus.UNRESOLVED,FieldStatus.INSUFFICIENT_CONTEXT}
               for group in ([t.article],t.studies,t.arms,t.interventions,t.outcomes,t.arm_results,t.comparisons,t.comparison_results)
               for item in group for _,x in item if hasattr(x,"status"))
    # Gold permits some empty evidence lists structurally; real annotation does not.
    evidence_by_id={e.evidence_id:e for e in t.evidence}
    assessments={(m.entity_type,m.entity_id,m.field_id):m for m in gold.missingness_assessments}
    from article_agent.evaluation.entity_matcher import GROUPS, entities
    for kind in GROUPS:
        for entity_id,item in entities(t,kind).items():
            for field,value in item:
                if not hasattr(value,"status"):
                    continue
                if value.status==FieldStatus.NOT_REPORTED:
                    assert assessments[(kind,entity_id,field)].coverage_complete
                if value.status in {FieldStatus.PRESENT,FieldStatus.SOURCE_CONFLICT}:
                    assert value.evidence_ids, (kind,entity_id,field)
                    lists=[value.evidence_ids]+[c.evidence_ids for c in value.conflict_candidates]
                    for ids in lists:
                        assert ids
                        for eid in ids:
                            e=evidence_by_id[eid]
                            assert e.source_id=="2015-06-article" and e.page
                            assert any(target.entity_type==kind and target.entity_id==entity_id and target.field_id==field for target in e.targets)
    serialized=gold.model_dump_json()
    assert "2015-06-01" not in serialized and "2015-06-02" not in serialized
    report = evaluate_article(t, gold, load_registry())
    assert report.metrics["hard_exact"]["rate"] == 1.0
    assert report.metrics["production_coverage"]["rate"] == 1.0
    assert report.metrics["supported_value_accuracy"]["rate"] == 1.0
    assert report.metrics["conflicts"]["conflict_detection_rate"]["rate"] == 1.0
    assert report.metrics["conflicts"]["candidate_set_accuracy"]["rate"] == 1.0
    statuses = Counter()
    for group in ([t.article],t.studies,t.arms,t.interventions,t.outcomes,t.arm_results,t.comparisons,t.comparison_results):
        for item in group:
            for _, value in item:
                if hasattr(value,"status"):
                    statuses[value.status.value] += 1
    summary = {
        "article_count": 1, "study_count": len(t.studies), "arm_count": len(t.arms),
        "intervention_count": len(t.interventions), "outcome_count": len(t.outcomes),
        "arm_result_count": len(t.arm_results), "comparison_count": len(t.comparisons),
        "comparison_result_count": len(t.comparison_results),
        "present_field_count": statuses["PRESENT"], "not_reported_count": statuses["NOT_REPORTED"],
        "not_applicable_count": statuses["NOT_APPLICABLE"], "source_conflict_count": statuses["SOURCE_CONFLICT"],
        "review_required_count": statuses["REVIEW_REQUIRED"], "evidence_count": len(t.evidence),
        "missingness_assessment_count": len(gold.missingness_assessments),
        "self_evaluation": {
            "hard_exact": report.metrics["hard_exact"],
            "production_coverage": report.metrics["production_coverage"],
            "supported_value_accuracy": report.metrics["supported_value_accuracy"],
            "conflict_detection": report.metrics["conflicts"],
        },
        "review_required_fields": [
            f"{typ}:{getattr(item, idf)}.{field}"
            for typ, group, idf in [
                ("Article",[t.article],"article_id"),("Study",t.studies,"study_id"),
                ("Arm",t.arms,"arm_id"),("Intervention",t.interventions,"intervention_id"),
                ("Outcome",t.outcomes,"outcome_id"),("ArmResult",t.arm_results,"arm_result_id"),
                ("Comparison",t.comparisons,"comparison_id"),
                ("ComparisonResult",t.comparison_results,"comparison_result_id")]
            for item in group for field,value in item if hasattr(value,"status") and value.status==FieldStatus.REVIEW_REQUIRED
        ],
    }
    return summary


def main():
    out = ROOT / "outputs/pr5c1_2015_06"
    out.mkdir(parents=True, exist_ok=True)
    summary = validate()
    (out/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    lines=["# 2015-06 Gold DRAFT acceptance","","状态：PASS（结构与 self-consistency），Gold 仍为 DRAFT，未评估人工事实正确性。","",
           "| 项目 | 数量 |","|---|---:|"]
    for key in ("article_count","study_count","arm_count","intervention_count","outcome_count","arm_result_count","comparison_count","comparison_result_count","present_field_count","not_reported_count","not_applicable_count","source_conflict_count","review_required_count","evidence_count","missingness_assessment_count"):
        lines.append(f"| {key} | {summary[key]} |")
    lines += ["","## Self-consistency","",f"- HARD exact: `{summary['self_evaluation']['hard_exact']}`",
              f"- Production coverage: `{summary['self_evaluation']['production_coverage']}`",
              f"- Supported value accuracy: `{summary['self_evaluation']['supported_value_accuracy']}`",
              f"- Conflict detection: `{summary['self_evaluation']['conflict_detection']}`",
              "","## Review queue",""]
    lines += [f"- `{x}`" for x in summary["review_required_fields"]]
    lines += ["","## Scope safeguards","",
              "- Source: primary PDF `-2015-06.pdf`; workbook is LEGACY_ANNOTATION only.",
              "- No API, LLM, extraction pipeline, evaluator benchmark or Gold migration was used.",
              "- No pseudo-article IDs `2015-06-01` / `2015-06-02` occur in canonical entities.",
              "- Self-consistency PASS is not a claim that human annotation is correct.",
              "- Review required before changing state to FROZEN."]
    (out/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
