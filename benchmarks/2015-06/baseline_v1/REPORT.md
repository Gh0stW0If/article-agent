# 2015-06 Real Baseline Benchmark

第一次 production baseline；未调优、未人工修改 prediction。

| Metric | Numerator | Denominator | Rate |
| --- | --- | --- | --- |
| hard_exact | 6 | 271 | 2.21% |
| production_coverage | 6 | 165 | 3.64% |
| supported_value_accuracy | 6 | 6 | 100.00% |
| status_accuracy | 15 | 595 | 2.52% |
| evidence_grounding | 17 | 17 | 100.00% |

注意：supported value accuracy 只评价已匹配且 PRESENT 的 supported 值；分母很小时，100% 不代表整篇提取正确。Entity 未匹配造成的级联丢失仍计入 HARD exact / coverage。

人工只读诊断见 [ROOT_CAUSE_NOTES.md](ROOT_CAUSE_NOTES.md)。它不改 prediction 或正式评分。

## Entity match summary

| Entity | Gold | Pred | Matched | Missing | Extra | Ambiguous Gold/Pred | Recall | Precision |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Article | 1 | 1 | 1 | 0 | 0 | 0/0 | 100.00% | 100.00% |
| Study | 1 | 1 | 1 | 0 | 0 | 0/0 | 100.00% | 100.00% |
| Arm | 3 | 3 | 3 | 0 | 0 | 0/0 | 100.00% | 100.00% |
| Intervention | 3 | 3 | 1 | 2 | 2 | 0/0 | 33.33% | 33.33% |
| Outcome | 4 | 5 | 0 | 4 | 5 | 0/0 | 0.00% | 0.00% |
| Comparison | 3 | 3 | 0 | 3 | 3 | 0/0 | 0.00% | 0.00% |
| ArmResult | 21 | 15 | 0 | 21 | 15 | 0/0 | 0.00% | 0.00% |
| ComparisonResult | 18 | 12 | 0 | 18 | 12 | 0/0 | 0.00% | 0.00% |

## Top failure classes

Field: {"ENTITY_MISSING": 548, "NOT_EXTRACTED": 32, "SOURCE_CONFLICT_DETECTED": 2, "VALUE_WRONG": 4}

Entity: {"COMPARATOR_SCOPE_UNRESOLVED": 12, "ENTITY_EXTRA": 10, "ENTITY_MISSING": 63}

## 2015-06 structural checks

1. Arms 数量：3；是否为三臂：True。
2. 冻结来源 Arm ID、实际名称与 components 如下（不按 Gold 改名）：

| Arm ID | Label | Intervention IDs | Component names |
| --- | --- | --- | --- |
| 2015-06-S1-A01 | CIC treatment | ["2015-06-S1-I01"] | ["clean intermittent catheterization (CIC)"] |
| 2015-06-S1-A02 | EA combined with CIC treatment | ["2015-06-S1-I02", "2015-06-S1-I01"] | ["electroacupuncture (EA)", "clean intermittent catheterization (CIC)"] |
| 2015-06-S1-A03 | sham acupuncture combined with CIC treatment | ["2015-06-S1-I03", "2015-06-S1-I01"] | ["sham acupuncture", "clean intermittent catheterization (CIC)"] |

3. 三组共同引用的 Intervention 实体（据实际结构显示，不做额外同义词匹配）：{"2015-06-S1-I01": "clean intermittent catheterization (CIC)"}
4. Outcome 数量：5；是否为 4：False。

## Outcome identity

| Side | Outcome ID | Name | Instrument status/value |
| --- | --- | --- | --- |
| Gold | 2015-06-S1-O01 | Bladder balance | {"status": "NOT_APPLICABLE", "value": null} |
| Gold | 2015-06-S1-O02 | CIC frequency | {"status": "NOT_APPLICABLE", "value": null} |
| Gold | 2015-06-S1-O03 | Residual urine volume | {"status": "NOT_REPORTED", "value": null} |
| Gold | 2015-06-S1-O04 | Voided volume | {"status": "NOT_REPORTED", "value": null} |
| Pred | 2015-06-S1-O01 | Bladder balance patients | {"status": "UNRESOLVED", "value": null} |
| Pred | 2015-06-S1-O02 | CIC frequency | {"status": "UNRESOLVED", "value": null} |
| Pred | 2015-06-S1-O03 | Residual urine volume | {"status": "UNRESOLVED", "value": null} |
| Pred | 2015-06-S1-O04 | Voided volume | {"status": "UNRESOLVED", "value": null} |
| Pred | 2015-06-S1-O05 | Rate of bladder balance patients | {"status": "UNRESOLVED", "value": null} |

Outcome matching records: [{"entity_type": "Outcome", "gold_entity_id": "2015-06-S1-O01", "prediction_entity_id": null, "match_status": "MISSING", "match_method": null, "identity_key": {}, "diagnostic": "Gold candidates=['2015-06-S1-O01']; prediction candidates=[]"}, {"entity_type": "Outcome", "gold_entity_id": "2015-06-S1-O02", "prediction_entity_id": null, "match_status": "MISSING", "match_method": null, "identity_key": {}, "diagnostic": "Gold candidates=['2015-06-S1-O02']; prediction candidates=[]"}, {"entity_type": "Outcome", "gold_entity_id": "2015-06-S1-O03", "prediction_entity_id": null, "match_status": "MISSING", "match_method": null, "identity_key": {}, "diagnostic": "Gold candidates=['2015-06-S1-O03']; prediction candidates=[]"}, {"entity_type": "Outcome", "gold_entity_id": "2015-06-S1-O04", "prediction_entity_id": null, "match_status": "MISSING", "match_method": null, "identity_key": {}, "diagnostic": "Gold candidates=['2015-06-S1-O04']; prediction candidates=[]"}, {"entity_type": "Outcome", "gold_entity_id": null, "prediction_entity_id": "2015-06-S1-O01", "match_status": "EXTRA", "match_method": null, "identity_key": {}, "diagnostic": null}, {"entity_type": "Outcome", "gold_entity_id": null, "prediction_entity_id": "2015-06-S1-O02", "match_status": "EXTRA", "match_method": null, "identity_key": {}, "diagnostic": null}, {"entity_type": "Outcome", "gold_entity_id": null, "prediction_entity_id": "2015-06-S1-O03", "match_status": "EXTRA", "match_method": null, "identity_key": {}, "diagnostic": null}, {"entity_type": "Outcome", "gold_entity_id": null, "prediction_entity_id": "2015-06-S1-O04", "match_status": "EXTRA", "match_method": null, "identity_key": {}, "diagnostic": null}, {"entity_type": "Outcome", "gold_entity_id": null, "prediction_entity_id": "2015-06-S1-O05", "match_status": "EXTRA", "match_method": null, "identity_key": {}, "diagnostic": null}]

5. 各 prediction Outcome 的时间点与来源行（用于检查 baseline、1 month、3 months 是否被拆成不同实体）：

| Outcome | ArmResult timepoints | Source rows |
| --- | --- | --- |
| 2015-06-S1-O01 | ["None"] | ["table-2:r002"] |
| 2015-06-S1-O02 | [] | [] |
| 2015-06-S1-O03 | ["1st month", "3rd month"] | ["table-2:r004", "table-2:r006"] |
| 2015-06-S1-O04 | ["1st month", "3d month"] | ["table-2:r005", "table-2:r007"] |
| 2015-06-S1-O05 | [] | [] |

## Comparison / result checks

6. 实际 Comparisons：3；正式 matched 数见 entity table，未自动补成三项。
7. 原始 P1/P2/P3 participant mapping 只依赖 production source；下面保留 comparison 原始显式关系供核对。

| Side | Comparison | Ordered arms | Relation | Contrast |
| --- | --- | --- | --- | --- |
| Gold | 2015-06-S1-C01 | ["2015-06-S1-A01", "2015-06-S1-A02"] | between-group | Group 1 vs Group 2 |
| Gold | 2015-06-S1-C02 | ["2015-06-S1-A01", "2015-06-S1-A03"] | between-group | Group 1 vs Group 3 |
| Gold | 2015-06-S1-C03 | ["2015-06-S1-A02", "2015-06-S1-A03"] | between-group | Group 2 vs Group 3 |
| Pred | 2015-06-S1-C01 | ["2015-06-S1-A01", "2015-06-S1-A02"] | null | null |
| Pred | 2015-06-S1-C02 | ["2015-06-S1-A01", "2015-06-S1-A03"] | null | Group 1 vs Group 3 |
| Pred | 2015-06-S1-C03 | ["2015-06-S1-A02", "2015-06-S1-A03"] | null | null |

Comparison relation/contrast 的完整状态（参与组正确并不保证身份字段匹配）：

| Comparison | Relation status | Contrast status | Contrast candidates |
| --- | --- | --- | --- |
| 2015-06-S1-C01 | UNRESOLVED | SOURCE_CONFLICT | ["Group 1 vs Group 2", "group 1 vs. group 2"] |
| 2015-06-S1-C02 | UNRESOLVED | PRESENT | [] |
| 2015-06-S1-C03 | UNRESOLVED | SOURCE_CONFLICT | ["Group 2 vs Group 3", "group 2 vs. group 3"] |

8. ArmResults=15；ComparisonResults=12。匹配/缺失/额外/歧义见 entity table，不合并为单一 result accuracy。
9. Sample-size source conflict：

| Arm | Status | Value | Candidates |
| --- | --- | --- | --- |
| 2015-06-S1-A01 | PRESENT | 35 | [] |
| 2015-06-S1-A02 | SOURCE_CONFLICT | null | [{"value": 38, "raw_value": "n=38", "evidence_ids": ["2015-06-S1-AD-E0015"]}, {"value": 34, "raw_value": "n=34", "evidence_ids": ["2015-06-S1-AD-E0016"]}] |
| 2015-06-S1-A03 | SOURCE_CONFLICT | null | [{"value": 34, "raw_value": "n=34", "evidence_ids": ["2015-06-S1-AD-E0026"]}, {"value": 38, "raw_value": "n=38", "evidence_ids": ["2015-06-S1-AD-E0027"]}] |

Conflict metrics: {"gold_conflict_total": 2, "conflict_detected": 2, "conflict_missed": 0, "conflict_detection_rate": {"numerator": 2, "denominator": 2, "rate": 1.0}, "spurious_conflict_count": 0, "candidate_set_exact": 2, "candidate_set_evaluated": 2, "candidate_set_accuracy": {"numerator": 2, "denominator": 2, "rate": 1.0}}

10. Assembly 没有生成 pairwise combinations；只调用现有 PR4 canonicalizer。是否多生成实体以 evaluator 的 Extra/ambiguous 记录为准；数量等于 C(3,2) 本身不是自动 all-pairs 的证据。

## Field-level layers

| Entity | Ordinary | Exact | Wrong value | Wrong status | Not extracted | Missing cascade |
| --- | --- | --- | --- | --- | --- | --- |
| Article | 7 | 3 | 1 | 0 | 3 | 0 |
| Study | 13 | 3 | 1 | 0 | 9 | 0 |
| Arm | 16 | 4 | 0 | 0 | 12 | 0 |
| Intervention | 33 | 1 | 2 | 0 | 8 | 22 |
| Outcome | 28 | 0 | 0 | 0 | 0 | 28 |
| Comparison | 6 | 0 | 0 | 0 | 0 | 6 |
| ArmResult | 294 | 0 | 0 | 0 | 0 | 294 |
| ComparisonResult | 198 | 0 | 0 | 0 | 0 | 198 |

## Production provenance / unresolved source warnings

生产原始模块完整保存在本地 output；canonicalization warnings（不作为第二套正式 taxonomy）：

- PR4 source[0]: comparison participants not uniquely explicit; P/effect retained without assignment; raw source retained
- PR4 source[1]: unknown/ambiguous arm binding NR (arm column 1); raw source retained
- PR4 source[1]: unknown/ambiguous arm binding NR (arm column 2); raw source retained
- PR4 source[1]: unknown/ambiguous arm binding NR (arm column 3); raw source retained
- PR4 source[2]: multiple explicit pairs: unscoped row-level statistics not copied to each pair; raw source retained
- PR4 source[7]: comparison participants not uniquely explicit; P/effect retained without assignment; raw source retained
- 2015-06:legacy:risk_of_bias: unresolved topology arm identity Group 2: electroacupuncture combined with clean intermittent catheterization.; source retained in legacy_fields
- 2015-06:legacy:risk_of_bias: unresolved topology arm identity Group 1: clean intermittent catheterization; group 3: sham acupuncture combined with clean intermittent catheterization.; source retained in legacy_fields
- 2015-06:legacy:consort_flow:arms:0: unresolved topology arm identity Group 1 (CIC treatment); source retained in legacy_fields
- 2015-06:legacy:consort_flow:arms:1: unresolved topology arm identity Group 2 (EA combined with CIC treatment); source retained in legacy_fields
- 2015-06:legacy:consort_flow:arms:2: unresolved topology arm identity Group 3 (sham acupuncture combined with CIC treatment); source retained in legacy_fields

## REVIEW_REQUIRED

centre_count、participant_blinding 是已审核后的不确定状态，不进入 ordinary HARD denominator，不解释为 Agent 错误。

## Evidence grounding

{"numerator": 17, "denominator": 17, "rate": 1.0}

EVIDENCE_UNGROUNDED: 0。这里只检查结构 evidence linkage，不独立重验 PDF 语义。

## Top 5 bottlenecks

1. STRUCTURE / Outcome: 9 entity failure events; 28 cascading field losses (not independent extraction bugs).
2. STRUCTURE / Comparison: 6 entity failure events; 6 cascading field losses (not independent extraction bugs).
3. STRUCTURE / Intervention: 4 entity failure events; 22 cascading field losses (not independent extraction bugs).
4. STRUCTURE / ArmResult: 36 entity failure events; 294 cascading field losses (not independent extraction bugs).
5. STRUCTURE / ComparisonResult: 30 entity failure events; 198 cascading field losses (not independent extraction bugs).

## Possible Gold Issues

None. Prediction 与 Gold 不同不构成修改 Gold 的理由。

## HARD targets

全部 HARD targets 见 HARD_TARGETS.md；REVIEW_REQUIRED 另外标明 excluded，不纳入普通评分。

## Production coverage and provenance audit

{"source_integrity": {"verified_files": 90, "mismatches": []}, "raw_source_bundle_preserved": true, "arm_intervention_sample_flow_unchanged": true, "raw_outcome_count": 14, "table_outcome_count": 8, "narrative_outcome_count": 6, "row_coverage": [{"table_id": "table-1", "category": "baseline", "status": "skipped", "selected_rows": 0, "covered_row_ids": [], "missing_row_ids": [], "outcomes": 0, "column_map_count": 5}, {"table_id": "table-2", "category": "outcome", "status": "success", "selected_rows": 7, "covered_row_ids": ["table-2:r001", "table-2:r002", "table-2:r003", "table-2:r004", "table-2:r005", "table-2:r006", "table-2:r007"], "missing_row_ids": [], "outcomes": 8, "column_map_count": 0}, {"table_id": "narrative-results:p002-p005", "category": "outcome", "status": "success", "selected_rows": 4, "covered_row_ids": ["narrative-results:r002", "narrative-results:r003", "narrative-results:r004", "narrative-results:r005"], "missing_row_ids": [], "outcomes": 0, "column_map_count": 0}, {"table_id": "narrative-results:p006-p007", "category": "outcome", "status": "success", "selected_rows": 2, "covered_row_ids": ["narrative-results:r006", "narrative-results:r007"], "missing_row_ids": [], "outcomes": 6, "column_map_count": 0}], "coverage_note": "Coverage means selected rows acknowledged, not clinical completeness or correct values. Baseline table was skipped.", "documented_outcome_request_operations": 12, "outcome_request_status_counts": {"failed": 2, "success": 10}, "outcome_row_fallback_operations": 9, "topology_requests": 2, "topology_validation_or_transport_failures": 1, "arm_details_requests": 1, "arm_details_failures": 0, "postprocessed_records": 14, "postprocessing_part_status_counts": {"success": 2}, "complete_http_request_total": null, "request_count_note": "Counts are persisted stage operations, not a complete wire-level request trace; unrecorded transport attempts cannot be reconstructed.", "request_run_ids": ["NR"], "run_id_note": "Production manifest identifies retry06; row request manifests retain the production-written NR. Original artifacts were not edited.", "model_configuration": {"default": "gpt-5.6-sol", "trial_topology": "gpt-5.6-sol", "arm_details": "gpt-5.6-sol", "structured_metadata_protocol_risk": "gpt-5.6-sol", "table_classification": "gpt-5.6-sol", "outcomes_postprocess": "gpt-5.6-sol", "vlm": "gpt-5.6-sol", "retry": "gpt-5.6-sol"}, "api_mode": "responses", "gold_used_for_postprocess_comparison": false}

原文行覆盖不等于 Gold target coverage；已选行全部返回，也可能因组别、结局、比较语义缺失而得低分。

## Authorized transport/configuration retry

本次使用用户授权的 Responses 通信适配与全 sol 配置；不是原始 main 的字节完全相同运行。提取算法、提示词、Gold、Registry、evaluator 未更改。

{"path": "src/article_agent/models.py", "sha256": "3adee63389441d527f4e558e61b633118ff9ca29e09cd8ff4576356ce7f726f4", "changed_files": [".env.example", "README.md", "src/article_agent/models.py", "tests/test_models.py"], "authorization": "User authorized Responses endpoint switch and all-sol full retry", "extraction_prompts_and_algorithms_changed": false}

{"attempt": 6, "authorization": "User requested retrying the full pending PR5D-1 workflow with gpt-5.6-sol for all model roles, following the authorized Responses endpoint switch.", "base_url": "https://api.lvping.cloud/v1", "api_mode": "responses", "fallback_urls": [], "model_configuration": {"ARTICLE_AGENT_MODEL": "gpt-5.6-sol", "ARTICLE_AGENT_TOPOLOGY_MODEL": "gpt-5.6-sol", "ARTICLE_AGENT_ARM_DETAILS_MODEL": "gpt-5.6-sol", "ARTICLE_AGENT_STRUCTURED_MODEL": "gpt-5.6-sol", "ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL": "gpt-5.6-sol", "ARTICLE_AGENT_VISION_MODEL": "gpt-5.6-sol", "ARTICLE_AGENT_BASIC_MATCH_MODEL": "gpt-5.6-sol", "ARTICLE_AGENT_RETRY_MODEL": "gpt-5.6-sol"}, "authorized_transport_file": "src/article_agent/models.py", "authorized_transport_sha256": "3adee63389441d527f4e558e61b633118ff9ca29e09cd8ff4576356ce7f726f4", "production_source_unchanged": false, "extraction_algorithms_and_prompts_unchanged": true, "gold_registry_evaluator_unchanged": true, "request_delay_seconds": 0.01, "serial": true, "credential_recorded": false, "previous_artifacts_preserved": true}
