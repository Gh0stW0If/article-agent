# PR5F-1 validation

Base: merged PR #13, `77f827089cfd98f178060312d3d83a188faa0136`.
Branch: `pr5f1-result-identity-normalization`.

## Executed checks

- Merged PR5E-1 baseline reproduced: all 7 published artifacts byte-identical.
- New identity acceptance: all 8 published artifacts byte-identical across two offline runs.
- Focused tests: **119 passed**, no warnings, skips or xfails reported.
- Full pytest: **575 passed**, no warnings, skips or xfails reported (27.45 s).
- Runtime: `D:\Application\Anaconda\envs\Agent\python.exe`.
- No production rerun, extraction API or online semantic judge calls.
- Protected input hashes unchanged; raw prediction serialize/revalidate unchanged.
- Original successful identity pairs and all previously value-correct targets preserved.
- Conflict detection and candidate-set exactness both remain **2/2**.

Commands:

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q `
  tests/test_result_identity_normalization.py tests/test_result_identity_acceptance.py `
  tests/test_entity_matcher.py tests/test_hybrid_semantic_evaluator.py
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q
D:\Application\Anaconda\envs\Agent\python.exe scripts/pr5f1_result_identity_acceptance.py `
  --source-context benchmarks/2015-06/result_identity_v1/SOURCE_IDENTITY_CONTEXT.json
```

## Interpretation

Identity matching recovered **22** existing results: ArmResult **0/21 → 12/21**,
ComparisonResult **0/18 → 10/18**. Outcome remains **3/4**.
Identity-unresolved HARD targets decreased **239 → 105**.

HARD acceptable is **12/271 → 43/271** and coverage is **12/165 → 72/165**.
These are gains from linking existing extraction, not new extraction.

Supported value accuracy changes **12/12 → 43/72**. The 72 exposed targets contain
43 acceptable values, 22 unjudged values (no frozen FIELD cache), and 7 strict
`ComparisonResult.raw_value` string mismatches. These 7 string mismatches are not
evidence that the clinical numerical values themselves are wrong.
Across all field families, there are 34 uncached FIELD targets.
Neither unjudged targets nor normalized identity labels are silently graded correct.

The intentionally unmatched Gold results comprise 6 missing source records,
6 Outcome-ambiguous results and 5 timepoint-contradictory results. Among the latter
are absent baseline records; an existing follow-up row cannot stand in for baseline.
Prediction has 5 Outcome-ambiguous results.

The table and narrative variants of the bladder-balance Outcome have no explicit
shared row/definition bridge in the supplied source context. They remain separate,
without using matching counts or percentages to force a merge.

Synthetic regression checks cover safe same-source Outcome grouping, contradictory
instrument/unit/source uncertainty, duplicate-child abstention, unmatched qualifiers,
ordinal/anchor normalization and numeric leakage isolation. Real-case spot checks and
per-result decisions are recorded in `REPORT.md` and the JSON audit artifacts.
