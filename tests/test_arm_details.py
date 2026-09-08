from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from article_agent.arm_details_agent import (
    ArmDetails,
    SampleFlowObservation,
    arm_details_to_canonical,
    extract_arm_details,
    run_arm_details,
)
from article_agent.domain import ArticleExtraction, FieldStatus
from article_agent.trial_topology_agent import TrialTopology, topology_to_canonical


def fixture(count=3):
    names = ["CIC", "EA + CIC", "Sham acupuncture + CIC"][:count]
    source = "Group 1 receives CIC. Group 2 receives Electroacupuncture and CIC. Group 3 receives Sham acupuncture and CIC.\nMethods: Group 1 n=35; Group 2 n=38; Group 3 n=34.\nTable 1: Group 1 n=35; Group 2 n=34; Group 3 n=38."
    topology = TrialTopology.model_validate({"number_of_arms": count, "arms": [
        {"name": name, "source_label": f"Group {i}", "evidence": [{"source_id": "article", "quote": source,
            "arm_text": f"Group {i}"}]} for i, name in enumerate(names,1)]})
    def evidence(quote): return [{"source_id": "article", "quote": quote}]
    def comp(name): return {"name":name,"kind":None,"description":None,"evidence":evidence(source)}
    def obs(value, quote): return {"field":"randomized_n","value":value,"raw_value":f"n={value}","evidence":evidence(quote)}
    rows=[]
    for i in range(count):
        components=[comp("CIC")] if i==0 else [comp(["", "Electroacupuncture", "Sham acupuncture"][i]), comp("CIC")]
        first=[35,38,34][i]; second=[35,34,38][i]
        rows.append({"arm_index":i+1,"intervention_components":components,"sample_flow":[
            obs(first,source.splitlines()[1]),obs(second,source.splitlines()[2]),obs(first,source.splitlines()[1])]})
    return source,topology,{"arms":rows}


class FakeClient:
    def __init__(self,response): self.response=response; self.requests=[]
    def chat_json(self,messages,temperature=0.0):
        self.requests.append(json.loads(messages[1]["content"]))
        return deepcopy(self.response)


@pytest.mark.parametrize("count",[2,3])
def test_components_aligned_and_shared(count):
    source,topology,response=fixture(count)
    frozen=topology.model_dump()
    details=extract_arm_details(source,topology,FakeClient(response))
    graph=arm_details_to_canonical("trial",topology,details)
    assert topology.model_dump()==frozen
    assert len(graph.arms)==count and len(graph.interventions)==count
    assert graph.arms[0].intervention_ids==["trial-S1-I01"]
    assert graph.arms[1].intervention_ids==["trial-S1-I02","trial-S1-I01"]
    assert [a.arm_id for a in graph.arms]==[a.arm_id for a in topology_to_canonical("trial",topology).arms]
    assert graph.interventions[0].name.value=="CIC"
    assert len(graph.interventions[0].name.evidence_ids)==count
    assert graph.interventions[0].frequency_value.status==FieldStatus.UNRESOLVED
    assert not graph.comparisons and not graph.outcomes and not graph.arm_results and not graph.comparison_results
    ArticleExtraction.model_validate_json(graph.model_dump_json())


def test_2015_06_conflicts_on_real_arm_ids_and_each_candidate_evidence(tmp_path):
    source,topology,response=fixture()
    graph=run_arm_details("2015-06",source,topology,tmp_path,FakeClient(response))
    assert [a.arm_id for a in graph.arms]==[f"2015-06-S1-A{i:02}" for i in range(1,4)]
    assert graph.arms[0].randomized_n.status==FieldStatus.PRESENT
    assert graph.arms[0].randomized_n.value==35
    assert len(graph.arms[0].randomized_n.evidence_ids)==3
    for arm,expected in [(graph.arms[1],[38,34]),(graph.arms[2],[34,38])]:
        field=arm.randomized_n
        assert field.status==FieldStatus.SOURCE_CONFLICT and field.value is None
        assert [c.value for c in field.conflict_candidates]==expected
        assert [len(c.evidence_ids) for c in field.conflict_candidates]==[2,1]
        pool={e.evidence_id:e for e in graph.evidence}
        for candidate in field.conflict_candidates:
            for eid in candidate.evidence_ids:
                assert any(t.entity_id==arm.arm_id and t.field_id=="randomized_n" for t in pool[eid].targets)
                assert str(candidate.value) in pool[eid].quote
    assert graph.arms[2].intervention_ids==["2015-06-S1-I03","2015-06-S1-I01"]
    assert (tmp_path/"arm_details.json").exists() and (tmp_path/"arm_details.canonical.json").exists()


def test_stable_intervention_ids_are_first_appearance_not_name_hash():
    source,topology,response=fixture()
    details=ArmDetails.model_validate(response)
    first=arm_details_to_canonical("trial",topology,details)
    changed=details.model_copy(deep=True)
    for arm in changed.arms:
        for component in arm.intervention_components:
            if component.name=="CIC": component.name="Expanded display name"
    second=arm_details_to_canonical("trial",topology,changed)
    assert first.studies[0].intervention_ids==second.studies[0].intervention_ids
    assert [a.intervention_ids for a in first.arms]==[a.intervention_ids for a in second.arms]


@pytest.mark.parametrize("mode",["reverse","missing","extra","duplicate"])
def test_cannot_change_topology(mode):
    source,topology,response=fixture()
    if mode=="reverse": response["arms"].reverse()
    if mode=="missing": response["arms"].pop()
    if mode=="extra": response["arms"].append({"arm_index":4,"intervention_components":[],"sample_flow":[]})
    if mode=="duplicate": response["arms"][1]["arm_index"]=1
    with pytest.raises(ValueError,match="frozen topology"):
        extract_arm_details(source,topology,FakeClient(response),retries=0)


@pytest.mark.parametrize("field",["received_n","analyzed_n","dropout_n"])
def test_sample_fields_bound_to_arm(field):
    source,topology,response=fixture(2)
    for arm in response["arms"]: arm["sample_flow"]=[]
    response["arms"][1]["sample_flow"]=[{"field":field,"value":0,"raw_value":"n=0","evidence":[{"source_id":"article","quote":"Group 2 n=0"}]}]
    graph=arm_details_to_canonical("trial",topology,extract_arm_details(source+" Group 2 n=0",topology,FakeClient(response)))
    assert getattr(graph.arms[0],field).status==FieldStatus.UNRESOLVED
    assert getattr(graph.arms[1],field).value==0


def test_no_model_generated_ids_or_false_evidence():
    source,topology,response=fixture()
    response["arms"][0]["arm_id"]="invented"
    with pytest.raises(ValidationError): ArmDetails.model_validate(response)
    del response["arms"][0]["arm_id"]
    response["arms"][0]["intervention_components"][0]["evidence"][0]["quote"]="invented source"
    with pytest.raises(ValueError,match="verbatim"):
        extract_arm_details(source,topology,FakeClient(response),retries=0)


def test_full_source_and_frozen_topology_sent_without_truncation():
    source,topology,response=fixture(2)
    source += " Long source context"*10000
    client=FakeClient(response)
    extract_arm_details(source,topology,client)
    assert client.requests[0]["sources"]["article"]==source
    assert [a["arm_index"] for a in client.requests[0]["frozen_topology"]]==[1,2]


def test_schema_matches_published():
    path=Path(__file__).resolve().parents[1]/"schemas/arm-details.schema.json"
    assert json.loads(path.read_text(encoding="utf-8"))==ArmDetails.model_json_schema()


def test_analysis_set_basis_wording_is_normalized():
    itt=SampleFlowObservation.model_validate({"field":"analyzed_n","value":80,"raw_value":"ITT 80",
        "basis":"intention_to_treat_analysis","evidence":[{"source_id":"article","quote":"ITT 80"}]})
    assert itt.basis=="intention_to_treat"
    assert SampleFlowObservation.model_validate({"field":"analyzed_n","value":80,"raw_value":"PP 80",
        "basis":"Per Protocol","evidence":[{"source_id":"article","quote":"PP 80"}]}).basis=="per_protocol"
    # Article-specific labels pass through normalized instead of failing.
    assert SampleFlowObservation.model_validate({"field":"dropout_n","value":7,"raw_value":"7",
        "basis":"Withdrawals at end of follow-up","evidence":[{"source_id":"article","quote":"7"}]}
        ).basis=="withdrawals_at_end_of_follow_up"
    with pytest.raises(ValidationError):
        SampleFlowObservation.model_validate({"field":"analyzed_n","value":80,"raw_value":"80",
            "basis":"  ","evidence":[{"source_id":"article","quote":"80"}]})


def test_ocr_spaced_digits_pass_value_check():
    source,topology,response=fixture(2)
    spaced="Table 2: Real (n = 8 8); Sham (n = 8 7)."
    for arm,value,raw in zip(response["arms"],[88,87],["Real (n = 8 8)","Sham (n = 8 7)"]):
        arm["sample_flow"]=[{"field":"randomized_n","value":value,"raw_value":raw,
            "evidence":[{"source_id":"article","quote":spaced}]}]
    graph=arm_details_to_canonical("trial",topology,
        extract_arm_details(source+"\n"+spaced,topology,FakeClient(response)))
    assert graph.arms[0].randomized_n.value==88
    # A digit broken across OCR whitespace must not satisfy a smaller value.
    response["arms"][0]["sample_flow"][0]["value"]=8
    with pytest.raises(ValueError,match="reported integer"):
        extract_arm_details(source+"\n"+spaced,topology,FakeClient(response),retries=0)


def test_word_form_counts_pass_value_check():
    source,topology,response=fixture(2)
    quote="At the end of follow-up, three from Group A and two from Group B had withdrawn."
    response["arms"][0]["sample_flow"]=[{"field":"dropout_n","value":3,"raw_value":"three from Group A",
        "evidence":[{"source_id":"article","quote":quote}]}]
    response["arms"][1]["sample_flow"]=[{"field":"dropout_n","value":2,"raw_value":"two from Group B",
        "evidence":[{"source_id":"article","quote":quote}]}]
    graph=arm_details_to_canonical("trial",topology,
        extract_arm_details(source+" "+quote,topology,FakeClient(response)))
    assert graph.arms[0].dropout_n.value==3
    assert graph.arms[1].dropout_n.value==2
    # A spelled count must not satisfy a different value.
    response["arms"][0]["sample_flow"][0]["value"]=4
    with pytest.raises(ValueError,match="reported integer"):
        extract_arm_details(source+" "+quote,topology,FakeClient(response),retries=0)
