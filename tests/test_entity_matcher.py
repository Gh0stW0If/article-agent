import copy
import pytest
from test_evaluator_engine import synthetic, replay
from article_agent.evaluation import GoldStandardV2


def test_all_eight_entities_matched():
    g=synthetic.synthetic_gold(); r=replay(g.truth.model_dump(mode="json"),g)
    assert len(r.metrics["entities"])==8
    assert all(m["matched"]==m["gold"]>0 for m in r.metrics["entities"].values())


def test_same_outcome_id_different_identity():
    g=synthetic.synthetic_gold(); p=g.truth.model_dump(mode="json")
    p["outcomes"][0]["name"]=synthetic.present("Quality of life")
    r=replay(p,g)
    assert r.metrics["entities"]["Outcome"]["missing"]==1
    assert r.metrics["entities"]["Outcome"]["extra"]==1
    assert r.metrics["entities"]["ArmResult"]["matched"]==0


def test_outcome_alias_and_merge():
    d=synthetic.synthetic_gold().model_dump(mode="json")
    o=d["truth"]["outcomes"][0]
    d["entity_aliases"]=[{"entity_type":"Outcome","entity_id":o["outcome_id"],"accepted_values":{"name":["Ache"]},"note":"Synthetic alias"}]
    g=GoldStandardV2.model_validate(d); p=g.truth.model_dump(mode="json")
    p["outcomes"][0]["name"]=synthetic.present("Ache")
    r=replay(p,g)
    assert any(m.entity_type=="Outcome" and m.match_method=="GOLD_ALIAS" for m in r.entity_matches)
    second=d["truth"]["outcomes"][1]
    second["instrument"]=copy.deepcopy(o["instrument"])
    d["entity_aliases"].append({"entity_type":"Outcome","entity_id":second["outcome_id"],"accepted_values":{"name":["Ache"]},"note":"Deliberate ambiguity"})
    synthetic.add_evidence(d["truth"]); g=GoldStandardV2.model_validate(d)
    p["outcomes"].pop(); p["studies"][0]["outcome_ids"].pop()
    r=replay(p,g)
    assert r.entity_failure_counts["OUTCOME_IDENTITY_MERGE"]==1
    assert r.metrics["entities"]["Outcome"]["matched"]==0


def test_different_instruments_do_not_match():
    g=synthetic.synthetic_gold(); p=g.truth.model_dump(mode="json")
    p["outcomes"][0]["instrument"]=synthetic.present("Different scale")
    assert replay(p,g).metrics["entities"]["Outcome"]["matched"]==1


def test_arm_fallback_and_intervention_context():
    g=synthetic.synthetic_gold(); p=g.truth.model_dump(mode="json")
    ids={a["arm_id"]:a["arm_id"]+"-changed" for a in p["arms"]}
    ids[p["interventions"][0]["intervention_id"]]="I99"
    p=synthetic.rename_ids(p,ids)
    r=replay(p,g)
    assert r.metrics["entities"]["Arm"]["matched"]==3
    assert r.metrics["entities"]["Intervention"]["matched"]==1


def test_ambiguous_arm_labels_do_not_guess():
    d=synthetic.synthetic_gold().model_dump(mode="json")
    d["truth"]["arms"][1]["label"]=copy.deepcopy(d["truth"]["arms"][0]["label"])
    synthetic.add_evidence(d["truth"]); g=GoldStandardV2.model_validate(d)
    p=g.truth.model_dump(mode="json")
    p=synthetic.rename_ids(p,{a["arm_id"]:a["arm_id"]+"-new" for a in p["arms"]})
    r=replay(p,g)
    assert r.entity_failure_counts["ENTITY_AMBIGUOUS"]>=1
    assert r.metrics["entities"]["Arm"]["matched"]==1
    assert r.entity_failure_counts["ARM_BINDING_UNRESOLVED"]==1
    assert r.entity_failure_counts["COMPARATOR_SCOPE_UNRESOLVED"]>=1


@pytest.mark.parametrize("collection,idf",[("arm_results","arm_result_id"),("comparison_results","comparison_result_id")])
def test_result_composite_identity(collection,idf):
    g=synthetic.synthetic_gold(); p=g.truth.model_dump(mode="json")
    p=synthetic.rename_ids(p,{p[collection][0][idf]:"result99"})
    assert replay(p,g).metrics["hard_exact"]["rate"]==1


def test_reported_derived_do_not_match():
    g=synthetic.synthetic_gold(); p=g.truth.model_dump(mode="json")
    p["arm_results"][0].update(derived=True,derivation="Synthetic computation")
    assert replay(p,g).metrics["entities"]["ArmResult"]["matched"]==0


def test_timepoint_numeric_fallback():
    d=synthetic.synthetic_gold().model_dump(mode="json")
    d["truth"]["arm_results"][0].update(timepoint={"status":"NOT_APPLICABLE"},timepoint_value=synthetic.present(4),timepoint_unit=synthetic.present("weeks"))
    synthetic.add_evidence(d["truth"]); g=GoldStandardV2.model_validate(d)
    assert replay(g.truth.model_dump(mode="json"),g).metrics["entities"]["ArmResult"]["matched"]==1


def test_study_id_not_matched_by_array_position():
    g=synthetic.synthetic_gold(); p=g.truth.model_dump(mode="json")
    p=synthetic.rename_ids(p,{p["studies"][0]["study_id"]:"different-study"})
    r=replay(p,g)
    assert r.metrics["entities"]["Study"]["matched"]==0
    assert r.metrics["entities"]["Arm"]["matched"]==0
