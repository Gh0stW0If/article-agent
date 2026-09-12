# Result surface projection

PR5F-2 repairs the representation of **existing source-backed result fields**.
It does not extract another PDF, discover/match entities, fill missing statuses,
change a public schema or request a semantic judgment.

## Source-only data flow

```text
Frozen raw ArticleExtraction + existing parsed table/source context
    -> explicit row / arm / comparison-column binding
    -> statistic and scalar surface normalization
    -> derived ArticleExtraction/2.0
    -> unchanged evaluator using frozen PR5F identity mappings and cache
```

`normalize_result_surfaces(prediction, source_context)` is a pure production
function. No Gold, expected value, evaluation target or cross-side mapping is
accepted. It returns the projected graph and three audit collections.

- `source_context.py`: adapts existing lossless blocks, complete columns/cells,
  adjacent table footnotes and explicit reporting statements. Does not modify
  MinerU/Docling or its parser.
- `statistic_surface.py`: recognizes mean only from explicit mean/SD context and
  compatible paired source cells. Bare numbers, n(%), median/IQR and mean/SE do
  not license mean. Missing scalar fields are not filled.
- `field_binding.py`: binds an existing comparison to an explicitly defined
  column, then reads the scalar. Numerical values never select a column.
  Duplicate/unresolved definitions, multiple eligible columns/source locations,
  ambiguous raw statistic roles and merged cells cause abstention.
- `surface_normalization.py`: only NFKC, case, whitespace and `vs`/`vs.`
  equivalence for complete binary contrast candidates. Participant order, names,
  timepoints and true source disagreements remain distinct.
- `projection.py`: creates an auditable copy using the existing canonical
  domain and derived Evidence. All original evidence objects remain unchanged.
  Original fields, source containers and conflict candidates are retained under
  entity `legacy_fields.result_surface.raw_fields`.

No source field is changed because it would improve its score. Missing
`p_value_comparator`, CI/effect, n and missing Result records are not populated.
For current P-only records, the local source scalar and operator are preserved
in the binding; the canonical surface omits the statistical `P` prefix.
Re-projecting the same graph still binds its immutable original source.

## Offline acceptance

Use the mandatory Agent environment:

```powershell
D:\Application\Anaconda\envs\Agent\python.exe scripts/pr5f2_result_surface_acceptance.py
```

Default input is the frozen `SOURCE_SURFACE_CONTEXT.json` snapshot. The runner
reproduces all predecessor artifacts before projection, disables network sockets,
reuses the 76-entry successful judgment cache, and passes the unchanged identity
mapping to the unchanged Hybrid engine. A cache miss raises, never creates a
fake judgment or falls through to an API.

Optional `--source-markdown <path>` rebuilds source context using the existing
table parser only, requiring the frozen source document hash. `--snapshot`
publishes to a new directory after two byte-identical replays and refuses to
overwrite a different snapshot.

Output: `benchmarks/2015-06/result_surface_v1/` (11 deterministic artifacts).
The benchmark-specific runner reads Gold only for scoring/audit and missingness
handoff, **after** the source-only projection.

## Validation — 2026-09-12

- Base main: `43278037eeea038018999ac3d3fbe181e51bca4e` (merged PR #15).
- Frozen baseline reproduced: HARD 64/271, coverage 72/165, supported value
  accuracy 64/72, status accuracy 97/595.
- Confirmed mean-as-other 12 → 0; raw mismatch 7 → 0; spurious conflict 2 → 0.
- Derived run: HARD 73/271; coverage 74/165; supported value accuracy 73/74;
  status accuracy 99/595. Existing correct fields do not regress.
- Coverage grows by two because two **already existing** supported contrast
  fields move from SOURCE_CONFLICT to PRESENT. This is the existing formula,
  not new extraction or a denominator change. The supported-value denominator
  becomes 74: 73 acceptable + 1 unchanged PARTIAL.
- ArmResult 12/21, ComparisonResult 10/18, Outcome 3/4 and identity-unresolved
  HARD 105 are unchanged. Real conflict detection and candidate set remain 2/2.
- 31 field-level normalization events, 42 scalar bindings. Four events belong to
  two existing unmatched narrative results and remain explicitly unscored; they
  do not create identity links or merge the bladder-balance Outcomes.
- Zero ambiguous bindings in this real fixture; generic negative tests exercise
  intentional abstention. Three n(%) statistic candidates stay `other`.
- All 76 historical judgments unchanged. Raw `other` ERROR/WRONG judgments are
  retained beside new source-supported `mean` deterministic fast-path results.
- NR/NA handoff: HARD 34/24; SOFT 104/9; all fields 138/33. No missingness changes.
- Focused **313 passed in 14.69 s**; full **650 passed in 65.20 s**.
- No pytest warnings, skips or xfails. API calls: **0**.
- All 11 final artifacts reproduced byte-for-byte in two offline runs.

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q `
  tests/test_result_surface.py tests/test_result_surface_acceptance.py `
  tests/test_result_identity_normalization.py tests/test_result_identity_acceptance.py `
  tests/test_incremental_adjudication.py tests/test_newly_scorable_acceptance.py `
  tests/test_hybrid_semantic_evaluator.py tests/test_entity_matcher.py `
  tests/test_evaluator_comparators.py tests/test_evaluator_engine.py `
  tests/test_evaluator_metrics.py tests/test_domain_models.py tests/test_outcome_canonicalizer.py
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q
```

Remaining HARD failures: 105 unresolved identity, 34 missing fields, 58 unresolved
NR/NA statuses, and 1 semantic PARTIAL timepoint. SOFT author/intervention
completeness and Outcome ambiguity remain out of scope.
