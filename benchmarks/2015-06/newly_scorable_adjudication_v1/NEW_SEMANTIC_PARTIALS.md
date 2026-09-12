# NEW_SEMANTIC_PARTIALS

Only newly adjudicated semantic field errors; no identity/missingness/raw-binding cases.

## ComparisonResult:2015-06-S1-CR18:timepoint

```json
{
  "target_key": "ComparisonResult:2015-06-S1-CR18:timepoint",
  "entity": "ComparisonResult",
  "gold_entity_id": "2015-06-S1-CR18",
  "prediction_entity_id": "2015-06-S1-CR012",
  "field": "comparisonResult.timepoint",
  "gold": "3 months",
  "prediction": "3 months after surgery",
  "grade": "PARTIAL",
  "reason": "The prediction correctly identifies the 3-month timepoint but adds the specific reference event 'after surgery,' which is not stated in the gold value.",
  "source_evidence_reference": [
    {
      "evidence_id": "2015-06-S1-O-E00150",
      "quote": "and group 2 vs. group 3, P<0.001",
      "source_type": "markdown",
      "source_id": "narrative-results:r007",
      "page": null,
      "section": null,
      "table_id": "narrative-results:p006-p007",
      "row_id": "narrative-results:r007",
      "support_type": "direct",
      "derivation": null
    }
  ],
  "judgment_id": "J-35427128853bbba5f2d4f1a8136c0c60b5a438c63f5c8ec19e2fb0dae1fc3e32"
}
```
