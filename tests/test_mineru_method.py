from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT = ROOT / "MinerU method"
sys.path.insert(0, str(EXPERIMENT))

from mineru_method.registry import canonical_ids, load_bindings, model_field_ids
from mineru_method.bibliography import enrich_metadata, extract_doi
from mineru_method.canonical import build_canonical_outcome_dataset
from mineru_method.flow import reconcile_flow
from mineru_method.llm import (
    ValidatedExtractor,
    classify_outcome_tables_with_llm,
    extract_outcomes_by_table,
    postprocess_outcomes_with_llm,
)
from mineru_method.prompts import PROMPT_SPECS, TABLE_OUTCOME_PROMPT_SPEC
from mineru_method.pipeline import _normalize_primary_analysis
from mineru_method.routing import contexts_for_modules
from evaluate_2015_01 import evaluate_outcomes_by_row
from mineru_method.schemas import (
    AcupunctureProtocol, ConsortFlowExtraction, EvidenceQuote, MetadataExtraction, MissingDataMethod,
    OutcomeExtraction, OutcomePostProcessRecord, OutcomePostProcessing, OutcomeStatistic, RiskOfBiasExtraction,
)
from mineru_method.table_parser import OutcomeTableBlock, extract_outcome_table_blocks, parse_primary_painvas


def test_validated_extractor_sends_four_part_prompt(tmp_path: Path) -> None:
    class FakeClient:
        messages = None

        def chat_json(self, messages):
            self.messages = messages
            return MetadataExtraction().model_dump()

    client = FakeClient()
    result = ValidatedExtractor(client, tmp_path).extract(
        "metadata", MetadataExtraction, "# Article", PROMPT_SPECS["metadata"]
    )
    payload = json.loads(client.messages[1]["content"])
    assert result.title == "NR"
    assert "医学 RCT 论文信息提取专家" in payload["role_definition"]
    assert payload["task_description"]
    assert payload["field_definitions"]["pydantic_json_schema"]
    assert payload["json_template"]["publication_year"] is None
    assert payload["source_context"] == "# Article"


def test_derived_evidence_records_reproducible_rule() -> None:
    evidence = EvidenceQuote(
        field_id="outcome_observation_timepoint_value",
        quote="T1 was at 10 weeks",
        source="markdown",
        support_type="derived",
        derivation="T0-T1 uses T1; Methods maps T1 to 10 weeks",
    )
    assert evidence.support_type == "derived"
    assert "10 weeks" in evidence.derivation


def test_section_routing_isolates_methods_and_results_tables() -> None:
    markdown = """# Abstract
Basic facts.
# Methods
one session per week for 9 weeks; simple linear regression imputation.
# Results
PainVAS was -41.0%.
| outcome | effect |
| --- | --- |
| PainVAS | d=0.50 |
# Discussion
Unrelated interpretation.
"""
    contexts = contexts_for_modules(markdown)
    assert "one session per week" in contexts["acupuncture"]
    assert "PainVAS" not in contexts["acupuncture"]
    assert "d=0.50" in contexts["outcomes"]
    assert "Unrelated interpretation" not in contexts["outcomes"]


def test_mineru_subheadings_inherit_canonical_parent_section() -> None:
    markdown = """# Trial title
## METHODS
Opening method paragraph.
### Interventions
nine sessions at one per week.
### Statistical plan
missing values used linear regression.
## RESULTS
### Primary outcome
PainVAS improved.
"""
    contexts = contexts_for_modules(markdown)
    assert "Trial title" in contexts["metadata"]
    assert "nine sessions" in contexts["acupuncture"]
    assert "linear regression" in contexts["risk_of_bias"]
    assert "PainVAS improved" in contexts["outcomes"]


def test_mineru_floating_html_table_is_routed_to_outcomes_only() -> None:
    markdown = """## METHODS
method text
## RESULTS
results text
## DISCUSSION
discussion text
<table><tr><td>PainVAS (T0–T1)</td><td>-41.0</td></tr></table>
"""
    contexts = contexts_for_modules(markdown)
    assert "PainVAS (T0–T1)" in contexts["outcomes"]
    assert "PainVAS (T0–T1)" not in contexts["acupuncture"]


def test_outcome_table_blocks_deduplicate_html_and_keep_pipe_tables() -> None:
    html_table = "<table><tr><th>Outcome</th><th>Mean</th></tr><tr><td>Pain</td><td>1.2</td></tr></table>"
    context = (
        "Table 1\n" + html_table + "\n" + html_table
        + "\nTable 2\n| Outcome | Mean |\n| --- | --- |\n| Anxiety | 2.3 |\n"
    )
    blocks = extract_outcome_table_blocks(context)
    assert len(blocks) == 2
    assert blocks[0].row_count == 2
    assert blocks[0].source == "html"
    assert blocks[1].source == "markdown"
    assert "[ROW 002] Pain | 1.2" in blocks[0].prompt_text()


def test_tablewise_outcome_extraction_has_no_document_row_cap(tmp_path: Path) -> None:
    class FakeClient:
        calls = []

        def chat_json(self, messages):
            self.calls.append(messages)
            return {
                "outcomes": [
                    {
                        "outcome_name": f"Outcome {index}",
                        "instrument": "VAS",
                        "timepoint_raw": "end of treatment",
                        "statistic_type": "continuous",
                        "analysis_population": "ITT",
                        "intervention_estimate": index,
                        "control_estimate": index + 0.5,
                        "between_group_measure": "MD",
                        "between_group_estimate": -0.5,
                        "p_value": 0.01,
                        "p_comparator": "=",
                        "quote": f"Outcome {index} | {index} | {index + 0.5}",
                    }
                    for index in range(1, 9)
                ]
            }

    block = OutcomeTableBlock(
        table_id="table-1",
        caption="Table 1 outcomes",
        raw_table="<table>...</table>",
        rows=tuple(f"<tr><td>Outcome {index}</td><td>{index}</td><td>{index + 0.5}</td></tr>" for index in range(1, 9)),
    )
    client = FakeClient()
    extraction, manifest = extract_outcomes_by_table(client, [block], tmp_path, max_rows_per_request=20)
    assert len(extraction.outcomes) == 8
    assert len(client.calls) == 1
    assert manifest[0]["row_count"] == 8
    assert manifest[0]["outcome_count"] == 8


def test_table_outcome_prompt_requires_all_rows_and_full_group_statistics() -> None:
    task = TABLE_OUTCOME_PROMPT_SPEC["task_description"]
    template = TABLE_OUTCOME_PROMPT_SPEC["json_template"]["outcomes"][0]
    assert "不能因为表格较长而抽样" in task
    assert "intervention_variance_lower" in template
    assert "control_variance_upper" in template
    assert "quote" in template


def test_tablewise_outcome_extraction_chunks_rows_but_keeps_all_rows(tmp_path: Path) -> None:
    class FakeClient:
        calls = []

        def chat_json(self, messages):
            self.calls.append(json.loads(messages[1]["content"])["source_context"])
            return {"outcomes": []}

    rows = tuple(
        f"<tr><td>Outcome {index}</td><td>{index}</td></tr>"
        for index in range(1, 15)
    )
    block = OutcomeTableBlock("table-1", "Table 1", "<table>...</table>", rows)
    client = FakeClient()
    extraction, manifest = extract_outcomes_by_table(
        client, [block], tmp_path, max_rows_per_request=6
    )
    assert not extraction.outcomes
    assert manifest[0]["part_count"] == 3
    assert len(client.calls) == 3
    data_rows = "\n".join(client.calls)
    for index in range(1, 15):
        assert f"Outcome {index} | {index}" in data_rows


def test_lossless_whole_table_fallback_covers_every_row(tmp_path: Path) -> None:
    class FakeClient:
        model = "gpt-5.6-sol"

        def __init__(self):
            self.calls = []

        def chat_json(self, messages):
            payload = json.loads(messages[1]["content"])
            context = payload["source_context"]
            row_ids = [line.rsplit("ROW_ID=", 1)[-1].strip() for line in context.splitlines() if "ROW_ID=" in line]
            self.calls.append((row_ids, context))
            if len(row_ids) > 1:
                first = row_ids[0]
                return {
                    "outcomes": [{
                        "table_id": "table-1", "row_id": first, "outcome_name": "Outcome 1",
                        "measurement_instrument": "VAS", "outcome_observation_timepoint_raw": "week 4",
                        "statistic_type": "continuous", "analysis_population": "ITT",
                        "quote": "Outcome 1 | 1.0",
                    }],
                    "row_decisions": [{"row_id": first, "status": "outcome", "reason": "test"}],
                }
            row_id = row_ids[0]
            return {"outcomes": [], "row_decisions": [{"row_id": row_id, "status": "non_outcome", "reason": "test"}]}

    block = OutcomeTableBlock(
        table_id="table-1", caption="Table 1", raw_table="<table>...</table>",
        rows=tuple(f"<tr><td>Outcome {index}</td><td>{index}.0</td></tr>" for index in range(1, 5)),
    )
    client = FakeClient()
    extraction, manifest = extract_outcomes_by_table(
        client, [block], tmp_path, retries=0, whole_table_first=True, request_delay_seconds=0,
    )
    part = manifest[0]["parts"][0]
    assert part["request_mode"] == "whole_table_then_row"
    assert part["status"] == "success"
    assert part["missing_row_ids"] == []
    assert len(client.calls) == 4
    request_manifest = (tmp_path / "request_manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(request_manifest) == 4
    assert all(json.loads(line)["lossless"] is True for line in request_manifest)


def test_multilevel_pipe_header_map_retains_arm_timepoint_and_statistic() -> None:
    context = """Table 2. Scores
| | Acupuncture group Mean (SD) | Acupuncture group Mean (SD) | Control group Mean (SD) | Control group Mean (SD) |
|---|---|---|---|---|
| | Before treatment | 4 weeks after treatment | Before treatment | 4 weeks after treatment |
| DOSS scores | 1.8 (0.7) | 5.8 (1.3) | 1.6 (0.6) | 3.7 (1.1) |
"""
    block = extract_outcome_table_blocks(context)[0]
    assert len(block.header_rows) == 3
    assert block.column_map[1]["arm_label"].startswith("Acupuncture group")
    assert block.column_map[1]["timepoint_raw"] == "Before treatment"
    assert "4 weeks" in block.column_map[2]["timepoint_raw"]
    assert block.column_map[2]["statistic"] == "mean_sd"
    assert "TABLE_COLUMN_MAP" in block.prompt_text()


def test_multilevel_pipe_header_consumes_statistical_test_row() -> None:
    context = """Table 2 Treatment effects
| Questionnaire | End of treatment | End of treatment | ANCOVA results |
|---|---|---|---|
| | RA group, mean (SD) | SA group, mean (SD) | P value |
| | | | F 1,172 |
| Pain score | 1.2 (0.4) | 1.5 (0.5) | .020 |
"""
    block = extract_outcome_table_blocks(context)[0]
    assert len(block.header_rows) == 4
    assert block.target_row_ids == ("table-2:r005",)
    assert "F 1,172" in block.column_labels[0] or "F 1,172" in " ".join(block.header_rows)


def test_outcome_source_values_are_preserved_in_normalized_record() -> None:
    from mineru_method.llm import _normalize_outcome_items

    extraction = _normalize_outcome_items(
        {
            "outcomes": [{
                "row_id": "table-2:r001",
                "outcome_name": "Pain",
                "source_values": ["1.0 (0.2)", "2.0 (0.3)", "p=0.04"],
                "source_evidence": "Pain | 1.0 (0.2) | 2.0 (0.3) | p=0.04",
                "derived": True,
                "derivation": "change = post - baseline",
                "conflict_group_id": "cg-test",
            }],
        },
        "TABLE_ID: table-2\nTABLE_DATA_ROWS:\ntable-2:r001 | Pain | 1.0 (0.2) | 2.0 (0.3) | p=0.04",
        table_id="table-2",
    )
    item = extraction.outcomes[0]
    assert item.source_values == ["1.0 (0.2)", "2.0 (0.3)", "p=0.04"]
    assert item.source_evidence.startswith("Pain |")
    assert item.derived is True
    assert item.derivation == "change = post - baseline"
    assert item.conflict_group_id == "cg-test"


def test_outcome_row_audit_sends_complete_source_and_gold(tmp_path: Path) -> None:
    class FakeClient:
        model = "gpt-5.6-sol"

        def __init__(self):
            self.payloads = []

        def chat_json(self, messages):
            payload = json.loads(messages[1]["content"])
            self.payloads.append(payload)
            return {"module_score": 80, "module_verdict": "complete", "field_findings": []}

    source = {
        "table_id": "table-2", "row_id": "table-2:r004", "outcome_name": "DOSS",
        "measurement_instrument": "DOSS", "outcome_observation_timepoint_raw": "4 weeks",
        "statistic_type": "continuous", "evidence": [{"quote": "DOSS | 1.8 | 5.8", "source": "table", "field_id": "outcome_name"}],
    }
    result = evaluate_outcomes_by_row(
        FakeClient(), {"outcomes": [source]},
        [{"gold_row_id": "gold-1", "OUTCOM": "DOSS", "INSTRU": "DOSS"}],
        "Table 2\nDOSS | 1.8 | 5.8",
        tmp_path, tag="lossless", retries=1, request_delay_seconds=0,
    )
    assert result["module_score"] == 80


def test_classified_table_excludes_headers_and_baseline_target_rows() -> None:
    context = """Table 1 Baseline characteristics
<table><tr><td>Variable</td><td>Group A (n=10)</td><td>Group C (n=11)</td></tr>
<tr><td>Age</td><td>40</td><td>41</td></tr></table>
Table 2 Results
<table><tr><td>Outcome</td><td>Group</td><td>Mean</td></tr>
<tr><td>Pain</td><td>A</td><td>2.0</td></tr></table>"""
    blocks = extract_outcome_table_blocks(context)
    assert blocks[0].table_category == "baseline"
    assert blocks[0].target_rows == ()
    assert blocks[0].arm_registry == ("Group A (n=10)", "Group C (n=11)")
    assert blocks[1].table_category == "outcome"
    assert len(blocks[1].header_rows) == 1
    assert blocks[1].target_row_ids == ("table-2:r002",)
    prompt = blocks[1].prompt_text()
    assert "TABLE_CATEGORY: outcome" in prompt
    assert "[ROW 002] Pain | A | 2.0" in prompt
    assert "TABLE_HEADER_ROWS" in prompt


def test_llm_table_classification_runs_before_row_selection(tmp_path: Path) -> None:
    class FakeClient:
        model = "gpt-5.6-luna"
        calls = []

        def chat_json(self, messages):
            payload = json.loads(messages[1]["content"])
            self.calls.append(payload)
            context = payload["table_context"]
            if "Maximum pain" in context:
                return {
                    "table_category": "outcome",
                    "confidence": 0.98,
                    "rationale": "三臂统计表包含术后疼痛的连续型结局。",
                }
            return {
                "table_category": "baseline",
                "confidence": 0.97,
                "rationale": "表格呈现随机化前人口学特征。",
            }

    context = """Table 1 Baseline characteristics
| Variable | Group A (n=10) | Group C (n=11) |
| --- | --- | --- |
| Age | 40 | 41 |
Table 2
| Variable | Acupuncture (n=52) | Placebo (n=49) | p-value |
| --- | --- | --- | --- |
| Maximum pain, median (IQR) | 39.5 (11, 63) | 70 (1, 81) | <0.01 |
"""
    blocks = extract_outcome_table_blocks(context, defer_classification=True)
    assert all(block.table_category == "unknown" for block in blocks)
    client = FakeClient()
    classified, manifest = classify_outcome_tables_with_llm(
        client,
        blocks,
        tmp_path,
        request_delay_seconds=0,
    )
    baseline = next(block for block in classified if block.caption.startswith("Table 1"))
    outcome = next(block for block in classified if block.caption == "Table 2")
    assert baseline.table_category == "baseline"
    assert baseline.target_rows == ()
    assert outcome.table_category == "outcome"
    assert any("Maximum pain" in row for row in outcome.target_rows)
    assert outcome.classification_model == "gpt-5.6-luna"
    assert all(item["status"] == "success" for item in manifest)
    assert len(client.calls) == 2


def test_outcome_schema_retains_source_identity_and_multi_arm_comparison() -> None:
    outcome = OutcomeStatistic.model_validate({
        "table_id": "table-2",
        "row_id": "table-2:r004",
        "outcome_name": "FSS",
        "measurement_instrument": "Fatigue Severity Scale",
        "outcome_observation_timepoint_raw": "5 weeks",
        "statistic_type": "continuous",
        "arm": [
            {"arm_id": "A", "arm_label": "Group A", "role": "intervention", "n": 49, "estimate": 3.38},
            {"arm_id": "C", "arm_label": "Group C", "role": "control", "n": 50, "estimate": 4.47},
        ],
        "comparison": {"relation": "intervention_vs_control", "intervention_arm_id": "A", "control_arm_id": "C", "contrast": "A vs C"},
        "analysis_set": "FAS",
        "record_role": "primary",
    })
    assert (outcome.table_id, outcome.row_id, outcome.analysis_set, outcome.record_role) == ("table-2", "table-2:r004", "FAS", "primary")
    assert outcome.arm[1].n == 50
    assert outcome.comparison.control_arm_id == "C"


def test_canonical_dataset_groups_conflicting_sources_without_gold() -> None:
    first = OutcomeStatistic(
        table_id="table-2", row_id="table-2:r004", outcome_name="FSS", measurement_instrument="FSS",
        outcome_observation_timepoint_raw="5 weeks", statistic_type="continuous", analysis_set="FAS",
        record_role="primary", outcome_between_group_estimate=-0.43,
    )
    second = first.model_copy(update={
        "table_id": "table-3", "row_id": "table-3:r004", "outcome_between_group_estimate": -1.14,
    })
    records = [
        OutcomePostProcessRecord(source_index=0, source_outcome=first, normalized_outcome_name="FSS", normalized_measurement_instrument="FSS", normalized_timepoint="5 weeks"),
        OutcomePostProcessRecord(source_index=1, source_outcome=second, normalized_outcome_name="FSS", normalized_measurement_instrument="FSS", normalized_timepoint="5 weeks"),
    ]
    dataset = build_canonical_outcome_dataset(records)
    assert dataset.gold_used is False
    assert dataset.source_outcome_count == 2
    assert dataset.canonical_outcome_count == 1
    assert dataset.conflict_group_count == 1
    assert dataset.conflict_groups[0].group_status == "conflict"
    assert dataset.conflict_groups[0].source_indices == [0, 1]
    assert dataset.records[0].selection_status == "conflict"
    assert dataset.records[0].source_indices == [0, 1]
    assert dataset.records[0].outcome.outcome_between_group_estimate in {-0.43, -1.14}


def test_canonical_dataset_honors_explicit_duplicate_group_as_conflict_hint() -> None:
    first = OutcomeStatistic(
        outcome_name="Pain", outcome_observation_timepoint_raw="week 4",
        statistic_type="continuous", measurement_instrument="VAS",
        outcome_between_group_estimate=-0.4,
    )
    second = first.model_copy(update={"measurement_instrument": "NRS", "outcome_between_group_estimate": -0.8})
    dataset = build_canonical_outcome_dataset([
        OutcomePostProcessRecord(
            source_index=0, source_outcome=first,
            normalized_outcome_name="Pain", normalized_timepoint="week 4",
            duplicate_group="same-row-copy",
        ),
        OutcomePostProcessRecord(
            source_index=1, source_outcome=second,
            normalized_outcome_name="Pain", normalized_timepoint="week 4",
            duplicate_group="same-row-copy",
        ),
    ])
    assert dataset.canonical_outcome_count == 1
    assert dataset.conflict_groups[0].group_status == "conflict"
    assert "measurement_instrument" in dataset.conflict_groups[0].conflict_fields


def test_outcome_postprocessing_preserves_raw_values_and_marks_gold_conflict(tmp_path: Path) -> None:
    class FakeClient:
        def __init__(self):
            self.payloads = []

        def chat_json(self, messages):
            payload = json.loads(messages[1]["content"])
            self.payloads.append(payload)
            indices = [item["source_index"] for item in payload["source_outcomes"]]
            return {
                "records": [{
                    "source_index": index,
                    "normalized_outcome_name": "Pain",
                    "normalized_measurement_instrument": "VAS",
                    "normalized_timepoint": "week 4",
                    "comparison_relation": "intervention vs control",
                    "duplicate_group": None,
                    "gold_row_ids": ["gold-1"] if index == 0 else [],
                    "conflict_status": "conflict" if index == 0 else "none",
                    "conflict_fields": ["p_value"] if index == 0 else [],
                    "conflict_reason": "candidate p=0.01; gold row p=NR" if index == 0 else "",
                } for index in indices],
                "notes": ["test annotation"],
            }

    source = OutcomeStatistic(
        outcome_name="Pain intensity",
        measurement_instrument="VAS",
        outcome_observation_timepoint_raw="week 4",
        statistic_type="continuous",
        intervention_estimate=-2.5,
        control_estimate=-1.0,
        outcome_p_value=0.01,
        outcome_p_value_comparator="=",
        evidence=[],
    )
    client = FakeClient()
    result, manifest = postprocess_outcomes_with_llm(
        client,
        OutcomeExtraction(outcomes=[source]),
        [{"gold_row_id": "gold-1", "OUTCOM": "pain"}, {"gold_row_id": "gold-2", "OUTCOM": "anxiety"}],
        "Table 1 Pain intensity week 4",
        tmp_path,
        batch_size=1,
        max_workers=1,
    )

    assert isinstance(result, OutcomePostProcessing)
    assert result.status == "success"
    assert result.records[0].processing_status == "processed"
    assert result.records[0].conflict_status == "conflict"
    assert result.records[0].source_outcome.outcome_p_value == 0.01
    assert result.records[0].source_outcome.intervention_estimate == -2.5
    assert result.records[0].value_preserved is True
    assert result.gold_conflicts[0].gold_row_id == "gold-2"
    assert result.gold_conflicts[0].conflict_status == "conflict"
    assert manifest[0]["status"] == "success"
    assert client.payloads[0]["post_extraction_only"] is True
    assert client.payloads[0]["gold_reference_rows"][0]["gold_row_id"] == "gold-1"
    assert "source_outcomes" in client.payloads[0]


def test_outcome_postprocessing_matches_human_gold_id_alias_without_rewriting_record(tmp_path: Path) -> None:
    class FakeClient:
        def chat_json(self, messages):
            payload = json.loads(messages[1]["content"])
            return {
                "records": [{
                    "source_index": payload["source_outcomes"][0]["source_index"],
                    "normalized_outcome_name": "Pain",
                    "normalized_measurement_instrument": "VAS",
                    "normalized_timepoint": "week 4",
                    "comparison_relation": "intervention vs control",
                    "gold_row_ids": ["2015-04-01"],
                    "conflict_status": "none",
                    "conflict_fields": [],
                    "conflict_reason": "",
                }],
            }

    source = OutcomeStatistic(
        outcome_name="Pain intensity",
        measurement_instrument="VAS",
        outcome_observation_timepoint_raw="week 4",
        statistic_type="continuous",
    )
    result, _ = postprocess_outcomes_with_llm(
        FakeClient(),
        OutcomeExtraction(outcomes=[source]),
        [{"gold_row_id": "2015-04-01-excel-row-016", "column_1": "2015-04-01", "OUTCOM": "pain"}],
        "Table 1 Pain intensity week 4",
        tmp_path,
        batch_size=20,
        max_workers=1,
    )

    assert result.status == "success"
    assert result.gold_conflicts == []
    assert result.records[0].gold_row_ids == ["2015-04-01"]
    assert result.records[0].value_preserved is True


def test_targeted_cross_section_routing_adds_blinding_and_timepoint_dictionary() -> None:
    markdown = """# Abstract
The trial was blinded to participants.
# Methods
Measurements occurred at baseline (T0) and at 10 weeks (T1).
# Results
PainVAS (T0-T1) improved.
"""
    contexts = contexts_for_modules(markdown)
    assert "blinded to participants" in contexts["risk_of_bias"]
    assert "10 weeks (T1)" in contexts["outcomes"]


def test_missing_data_codebook_matches_legacy_sheet1() -> None:
    assert MissingDataMethod.REGRESSION == 5
    assert MissingDataMethod.MIXED_EFFECT_MODEL == 10
    assert MissingDataMethod.NOT_REPORTED == 13


def test_model_fields_are_backed_by_excel_registry() -> None:
    bindings = load_bindings(ROOT)
    ids = model_field_ids([MetadataExtraction, AcupunctureProtocol, RiskOfBiasExtraction, OutcomeStatistic])
    assert ids <= canonical_ids(bindings)


def test_randomized_arm_sum_is_validated() -> None:
    try:
        RiskOfBiasExtraction(
            randomized_sample_intervention_raw=82,
            randomized_sample_control_raw=82,
            total_randomized=160,
        )
    except ValueError as exc:
        assert "represented arm sum=164" in str(exc)
    else:
        raise AssertionError("inconsistent total should fail")


def test_multiarms_allow_total_above_two_legacy_arm_slots() -> None:
    result = RiskOfBiasExtraction(
        randomized_sample_intervention_raw=53,
        randomized_sample_control_raw=50,
        total_randomized=153,
    )
    assert result.total_randomized == 153


def test_painvas_table_parser_keeps_itt_ci_and_cohens_d_distinct() -> None:
    context = "PainVAS (T0–T1) 78 −41.2 −47.6 to −34.9 81 −27.0 −33.2 to −20.8 0.001 −41.0 −47.2 to −34.8 −27.1 −33.2 to −20.9 0.001 0.50 Medium"
    item = parse_primary_painvas(context).outcomes[0]
    assert item.intervention_estimate == -41.0
    assert (item.intervention_variance_lower, item.intervention_variance_upper) == (-47.2, -34.8)
    assert item.control_estimate == -27.1
    assert item.outcome_between_group_estimate == 0.50
    assert item.effect_size_name == "Cohen's d"


def test_painvas_table_parser_accepts_mineru_html_table() -> None:
    context = "<table><tr><td>PainVAS (T0–T1)</td><td>78</td><td>−41.2</td><td>−47.6 to −34.9</td><td>81</td><td>−27.0</td><td>−33.2 to −20.8</td><td>0.001</td><td>−41.0</td><td>−47.2 to −34.8</td><td>−27.1</td><td>−33.2 to −20.9</td><td>0.001</td><td>0.50</td></tr></table>"
    item = parse_primary_painvas(context).outcomes[0]
    assert item.intervention_estimate == -41.0
    assert item.outcome_between_group_estimate == 0.5


def test_painvas_html_parser_separates_itt_and_pp_populations() -> None:
    context = """## Timepoint dictionary from Methods
baseline (T0) and at 10 weeks (T1)
<table><tr><td>Per protocol</td></tr>
<tr><td>Acupuncture n=80</td><td>Sham n=82</td></tr>
<tr><td>PainVAS (T0–T1)</td><td>78</td><td>−41.2</td><td>−47.6 to −34.9</td><td>81</td><td>−27.0</td><td>−33.2 to −20.8</td><td>0.001</td><td>−41.0</td><td>−47.2 to −34.8</td><td>−27.1</td><td>−33.2 to −20.9</td><td>0.001</td><td>0.50</td><td>Medium</td></tr></table>"""
    outcomes = parse_primary_painvas(context).outcomes
    itt, pp = outcomes
    assert (itt.analysis_population, itt.intervention_n, itt.control_n) == ("ITT", 80, 82)
    assert (pp.analysis_population, pp.intervention_n, pp.control_n) == ("PP", 78, 81)
    assert itt.outcome_observation_timepoint_value == 10
    assert itt.evidence[-1].support_type == "derived"


def test_flow_schema_preserves_timepoint_counts_and_structured_reasons() -> None:
    flow = ConsortFlowExtraction.model_validate({
        "screened_n": 189,
        "randomized_n": 164,
        "arms": [{
            "arm_name": "Individualised Acupuncture",
            "randomized_n": 82,
            "dropout_reasons": [{"stage": "T1", "n": 1, "reason": "work problem"}],
            "follow_up_completed_n": {"10_weeks": 78},
        }],
        "evidence": [{"source": "figure", "quote": "164 randomised"}],
    })
    assert flow.arms[0].follow_up_completed_n["10_weeks"] == 78


def test_flow_reconciliation_does_not_sum_stage_missing_as_dropout() -> None:
    flow = ConsortFlowExtraction.model_validate({
        "randomized_n": 164,
        "arms": [{
            "arm_name": "Individualised Acupuncture", "randomized_n": 82, "dropout_n": 9,
            "dropout_reasons": [
                {"stage": "at the outset", "n": 2, "reason": "lost from trial"},
                {"stage": "T1", "n": 2, "reason": "follow-up missing"},
                {"stage": "T2", "n": 3, "reason": "follow-up missing"},
            ],
        }, {"arm_name": "Sham Acupuncture", "randomized_n": 82}],
    })
    markdown = "Thus, the study comprised 80 participants in the IA group and 82 in the SA group."
    fixed = reconcile_flow(flow, markdown)
    assert fixed.arms[0].dropout_n == 2
    assert len(fixed.arms[0].other_missing_data) == 2
    assert (fixed.arms[0].received_n, fixed.arms[1].received_n) == (80, 82)


def test_flow_reconciliation_recovers_explicit_pretreatment_withdrawals() -> None:
    flow = ConsortFlowExtraction.model_validate({
        "randomized_n": 164,
        "arms": [
            {"arm_name": "Individualised Acupuncture", "randomized_n": 82},
            {"arm_name": "Sham Acupuncture", "randomized_n": 82},
        ],
    })
    markdown = (
        "Two withdrew before the start of treatment, one due to comorbidity "
        "(acute myocardial infarction) and the other due to a change of address. "
        "Thus, the study comprised 80 participants in the IA group and 82 in the SA group."
    )
    fixed = reconcile_flow(flow, markdown)
    assert fixed.arms[0].dropout_n == 2
    assert len(fixed.arms[0].dropout_reasons) == 2


def test_primary_analysis_can_be_derived_from_abstract_primary_result() -> None:
    risk = RiskOfBiasExtraction()
    context = "The primary outcome was pain. Results Intention-to-treat analysis revealed a greater decrease."
    normalized = _normalize_primary_analysis(risk, context)
    assert normalized.primary_analysis == 1
    assert normalized.evidence[-1].support_type == "derived"


def test_crossref_enrichment_uses_doi_metadata(monkeypatch, tmp_path: Path) -> None:
    assert extract_doi("doi: 10.1136/acupmed-2015-010950.") == "10.1136/acupmed-2015-010950"
    monkeypatch.setattr("mineru_method.bibliography.lookup_crossref", lambda title, doi=None: {
        "lookup_method": "doi", "match_score": 1.0, "doi": doi, "title": title,
        "journal": "Acupuncture in Medicine", "publication_year": 2016,
        "publication_year_source": "published-print", "first_author": "Jorge Vas", "url": "https://doi.org/example",
    })
    enriched, lookup = enrich_metadata(
        MetadataExtraction(
            title="Acupuncture for fibromyalgia in primary care: a randomised controlled trial",
            publication_year=2015,
            journal="Acupunct Med",
        ),
        "doi: 10.1136/acupmed-2015-010950",
        tmp_path / "lookup.json",
    )
    assert (enriched.publication_year, enriched.journal) == (2016, "Acupuncture in Medicine")
    assert lookup["lookup_method"] == "doi"
