# PR5E-2 — Adjudicate newly scorable frozen fields

本次只补充已经存在、已经匹配但此前未冻结评分的字段判断，不代表 extraction 能力提高。

## Before → after

| Metric | PR5F-1 | PR5E-2 |
|---|---|---|
| hybrid_hard_acceptable | 43/271 (15.87%) | 64/271 (23.62%) |
| hybrid_production_coverage | 72/165 (43.64%) | 72/165 (43.64%) |
| hybrid_supported_value_accuracy | 43/72 (59.72%) | 64/72 (88.89%) |
| hybrid_status_accuracy | 97/595 (16.30%) | 97/595 (16.30%) |
| ArmResult matched | 12/21 | 12/21 |
| ComparisonResult matched | 10/18 | 10/18 |
| Outcome matched | 3/4 | 3/4 |
| Identity-unresolved HARD | 105 | 105 |
| Evaluation backlog | 34 | 0 |
| JUDGE_UNAVAILABLE fields | 34 | 0 |

基线真实的JUDGE_UNAVAILABLE为34个零调用占位，并非0；实际已尝试但失败的请求数另列technical_failures。
Coverage公式保持：SUPPORTED且Gold=PRESENT的165项中，已匹配且prediction=PRESENT的72项。补语义评分不改变它。

## Cache and calls

旧成功判断保留 42 条，逐条payload哈希不变。其中本次字段评分直接复用 7 条；其余历史身份/字段判断保留，不重算。
新增目标 34；API判断尝试 34；成功 34；技术失败 0；retry 0；未尝试 0。
Existing LiveSemanticJudge client.chat_json attempts; internal transport failover is not a separate semantic rejudgment
所有离线重放禁止API。成功grade无论好坏均只冻结一次，不因PARTIAL/ERROR/WRONG重试。

## New semantic quality by field family

```json
{
  "timepoint": {
    "EXACT": 17,
    "EQUIVALENT": 4,
    "PARTIAL": 1,
    "ERROR": 0,
    "WRONG": 0,
    "JUDGE_UNAVAILABLE": 0
  },
  "value_kind": {
    "EXACT": 0,
    "EQUIVALENT": 0,
    "PARTIAL": 0,
    "ERROR": 6,
    "WRONG": 6,
    "JUDGE_UNAVAILABLE": 0
  }
}
```

## Existing / new / combined grades

ENTITY判断使用SAME/DIFFERENT/AMBIGUOUS，不能混入五级grade；以下non_entity含历史RESULT_IDENTITY_FIELD，并另列FIELD-only分布。

```json
{
  "semantic_grades": {
    "existing_frozen_non_entity": {
      "EXACT": 5,
      "EQUIVALENT": 1,
      "PARTIAL": 6,
      "ERROR": 4,
      "WRONG": 4
    },
    "newly_adjudicated": {
      "EXACT": 17,
      "EQUIVALENT": 4,
      "PARTIAL": 1,
      "ERROR": 6,
      "WRONG": 6
    },
    "combined_non_entity": {
      "EXACT": 22,
      "EQUIVALENT": 5,
      "PARTIAL": 7,
      "ERROR": 10,
      "WRONG": 10
    }
  },
  "old_cache_judge_types": {
    "ENTITY": 22,
    "FIELD": 7,
    "RESULT_IDENTITY_FIELD": 13
  },
  "existing_field_only_grades": {
    "EXACT": 2,
    "EQUIVALENT": 1,
    "PARTIAL": 4,
    "ERROR": 0,
    "WRONG": 0
  },
  "combined_field_only_grades": {
    "EXACT": 19,
    "EQUIVALENT": 5,
    "PARTIAL": 5,
    "ERROR": 6,
    "WRONG": 6
  }
}
```

## Supported value accuracy denominator breakdown

```json
{
  "fully_acceptable": 64,
  "partial": 1,
  "error": 0,
  "wrong": 0,
  "deterministic_mismatch": 7,
  "judge_unavailable": 0
}
```

## Frozen boundaries and remaining blockers

Gold、Registry、prediction、原始字段值/状态/证据、抽取prompt、semantic prompt、model/temperature、identity normalizer/linker、PR5F mappings、评分口径均未修改。
value_kind仍以Gold=mean / Prediction=other送评，未替换为投影层的mean。保留原FIELD证据输入，冻结rubric禁止用证据修补缺失预测内容；未增加任何提示指令。
7个raw字符串不一致、2个假SOURCE_CONFLICT、58个NR/NA缺失状态均未交给judge。

```json
{
  "identity_unresolved": 105,
  "field_or_status_unresolved": 92,
  "raw_deterministic_mismatch": 7,
  "spurious_source_conflict": 2
}
```

新增PARTIAL见NEW_SEMANTIC_PARTIALS.md；ERROR/WRONG见NEW_SEMANTIC_ERRORS.md。
PR5G_EXTRACTION_CANDIDATES.json只收新增PARTIAL/ERROR/WRONG，不混入身份或缺失状态等问题。
