# PR5F-2 — Result Surface Binding & Statistic Representation

只修正已保存 source 的字段绑定和规范化表示。原始 prediction、Gold、Registry、prompt、76条历史judge cache、PR5F identity mappings 均未修改。

## Before → after

| Metric | Before | After |
|---|---:|---:|
| hybrid_hard_acceptable | 64/271 (23.62%) | 73/271 (26.94%) |
| hybrid_production_coverage | 72/165 (43.64%) | 74/165 (44.85%) |
| hybrid_supported_value_accuracy | 64/72 (88.89%) | 73/74 (98.65%) |
| hybrid_status_accuracy | 97/595 (16.30%) | 99/595 (16.64%) |
| ArmResult matched | 12/21 | 12/21 |
| ComparisonResult matched | 10/18 | 10/18 |
| Outcome matched | 3/4 | 3/4 |

## Confirmed issue-level results

- confirmed_mean_as_other: 12 → 0
  - ArmResult:2015-06-S1-AR07:value_kind: SEMANTIC_ERROR → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR08:value_kind: SEMANTIC_WRONG → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR09:value_kind: SEMANTIC_WRONG → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR10:value_kind: SEMANTIC_WRONG → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR11:value_kind: SEMANTIC_WRONG → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR12:value_kind: SEMANTIC_ERROR → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR13:value_kind: SEMANTIC_ERROR → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR14:value_kind: SEMANTIC_ERROR → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR15:value_kind: SEMANTIC_ERROR → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR16:value_kind: SEMANTIC_WRONG → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR17:value_kind: SEMANTIC_WRONG → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ArmResult:2015-06-S1-AR18:value_kind: SEMANTIC_ERROR → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
- raw_deterministic_mismatch: 7 → 0
  - ComparisonResult:2015-06-S1-CR10:raw_value: VALUE_WRONG → EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ComparisonResult:2015-06-S1-CR11:raw_value: VALUE_WRONG → EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ComparisonResult:2015-06-S1-CR12:raw_value: VALUE_WRONG → EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ComparisonResult:2015-06-S1-CR13:raw_value: VALUE_WRONG → EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ComparisonResult:2015-06-S1-CR15:raw_value: VALUE_WRONG → EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ComparisonResult:2015-06-S1-CR16:raw_value: VALUE_WRONG → EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - ComparisonResult:2015-06-S1-CR18:raw_value: VALUE_WRONG → EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
- spurious_source_conflict: 2 → 0
  - Comparison:2015-06-S1-C01:contrast: SOURCE_CONFLICT_SPURIOUS → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)
  - Comparison:2015-06-S1-C03:contrast: SOURCE_CONFLICT_SPURIOUS → SEMANTIC_EXACT (SOURCE_SUPPORTED_DERIVED_REPRESENTATION)

## Coverage formula and supported-value denominator

现有coverage计数SUPPORTED、Gold=PRESENT且Prediction=PRESENT的字段。假冲突转PRESENT后新增的覆盖项如下；没有增加Result、没有改分母，也未改任何指标公式。
```json
[
  "Comparison:2015-06-S1-C01:contrast",
  "Comparison:2015-06-S1-C03:contrast"
]
```
value_kind为SOFT/PARTIAL，不混入SUPPORTED value accuracy分母。

```json
{
  "before": {
    "fully_acceptable": 64,
    "partial": 1,
    "deterministic_mismatch": 7,
    "other": 0
  },
  "after": {
    "fully_acceptable": 73,
    "partial": 1,
    "deterministic_mismatch": 0,
    "other": 0
  }
}
```

## Source and historical judgment audit

Normalization events: 31; scalar bindings: 42; ambiguous abstentions: 0; unchanged statistic candidates: 3.
所有生产normalizer/binder均不接收Gold/期望值/跨侧mapping。先按parent comparison和脚注明确列身份，再读取单元格；不按数值搜索。保留完整raw container、原始证据、source row/column/header和选中scalar。
历史value_kind=other的ERROR/WRONG判断仍原样保留；新投影mean走现有evaluator的deterministic exact路径。不是judge改判。
source raw P<0.001仍保存在selected_source_scalar，operator=<、numeric_value=0.001，canonical scalar为<0.001。未填补UNRESOLVED的p_value_comparator。
source-only流程也记录了2条未匹配正文Result的局部P表示（额外4个raw/P字段事件），但其identity仍未解决，评价为UNMATCHED_NOT_SCORED，不进入得分。未合并Outcome或新增comparison。
未绑定的CI/effect等缺失字段不填充；多统计raw角色不明确时停止绑定。计数/百分比记录不被当作mean。
详见STATISTIC_REPRESENTATION_NORMALIZATION.json、FIELD_SOURCE_BINDINGS.json、SURFACE_CONFLICT_NORMALIZATION.json和BEFORE_AFTER_FIELD_EVALUATION.json。

## HARD failures and next-stage handoff

```json
{
  "before": {
    "identity_unresolved": 105,
    "field_missing": 34,
    "status_unresolved": 58,
    "raw_deterministic_mismatch": 7,
    "semantic_partial": 1,
    "semantic_error": 0,
    "semantic_wrong": 0,
    "source_conflict": 2,
    "other": 0
  },
  "after": {
    "identity_unresolved": 105,
    "field_missing": 34,
    "status_unresolved": 58,
    "raw_deterministic_mismatch": 0,
    "semantic_partial": 1,
    "semantic_error": 0,
    "semantic_wrong": 0,
    "source_conflict": 0,
    "other": 0
  }
}
```
105项identity unresolved、missing Result、bladder balance Outcome歧义、timepoint PARTIAL及SOFT作者/干预completeness不处理。
PR5G1_MISSINGNESS_INPUT.json只整理NR/NA对UNRESOLVED，不进行修复。原先34 NR / 24 NA是HARD口径；全字段清单另含SOFT项，按tier明确区分，并非本PR新增缺失：
```json
{
  "all": {
    "NOT_REPORTED": 138,
    "NOT_APPLICABLE": 33
  },
  "HARD": {
    "NOT_REPORTED": 34,
    "NOT_APPLICABLE": 24
  },
  "SOFT": {
    "NOT_REPORTED": 104,
    "NOT_APPLICABLE": 9
  }
}
```

API calls = 0。两个完整离线回放须逐字节一致后才发布新快照。

本 PR 的变化来自 deterministic source binding / statistic representation normalization，不来自重新 extraction、不来自新的 LLM judgment，也不代表原始 PDF 中出现了新的信息。
