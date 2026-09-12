# Semantic rescues — manual review required

Counts include structural-context/dependency rescue as well as LLM wording rescue; method is explicit.

## Entity Intervention: 2015-06-S1-I01 → 2015-06-S1-I01

Old: ['MISSING', 'EXTRA']; New: MATCHED; method: STRUCTURAL_CONTEXT; field grade: N/A.
Gold: {"name": {"status": "PRESENT", "value": "Clean intermittent catheterization", "raw_value": "Clean intermittent catheterization (CIC)", "evidence_ids": ["E0029"], "conflict_candidates": []}, "kind": {"status": "PRESENT", "value": "catheterization", "raw_value": "Before catheter placement, behavioral interventions (such as fluid schedules and regular voiding attempts) were firstly performed to induce emiction.", "evidence_ids": ["E0030"], "conflict_candidates": []}}
Prediction: {"name": {"status": "PRESENT", "value": "clean intermittent catheterization (CIC)", "raw_value": "clean intermittent catheterization (CIC)", "evidence_ids": ["2015-06-S1-AD-E0001", "2015-06-S1-AD-E0009", "2015-06-S1-AD-E0010", "2015-06-S1-AD-E0020", "2015-06-S1-AD-E0021"], "conflict_candidates": []}, "kind": {"status": "PRESENT", "value": "catheterization", "raw_value": "catheterization", "evidence_ids": ["2015-06-S1-AD-E0002", "2015-06-S1-AD-E0011", "2015-06-S1-AD-E0012", "2015-06-S1-AD-E0022", "2015-06-S1-AD-E0023"], "conflict_candidates": []}}
Reason: Deterministic structural context; no LLM decision.

## Entity Intervention: 2015-06-S1-I02 → 2015-06-S1-I02

Old: ['MISSING', 'EXTRA']; New: MATCHED; method: STRUCTURAL_CONTEXT; field grade: N/A.
Gold: {"name": {"status": "PRESENT", "value": "Electroacupuncture", "raw_value": "electroacupuncture (EA)", "evidence_ids": ["E0038"], "conflict_candidates": []}, "kind": {"status": "PRESENT", "value": "electroacupuncture", "raw_value": "filiform needles (0.38 mm in diameter and 5 cm in length)", "evidence_ids": ["E0039"], "conflict_candidates": []}}
Prediction: {"name": {"status": "PRESENT", "value": "electroacupuncture (EA)", "raw_value": "electroacupuncture (EA)", "evidence_ids": ["2015-06-S1-AD-E0006"], "conflict_candidates": []}, "kind": {"status": "PRESENT", "value": "electroacupuncture", "raw_value": "electroacupuncture", "evidence_ids": ["2015-06-S1-AD-E0007"], "conflict_candidates": []}}
Reason: Deterministic structural context; no LLM decision.

## Entity Outcome: 2015-06-S1-O02 → 2015-06-S1-O02

Old: ['MISSING', 'EXTRA']; New: MATCHED; method: SEMANTIC_IDENTITY; field grade: N/A.
Gold: {"name": {"status": "PRESENT", "value": "CIC frequency", "raw_value": "CIC frequency (times/day)", "evidence_ids": ["E0068"], "conflict_candidates": []}, "instrument": {"status": "NOT_APPLICABLE", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}}
Prediction: {"name": {"status": "PRESENT", "value": "CIC frequency", "raw_value": "CIC frequency", "evidence_ids": ["2015-06-S1-O-E00008"], "conflict_candidates": []}, "instrument": {"status": "UNRESOLVED", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}}
Reason: Both identify CIC frequency as the measured outcome. The prediction omits the times/day unit and lower-is-better direction, but gives no conflicting identity information.

## Entity Outcome: 2015-06-S1-O03 → 2015-06-S1-O03

Old: ['MISSING', 'EXTRA']; New: MATCHED; method: SEMANTIC_IDENTITY; field grade: N/A.
Gold: {"name": {"status": "PRESENT", "value": "Residual urine volume", "raw_value": "Residual urine volume (ml) in the 1st month", "evidence_ids": ["E0071"], "conflict_candidates": []}, "instrument": {"status": "NOT_REPORTED", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}}
Prediction: {"name": {"status": "PRESENT", "value": "Residual urine volume", "raw_value": "Residual urine volume", "evidence_ids": ["2015-06-S1-O-E00009", "2015-06-S1-O-E00091", "2015-06-S1-O-E00133", "2015-06-S1-O-E00138"], "conflict_candidates": []}, "instrument": {"status": "UNRESOLVED", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}}
Reason: Both identify the outcome as residual urine volume. The prediction omits the gold unit and direction, but these omissions do not establish a different outcome entity.

## Entity Outcome: 2015-06-S1-O04 → 2015-06-S1-O04

Old: ['MISSING', 'EXTRA']; New: MATCHED; method: SEMANTIC_IDENTITY; field grade: N/A.
Gold: {"name": {"status": "PRESENT", "value": "Voided volume", "raw_value": "Voided volume (ml) in the 1st month", "evidence_ids": ["E0074"], "conflict_candidates": []}, "instrument": {"status": "NOT_REPORTED", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}}
Prediction: {"name": {"status": "PRESENT", "value": "Voided volume", "raw_value": "Voided volume", "evidence_ids": ["2015-06-S1-O-E00031", "2015-06-S1-O-E00051", "2015-06-S1-O-E00071", "2015-06-S1-O-E00107", "2015-06-S1-O-E00143", "2015-06-S1-O-E00148"], "conflict_candidates": []}, "instrument": {"status": "UNRESOLVED", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}}
Reason: Both identify the outcome as voided volume. The prediction omits the gold unit (ml) and direction, but these omissions do not establish a different outcome entity within the supplied structural context.

## Entity Comparison: 2015-06-S1-C01 → 2015-06-S1-C01

Old: ['MISSING', 'EXTRA']; New: MATCHED; method: STRUCTURAL_CONTEXT; field grade: N/A.
Gold: {"arm_ids": ["2015-06-S1-A01", "2015-06-S1-A02"], "relation": {"status": "PRESENT", "value": "between-group", "raw_value": "P1: group 1 vs. group 2", "evidence_ids": ["E0077"], "conflict_candidates": []}, "contrast": {"status": "PRESENT", "value": "Group 1 vs Group 2", "raw_value": "P1: group 1 vs. group 2", "evidence_ids": ["E0078"], "conflict_candidates": []}}
Prediction: {"arm_ids": ["2015-06-S1-A01", "2015-06-S1-A02"], "relation": {"status": "UNRESOLVED", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}, "contrast": {"status": "SOURCE_CONFLICT", "value": null, "raw_value": null, "evidence_ids": ["2015-06-S1-O-E00025", "2015-06-S1-O-E00047", "2015-06-S1-O-E00124", "2015-06-S1-O-E00134", "2015-06-S1-O-E00144"], "conflict_candidates": [{"value": "Group 1 vs Group 2", "raw_value": "Group 1 vs Group 2", "evidence_ids": ["2015-06-S1-O-E00025", "2015-06-S1-O-E00047"]}, {"value": "group 1 vs. group 2", "raw_value": "group 1 vs. group 2", "evidence_ids": ["2015-06-S1-O-E00124", "2015-06-S1-O-E00134", "2015-06-S1-O-E00144"]}]}}
Reason: Deterministic structural context; no LLM decision.

## Entity Comparison: 2015-06-S1-C02 → 2015-06-S1-C02

Old: ['MISSING', 'EXTRA']; New: MATCHED; method: STRUCTURAL_CONTEXT; field grade: N/A.
Gold: {"arm_ids": ["2015-06-S1-A01", "2015-06-S1-A03"], "relation": {"status": "PRESENT", "value": "between-group", "raw_value": "P2: group 1 vs. group 3", "evidence_ids": ["E0079"], "conflict_candidates": []}, "contrast": {"status": "PRESENT", "value": "Group 1 vs Group 3", "raw_value": "P2: group 1 vs. group 3", "evidence_ids": ["E0080"], "conflict_candidates": []}}
Prediction: {"arm_ids": ["2015-06-S1-A01", "2015-06-S1-A03"], "relation": {"status": "UNRESOLVED", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}, "contrast": {"status": "PRESENT", "value": "Group 1 vs Group 3", "raw_value": "Group 1 vs Group 3", "evidence_ids": ["2015-06-S1-O-E00027", "2015-06-S1-O-E00067"], "conflict_candidates": []}}
Reason: Deterministic structural context; no LLM decision.

## Entity Comparison: 2015-06-S1-C03 → 2015-06-S1-C03

Old: ['MISSING', 'EXTRA']; New: MATCHED; method: STRUCTURAL_CONTEXT; field grade: N/A.
Gold: {"arm_ids": ["2015-06-S1-A02", "2015-06-S1-A03"], "relation": {"status": "PRESENT", "value": "between-group", "raw_value": "P3: group 2 vs. group 3", "evidence_ids": ["E0081"], "conflict_candidates": []}, "contrast": {"status": "PRESENT", "value": "Group 2 vs Group 3", "raw_value": "P3: group 2 vs. group 3", "evidence_ids": ["E0082"], "conflict_candidates": []}}
Prediction: {"arm_ids": ["2015-06-S1-A02", "2015-06-S1-A03"], "relation": {"status": "UNRESOLVED", "value": null, "raw_value": null, "evidence_ids": [], "conflict_candidates": []}, "contrast": {"status": "SOURCE_CONFLICT", "value": null, "raw_value": null, "evidence_ids": ["2015-06-S1-O-E00029", "2015-06-S1-O-E00087", "2015-06-S1-O-E00129", "2015-06-S1-O-E00139", "2015-06-S1-O-E00149"], "conflict_candidates": [{"value": "Group 2 vs Group 3", "raw_value": "Group 2 vs Group 3", "evidence_ids": ["2015-06-S1-O-E00029", "2015-06-S1-O-E00087"]}, {"value": "group 2 vs. group 3", "raw_value": "group 2 vs. group 3", "evidence_ids": ["2015-06-S1-O-E00129", "2015-06-S1-O-E00139", "2015-06-S1-O-E00149"]}]}}
Reason: Deterministic structural context; no LLM decision.

## Study:2015-06-S1:condition

Gold (PRESENT): "urinary retention after spinal cord injury"
Prediction (PRESENT): "Spinal cord injury-induced urinary retention"
Old: VALUE_WRONG; New: SEMANTIC_EQUIVALENT; grade: EQUIVALENT
Method: LLM; judgment: J-c66ce22e7a64379b054f77160944e1d27b1d04ea62dc1d2820e640b1748a3e82
Reason: The prediction identifies the same clinical condition, urinary retention associated with spinal cord injury. "Spinal cord injury-induced" is equivalent in meaning to "after spinal cord injury."

## Intervention:2015-06-S1-I01:kind

Gold (PRESENT): "catheterization"
Prediction (PRESENT): "catheterization"
Old: ENTITY_MISSING; New: SEMANTIC_EXACT; grade: EXACT
Method: DETERMINISTIC_EXACT; judgment: None
Reason: Deterministic value/status comparison after structural or parent-identity rescue.

## Intervention:2015-06-S1-I01:name

Gold (PRESENT): "Clean intermittent catheterization"
Prediction (PRESENT): "clean intermittent catheterization (CIC)"
Old: ENTITY_MISSING; New: SEMANTIC_EXACT; grade: EXACT
Method: LLM; judgment: J-6aa9435b7e5e7666182e19b1287b1bb3d8c581157c04bbb936947c487da67368
Reason: The prediction identifies the same intervention, Clean intermittent catheterization, and adds the equivalent abbreviation '(CIC)'.

## Intervention:2015-06-S1-I02:kind

Gold (PRESENT): "electroacupuncture"
Prediction (PRESENT): "electroacupuncture"
Old: ENTITY_MISSING; New: SEMANTIC_EXACT; grade: EXACT
Method: DETERMINISTIC_EXACT; judgment: None
Reason: Deterministic value/status comparison after structural or parent-identity rescue.

## Intervention:2015-06-S1-I02:name

Gold (PRESENT): "Electroacupuncture"
Prediction (PRESENT): "electroacupuncture (EA)"
Old: ENTITY_MISSING; New: SEMANTIC_EXACT; grade: EXACT
Method: LLM; judgment: J-cb60b151fbbdcaf03f9f3f27b79cdb2e2fc22403cfaea9acee846bf52681291b
Reason: The prediction identifies the same intervention modality, electroacupuncture, with only the addition of the abbreviation and capitalization difference.

## Outcome:2015-06-S1-O02:name

Gold (PRESENT): "CIC frequency"
Prediction (PRESENT): "CIC frequency"
Old: ENTITY_MISSING; New: SEMANTIC_EXACT; grade: EXACT
Method: DETERMINISTIC_EXACT; judgment: None
Reason: Deterministic value/status comparison after structural or parent-identity rescue.

## Outcome:2015-06-S1-O03:name

Gold (PRESENT): "Residual urine volume"
Prediction (PRESENT): "Residual urine volume"
Old: ENTITY_MISSING; New: SEMANTIC_EXACT; grade: EXACT
Method: DETERMINISTIC_EXACT; judgment: None
Reason: Deterministic value/status comparison after structural or parent-identity rescue.

## Outcome:2015-06-S1-O04:name

Gold (PRESENT): "Voided volume"
Prediction (PRESENT): "Voided volume"
Old: ENTITY_MISSING; New: SEMANTIC_EXACT; grade: EXACT
Method: DETERMINISTIC_EXACT; judgment: None
Reason: Deterministic value/status comparison after structural or parent-identity rescue.

## Comparison:2015-06-S1-C02:contrast

Gold (PRESENT): "Group 1 vs Group 3"
Prediction (PRESENT): "Group 1 vs Group 3"
Old: ENTITY_MISSING; New: SEMANTIC_EXACT; grade: EXACT
Method: DETERMINISTIC_EXACT; judgment: None
Reason: Deterministic value/status comparison after structural or parent-identity rescue.
