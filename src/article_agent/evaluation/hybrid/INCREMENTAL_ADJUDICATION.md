# PR5E-2 incremental FIELD adjudication

This utility completes evaluation backlog; it does not change extraction, result
identity, missingness decisions, scoring rules, or the frozen semantic rubric.

1. Replay the frozen PR5F-1 baseline.
2. Build an explicit manifest from newly matched PRESENT/PRESENT semantic fields.
   Require an existing PR5F-1 unavailable artifact and an identical reconstructed
   FIELD request. Reject unresolved identity, missingness/conflict statuses,
   deterministic-only fields and targets that were already scorable.
3. Look up all historical successful judgments with the existing cache contract.
   The 42-entry historical cache remains unchanged; only seven FIELD judgments
   are directly needed in this fixed-mapping field replay.
4. Permit live requests only when the exact canonical input is in the manifest.
   Use the existing `LiveSemanticJudge`: gpt-5.6-sol, Responses, temperature 0,
   serial calls, 10 ms delay, two technical retries. Never retry for a better grade.
5. Store new observations in their own cache directory using exclusive file creation.
   Merge immutable old payloads plus new observations for replay. Historical ENTITY
   and RESULT_IDENTITY_FIELD judgments are preserved but not requested again.
6. Pass the frozen PR5F-1 entity mappings to the unchanged Hybrid scorer. No result
   normalizer/linker runs inside this field-adjudication step.
7. Emit a field-only PARTIAL/ERROR/WRONG handoff. Do not include identity, NR/NA,
   raw-binding or structural-conflict cases.

The benchmark-specific runner verifies the requested 34-target expectation before
constructing an API client. The general planner has no hardcoded target count.
The original FIELD evidence remains part of the unchanged request/cache contract.
`value_kind` is still `mean` versus `other`; projection-level `mean` is never used
as replacement prediction content for scoring.

## Commands

Use the mandatory Agent conda runtime from the repository root:

```powershell
D:\Application\Anaconda\envs\Agent\python.exe scripts/pr5e2_adjudicate_new_fields.py --dry-run
D:\Application\Anaconda\envs\Agent\python.exe scripts/pr5e2_adjudicate_new_fields.py --live
D:\Application\Anaconda\envs\Agent\python.exe scripts/pr5e2_adjudicate_new_fields.py `
  --judgments benchmarks/2015-06/newly_scorable_adjudication_v1/NEWLY_ADJUDICATED_JUDGMENTS.json
```

Only `--live` authorizes external judging, and only for manifest-eligible cache
misses. A second invocation reuses saved observations. Failed observations remain
explicit `JUDGE_UNAVAILABLE`, never WRONG. No new failure-retry/cache-overwrite
policy is introduced.

`--snapshot` publishes only the new benchmark directory after two byte-identical
offline replays. It refuses to overwrite a different existing snapshot. No old
benchmark, prediction, Gold, Registry, prompt or source evidence is modified.

## Frozen 2015-06 validation — 2026-09-12

- Base main: `fb587bd3cd328cf68efc8d41e73d0ae3792f9193` (merged PR #14).
- Baseline reproduced byte-for-byte: HARD 43/271, coverage 72/165,
  ArmResult 12/21, ComparisonResult 10/18, Outcome 3/4, identity-unresolved HARD 105.
- All 34 new FIELD targets succeeded in one judge attempt each; zero technical
  failures and zero retries. All 42 historical cache payloads are unchanged;
  seven historical FIELD judgments are directly reused.
- New grades: EXACT 17, EQUIVALENT 4, PARTIAL 1, ERROR 6, WRONG 6.
  Timepoints account for 17 EXACT, 4 EQUIVALENT and 1 PARTIAL; the 12
  `value_kind` pairs account for all 6 ERROR and 6 WRONG.
- HARD is now 64/271. Supported value accuracy is 64/72: 64 acceptable,
  1 partial, 7 deterministic mismatches, zero unavailable. The `value_kind`
  errors are not in this supported-value denominator.
- Coverage, status accuracy, entity mappings, conflict detection/candidate-set
  metrics and identity-unresolved counts are unchanged. Backlog is 34 → 0.
- Two offline replays reproduce all 11 published artifacts byte-for-byte;
  the regression test blocks network connections during replay.
- Focused tests: **139 passed in 5.85 s**.
- Full tests: **595 passed in 33.63 s**, no warnings, skips or xfails.

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q `
  tests/test_incremental_adjudication.py tests/test_newly_scorable_acceptance.py `
  tests/test_hybrid_semantic_evaluator.py tests/test_result_identity_normalization.py `
  tests/test_result_identity_acceptance.py tests/test_entity_matcher.py
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q
```

The remaining HARD blockers are 105 identity-unresolved, 92 field/status
unresolved, 7 raw mismatches, 2 spurious conflicts, and the newly judged
1 partial timepoint. The separate PR5G handoff contains only the 13 new semantic
PARTIAL/ERROR/WRONG observations. No extraction improvement is claimed.
