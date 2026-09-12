# All HARD targets

Includes all HARD entries for audit; REVIEW_REQUIRED entries are excluded from ordinary scoring.

| Entity | Gold ID | Pred ID | Field | Gold status | Pred status | Gold value | Pred value | Classification |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Study | 2015-06-S1 | 2015-06-S1 | study.randomized_n | PRESENT | PRESENT | 107 | 107 | EXACT |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.analyzed_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.dropout_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.label | PRESENT | PRESENT | CIC treatment | CIC treatment | EXACT |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.randomized_n | PRESENT | PRESENT | 35 | 35 | EXACT |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.received_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A01 | 2015-06-S1-A01 | arm.role | PRESENT | UNRESOLVED | active_control | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A02 | 2015-06-S1-A02 | arm.analyzed_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A02 | 2015-06-S1-A02 | arm.dropout_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A02 | 2015-06-S1-A02 | arm.label | PRESENT | PRESENT | EA combined with CIC treatment | EA combined with CIC treatment | EXACT |
| Arm | 2015-06-S1-A02 | 2015-06-S1-A02 | arm.randomized_n | SOURCE_CONFLICT | SOURCE_CONFLICT | null | null | SOURCE_CONFLICT_DETECTED |
| Arm | 2015-06-S1-A02 | 2015-06-S1-A02 | arm.received_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A02 | 2015-06-S1-A02 | arm.role | PRESENT | UNRESOLVED | experimental | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A03 | 2015-06-S1-A03 | arm.analyzed_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A03 | 2015-06-S1-A03 | arm.dropout_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A03 | 2015-06-S1-A03 | arm.label | PRESENT | PRESENT | sham acupuncture combined with CIC treatment | sham acupuncture combined with CIC treatment | EXACT |
| Arm | 2015-06-S1-A03 | 2015-06-S1-A03 | arm.randomized_n | SOURCE_CONFLICT | SOURCE_CONFLICT | null | null | SOURCE_CONFLICT_DETECTED |
| Arm | 2015-06-S1-A03 | 2015-06-S1-A03 | arm.received_n | NOT_REPORTED | UNRESOLVED | null | null | NOT_EXTRACTED |
| Arm | 2015-06-S1-A03 | 2015-06-S1-A03 | arm.role | PRESENT | UNRESOLVED | sham_control | null | NOT_EXTRACTED |
| Intervention | 2015-06-S1-I01 | null | intervention.name | PRESENT | null | Clean intermittent catheterization | null | ENTITY_MISSING |
| Intervention | 2015-06-S1-I02 | null | intervention.name | PRESENT | null | Electroacupuncture | null | ENTITY_MISSING |
| Intervention | 2015-06-S1-I03 | 2015-06-S1-I03 | intervention.name | PRESENT | PRESENT | Sham acupuncture | sham acupuncture | EXACT |
| Outcome | 2015-06-S1-O01 | null | outcome.name | PRESENT | null | Bladder balance | null | ENTITY_MISSING |
| Outcome | 2015-06-S1-O01 | null | outcome.role | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| Outcome | 2015-06-S1-O02 | null | outcome.name | PRESENT | null | CIC frequency | null | ENTITY_MISSING |
| Outcome | 2015-06-S1-O02 | null | outcome.role | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| Outcome | 2015-06-S1-O03 | null | outcome.name | PRESENT | null | Residual urine volume | null | ENTITY_MISSING |
| Outcome | 2015-06-S1-O03 | null | outcome.role | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| Outcome | 2015-06-S1-O04 | null | outcome.name | PRESENT | null | Voided volume | null | ENTITY_MISSING |
| Outcome | 2015-06-S1-O04 | null | outcome.role | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| Comparison | 2015-06-S1-C01 | null | comparison.contrast | PRESENT | null | Group 1 vs Group 2 | null | ENTITY_MISSING |
| Comparison | 2015-06-S1-C01 | null | comparison.relation | PRESENT | null | between-group | null | ENTITY_MISSING |
| Comparison | 2015-06-S1-C02 | null | comparison.contrast | PRESENT | null | Group 1 vs Group 3 | null | ENTITY_MISSING |
| Comparison | 2015-06-S1-C02 | null | comparison.relation | PRESENT | null | between-group | null | ENTITY_MISSING |
| Comparison | 2015-06-S1-C03 | null | comparison.contrast | PRESENT | null | Group 2 vs Group 3 | null | ENTITY_MISSING |
| Comparison | 2015-06-S1-C03 | null | comparison.relation | PRESENT | null | between-group | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR01 | null | armResult.denominator | PRESENT | null | 35 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR01 | null | armResult.event_count | PRESENT | null | 21 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR01 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR01 | null | armResult.raw_value | PRESENT | null | 21 (60.0) | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR01 | null | armResult.standard_deviation | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR01 | null | armResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR01 | null | armResult.value | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR02 | null | armResult.denominator | PRESENT | null | 34 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR02 | null | armResult.event_count | PRESENT | null | 29 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR02 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR02 | null | armResult.raw_value | PRESENT | null | 29 (85.29) | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR02 | null | armResult.standard_deviation | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR02 | null | armResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR02 | null | armResult.value | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR03 | null | armResult.denominator | PRESENT | null | 38 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR03 | null | armResult.event_count | PRESENT | null | 23 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR03 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR03 | null | armResult.raw_value | PRESENT | null | 23 (60.5) | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR03 | null | armResult.standard_deviation | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR03 | null | armResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR03 | null | armResult.value | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR04 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR04 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR04 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR04 | null | armResult.raw_value | PRESENT | null | 1.7±0.14 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR04 | null | armResult.standard_deviation | PRESENT | null | 0.14 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR04 | null | armResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR04 | null | armResult.value | PRESENT | null | 1.7 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR05 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR05 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR05 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR05 | null | armResult.raw_value | PRESENT | null | 0.35±0.07 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR05 | null | armResult.standard_deviation | PRESENT | null | 0.07 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR05 | null | armResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR05 | null | armResult.value | PRESENT | null | 0.35 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR06 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR06 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR06 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR06 | null | armResult.raw_value | PRESENT | null | 1.35±0.21 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR06 | null | armResult.standard_deviation | PRESENT | null | 0.21 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR06 | null | armResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR06 | null | armResult.value | PRESENT | null | 1.35 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR07 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR07 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR07 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR07 | null | armResult.raw_value | PRESENT | null | 301.0±8.48 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR07 | null | armResult.standard_deviation | PRESENT | null | 8.48 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR07 | null | armResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR07 | null | armResult.value | PRESENT | null | 301.0 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR08 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR08 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR08 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR08 | null | armResult.raw_value | PRESENT | null | 213.0±9.19 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR08 | null | armResult.standard_deviation | PRESENT | null | 9.19 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR08 | null | armResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR08 | null | armResult.value | PRESENT | null | 213.0 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR09 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR09 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR09 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR09 | null | armResult.raw_value | PRESENT | null | 295.0±9.89 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR09 | null | armResult.standard_deviation | PRESENT | null | 9.89 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR09 | null | armResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR09 | null | armResult.value | PRESENT | null | 295.0 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR10 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR10 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR10 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR10 | null | armResult.raw_value | PRESENT | null | 271.5±12.06 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR10 | null | armResult.standard_deviation | PRESENT | null | 12.06 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR10 | null | armResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR10 | null | armResult.value | PRESENT | null | 271.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR11 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR11 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR11 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR11 | null | armResult.raw_value | PRESENT | null | 375.5±10.06 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR11 | null | armResult.standard_deviation | PRESENT | null | 10.06 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR11 | null | armResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR11 | null | armResult.value | PRESENT | null | 375.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR12 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR12 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR12 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR12 | null | armResult.raw_value | PRESENT | null | 276.5±9.09 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR12 | null | armResult.standard_deviation | PRESENT | null | 9.09 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR12 | null | armResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR12 | null | armResult.value | PRESENT | null | 276.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR13 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR13 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR13 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR13 | null | armResult.raw_value | PRESENT | null | 193.5±10.6 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR13 | null | armResult.standard_deviation | PRESENT | null | 10.6 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR13 | null | armResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR13 | null | armResult.value | PRESENT | null | 193.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR14 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR14 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR14 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR14 | null | armResult.raw_value | PRESENT | null | 113.5±12.02 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR14 | null | armResult.standard_deviation | PRESENT | null | 12.02 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR14 | null | armResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR14 | null | armResult.value | PRESENT | null | 113.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR15 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR15 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR15 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR15 | null | armResult.raw_value | PRESENT | null | 176.5±9.19 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR15 | null | armResult.standard_deviation | PRESENT | null | 9.19 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR15 | null | armResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR15 | null | armResult.value | PRESENT | null | 176.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR16 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR16 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR16 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR16 | null | armResult.raw_value | PRESENT | null | 360.0±14.14 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR16 | null | armResult.standard_deviation | PRESENT | null | 14.14 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR16 | null | armResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR16 | null | armResult.value | PRESENT | null | 360.0 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR17 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR17 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR17 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR17 | null | armResult.raw_value | PRESENT | null | 471.0±10.4 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR17 | null | armResult.standard_deviation | PRESENT | null | 10.4 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR17 | null | armResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR17 | null | armResult.value | PRESENT | null | 471.0 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR18 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR18 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR18 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR18 | null | armResult.raw_value | PRESENT | null | 382.5±10.2 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR18 | null | armResult.standard_deviation | PRESENT | null | 10.2 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR18 | null | armResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR18 | null | armResult.value | PRESENT | null | 382.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR19 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR19 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR19 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR19 | null | armResult.raw_value | PRESENT | null | 566.0±8.9 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR19 | null | armResult.standard_deviation | PRESENT | null | 8.9 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR19 | null | armResult.timepoint | PRESENT | null | baseline | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR19 | null | armResult.value | PRESENT | null | 566.0 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR20 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR20 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR20 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR20 | null | armResult.raw_value | PRESENT | null | 591.0±9.4 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR20 | null | armResult.standard_deviation | PRESENT | null | 9.4 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR20 | null | armResult.timepoint | PRESENT | null | baseline | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR20 | null | armResult.value | PRESENT | null | 591.0 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR21 | null | armResult.denominator | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR21 | null | armResult.event_count | NOT_APPLICABLE | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR21 | null | armResult.n | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR21 | null | armResult.raw_value | PRESENT | null | 575.0±10.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR21 | null | armResult.standard_deviation | PRESENT | null | 10.5 | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR21 | null | armResult.timepoint | PRESENT | null | baseline | null | ENTITY_MISSING |
| ArmResult | 2015-06-S1-AR21 | null | armResult.value | PRESENT | null | 575.0 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR01 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR01 | null | comparisonResult.p_value | PRESENT | null | 0.019 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR01 | null | comparisonResult.p_value_comparator | PRESENT | null | = | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR01 | null | comparisonResult.raw_value | PRESENT | null | 0.019 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR01 | null | comparisonResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR02 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR02 | null | comparisonResult.p_value | PRESENT | null | 0.963 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR02 | null | comparisonResult.p_value_comparator | PRESENT | null | = | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR02 | null | comparisonResult.raw_value | PRESENT | null | 0.963 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR02 | null | comparisonResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR03 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR03 | null | comparisonResult.p_value | PRESENT | null | 0.019 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR03 | null | comparisonResult.p_value_comparator | PRESENT | null | = | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR03 | null | comparisonResult.raw_value | PRESENT | null | 0.019 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR03 | null | comparisonResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR04 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR04 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR04 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR04 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR04 | null | comparisonResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR05 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR05 | null | comparisonResult.p_value | PRESENT | null | 0.01 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR05 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR05 | null | comparisonResult.raw_value | PRESENT | null | <0.01 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR05 | null | comparisonResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR06 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR06 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR06 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR06 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR06 | null | comparisonResult.timepoint | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR07 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR07 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR07 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR07 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR07 | null | comparisonResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR08 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR08 | null | comparisonResult.p_value | PRESENT | null | 0.018 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR08 | null | comparisonResult.p_value_comparator | PRESENT | null | = | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR08 | null | comparisonResult.raw_value | PRESENT | null | 0.018 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR08 | null | comparisonResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR09 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR09 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR09 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR09 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR09 | null | comparisonResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR10 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR10 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR10 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR10 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR10 | null | comparisonResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR11 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR11 | null | comparisonResult.p_value | PRESENT | null | 0.107 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR11 | null | comparisonResult.p_value_comparator | PRESENT | null | = | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR11 | null | comparisonResult.raw_value | PRESENT | null | 0.107 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR11 | null | comparisonResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR12 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR12 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR12 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR12 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR12 | null | comparisonResult.timepoint | PRESENT | null | 1 month | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR13 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR13 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR13 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR13 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR13 | null | comparisonResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR14 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR14 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR14 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR14 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR14 | null | comparisonResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR15 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR15 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR15 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR15 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR15 | null | comparisonResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR16 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR16 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR16 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR16 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR16 | null | comparisonResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR17 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR17 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR17 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR17 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR17 | null | comparisonResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR18 | null | comparisonResult.estimate | NOT_REPORTED | null | null | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR18 | null | comparisonResult.p_value | PRESENT | null | 0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR18 | null | comparisonResult.p_value_comparator | PRESENT | null | < | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR18 | null | comparisonResult.raw_value | PRESENT | null | <0.001 | null | ENTITY_MISSING |
| ComparisonResult | 2015-06-S1-CR18 | null | comparisonResult.timepoint | PRESENT | null | 3 months | null | ENTITY_MISSING |
