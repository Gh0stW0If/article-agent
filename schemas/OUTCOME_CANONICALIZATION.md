# PR4 — Outcome and Result Canonicalization

## Scope and offline replay

`article_agent.outcome_canonicalizer.canonicalize_outcomes(article_id, topology,
arm_graph, source_outcomes)` is a pure function. It returns a new
`ArticleExtraction/2.0`, without changing any input. No API, parser, Gold or
Evaluator is called. The existing domain already contains every required result
field; the canonical JSON Schema does not change in this PR.

Inputs are a frozen PR2 topology, accepted PR3 arm graph and an ordered list of
raw outcome records. The raw `{outcomes: [...]}` module and legacy extraction
bundle are also accepted. Postprocessed/canonical-selection/Gold payloads are
not accepted. Replay starts from the original arm-only graph, not a previously
enriched result graph.

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -m article_agent.outcome_canonicalizer `
  --article-id 2015-06 `
  --topology PATH_TO_ACCEPTED_TOPOLOGY.json `
  --arm-graph PATH_TO_PR3_ARM_GRAPH.json `
  --source-outcomes PATH_TO_RAW_EXTRACTION.json `
  --output outputs/pr4_outcome_canonicalization/2015-06/article.canonical.json
```

## Data flow

Raw source records + frozen topology + PR3 graph
→ lexical Outcome identity and exact Arm binding
→ reported comparison participant binding
→ field observations with reciprocal evidence
→ merge equal observations / retain source conflicts
→ serialize and validate the complete canonical graph.

All original rows, including unresolved rows, are retained unchanged in
`article.legacy_fields.pr4_source_outcomes`. Warnings identify the zero-based
source index. Result `legacy_fields.source_observations` preserve source indexes,
tables and rows when multiple observations merge. No source row is discarded.

## Identity and references

- Outcome identity uses case/whitespace-normalized name plus instrument, never
  Arm or timepoint. Two limited grammatical rules normalize `frequency of X`
  to `X frequency` and remove a leading `(the) number of`. These identify a
  clinical outcome, not whether a result is a count, proportion or mean. No
  clinical synonym dictionary, fuzzy matching or instrument guessing is used.
- Missing instrument can join a name with exactly one reported instrument.
  If several instruments occur, the missing-instrument identity remains separate
  with a warning. Missing name cannot create an Outcome.
- IDs follow first appearance: `<study_id>-O01`, `-C01`, `-AR001`, `-CR001`.
  Stability means identical ordered inputs give identical IDs and output;
  reordering source records can change first-appearance IDs.
- Arm matching is exact after case/whitespace normalization, against frozen ID,
  label, source_label and aliases. Role is never an identity shortcut. Conflicting
  ID/label or ambiguous aliases produce warnings, not extra Arms or dangling
  ArmResults. Arm and Intervention entities are byte-for-byte structurally
  preserved; only Study.outcome_ids is extended on the Study.
- Result identity includes target, Outcome, reported timepoint representation,
  analysis set, statistic/effect kind, and reported/derived provenance. Unknown
  timepoints are additionally scoped to table/row to avoid false cross-row
  conflicts. Timepoint synonyms and numeric units are not inferred or converted.

## Source field mapping

| Canonical family | Accepted raw source fields |
|---|---|
| Outcome | outcome_name/name, measurement_instrument/instrument, outcome_role/role/record_role, direction, unit, scale_min, scale_max |
| Result time | timepoint or outcome_observation_timepoint_raw; corresponding *_value and *_unit; analysis_set/analysis_population |
| ArmResult | nested arm/arms; value/estimate, standard_deviation/sd, change_from_baseline/change, dispersion_lower/lower, dispersion_upper/upper, n, event_count, denominator, raw_value |
| Comparison | comparison or comparisons; explicit arm_ids/arm_labels or intervention_arm_id + comparator_arm_ids/control_arm_id; relation and contrast |
| ComparisonResult | effect_measure/between_group_measure/effect_size_name; estimate/outcome_between_group_estimate; confidence_interval_lower/upper or outcome_between_group_lower/upper; p_value/outcome_p_value; p_value_comparator/outcome_p_value_comparator; raw_value |

Numeric fields are copied from already structured records, not reconstructed
from cells. An existing uniquely arm-bound source cell can supply raw_value,
but `21 (60.0)` is not reparsed into an event count. Coded timepoint units are
retained as source strings rather than interpreted through an evaluator registry.
Numeric P strings such as `<0.001` preserve the threshold and comparator.

## Explicit comparisons only

An explicit complete `A vs B` string can identify a pair. Semicolon-separated
complete pairs can identify several reported comparisons. There is no
`combinations(arms, 2)` or inference from the count of arms. Explicit multi-arm
omnibus comparisons can retain all explicitly listed participants without
expanding them into pairwise comparisons.

Every comparison must have source evidence and a reported relation/contrast.
For multiple comparisons, statistics must be supplied within each comparison
object. A shared row P/estimate/CI is never copied across pairs. `P1/P2/P3` alone
does not establish participants. Such statistics remain in the raw source with
a warning; their canonical fields remain UNRESOLVED.

Equal observations merge evidence with `merge_field_observation`; disagreeing
values create SOURCE_CONFLICT. Candidate evidence remains reciprocal. A
comparison's participant order is retained (important for signed effects).
Reported and derived results never merge. Derived records need explicit
`derived=true` and a derivation; contradictory/missing provenance is warned and
not silently treated as a reported result.

## 2015-06 offline acceptance and limits

Using the accepted PR3 graph and the existing raw extraction's 10 source rows:

- 3 unchanged Arms, 4 Outcomes, 30 ArmResults.
- 2 explicitly reported comparisons: A01 vs A02 and A02 vs A03.
- 8 ComparisonResults; no inferred A01 vs A03 comparison.
- Source rows contain ambiguous P1/P2/P3 table columns and unscoped statistics
  for multi-comparison narrative rows. Their P values are preserved in raw
  records, **not assigned to individual ComparisonResults**. CI/effect values
  absent in the source remain UNRESOLVED, not invented.
- Some source Arm observations contain no numeric value, and some timepoints
  are NR or combined (`1 month; 3 months`). They remain unresolved/source-shaped.
  This PR does not repair missing extraction or parse new table content.

The offline replay demonstrates canonical structure and lossless retention,
not extraction completeness or clinical accuracy. Synthetic regression tests
separately verify correctly scoped effect/CI/P mapping and conflict merging.
