from copy import deepcopy

import pytest
from pydantic import ValidationError

from article_agent.domain import ArticleExtraction
from article_agent.outcome_canonicalizer import canonicalize_outcomes
from article_agent.trial_topology_agent import TrialTopology, topology_to_canonical


def inputs():
    topology = TrialTopology(number_of_arms=3, arms=[
        {"name": name, "source_label": f"Group {i}", "evidence": [
            {"source_id": "article", "quote": f"Group {i}: {name}", "arm_text": f"Group {i}"}]
        } for i, name in enumerate(["CIC", "EA + CIC", "Sham acupuncture + CIC"], 1)])
    return topology, topology_to_canonical("2015-06", topology)


def row(**changes):
    result = {"outcome_name": "Residual urine volume", "instrument": "Ultrasound", "unit": "ml",
        "timepoint": "1 month", "analysis_set": "ITT", "value_kind": "mean", "table_id": "T2", "row_id": "r1",
        "source_evidence": "Residual urine volume Group 2 vs Group 1: 38 (SD 4), difference -2, 95% CI -3 to -1, P < 0.05",
        "arm": [{"arm_label": "Group 2", "value": 38, "sd": 4, "n": 34}],
        "comparison": {"contrast": "Group 2 vs Group 1", "relation": "between-group"},
        "effect_measure": "mean difference", "outcome_between_group_estimate": -2,
        "outcome_between_group_lower": -3, "outcome_between_group_upper": -1,
        "outcome_p_value": 0.05, "outcome_p_value_comparator": "<"}
    result.update(changes)
    return result


def run(rows):
    topology, graph = inputs()
    return canonicalize_outcomes("2015-06", topology, graph, rows)


def test_identity_shared_across_arms_times_and_rows():
    g = run([row(), row(timepoint="3 months", row_id="r2", arm=[{"arm_label": "Group 1", "value": 2}])])
    assert len(g.outcomes) == 1
    assert g.outcomes[0].outcome_id == "2015-06-S1-O01"
    assert len(g.arm_results) == 2
    assert [r.arm_id for r in g.arm_results] == ["2015-06-S1-A02", "2015-06-S1-A01"]
    assert len(g.comparisons) == 1
    assert len(g.comparison_results) == 2


def test_distinct_outcome_or_instrument_not_merged():
    g = run([row(), row(outcome_name="Voided volume"), row(instrument="MRI")])
    assert len(g.outcomes) == 3


def test_grammatical_identity_and_missing_instrument():
    g = run([row(outcome_name="CIC frequency", instrument="NR"), row(outcome_name="frequency of CIC")])
    assert len(g.outcomes) == 1
    assert g.outcomes[0].name.status == "PRESENT"
    assert g.outcomes[0].instrument.value == "Ultrasound"


@pytest.mark.parametrize("label", ["new treatment", "intervention", "control"])
def test_unknown_labels_never_create_arm(label):
    g = run([row(arm=[{"arm_label": label, "value": 10}], comparison={})])
    assert len(g.arms) == 3 and not g.arm_results
    assert g.adapter_warnings
    assert g.article.legacy_fields["pr4_source_outcomes"][0]["arm"][0]["value"] == 10


def test_ambiguous_alias_and_conflicting_id_label_rejected():
    topology, graph = inputs()
    topology.arms[0].aliases = ["shared"]
    topology.arms[1].aliases = ["shared"]
    g = canonicalize_outcomes("2015-06", topology, graph, [row(arm=[{"arm_label":"shared", "value":3}])])
    assert not g.arm_results
    g = run([row(arm=[{"arm_id":"2015-06-S1-A01", "arm_label":"Group 2", "value":3}])])
    assert not g.arm_results


def test_no_automatic_pairwise_comparisons_even_with_p_value():
    g = run([row(comparison={}, arm=[{"arm_label": f"Group {i}", "value": i} for i in range(1,4)])])
    assert len(g.arm_results) == 3
    assert not g.comparisons and not g.comparison_results
    assert g.adapter_warnings


def test_explicit_comparison_binding_ci_p_and_evidence():
    g = run([row()])
    assert len(g.comparisons) == 1
    assert g.comparisons[0].arm_ids == ["2015-06-S1-A02", "2015-06-S1-A01"]
    r = g.comparison_results[0]
    assert r.comparison_id == "2015-06-S1-C01"
    assert r.outcome_id == "2015-06-S1-O01"
    assert r.confidence_interval_lower.value == -3
    assert r.confidence_interval_upper.value == -1
    assert r.p_value.value == .05 and r.p_value_comparator.value == "<"
    assert r.estimate.evidence_ids
    assert ArticleExtraction.model_validate_json(g.model_dump_json()) == g


def test_multiple_explicit_pairs_do_not_copy_unscoped_p():
    g = run([row(comparison={"contrast":"Group 2 vs Group 1; Group 2 vs Group 3"})])
    assert len(g.comparisons) == 2
    assert all(r.p_value.status == "UNRESOLVED" for r in g.comparison_results)
    assert all(c.arm_ids != ["2015-06-S1-A01", "2015-06-S1-A03"] for c in g.comparisons)


def test_multiple_structured_pairs_keep_their_own_p():
    g = run([row(comparisons=[{"contrast":"Group 2 vs Group 1", "p_value":.01},
        {"contrast":"Group 2 vs Group 3", "p_value":.02}])])
    assert [r.p_value.value for r in g.comparison_results] == [.01, .02]


def test_identical_observations_merge_evidence_then_conflict():
    first = row()
    second = row(row_id="r2", source_evidence="Second source: difference -2 and 38 participants")
    third = row(row_id="r3", outcome_between_group_estimate=-4, arm=[{"arm_label":"Group 2", "value":34}])
    g = run([first, second])
    assert len(g.arm_results) == len(g.comparison_results) == 1
    assert len(g.arm_results[0].value.evidence_ids) == 2
    assert len(g.comparison_results[0].estimate.evidence_ids) == 2
    g = run([first, second, third, first])
    assert [c.value for c in g.arm_results[0].value.conflict_candidates] == [38,34]
    field = g.comparison_results[0].estimate
    assert field.status == "SOURCE_CONFLICT"
    assert [c.value for c in field.conflict_candidates] == [-2,-4]
    assert len(field.conflict_candidates[0].evidence_ids) == 3
    assert all(c.evidence_ids for c in field.conflict_candidates)
    assert ArticleExtraction.model_validate_json(g.model_dump_json()) == g


def test_unknown_timepoints_do_not_merge_different_rows():
    g = run([row(timepoint="NR"), row(timepoint="NR",row_id="r2")])
    assert len(g.outcomes) == 1 and len(g.arm_results) == 2


def test_reported_and_derived_remain_separate():
    g = run([row(), row(derived=True, derivation="reported group means subtracted")])
    assert len(g.arm_results) == len(g.comparison_results) == 2
    assert [r.derived for r in g.comparison_results] == [False, True]
    r = g.comparison_results[1]
    linked = [e for e in g.evidence if e.evidence_id in r.estimate.evidence_ids]
    assert all(e.support_type == "derived" and e.derivation for e in linked)


def test_derived_without_formula_retained_not_mislabeled_reported():
    g = run([row(derived=True)])
    assert not g.arm_results and not g.comparison_results
    assert g.article.legacy_fields["pr4_source_outcomes"][0]["derived"] is True


def test_original_inputs_unchanged_and_deterministic():
    topology, graph = inputs()
    records = [row()]
    original = deepcopy((topology.model_dump(),graph.model_dump(),records))
    a = canonicalize_outcomes("2015-06",topology,graph,records)
    b = canonicalize_outcomes("2015-06",topology,graph,records)
    assert a.model_dump_json() == b.model_dump_json()
    assert original == (topology.model_dump(),graph.model_dump(),records)
    assert a.arms == graph.arms and a.interventions == graph.interventions
    assert a.studies[0].randomized_n == graph.studies[0].randomized_n


def test_reciprocal_evidence_enforced_for_conflict_candidates():
    g = run([row(),row(outcome_between_group_estimate=-9)])
    payload = g.model_dump()
    eid = g.comparison_results[0].estimate.conflict_candidates[1].evidence_ids[0]
    next(e for e in payload['evidence'] if e['evidence_id']==eid)['targets'] = []
    with pytest.raises(ValidationError):
        ArticleExtraction.model_validate(payload)


def test_no_evidence_does_not_create_present_fields():
    g = run([row(source_evidence=None)])
    assert g.outcomes[0].name.status == 'UNRESOLVED'
    assert g.arm_results[0].value.status == 'UNRESOLVED'


def test_2015_06_regression_frozen_three_arms_and_two_reported_pairs():
    g = run([row(outcome_name='The number of bladder balance patients', instrument='NR',
        arm=[{'arm_label':f'Group {i}','event_count':n} for i,n in enumerate([21,29,23],1)],
        comparisons=[{'contrast':'Group 2 vs Group 1','p_value':.019},
                     {'contrast':'Group 2 vs Group 3','p_value':.019}]),
        row(outcome_name='bladder balance patients', instrument='NR', timepoint='3 months', comparison={})])
    assert len(g.arms)==3 and len(g.outcomes)==1 and len(g.comparisons)==2
    assert all(r.arm_id in {a.arm_id for a in g.arms} for r in g.arm_results)
    assert [r.p_value.value for r in g.comparison_results]==[.019,.019]


def test_invalid_input_and_frozen_graph_mismatch():
    t,g=inputs()
    with pytest.raises(ValueError): canonicalize_outcomes('wrong',t,g,[])
    with pytest.raises(ValueError): canonicalize_outcomes('2015-06',t,g,{'records':[]})
    with pytest.raises(ValueError): canonicalize_outcomes('2015-06',t,run([row()]),[row()])


def test_nested_arm_fields_and_source_coordinates():
    g=run([row(arm=[{'arm_id':'2015-06-S1-A03','value':0,'standard_deviation':2,
        'change_from_baseline':-1,'dispersion_lower':-2,'dispersion_upper':3,'event_count':0,'denominator':34,
        'n':34,'raw_value':'0 (2)','timepoint_value':1,'timepoint_unit':'month'}])])
    r=g.arm_results[0]
    assert r.value.value==0 and r.denominator.value==34 and r.event_count.value==0
    assert r.timepoint_value.value==1 and r.timepoint_unit.value=='month'
    assert (r.source_table_id,r.source_row_id)==('T2','r1')


def test_ci_p_conflicts_preserve_each_candidate_evidence():
    g=run([row(),row(outcome_between_group_lower=-5,outcome_p_value=.01)])
    r=g.comparison_results[0]
    for field in (r.confidence_interval_lower,r.p_value):
        assert field.status=='SOURCE_CONFLICT'
        assert all(c.evidence_ids for c in field.conflict_candidates)


def test_p_string_retains_threshold_and_raw_source():
    source=row(outcome_p_value='<0.001',source_values=['P <0.001'])
    g=run([source]);r=g.comparison_results[0]
    assert r.p_value.value==.001 and r.p_value_comparator.value=='<'
    assert 'P <0.001' in r.raw_value.value
    assert g.article.legacy_fields['pr4_source_outcomes']==[source]


def test_derived_evidence_cannot_be_silently_reported():
    g=run([row(evidence=[{'quote':'calculated difference','support_type':'derived'}])])
    assert not g.arm_results and not g.comparison_results


def test_foreign_source_record_not_mapped():
    g=run([row(article_id='foreign')])
    assert not g.outcomes and g.adapter_warnings


def test_offline_no_api_or_network(monkeypatch):
    import socket
    def forbidden(*args,**kwargs): raise AssertionError('network prohibited')
    monkeypatch.setattr(socket,'socket',forbidden)
    assert run([row()]).arm_results


def test_same_time_raw_and_pair_merge_despite_missing_auxiliary_metadata():
    g=run([row(), row(timepoint_value=1,timepoint_unit='month',
        comparison={'contrast':'Group 2 vs Group 1'},outcome_between_group_estimate=-7)])
    assert len(g.comparisons)==1 and len(g.comparison_results)==1
    assert g.comparison_results[0].estimate.status=='SOURCE_CONFLICT'
    assert g.comparison_results[0].timepoint_value.value==1
