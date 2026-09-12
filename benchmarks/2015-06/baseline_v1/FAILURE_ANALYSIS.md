# Failure Analysis

正式分类来自 PR5B；六类 root-cause grouping 仅用于报告。结构事件、匹配实体字段错误与级联丢失分开，不相加当成独立 bugs。

## 1. Primary structural failures

{"COMPARATOR_SCOPE_UNRESOLVED": 12, "ENTITY_EXTRA": 10, "ENTITY_MISSING": 63}

| Entity | Classification | Details |
| --- | --- | --- |
| Intervention | ENTITY_MISSING | {"entity_type": "Intervention", "gold_entity_ids": ["2015-06-S1-I01"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-I01']; prediction candidates=[]"} |
| Intervention | ENTITY_MISSING | {"entity_type": "Intervention", "gold_entity_ids": ["2015-06-S1-I02"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-I02']; prediction candidates=[]"} |
| Intervention | ENTITY_EXTRA | {"entity_type": "Intervention", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-I01"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Intervention | ENTITY_EXTRA | {"entity_type": "Intervention", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-I02"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Outcome | ENTITY_MISSING | {"entity_type": "Outcome", "gold_entity_ids": ["2015-06-S1-O01"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-O01']; prediction candidates=[]"} |
| Outcome | ENTITY_MISSING | {"entity_type": "Outcome", "gold_entity_ids": ["2015-06-S1-O02"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-O02']; prediction candidates=[]"} |
| Outcome | ENTITY_MISSING | {"entity_type": "Outcome", "gold_entity_ids": ["2015-06-S1-O03"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-O03']; prediction candidates=[]"} |
| Outcome | ENTITY_MISSING | {"entity_type": "Outcome", "gold_entity_ids": ["2015-06-S1-O04"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-O04']; prediction candidates=[]"} |
| Outcome | ENTITY_EXTRA | {"entity_type": "Outcome", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-O01"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Outcome | ENTITY_EXTRA | {"entity_type": "Outcome", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-O02"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Outcome | ENTITY_EXTRA | {"entity_type": "Outcome", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-O03"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Outcome | ENTITY_EXTRA | {"entity_type": "Outcome", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-O04"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Outcome | ENTITY_EXTRA | {"entity_type": "Outcome", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-O05"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Comparison | ENTITY_MISSING | {"entity_type": "Comparison", "gold_entity_ids": ["2015-06-S1-C01"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-C01']; prediction candidates=[]"} |
| Comparison | ENTITY_MISSING | {"entity_type": "Comparison", "gold_entity_ids": ["2015-06-S1-C02"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-C02']; prediction candidates=[]"} |
| Comparison | ENTITY_MISSING | {"entity_type": "Comparison", "gold_entity_ids": ["2015-06-S1-C03"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-C03']; prediction candidates=[]"} |
| Comparison | ENTITY_EXTRA | {"entity_type": "Comparison", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-C01"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Comparison | ENTITY_EXTRA | {"entity_type": "Comparison", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-C02"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| Comparison | ENTITY_EXTRA | {"entity_type": "Comparison", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-C03"], "classification": "ENTITY_EXTRA", "diagnostic": null} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR01"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR01']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR02"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR02']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR03"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR03']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR04"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR04']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR05"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR05']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR06"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR06']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR07"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR07']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR08"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR08']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR09"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR09']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR10"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR10']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR11"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR11']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR12"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR12']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR13"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR13']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR14"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR14']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR15"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR15']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR16"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR16']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR17"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR17']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR18"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR18']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR19"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR19']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR20"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR20']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": ["2015-06-S1-AR21"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-AR21']; prediction candidates=[]"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR001"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR002"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR003"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR004"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR005"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR006"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR007"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR008"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR009"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR010"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR011"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR012"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR013"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR014"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ArmResult | ENTITY_MISSING | {"entity_type": "ArmResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-AR015"], "classification": "ENTITY_MISSING", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR01"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR01']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR02"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR02']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR03"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR03']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR04"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR04']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR05"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR05']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR06"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR06']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR07"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR07']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR08"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR08']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR09"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR09']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR10"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR10']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR11"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR11']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR12"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR12']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR13"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR13']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR14"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR14']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR15"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR15']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR16"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR16']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR17"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR17']; prediction candidates=[]"} |
| ComparisonResult | ENTITY_MISSING | {"entity_type": "ComparisonResult", "gold_entity_ids": ["2015-06-S1-CR18"], "prediction_entity_ids": [], "classification": "ENTITY_MISSING", "diagnostic": "Gold candidates=['2015-06-S1-CR18']; prediction candidates=[]"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR001"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR002"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR003"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR004"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR005"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR006"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR007"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR008"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR009"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR010"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR011"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |
| ComparisonResult | COMPARATOR_SCOPE_UNRESOLVED | {"entity_type": "ComparisonResult", "gold_entity_ids": [], "prediction_entity_ids": ["2015-06-S1-CR012"], "classification": "COMPARATOR_SCOPE_UNRESOLVED", "diagnostic": "Parent identity unmatched; no inferred binding"} |

## 2. Coverage / NOT_EXTRACTED

Matched-entity field counts: {"NOT_EXTRACTED": 32}

| Entity | Gold ID | Pred ID | Field | Gold status | Pred status | Gold value | Pred value | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Article | 2015-06 | 2015-06 | article.correspondence | PRESENT | UNRESOLVED | ["Address correspondence to: Dr. Jing Wang, Department of Rehabilitation Medicine, Second Hospital, Jiaxing University, Jiaxing 314000, China. Tel: +86-57382971932; Fax: +86-57382971932; E-mail: jingwangjw1@163.com"] | null | NOT_EXTRACTED |
| Article | 2015-06 | 2015-06 | article.doi | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Article | 2015-06 | 2015-06 | article.journal | PRESENT | UNRESOLVED | Int J Clin Exp Med | null | NOT_EXTRACTED |
| Study | 2015-06-S1 | 2015-06-S1 | study.allocation_concealment | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Study | 2015-06-S1 | 2015-06-S1 | study.allocation_concealment_code | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Study | 2015-06-S1 | 2015-06-S1 | study.countries | PRESENT | UNRESOLVED | ["China"] | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.analyzed_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.dropout_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.received_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Intervention | 2015-06-S1-I03 | 2015-06-S1-I03 | intervention.components | PRESENT | UNRESOLVED | ["surface-taped needle without insertion", "mock EA sound and blinking light"] | null | NOT_EXTRACTED |
| Intervention | 2015-06-S1-I03 | 2015-06-S1-I03 | intervention.duration_raw | PRESENT | UNRESOLVED | 3 months | null | NOT_EXTRACTED |
| Intervention | 2015-06-S1-I03 | 2015-06-S1-I03 | intervention.duration_unit | PRESENT | UNRESOLVED | months | null | NOT_EXTRACTED |

{"not_extracted": 32, "hard_not_extracted": 12, "supported_present_not_extracted": 3, "by_field": {"arm.analyzed_n": 3, "arm.dropout_n": 3, "arm.received_n": 3, "arm.role": 3, "article.correspondence": 1, "article.doi": 1, "article.journal": 1, "study.allocation_concealment": 1, "study.allocation_concealment_code": 1, "study.countries": 1, "study.design": 1, "study.missing_data_method": 1, "study.outcome_assessor_blinding": 1, "study.practitioner_blinding": 1, "study.primary_analysis_set": 1, "study.statistician_blinding": 1, "intervention.components": 1, "intervention.duration_raw": 1, "intervention.duration_unit": 1, "intervention.duration_value": 1, "intervention.frequency_raw": 1, "intervention.frequency_unit": 1, "intervention.frequency_value": 1, "intervention.total_sessions": 1}}

## 3. Wrong values

Matched-entity field counts: {"VALUE_WRONG": 4}

| Entity | Gold ID | Pred ID | Field | Gold status | Pred status | Gold value | Pred value | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Article | 2015-06 | 2015-06 | article.authors | PRESENT | PRESENT | ["Xu-Dong Gu", "Jing Wang", "Peng Yu", "Jian-Hua Li", "Yun-Hai Yao", "Jian-Ming Fu", "Zhong-Li Wang", "Ming Zeng", "Liang Li", "Ming Shi", "Wen-Ping Pan"] | ["Xu-Dong Gu"] | VALUE_WRONG |
| Study | 2015-06-S1 | 2015-06-S1 | study.condition | PRESENT | PRESENT | urinary retention after spinal cord injury | Spinal cord injury-induced urinary retention | VALUE_WRONG |
| Intervention | 2015-06-S1-I03 | 2015-06-S1-I03 | intervention.description | PRESENT | PRESENT | Needle taped to BL31–BL34 dermal surface without insertion; mock EA device emits sound/blinking light; same CIC procedure. | The sham procedure followed the EA method, but the needle was taped to the dermal surface of BL 31-34 without insertion. A mock EA instrument producing sound and blinking light was attached to facilitate blinding. | VALUE_WRONG |
| Intervention | 2015-06-S1-I03 | 2015-06-S1-I03 | intervention.kind | PRESENT | PRESENT | non-penetrating sham acupuncture | sham acupuncture | VALUE_WRONG |

Value errors by entity family: {"Article": 1, "Study": 1, "Intervention": 2}

## 4. Status errors

Matched-entity field counts: {}

| Entity | Gold ID | Pred ID | Field | Gold status | Pred status | Gold value | Pred value | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Top 10 FALSE_PRESENT fields (Gold NOT_REPORTED): []

## 5. Conflict handling

Matched-entity field counts: {"SOURCE_CONFLICT_DETECTED": 2}

| Entity | Gold ID | Pred ID | Field | Gold status | Pred status | Gold value | Pred value | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Arm | 2015-06-S1-A02 | 2015-06-S1-A02 | arm.randomized_n | SOURCE_CONFLICT | SOURCE_CONFLICT | null | null | SOURCE_CONFLICT_DETECTED |
| Arm | 2015-06-S1-A03 | 2015-06-S1-A03 | arm.randomized_n | SOURCE_CONFLICT | SOURCE_CONFLICT | null | null | SOURCE_CONFLICT_DETECTED |

{"gold_conflict_total": 2, "conflict_detected": 2, "conflict_missed": 0, "conflict_detection_rate": {"numerator": 2, "denominator": 2, "rate": 1.0}, "spurious_conflict_count": 0, "candidate_set_exact": 2, "candidate_set_evaluated": 2, "candidate_set_accuracy": {"numerator": 2, "denominator": 2, "rate": 1.0}}

[{"target_id": "Arm:2015-06-S1-A02:randomized_n", "classification": "SOURCE_CONFLICT_DETECTED", "candidate_set_match": true, "gold_candidates": [{"value": 38, "raw_value": "group 2 (EA combined with CIC treatment, n=38", "evidence_ids": ["E0023"]}, {"value": 34, "raw_value": "Group 2 (n=34)", "evidence_ids": ["E0024"]}], "prediction_candidates": [{"value": 38, "raw_value": "n=38", "evidence_ids": ["2015-06-S1-AD-E0015"]}, {"value": 34, "raw_value": "n=34", "evidence_ids": ["2015-06-S1-AD-E0016"]}]}, {"target_id": "Arm:2015-06-S1-A03:randomized_n", "classification": "SOURCE_CONFLICT_DETECTED", "candidate_set_match": true, "gold_candidates": [{"value": 34, "raw_value": "group 3 (sham acupuncture combined with CIC treatment, n=34", "evidence_ids": ["E0027"]}, {"value": 38, "raw_value": "Group 3 (n=38)", "evidence_ids": ["E0028"]}], "prediction_candidates": [{"value": 34, "raw_value": "n=34", "evidence_ids": ["2015-06-S1-AD-E0026"]}, {"value": 38, "raw_value": "n=38", "evidence_ids": ["2015-06-S1-AD-E0027"]}]}]

## 6. Evidence grounding

{"numerator": 17, "denominator": 17, "rate": 1.0}

只测结构引用闭环，不独立判定 PDF 语义。

| Entity | Gold ID | Pred ID | Field | Gold status | Pred status | Gold value | Pred value | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

## 7. Cascaded losses

548 fields were lost because their Gold entity did not match, not 548 independently diagnosed extraction bugs.

| Entity family | Cascaded fields |
| --- | --- |
| ArmResult | 294 |
| Comparison | 6 |
| ComparisonResult | 198 |
| Intervention | 22 |
| Outcome | 28 |

All formal field counts: {"ENTITY_MISSING": 548, "NOT_EXTRACTED": 32, "SOURCE_CONFLICT_DETECTED": 2, "VALUE_WRONG": 4}

Root-cause groups: {"STRUCTURE": {"entity_failure_events": 85, "cascaded_field_losses": 548}, "COVERAGE": 32, "VALUE": 4, "STATUS": 0, "CONFLICT": 0, "EVIDENCE": 0}

## 8. Most important next bottlenecks

1. STRUCTURE / Outcome: 9 entity failure events; 28 cascading field losses (not independent extraction bugs).
2. STRUCTURE / Comparison: 6 entity failure events; 6 cascading field losses (not independent extraction bugs).
3. STRUCTURE / Intervention: 4 entity failure events; 22 cascading field losses (not independent extraction bugs).
4. STRUCTURE / ArmResult: 36 entity failure events; 294 cascading field losses (not independent extraction bugs).
5. STRUCTURE / ComparisonResult: 30 entity failure events; 198 cascading field losses (not independent extraction bugs).

仅按观测数量与影响范围排序。本 PR 不给新规则、不优化、不重跑 production。

## Production coverage and provenance audit

{"source_integrity": {"verified_files": 90, "mismatches": []}, "raw_source_bundle_preserved": true, "arm_intervention_sample_flow_unchanged": true, "raw_outcome_count": 14, "table_outcome_count": 8, "narrative_outcome_count": 6, "row_coverage": [{"table_id": "table-1", "category": "baseline", "status": "skipped", "selected_rows": 0, "covered_row_ids": [], "missing_row_ids": [], "outcomes": 0, "column_map_count": 5}, {"table_id": "table-2", "category": "outcome", "status": "success", "selected_rows": 7, "covered_row_ids": ["table-2:r001", "table-2:r002", "table-2:r003", "table-2:r004", "table-2:r005", "table-2:r006", "table-2:r007"], "missing_row_ids": [], "outcomes": 8, "column_map_count": 0}, {"table_id": "narrative-results:p002-p005", "category": "outcome", "status": "success", "selected_rows": 4, "covered_row_ids": ["narrative-results:r002", "narrative-results:r003", "narrative-results:r004", "narrative-results:r005"], "missing_row_ids": [], "outcomes": 0, "column_map_count": 0}, {"table_id": "narrative-results:p006-p007", "category": "outcome", "status": "success", "selected_rows": 2, "covered_row_ids": ["narrative-results:r006", "narrative-results:r007"], "missing_row_ids": [], "outcomes": 6, "column_map_count": 0}], "coverage_note": "Coverage means selected rows acknowledged, not clinical completeness or correct values. Baseline table was skipped.", "documented_outcome_request_operations": 12, "outcome_request_status_counts": {"failed": 2, "success": 10}, "outcome_row_fallback_operations": 9, "topology_requests": 2, "topology_validation_or_transport_failures": 1, "arm_details_requests": 1, "arm_details_failures": 0, "postprocessed_records": 14, "postprocessing_part_status_counts": {"success": 2}, "complete_http_request_total": null, "request_count_note": "Counts are persisted stage operations, not a complete wire-level request trace; unrecorded transport attempts cannot be reconstructed.", "request_run_ids": ["NR"], "run_id_note": "Production manifest identifies retry06; row request manifests retain the production-written NR. Original artifacts were not edited.", "model_configuration": {"default": "gpt-5.6-sol", "trial_topology": "gpt-5.6-sol", "arm_details": "gpt-5.6-sol", "structured_metadata_protocol_risk": "gpt-5.6-sol", "table_classification": "gpt-5.6-sol", "outcomes_postprocess": "gpt-5.6-sol", "vlm": "gpt-5.6-sol", "retry": "gpt-5.6-sol"}, "api_mode": "responses", "gold_used_for_postprocess_comparison": false}

原文行覆盖不等于 Gold target coverage；已选行全部返回，也可能因组别、结局、比较语义缺失而得低分。
