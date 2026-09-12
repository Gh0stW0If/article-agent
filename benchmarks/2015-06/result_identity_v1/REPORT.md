# PR5F-1 — Result Identity Normalization & Canonical Linking

PR5F-1 improved canonical result identity resolution. No extraction prompt was changed; newly scorable fields reflect recovery of previously unresolved result mappings rather than newly extracted source values.

原始 prediction、Gold、数值、状态、证据均未改写。只改变身份投影和安全关联。

## Before → after

| Metric | PR5E-1 | PR5F-1 |
|---|---|---|
| Arm matched | 3/3 | 3/3 |
| Intervention matched | 3/3 | 3/3 |
| Outcome matched | 3/4 | 3/4 |
| Comparison matched | 3/3 | 3/3 |
| ArmResult matched | 0/21 | 12/21 |
| ComparisonResult matched | 0/18 | 10/18 |
| hybrid_hard_acceptable | 12/271 (4.43%) | 43/271 (15.87%) |
| hybrid_production_coverage | 12/165 (7.27%) | 72/165 (43.64%) |
| hybrid_supported_value_accuracy | 12/12 (100.00%) | 43/72 (59.72%) |
| hybrid_status_accuracy | 25/595 (4.20%) | 97/595 (16.30%) |
| Identity-unresolved HARD | 239 | 105 |

Newly matched results: 22.
新关联后有 34 个字段缺少既有 FIELD Judge 缓存，标记 JUDGE_UNAVAILABLE；本次 API 调用为 0。
Identity EXACT/COMPATIBLE 不会自动成为字段 EXACT；raw value_kind=other、原始时间点和 missing statuses 仍按冻结评分规则评价。
因此 supported value accuracy 若下降，须区分新纳入的未评价字段与原有正确字段的退化；本次原有 value_acceptable=True 的字段全部保持正确。
以下分类解释新的 supported value accuracy 分母；VALUE_WRONG 明细单列，不能将 raw_value 的严格字符串不一致表述成已确认的临床数值错误。

```json
{
  "EXACT": 33,
  "JUDGE_UNAVAILABLE": 22,
  "SEMANTIC_EXACT": 10,
  "VALUE_WRONG": 7
}
```

### Newly visible deterministic mismatches (grading only, never identity inputs)

```json
[
  {
    "target_id": "ComparisonResult:2015-06-S1-CR10:raw_value",
    "field_id": "comparisonResult.raw_value",
    "gold_value": "<0.001",
    "prediction_value": "[\"271.5±12.06\", \"375.5±10.06\", \"276.5±9.09\", \"<0.001\", \"0.107\", \"<0.001\"]"
  },
  {
    "target_id": "ComparisonResult:2015-06-S1-CR11:raw_value",
    "field_id": "comparisonResult.raw_value",
    "gold_value": "0.107",
    "prediction_value": "[\"271.5±12.06\", \"375.5±10.06\", \"276.5±9.09\", \"<0.001\", \"0.107\", \"<0.001\"]"
  },
  {
    "target_id": "ComparisonResult:2015-06-S1-CR12:raw_value",
    "field_id": "comparisonResult.raw_value",
    "gold_value": "<0.001",
    "prediction_value": "[\"271.5±12.06\", \"375.5±10.06\", \"276.5±9.09\", \"<0.001\", \"0.107\", \"<0.001\"]"
  },
  {
    "target_id": "ComparisonResult:2015-06-S1-CR13:raw_value",
    "field_id": "comparisonResult.raw_value",
    "gold_value": "<0.001",
    "prediction_value": "[\"P<0.001\"]"
  },
  {
    "target_id": "ComparisonResult:2015-06-S1-CR15:raw_value",
    "field_id": "comparisonResult.raw_value",
    "gold_value": "<0.001",
    "prediction_value": "[\"P<0.001\"]"
  },
  {
    "target_id": "ComparisonResult:2015-06-S1-CR16:raw_value",
    "field_id": "comparisonResult.raw_value",
    "gold_value": "<0.001",
    "prediction_value": "[\"P<0.001\"]"
  },
  {
    "target_id": "ComparisonResult:2015-06-S1-CR18:raw_value",
    "field_id": "comparisonResult.raw_value",
    "gold_value": "<0.001",
    "prediction_value": "[\"P<0.001\"]"
  }
]
```

## Failure decomposition

| Category | Ordinary before | Ordinary after | HARD before | HARD after |
|---|---|---|---|---|
| A_NOT_EXTRACTED | 69 | 275 | 18 | 92 |
| B_STATUS_ERROR | 2 | 2 | 2 | 2 |
| C_WORDING_OR_IDENTITY_RESCUED | 9 | 40 | 6 | 37 |
| D_PARTIAL | 4 | 4 | 0 | 0 |
| E_SEMANTIC_ERROR_OR_WRONG | 0 | 0 | 0 | 0 |
| DETERMINISTIC_VALUE_ERROR | 1 | 8 | 0 | 7 |
| IDENTITY_UNRESOLVED | 499 | 221 | 239 | 105 |
| JUDGE_UNAVAILABLE | 0 | 34 | 0 | 22 |
| OTHER | 0 | 0 | 0 | 0 |

## Remaining unmatched reasons

Counts below are reason incidences, separated by Gold and Prediction; each result is fully listed in RESULT_IDENTITY_UNRESOLVED.json.

```json
{
  "Gold": {
    "MISSING_RESULT_IN_PREDICTION": 6,
    "OUTCOME_AMBIGUOUS": 6,
    "TIMEPOINT_CONTRADICTION": 5
  },
  "Prediction": {
    "OUTCOME_AMBIGUOUS": 5
  }
}
```

## Required outcome audit

- 2015-06-S1-O01: `Bladder balance patients` → `bladder balance`; canonical group `2015-06-S1-O01`; source blocks `['table-2|table-2:r002']`.
- 2015-06-S1-O02: `CIC frequency` → `cic frequency`; canonical group `2015-06-S1-O02`; source blocks `['table-2|table-2:r003']`.
- 2015-06-S1-O03: `Residual urine volume` → `residual urine volume`; canonical group `2015-06-S1-O03`; source blocks `['narrative-results:p006-p007|narrative-results:r007', 'table-2|table-2:r004', 'table-2|table-2:r006']`.
- 2015-06-S1-O04: `Voided volume` → `voided volume`; canonical group `2015-06-S1-O04`; source blocks `['narrative-results:p006-p007|narrative-results:r007', 'table-2|table-2:r005', 'table-2|table-2:r007']`.
- 2015-06-S1-O05: `Rate of bladder balance patients` → `bladder balance`; canonical group `2015-06-S1-O05`; source blocks `['narrative-results:p006-p007|narrative-results:r007']`.

```json
[
  {
    "outcome_ids": [
      "2015-06-S1-O01",
      "2015-06-S1-O05"
    ],
    "merge": false,
    "reason": "OUTCOME_NO_SHARED_SOURCE_BLOCK",
    "shared_source_blocks": []
  }
]
```

Different source blocks without an explicit common definition/row are not merged. No count/rate numeric agreement was consulted.

## Spot checks

| Category | Representative evidence |
|---|---|
| canonical exact timepoint | Gold 2015-06-S1-AR07: MATCHED; {'gold_id': '2015-06-S1-AR07', 'prediction_id': '2015-06-S1-AR004'} |
| normalized ordinal timepoint | Prediction 2015-06-S1-AR004: MATCHED; {'gold_id': '2015-06-S1-AR07', 'prediction_id': '2015-06-S1-AR004'} |
| anchor-compatible timepoint | Gold 2015-06-S1-CR13: MATCHED; {'gold_id': '2015-06-S1-CR13', 'prediction_id': '2015-06-S1-CR009'} |
| timepoint contradiction | Gold 2015-06-S1-AR19: MISSING; ['TIMEPOINT_CONTRADICTION'] |
| statistic kind rescued | Prediction 2015-06-S1-AR004: MATCHED; {'gold_id': '2015-06-S1-AR07', 'prediction_id': '2015-06-S1-AR004'} |
| unique result link | Gold 2015-06-S1-AR07: MATCHED; {'gold_id': '2015-06-S1-AR07', 'prediction_id': '2015-06-S1-AR004'} |
| ambiguous result intentionally abstained | No real case; generic regression fixture covers this case. |
| statistic kind unresolved | Naked numeric observation + `other` stays `other`; synthetic source-structure negative test. |
| outcome merged | Same source row + explicit construct + count/rate wrappers; synthetic generic fixture (no real forced merge). |
| outcome intentionally not merged | Table and narrative blocks do not supply a shared row/definition bridge; see outcome decisions above. |

## Normalization events

- 2015-06-S1-AR001: raw time `None` → `{'kind': 'unknown', 'value': None, 'unit': None, 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `event_count`; rules `['STATISTIC_KIND_FROM_COUNT_PERCENT_STRUCTURE']`.
- 2015-06-S1-AR002: raw time `None` → `{'kind': 'unknown', 'value': None, 'unit': None, 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `event_count`; rules `['STATISTIC_KIND_FROM_COUNT_PERCENT_STRUCTURE']`.
- 2015-06-S1-AR003: raw time `None` → `{'kind': 'unknown', 'value': None, 'unit': None, 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `event_count`; rules `['STATISTIC_KIND_FROM_COUNT_PERCENT_STRUCTURE']`.
- 2015-06-S1-AR004: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR005: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR006: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR007: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR008: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR009: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR010: raw time `3rd month` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR011: raw time `3rd month` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR012: raw time `3rd month` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR013: raw time `3d month` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR014: raw time `3d month` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-AR015: raw time `3d month` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `other` → `mean`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION', 'STATISTIC_KIND_FROM_MEAN_SD_STRUCTURE']`.
- 2015-06-S1-CR001: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR002: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR003: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR004: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR005: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR006: raw time `1st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR007: raw time `the 1 st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR008: raw time `the 1 st month` → `{'kind': 'follow_up', 'value': 1.0, 'unit': 'month', 'anchor': None, 'relation': None, 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_ORDINAL_FORMAT_NORMALIZED', 'TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR009: raw time `3 months after surgery` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': 'surgery', 'relation': 'after', 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR010: raw time `3 months after surgery` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': 'surgery', 'relation': 'after', 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR011: raw time `3 months after surgery` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': 'surgery', 'relation': 'after', 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_CANONICAL_DURATION']`.
- 2015-06-S1-CR012: raw time `3 months after surgery` → `{'kind': 'follow_up', 'value': 3.0, 'unit': 'month', 'anchor': 'surgery', 'relation': 'after', 'blockers': []}`; raw statistic `None` → `None`; rules `['TIMEPOINT_CANONICAL_DURATION']`.

## Limitations and follow-up (not implemented here)

- Missing baseline/CIC records are not created. Gold-only result targets retain explicit unmatched reasons.
- A statistic inferred safely for identity does not rewrite the raw source field for scoring.
- No new semantic judgment is made for newly scorable fields; these remain visibly unevaluated where necessary.
- Duplicate result candidates are not selected using their values, even if one value exactly equals Gold.
- Existing comparison SOURCE_CONFLICT due to punctuation/case remains a follow-up issue; parent binding was already available.
- No time-unit arithmetic, clinical synonym dictionary, effect-size calculation or automatic pairwise comparison generation.

No production rerun. No API. No numerical value was used for identity matching.
