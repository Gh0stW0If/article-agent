# PR5E-1 validation — 2026-09-12

Branch: `pr5e1-hybrid-semantic-evaluator`.
Base: `9fb22e9a3e2fe1acbe084cd15ba8254c67ece2c7` (PR #12).

This is an evaluator experiment, not a production rerun or an extraction-quality acceptance.
No production, Gold, Registry V3, PR5B evaluator or baseline snapshot was changed.

## Inputs and judge

- Frozen prediction SHA256: `ebe87d48a43c065f866b136854da65532d90dcf644e74fc2b33a68eb7cf53ffb`.
- Frozen PR5B evaluation SHA256: `4899ebde62cd0d4f4c42ecebdf2e387a82b518bf118f59293a5397f8bb64e73d`.
- Gold: `2015-06-gold-v1`, FROZEN.
- Judge: `gpt-5.6-sol`, existing Responses adapter, temperature 0, serial, 10 ms interval.
- Prompt: `SEMANTIC_JUDGE_PROMPT/1.0.0`.
- Prompt SHA256: `1c01740f6be269269da667c5a4c01841a77008255a3df72d0fe13aef70e55d95`.
- 42 unique live judgments: 22 entity, 13 result-identity field, 7 ordinary semantic field.
- Technical retries: 0. Technical failures: 0.
- No successful judgment was requested again for a different grade.

## Tests and replay

Runtime: `D:\Application\Anaconda\envs\Agent\python.exe`.

```powershell
python -m pytest -q tests/test_hybrid_semantic_evaluator.py
# 49 passed in 1.68s

python -m pytest -q
# 516 passed in 24.95s
```

PR5B was rerun and matched the original evaluation bytes:

- HARD exact: 6/271.
- Production coverage: 6/165.
- Supported value accuracy: 6/6.
- Conflict detection: 2/2; candidate set: 2/2.

After the live run, only report presentation was completed (including separate identity-rejection
audits). Judge responses and core scoring/matching results were not changed. The initial live
output is retained locally at `outputs/pr5e1_2015_06_hybrid_live_initial/`.

The finalized report was produced twice from those frozen judgments with no API client.
All seven artifacts in `hybrid_eval_v1/` are byte-identical between the two offline runs.
The snapshot regression also disables sockets and replaces the API client constructor with a
failing stub, then checks all seven files against the committed snapshot.

## Observed results, not performance targets

| Metric | Hybrid |
|---|---|
| HARD acceptable | 12/271 (4.43%) |
| Production coverage | 12/165 (7.27%) |
| Supported value accuracy | 12/12 (100%) |
| Status accuracy | 25/595 (4.20%) |
| Semantic acceptable accuracy | 3/7 (42.86%) |
| Semantic weighted score | 5/7 (71.43%) |

Ordinary semantic field grades: EXACT 2, EQUIVALENT 1, PARTIAL 4, ERROR 0, WRONG 0.
Result-identity grades are separate: EXACT 3, EQUIVALENT 0, PARTIAL 2, ERROR 4, WRONG 4.
The latter must not be hidden or treated as 13 additional ordinary field targets.

| Entity | PR5B matched | Hybrid matched | Gold count |
|---|---:|---:|---:|
| Intervention | 1 | 3 | 3 |
| Outcome | 0 | 3 | 4 |
| Comparison | 0 | 3 | 3 |
| ArmResult | 0 | 0 | 21 |
| ComparisonResult | 0 | 0 | 18 |

Eight entities and nine ordinary field targets were rescued (including structural/dependency
rescues, not only LLM wording rescues).

The bladder-balance construct remains SPLIT between two prediction Outcomes. It is not merged.
ArmResult `value_kind="other"` is not accepted as Gold `"mean"`. Missing comparison effect
identity and timepoint differences remain unresolved or rejected without inspecting result
values. No claim is made that all unmatched result values are wrong or were never extracted.

Review `hybrid_eval_v1/SEMANTIC_RESCUES.md` and `hybrid_eval_v1/SEMANTIC_DISAGREEMENTS.md`.
Stop here for human rubric review; no PR5D-2 or extraction optimization has been started.
