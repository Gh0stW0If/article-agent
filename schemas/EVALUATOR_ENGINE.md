# PR5B deterministic evaluator

## Inputs and API

`evaluate_article(prediction, gold, registry) -> EvaluationReportV2` is exported
from `article_agent.evaluation`. Inputs are copied and revalidated, never mutated.
The contracts remain ARTICLE_EXTRACTION/2.0, GOLD_STANDARD/2.0.0 and
EVALUATOR_FIELD_REGISTRY/3.0.0. Report version is EVALUATION_REPORT/2.0.0.
Both DRAFT and FROZEN Gold are accepted. Invalid contracts raise ValueError (or
Pydantic ValidationError); they do not produce an accuracy result. Article ID
mismatch is a contract error at the engine boundary, per specification section 76.
The lower-level entity matcher can describe mismatched Articles as missing/extra.

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -m article_agent.evaluation.engine --prediction tests/fixtures/evaluator/exact_prediction.json --gold tests/fixtures/evaluator/synthetic_gold.json --registry schemas/evaluator-field-registry-v3.json --output outputs/pr5b_synthetic/evaluation.json
```

Legacy EVALUATION_HEADERS, build_evaluation_rows, compute_evaluation_summary,
and write_evaluation_summary remain available. Production extraction does not
import the engine or read Gold.

## Entity matching

Dependencies are processed as Article, Study, Arm, Intervention, Outcome,
Comparison, ArmResult, ComparisonResult. Each category constructs a bipartite
candidate graph. Only singleton/singleton connected components match. Ambiguous
components never select the first candidate. Outcome 1:many is SPLIT; many:1 is
MERGED; many:many remains AMBIGUOUS. Events and affected entity IDs are retained.

- Article/Study: exact IDs; no array-position fallback.
- Arm: frozen ID first; otherwise unique normalized label or human Gold alias.
- Intervention: normalized name/Gold alias and unordered mapped linked Arms.
- Outcome: normalized name/Gold alias and instrument, within a matched Study.
- Comparison: ordered mapped Arms and relation/contrast; no pairwise expansion.
- ArmResult: mapped Arm/Outcome, timepoint, analysis set, value kind, provenance.
- ComparisonResult: mapped Comparison/Outcome, timepoint, analysis set,
  effect measure, provenance.

Outcome, Intervention and Result identities do not rely solely on ordinal IDs.
Timepoint uses PRESENT text, otherwise PRESENT numeric value + unit; no parsing
from evidence/raw text. Non-present instrument/analysis fields compare only as
the same explicit status, not as wildcards. Missing names do not establish
semantic identity. Child binding failures retain ARM_BINDING_UNRESOLVED,
COMPARATOR_SCOPE_UNRESOLVED or unmatched-parent diagnostics.

## Comparators

- EXACT_VALUE: typed equality, no automatic numeric parsing/case changes.
- NORMALIZED_STRING: NFKC, strip, casefold and collapse whitespace. Punctuation stays.
- NORMALIZED_NUMERIC: finite typed numbers; absolute tolerance default 1e-6,
  relative tolerance default 0; uses max(abs_tol, rel_tol * max(abs(a),abs(b))).
- ORDERED_LIST: normalized string elements in original order, preserving counts.
- UNORDERED_LIST: normalized string multiset, preserving counts.
- SET_EQUALITY: normalized string set, ignoring counts and order.
- SEMANTIC_CODE: canonical typed equality; no ontology/code remapping.
- STATUS_ONLY: low-level comparator accepts statuses, not clinical values.
- EVIDENCE_GROUNDED: low-level comparator accepts structurally computed flags.

The frozen Registry uses clinical value comparators. STATUS_ONLY and
EVIDENCE_GROUNDED are not replacements for those comparator assignments; the
engine separately compares statuses and evidence. Registry compatibility remains
enforced. Explicit normalization supports unicode_nfkc, strip, casefold and
collapse_whitespace only; unknown operations are contract errors.

## Field scoring and denominators

Targets come from Gold entities and enabled Registry fields, not prediction
coverage. Missing entities still contribute all their ordinary HARD targets.
HARD exact = entity matched + status matched + value comparator matched.
PRESENT, NOT_REPORTED and NOT_APPLICABLE are ordinary scorable Gold statuses.
SOURCE_CONFLICT and REVIEW_REQUIRED are excluded from the ordinary denominator.

- Hard exact: EXACT HARD targets / ordinary HARD Gold targets.
- Production coverage: matched prediction PRESENT / Gold PRESENT SUPPORTED.
- Supported value accuracy: comparator correct / matched prediction PRESENT
  among Gold PRESENT SUPPORTED targets.
- Status accuracy: status matched / all ordinary Gold targets.
- Evidence grounding and entity precision/recall are separate metrics.

Every rate carries numerator, denominator and rate; zero denominator gives null.
Entity and field failure counts are separate. Field results retain target ID,
both entity IDs, registry field ID, comparator, statuses, values, classification,
denominator flags and diagnostics. Reviewed Gold is unscored (null classification).

## Conflict and evidence

Gold conflicts yield detected/missed events, never ordinary hard success/failure.
Candidate values are compared using the field comparator with unordered
bipartite perfect matching; numeric tolerance cannot cause greedy candidate loss.
Null-only candidates cannot be value-compared and yield null candidate_set_match.
Spurious prediction conflicts on ordinary Gold are counted separately and fail
ordinary status/value scoring. Conflict results preserve each candidate/evidence.

REQUIRED_WHEN_PRESENT checks nonempty evidence IDs, existence and reciprocal
entity/field targets; conflict candidates are checked independently. Ungrounded
evidence adds EVIDENCE_UNGROUNDED without replacing a correct value classification.
Dangling references themselves are rejected during canonical input validation.

Evidence grounding in PR5B is structural linkage, not independent verification
against the PDF. No fuzzy/embedding/LLM matching. No clinical synonym matching.
No source retrieval, clinical evidence judgment, extraction optimization, real
Gold labeling, Excel migration or real benchmark is included.

## Reproducible synthetic acceptance

Run `python scripts/pr5b_synthetic_acceptance.py` in Agent. It uses the PR5A
synthetic fixture as a base and constructs all eight entity families. The 13
scenarios cover perfect, wrong value, false NR, unresolved, missing/extra entity,
Outcome ID reorder/split, reversed comparison, detected/missed/spurious conflict,
and missing evidence. REPORT.json retains complete per-target reports; REPORT.md
summarizes metrics and invariant checks. Neither includes timestamps/random IDs.
Run twice and compare bytes. Focused tests additionally cover merge, aliases,
ambiguous Arms, missing parents, derived provenance, numeric timepoint fallback,
all comparators/statuses, immutability, network prohibition and a 7-target HARD
denominator fixture (coverage 3/4, value accuracy 2/3).
