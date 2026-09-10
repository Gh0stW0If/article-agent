from test_evaluator_engine import synthetic, replay
from article_agent.evaluation import GoldStandardV2
from article_agent.evaluation.engine import ratio


def test_exact_denominator_and_coverage_accuracy_separation():
    d=synthetic.synthetic_gold().model_dump(mode="json")
    # Only these nine HARD targets are ordinary/conflict/review; the rest review.
    from article_agent.evaluation.entity_matcher import GROUPS
    from article_agent.evaluation.registry import load_registry
    fields={f.field_id:f for f in load_registry().fields}
    for kind,(collection,_) in GROUPS.items():
        items=[d["truth"]["article"]] if kind=="Article" else d["truth"].get(collection,[])
        for item in items:
            for name,value in list(item.items()):
                fid=kind[0].lower()+kind[1:]+"."+name
                if fid in fields and fields[fid].evaluation_tier=="HARD":
                    item[name]={"status":"REVIEW_REQUIRED"}
    a,b,c=d["truth"]["arms"]
    # Frozen IDs allow Arm matching independent of reviewed label fields.
    targets=[(a,"randomized_n"),(a,"received_n"),(a,"analyzed_n"),(a,"dropout_n")]
    for arm,name in targets: arm[name]=synthetic.present(35)
    for name in ("received_n","analyzed_n"):
        b[name]={"status":"NOT_REPORTED"}
        d["missingness_assessments"].append({"entity_type":"Arm","entity_id":b["arm_id"],"field_id":name,"status":"NOT_REPORTED","coverage_complete":True,"rationale":"Synthetic absence"})
    b["dropout_n"]={"status":"NOT_APPLICABLE"}
    b["randomized_n"]=synthetic.conflict()
    c["randomized_n"]={"status":"REVIEW_REQUIRED"}
    synthetic.add_evidence(d["truth"]); g=GoldStandardV2.model_validate(d)
    p=g.truth.model_dump(mode="json")
    p["arms"][0]["received_n"]=synthetic.present(34)
    p["arms"][0]["analyzed_n"]={"status":"UNRESOLVED"}
    r=replay(p,g)
    assert r.metrics["hard_exact"]==ratio(5,7)
    assert r.metrics["production_coverage"]==ratio(3,4)
    assert r.metrics["supported_value_accuracy"]==ratio(2,3)


def test_zero_denominator_null():
    assert ratio(0,0)=={"numerator":0,"denominator":0,"rate":None}
