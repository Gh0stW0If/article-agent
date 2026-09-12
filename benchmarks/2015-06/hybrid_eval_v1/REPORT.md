# PR5E-1 — Frozen 2015-06 hybrid evaluator experiment

Same frozen prediction, no production rerun. Gold, Registry V3 and PR5B are unchanged.

## Deterministic PR5B baseline

| Metric | Unchanged result |
|---|---|
| hard_exact | 6 / 271 (2.21%) |
| production_coverage | 6 / 165 (3.64%) |
| supported_value_accuracy | 6 / 6 (100.00%) |
| Outcome matched | 0 / 4 |
| Comparison matched | 0 / 3 |
| Intervention matched | 1 / 3 |

## Hybrid semantic evaluation

| Metric | Result |
|---|---|
| hard_acceptable | 12 / 271 (4.43%) |
| production_coverage | 12 / 165 (7.27%) |
| supported_value_accuracy | 12 / 12 (100.00%) |
| status_accuracy | 25 / 595 (4.20%) |
| semantic_acceptable_accuracy | 3 / 7 (42.86%) |
| semantic_weighted_score | 5.0 / 7 (71.43%) |

| Entity | Deterministic matched | Hybrid matched | Gold | Ambiguous Gold |
|---|---|---|---|---|
| Article | 1 | 1 | 1 | 0 |
| Study | 1 | 1 | 1 | 0 |
| Arm | 3 | 3 | 3 | 0 |
| Intervention | 1 | 3 | 3 | 0 |
| Outcome | 0 | 3 | 4 | 1 |
| Comparison | 0 | 3 | 3 | 0 |
| ArmResult | 0 | 0 | 21 | 0 |
| ComparisonResult | 0 | 0 | 18 | 6 |

## Grade and technical audit

Grade distribution (successful LLM field targets only): {"EXACT": 2, "EQUIVALENT": 1, "PARTIAL": 4, "ERROR": 0, "WRONG": 0}
Result-identity grade distribution (unique pair judgments, separate denominator): {"EXACT": 3, "EQUIVALENT": 0, "PARTIAL": 2, "ERROR": 4, "WRONG": 4}
Deterministic semantic fast paths: 11.
Rescued entities: 8; rescued fields: 9.
LLM-confirmed ERROR/WRONG among old failures: 0.
Judge failures: 0; unavailable field targets: 0.
Semantic accuracy excludes technical failures; they are JUDGE_UNAVAILABLE, never WRONG. Fixed HARD/coverage denominators are unchanged. If any judge is unavailable, aggregate acceptable rates are conservative observed rates, not a resolved assessment of those targets.
Conflicts: {"gold_conflict_total": 2, "conflict_detected": 2, "conflict_detection_rate": {"numerator": 2, "denominator": 2, "rate": 1.0}, "candidate_set_exact": 2, "candidate_set_accuracy": {"numerator": 2, "denominator": 2, "rate": 1.0}}

## Why was the baseline low?

The following is a disjoint decomposition of prior ordinary-target failures. Identity-ambiguous targets are kept separate: absence of a match does NOT prove absence of extraction.

| Category | All ordinary old failures | HARD old failures |
|---|---|---|
| A — Matched entity, field not extracted | 69 | 18 |
| B — Status error | 2 | 2 |
| C — Wording/identity mismatch rescued | 9 | 6 |
| D — Partial, not fully correct | 4 | 0 |
| E — Related-but-incorrect or wrong semantic content | 0 | 0 |
| Deterministic value mismatch (not semantic) | 1 | 0 |
| Identity still unresolved (cannot assign to A–E) | 499 | 239 |
| Judge unavailable (not prediction wrong) | 0 | 0 |
| Other | 0 | 0 |

### Result identity blockers (not ordinary field grades)

Identity judgments do not use observed values, estimates, CI or P to choose a result. A semantic identity failure is not evidence that every downstream value is wrong.

| Identity field | Gold | Prediction | Grade | Reason |
|---|---|---|---|---|
| armResult.value_kind | "mean" | "other" | WRONG | "The reference specifies that the arm result is a mean, whereas the prediction labels it as \"other,\" which does not preserve the statistic type." |
| armResult.timepoint | "3 months" | "1st month" | ERROR | "Both values describe a follow-up timepoint, but the prediction gives the first month instead of 3 months, changing the result's temporal interpretation." |
| comparisonResult.timepoint | "3 months" | "3 months after surgery" | PARTIAL | "The prediction preserves the 3-month interval but adds the specific reference event 'after surgery,' which is not stated in the gold value and cannot be verified from the supplied information." |
| comparisonResult.timepoint | "1 month" | "3 months after surgery" | ERROR | "Both values describe postoperative follow-up timepoints, but the prediction reports 3 months after surgery rather than the gold timepoint of 1 month. This is a material contradiction in timing." |
| comparisonResult.timepoint | "3 months" | "1st month" | WRONG | "The prediction reports the result at 1 month, whereas the reference specifies 3 months. These are different follow-up intervals." |
| armResult.timepoint | "3 months" | "3rd month" | EXACT | "Both expressions denote the same follow-up timepoint of 3 months." |
| armResult.timepoint | "baseline" | "1st month" | WRONG | "The prediction identifies a follow-up timepoint at the first month, whereas the gold identifies the baseline timepoint. These are distinct observation times relative to the intervention/reference event." |
| armResult.timepoint | "1 month" | "1st month" | EXACT | "Both values identify the one-month observation timepoint; the ordinal wording does not change its meaning." |
| armResult.timepoint | "baseline" | "3rd month" | WRONG | "The prediction identifies a third-month follow-up timepoint, whereas the gold reference specifies baseline. These are different observation timepoints relative to the intervention/reference event." |
| armResult.timepoint | "3 months" | "3d month" | PARTIAL | "The prediction appears to refer to the third month and therefore captures the general follow-up timing, but “3d month” is malformed and does not clearly express the specified 3-month interval." |
| armResult.timepoint | "1 month" | "3d month" | ERROR | "The prediction specifies the third month, while the Gold timepoint is one month." |
| comparisonResult.timepoint | "1 month" | "1st month" | EXACT | "“1st month” and “1 month” identify the same reported timepoint; the difference is only phrasing." |
| armResult.timepoint | "1 month" | "3rd month" | ERROR | "Both values describe a follow-up timepoint, but they specify different intervals: 1 month versus the third month." |

Missing identity qualifiers and unresolved parent bindings are also retained. See the complete identity-only inputs below; these never include result values.

| Side | Entity | ID | Parent | Outcome | Timepoint (status/value) | Analysis set | Statistic kind | Derived |
|---|---|---|---|---|---|---|---|---|
| Gold | ArmResult | 2015-06-S1-AR01 | 2015-06-S1-A01 | 2015-06-S1-O01 | NOT_REPORTED: null | NOT_REPORTED: null | PRESENT: "event_count" | False |
| Gold | ArmResult | 2015-06-S1-AR02 | 2015-06-S1-A02 | 2015-06-S1-O01 | NOT_REPORTED: null | NOT_REPORTED: null | PRESENT: "event_count" | False |
| Gold | ArmResult | 2015-06-S1-AR03 | 2015-06-S1-A03 | 2015-06-S1-O01 | NOT_REPORTED: null | NOT_REPORTED: null | PRESENT: "event_count" | False |
| Gold | ArmResult | 2015-06-S1-AR04 | 2015-06-S1-A01 | 2015-06-S1-O02 | NOT_REPORTED: null | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR05 | 2015-06-S1-A02 | 2015-06-S1-O02 | NOT_REPORTED: null | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR06 | 2015-06-S1-A03 | 2015-06-S1-O02 | NOT_REPORTED: null | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR07 | 2015-06-S1-A01 | 2015-06-S1-O03 | PRESENT: "1 month" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR08 | 2015-06-S1-A02 | 2015-06-S1-O03 | PRESENT: "1 month" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR09 | 2015-06-S1-A03 | 2015-06-S1-O03 | PRESENT: "1 month" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR10 | 2015-06-S1-A01 | 2015-06-S1-O04 | PRESENT: "1 month" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR11 | 2015-06-S1-A02 | 2015-06-S1-O04 | PRESENT: "1 month" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR12 | 2015-06-S1-A03 | 2015-06-S1-O04 | PRESENT: "1 month" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR13 | 2015-06-S1-A01 | 2015-06-S1-O03 | PRESENT: "3 months" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR14 | 2015-06-S1-A02 | 2015-06-S1-O03 | PRESENT: "3 months" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR15 | 2015-06-S1-A03 | 2015-06-S1-O03 | PRESENT: "3 months" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR16 | 2015-06-S1-A01 | 2015-06-S1-O04 | PRESENT: "3 months" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR17 | 2015-06-S1-A02 | 2015-06-S1-O04 | PRESENT: "3 months" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR18 | 2015-06-S1-A03 | 2015-06-S1-O04 | PRESENT: "3 months" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR19 | 2015-06-S1-A01 | 2015-06-S1-O03 | PRESENT: "baseline" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR20 | 2015-06-S1-A02 | 2015-06-S1-O03 | PRESENT: "baseline" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ArmResult | 2015-06-S1-AR21 | 2015-06-S1-A03 | 2015-06-S1-O03 | PRESENT: "baseline" | NOT_REPORTED: null | PRESENT: "mean" | False |
| Gold | ComparisonResult | 2015-06-S1-CR01 | 2015-06-S1-C01 | 2015-06-S1-O01 | NOT_REPORTED: null | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR02 | 2015-06-S1-C02 | 2015-06-S1-O01 | NOT_REPORTED: null | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR03 | 2015-06-S1-C03 | 2015-06-S1-O01 | NOT_REPORTED: null | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR04 | 2015-06-S1-C01 | 2015-06-S1-O02 | NOT_REPORTED: null | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR05 | 2015-06-S1-C02 | 2015-06-S1-O02 | NOT_REPORTED: null | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR06 | 2015-06-S1-C03 | 2015-06-S1-O02 | NOT_REPORTED: null | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR07 | 2015-06-S1-C01 | 2015-06-S1-O03 | PRESENT: "1 month" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR08 | 2015-06-S1-C02 | 2015-06-S1-O03 | PRESENT: "1 month" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR09 | 2015-06-S1-C03 | 2015-06-S1-O03 | PRESENT: "1 month" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR10 | 2015-06-S1-C01 | 2015-06-S1-O04 | PRESENT: "1 month" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR11 | 2015-06-S1-C02 | 2015-06-S1-O04 | PRESENT: "1 month" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR12 | 2015-06-S1-C03 | 2015-06-S1-O04 | PRESENT: "1 month" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR13 | 2015-06-S1-C01 | 2015-06-S1-O03 | PRESENT: "3 months" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR14 | 2015-06-S1-C02 | 2015-06-S1-O03 | PRESENT: "3 months" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR15 | 2015-06-S1-C03 | 2015-06-S1-O03 | PRESENT: "3 months" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR16 | 2015-06-S1-C01 | 2015-06-S1-O04 | PRESENT: "3 months" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR17 | 2015-06-S1-C02 | 2015-06-S1-O04 | PRESENT: "3 months" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Gold | ComparisonResult | 2015-06-S1-CR18 | 2015-06-S1-C03 | 2015-06-S1-O04 | PRESENT: "3 months" | NOT_REPORTED: null | NOT_REPORTED: null | False |
| Prediction | ArmResult | 2015-06-S1-AR001 | 2015-06-S1-A01 | 2015-06-S1-O01 | UNRESOLVED: null | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR002 | 2015-06-S1-A02 | 2015-06-S1-O01 | UNRESOLVED: null | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR003 | 2015-06-S1-A03 | 2015-06-S1-O01 | UNRESOLVED: null | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR004 | 2015-06-S1-A01 | 2015-06-S1-O03 | PRESENT: "1st month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR005 | 2015-06-S1-A02 | 2015-06-S1-O03 | PRESENT: "1st month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR006 | 2015-06-S1-A03 | 2015-06-S1-O03 | PRESENT: "1st month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR007 | 2015-06-S1-A01 | 2015-06-S1-O04 | PRESENT: "1st month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR008 | 2015-06-S1-A02 | 2015-06-S1-O04 | PRESENT: "1st month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR009 | 2015-06-S1-A03 | 2015-06-S1-O04 | PRESENT: "1st month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR010 | 2015-06-S1-A01 | 2015-06-S1-O03 | PRESENT: "3rd month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR011 | 2015-06-S1-A02 | 2015-06-S1-O03 | PRESENT: "3rd month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR012 | 2015-06-S1-A03 | 2015-06-S1-O03 | PRESENT: "3rd month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR013 | 2015-06-S1-A01 | 2015-06-S1-O04 | PRESENT: "3d month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR014 | 2015-06-S1-A02 | 2015-06-S1-O04 | PRESENT: "3d month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ArmResult | 2015-06-S1-AR015 | 2015-06-S1-A03 | 2015-06-S1-O04 | PRESENT: "3d month" | UNRESOLVED: null | PRESENT: "other" | False |
| Prediction | ComparisonResult | 2015-06-S1-CR001 | 2015-06-S1-C01 | 2015-06-S1-O03 | PRESENT: "1st month" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR002 | 2015-06-S1-C02 | 2015-06-S1-O03 | PRESENT: "1st month" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR003 | 2015-06-S1-C03 | 2015-06-S1-O03 | PRESENT: "1st month" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR004 | 2015-06-S1-C01 | 2015-06-S1-O04 | PRESENT: "1st month" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR005 | 2015-06-S1-C02 | 2015-06-S1-O04 | PRESENT: "1st month" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR006 | 2015-06-S1-C03 | 2015-06-S1-O04 | PRESENT: "1st month" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR007 | 2015-06-S1-C01 | 2015-06-S1-O05 | PRESENT: "the 1 st month" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR008 | 2015-06-S1-C03 | 2015-06-S1-O05 | PRESENT: "the 1 st month" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR009 | 2015-06-S1-C01 | 2015-06-S1-O03 | PRESENT: "3 months after surgery" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR010 | 2015-06-S1-C03 | 2015-06-S1-O03 | PRESENT: "3 months after surgery" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR011 | 2015-06-S1-C01 | 2015-06-S1-O04 | PRESENT: "3 months after surgery" | UNRESOLVED: null | UNRESOLVED: null | False |
| Prediction | ComparisonResult | 2015-06-S1-CR012 | 2015-06-S1-C03 | 2015-06-S1-O04 | PRESENT: "3 months after surgery" | UNRESOLVED: null | UNRESOLVED: null | False |

## Required manual spot checks

| Target | Gold | Prediction | Old | Hybrid |
|---|---|---|---|---|
| Study:2015-06-S1:condition | PRESENT: "urinary retention after spinal cord injury" | PRESENT: "Spinal cord injury-induced urinary retention" | VALUE_WRONG | SEMANTIC_EQUIVALENT |
| Intervention:2015-06-S1-I01:name | PRESENT: "Clean intermittent catheterization" | PRESENT: "clean intermittent catheterization (CIC)" | ENTITY_MISSING | SEMANTIC_EXACT |
| Intervention:2015-06-S1-I02:name | PRESENT: "Electroacupuncture" | PRESENT: "electroacupuncture (EA)" | ENTITY_MISSING | SEMANTIC_EXACT |
| Intervention:2015-06-S1-I03:name | PRESENT: "Sham acupuncture" | PRESENT: "sham acupuncture" | EXACT | SEMANTIC_EXACT |
| Outcome:2015-06-S1-O01:instrument | NOT_APPLICABLE: null | None: null | ENTITY_MISSING | ENTITY_MISSING |
| Outcome:2015-06-S1-O01:name | PRESENT: "Bladder balance" | None: null | ENTITY_MISSING | ENTITY_MISSING |
| Outcome:2015-06-S1-O02:instrument | NOT_APPLICABLE: null | UNRESOLVED: null | ENTITY_MISSING | NOT_EXTRACTED |
| Outcome:2015-06-S1-O02:name | PRESENT: "CIC frequency" | PRESENT: "CIC frequency" | ENTITY_MISSING | SEMANTIC_EXACT |
| Outcome:2015-06-S1-O03:instrument | NOT_REPORTED: null | UNRESOLVED: null | ENTITY_MISSING | NOT_EXTRACTED |
| Outcome:2015-06-S1-O03:name | PRESENT: "Residual urine volume" | PRESENT: "Residual urine volume" | ENTITY_MISSING | SEMANTIC_EXACT |
| Outcome:2015-06-S1-O04:instrument | NOT_REPORTED: null | UNRESOLVED: null | ENTITY_MISSING | NOT_EXTRACTED |
| Outcome:2015-06-S1-O04:name | PRESENT: "Voided volume" | PRESENT: "Voided volume" | ENTITY_MISSING | SEMANTIC_EXACT |
| Comparison:2015-06-S1-C01:contrast | PRESENT: "Group 1 vs Group 2" | SOURCE_CONFLICT: null | ENTITY_MISSING | SOURCE_CONFLICT_SPURIOUS |
| Comparison:2015-06-S1-C01:relation | PRESENT: "between-group" | UNRESOLVED: null | ENTITY_MISSING | NOT_EXTRACTED |
| Comparison:2015-06-S1-C02:contrast | PRESENT: "Group 1 vs Group 3" | PRESENT: "Group 1 vs Group 3" | ENTITY_MISSING | SEMANTIC_EXACT |
| Comparison:2015-06-S1-C02:relation | PRESENT: "between-group" | UNRESOLVED: null | ENTITY_MISSING | NOT_EXTRACTED |
| Comparison:2015-06-S1-C03:contrast | PRESENT: "Group 2 vs Group 3" | SOURCE_CONFLICT: null | ENTITY_MISSING | SOURCE_CONFLICT_SPURIOUS |
| Comparison:2015-06-S1-C03:relation | PRESENT: "between-group" | UNRESOLVED: null | ENTITY_MISSING | NOT_EXTRACTED |

## Unresolved identity graph

- Outcome 2015-06-S1-O01: SPLIT; Gold candidates=['2015-06-S1-O01']; prediction candidates=['2015-06-S1-O01', '2015-06-S1-O05']; uncertain_edges=False; no best-candidate selection
- Outcome 2015-06-S1-O01: SPLIT; Gold candidates=['2015-06-S1-O01']; prediction candidates=['2015-06-S1-O01', '2015-06-S1-O05']; uncertain_edges=False; no best-candidate selection
- Outcome 2015-06-S1-O05: SPLIT; Gold candidates=['2015-06-S1-O01']; prediction candidates=['2015-06-S1-O01', '2015-06-S1-O05']; uncertain_edges=False; no best-candidate selection
- ComparisonResult 2015-06-S1-CR07: AMBIGUOUS; Gold candidates=['2015-06-S1-CR07']; prediction candidates=['2015-06-S1-CR001']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR001: AMBIGUOUS; Gold candidates=['2015-06-S1-CR07']; prediction candidates=['2015-06-S1-CR001']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR08: AMBIGUOUS; Gold candidates=['2015-06-S1-CR08']; prediction candidates=['2015-06-S1-CR002']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR002: AMBIGUOUS; Gold candidates=['2015-06-S1-CR08']; prediction candidates=['2015-06-S1-CR002']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR09: AMBIGUOUS; Gold candidates=['2015-06-S1-CR09']; prediction candidates=['2015-06-S1-CR003']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR003: AMBIGUOUS; Gold candidates=['2015-06-S1-CR09']; prediction candidates=['2015-06-S1-CR003']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR10: AMBIGUOUS; Gold candidates=['2015-06-S1-CR10']; prediction candidates=['2015-06-S1-CR004']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR004: AMBIGUOUS; Gold candidates=['2015-06-S1-CR10']; prediction candidates=['2015-06-S1-CR004']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR11: AMBIGUOUS; Gold candidates=['2015-06-S1-CR11']; prediction candidates=['2015-06-S1-CR005']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR005: AMBIGUOUS; Gold candidates=['2015-06-S1-CR11']; prediction candidates=['2015-06-S1-CR005']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR12: AMBIGUOUS; Gold candidates=['2015-06-S1-CR12']; prediction candidates=['2015-06-S1-CR006']; uncertain_edges=True; no best-candidate selection
- ComparisonResult 2015-06-S1-CR006: AMBIGUOUS; Gold candidates=['2015-06-S1-CR12']; prediction candidates=['2015-06-S1-CR006']; uncertain_edges=True; no best-candidate selection

## Reproducibility

Judge: {"model": "gpt-5.6-sol", "prompt_version": "SEMANTIC_JUDGE_PROMPT/1.0.0", "prompt_sha256": "1c01740f6be269269da667c5a4c01841a77008255a3df72d0fe13aef70e55d95", "temperature": 0}
Prediction SHA256: `ebe87d48a43c065f866b136854da65532d90dcf644e74fc2b33a68eb7cf53ffb`.
Successful judgments are never retried for their grade. Only technical retries are allowed.
Offline replay loads frozen judgments only; RUN_MANIFEST records protected input hashes.
Review SEMANTIC_RESCUES.md and SEMANTIC_DISAGREEMENTS.md before any extraction optimization.
