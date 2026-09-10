"""Synthetic-only acceptance and reproducible fixtures. Never reads real Gold."""
import argparse
import copy
import json
from pathlib import Path
from article_agent.domain import models as dm
from article_agent.evaluation import GoldStandardV2, evaluate_article
from article_agent.evaluation.entity_matcher import GROUPS, entities
from article_agent.evaluation.registry import load_registry

ROOT = Path(__file__).resolve().parents[1]


def present(value):
    return {"status":"PRESENT","value":value}


def conflict(values=(38,34)):
    return {"status":"SOURCE_CONFLICT","conflict_candidates":[{"value":v} for v in values]}


def fill(model, **values):
    result = model(**values).model_dump(mode="json")
    for name, value in result.items():
        if isinstance(value,dict) and value.get("status")=="UNRESOLVED":
            result[name] = {"status":"NOT_APPLICABLE"}
    return result


def add_evidence(truth):
    truth["evidence"] = []
    for kind,(collection,idf) in GROUPS.items():
        items = [truth["article"]] if kind=="Article" else truth.get(collection,[])
        for item in items:
            for name,field in item.items():
                if not isinstance(field,dict) or field.get("status") not in {"PRESENT","SOURCE_CONFLICT"}:
                    continue
                observations = field.get("conflict_candidates",[]) if field["status"]=="SOURCE_CONFLICT" else [field]
                for i,observation in enumerate(observations):
                    eid=f"E:{kind}:{item[idf]}:{name}:{i}"
                    observation["evidence_ids"]=[eid]
                    truth["evidence"].append({"evidence_id":eid,"source_type":"other","source_id":"synthetic",
                        "quote":str(observation.get("value")),"targets":[{"entity_type":kind,"entity_id":item[idf],"field_id":name}]})


def synthetic_gold():
    # Start from the PR5A synthetic contract fixture, never a production prediction.
    base=json.loads((ROOT/"tests/fixtures/gold_v2_synthetic.json").read_text(encoding="utf-8"))
    aid=base["article_id"]; sid=aid+"-S1"
    arms=[sid+f"-A{i:02}" for i in (1,2,3)]
    outcomes=[sid+"-O01",sid+"-O02"]
    iid=sid+"-I01"; cid=sid+"-C01"
    truth={"article":fill(dm.Article,article_id=aid,title=present("Synthetic trial"),doi=present("10.synthetic/test"),publication_year=present(2000)),
        "studies":[fill(dm.Study,study_id=sid,article_id=aid,arm_ids=arms,intervention_ids=[iid],outcome_ids=outcomes)],
        "arms":[fill(dm.Arm,arm_id=a,study_id=sid,label=present(f"Arm {i}"),intervention_ids=[iid],randomized_n=present(35)) for i,a in enumerate(arms)],
        "interventions":[fill(dm.Intervention,intervention_id=iid,study_id=sid,name=present("Shared synthetic care"))],
        "outcomes":[fill(dm.Outcome,outcome_id=o,study_id=sid,name=present(n),instrument=present(inst)) for o,n,inst in zip(outcomes,["Pain","Disability"],["VAS","ODI"])],
        "comparisons":[fill(dm.Comparison,comparison_id=cid,study_id=sid,arm_ids=arms[:2],relation=present("between-group"),contrast=present("difference"))],
        "arm_results":[fill(dm.ArmResult,arm_result_id=sid+"-AR01",arm_id=arms[0],outcome_id=outcomes[0],timepoint=present("4 weeks"),analysis_set=present("ITT"),value_kind=present("mean"),value=present(5.0))],
        "comparison_results":[fill(dm.ComparisonResult,comparison_result_id=sid+"-CR01",comparison_id=cid,outcome_id=outcomes[0],timepoint=present("4 weeks"),analysis_set=present("ITT"),effect_measure=present("MD"),estimate=present(-2.0),confidence_interval_lower=present(-3.0),confidence_interval_upper=present(-1.0),p_value=present(0.02))]}
    truth["arms"][1]["randomized_n"]=conflict()
    add_evidence(truth)
    base.update(truth=truth,entity_aliases=[],missingness_assessments=[],state="DRAFT")
    return GoldStandardV2.model_validate(base)


def rename_ids(truth, mapping):
    # IDs, references and EvidenceTargets must move together; text values never move.
    def visit(value):
        if isinstance(value,dict):
            return {k:visit(v) for k,v in value.items()}
        if isinstance(value,list):
            return [visit(v) for v in value]
        return mapping.get(value,value) if isinstance(value,str) else value
    return visit(truth)


def scenarios():
    gold=synthetic_gold()
    for name in ("perfect","wrong_value","false_nr","not_extracted","missing_entity","extra_entity",
                 "outcome_id_reordered","outcome_split","comparison_reversed","source_conflict_detected",
                 "source_conflict_missed","source_conflict_spurious","evidence_missing"):
        p=gold.truth.model_dump(mode="json")
        if name in {"wrong_value","false_nr","not_extracted"}:
            p["arms"][0]["randomized_n"] = {"wrong_value":present(99),"false_nr":{"status":"NOT_REPORTED"},"not_extracted":{"status":"UNRESOLVED"}}[name]
        elif name=="missing_entity":
            oid=p["outcomes"].pop()["outcome_id"]
            p["studies"][0]["outcome_ids"].remove(oid)
        elif name in {"extra_entity","outcome_split"}:
            o=copy.deepcopy(p["outcomes"][0]); o["outcome_id"]+="-extra"
            if name=="extra_entity": o["name"]=present("Unrelated outcome")
            p["outcomes"].append(o); p["studies"][0]["outcome_ids"].append(o["outcome_id"])
        elif name=="outcome_id_reordered":
            a,b=[o["outcome_id"] for o in p["outcomes"]]
            p=rename_ids(p,{a:b,b:a})
        elif name=="comparison_reversed":
            p["comparisons"][0]["arm_ids"].reverse()
        elif name=="source_conflict_detected":
            p["arms"][1]["randomized_n"]=conflict((34,38))
        elif name=="source_conflict_missed":
            p["arms"][1]["randomized_n"]=present(38)
        elif name=="source_conflict_spurious":
            p["arms"][0]["randomized_n"]=conflict()
        add_evidence(p)
        if name=="evidence_missing":
            p["article"]["title"]["evidence_ids"]=[]
            p["evidence"]=[e for e in p["evidence"] if not any(t["entity_type"]=="Article" and t["field_id"]=="title" for t in e["targets"])]
        yield name,gold,dm.ArticleExtraction.model_validate(p)


def acceptance():
    reports={name:evaluate_article(p,g,load_registry()) for name,g,p in scenarios()}
    baseline=reports["perfect"].metrics
    checks={
        "perfect":lambda r:all(r.metrics[k]["rate"]==1 for k in ("hard_exact","production_coverage","supported_value_accuracy")) and not r.entity_failures,
        "wrong_value":lambda r:r.metrics["production_coverage"]==baseline["production_coverage"] and r.metrics["supported_value_accuracy"]["rate"]<1,
        "false_nr":lambda r:r.field_failure_counts.get("FALSE_NR")==1,
        "not_extracted":lambda r:r.metrics["production_coverage"]["rate"]<1,
        "missing_entity":lambda r:r.metrics["hard_exact"]["rate"]<1 and r.entity_failure_counts.get("ENTITY_MISSING",0)>0,
        "extra_entity":lambda r:r.entity_failure_counts.get("ENTITY_EXTRA")==1 and r.metrics["hard_exact"]==baseline["hard_exact"],
        "outcome_id_reordered":lambda r:r.metrics==baseline,
        "outcome_split":lambda r:r.entity_failure_counts.get("OUTCOME_IDENTITY_SPLIT")==1,
        "comparison_reversed":lambda r:r.metrics["entities"]["Comparison"]["matched"]==0,
        "source_conflict_detected":lambda r:r.metrics["conflicts"]["candidate_set_exact"]==1 and r.metrics["hard_exact"]==baseline["hard_exact"],
        "source_conflict_missed":lambda r:r.metrics["conflicts"]["conflict_missed"]==1 and r.metrics["hard_exact"]==baseline["hard_exact"],
        "source_conflict_spurious":lambda r:r.metrics["conflicts"]["spurious_conflict_count"]==1,
        "evidence_missing":lambda r:r.field_failure_counts.get("EVIDENCE_UNGROUNDED")==1 and r.metrics["hard_exact"]==baseline["hard_exact"],
    }
    return {n:{"passed":bool(checks[n](r)),"report":r.model_dump(mode="json")} for n,r in reports.items()}


def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--output",type=Path,default=ROOT/"outputs/pr5b_synthetic_acceptance")
    parser.add_argument("--write-fixtures", action="store_true", help="Regenerate synthetic-only test fixtures")
    args=parser.parse_args(argv); args.output.mkdir(parents=True,exist_ok=True)
    if args.write_fixtures:
        directory=ROOT/"tests/fixtures/evaluator"
        directory.mkdir(parents=True,exist_ok=True)
        (directory/"synthetic_gold.json").write_text(synthetic_gold().model_dump_json(indent=2)+"\n",encoding="utf-8")
        names={"perfect":"exact_prediction","wrong_value":"wrong_value_prediction","missing_entity":"missing_entity_prediction","source_conflict_detected":"conflict_prediction"}
        for name,_,prediction in scenarios():
            if name in names:
                (directory/(names[name]+".json")).write_text(prediction.model_dump_json(indent=2)+"\n",encoding="utf-8")
    result=acceptance()
    (args.output/"REPORT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    rows=["# PR5B synthetic acceptance", "", "| Scenario | Hard exact | Coverage | Value accuracy | Entity failures | Conflict result | Expected | Pass/Fail |", "|---|---|---|---|---|---|---|---|"]
    for name,item in result.items():
        r=item["report"]; m=r["metrics"]
        rows.append(f"| {name} | {m['hard_exact']} | {m['production_coverage']} | {m['supported_value_accuracy']} | {r['entity_failure_counts']} | {m['conflicts']} | Scenario invariant in acceptance() | {item['passed']} |")
    (args.output/"REPORT.md").write_text("\n".join(rows)+"\n",encoding="utf-8")
    print(json.dumps({n:r["passed"] for n,r in result.items()},indent=2))
    return 0 if all(r["passed"] for r in result.values()) else 1


if __name__=="__main__":
    raise SystemExit(main())
