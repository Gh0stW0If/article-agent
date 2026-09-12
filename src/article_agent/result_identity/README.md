# Result identity normalization (PR5F-1)

This internal, opt-in projection does not rewrite ArticleExtraction/2.0 or change field
grading. It uses the frozen extraction; it makes no API calls.

```
Frozen prediction + its own parsed source context
  → source-only Outcome normalization
  → identity-only Result projections
  → mapped parent → mapped Outcome → timepoint → analysis → statistic → derived
  → mutual unique candidate, otherwise abstain
  → existing Hybrid evaluator, scoring the ORIGINAL fields
```

Gold is projected independently. Source normalizers have no Gold parameter and receive
no expected labels, values or counts. The result matcher accepts only identity projections,
not extraction graphs or observed result values.

## Rules and limits

- Normalize generic ordinal/timepoint formatting, retaining raw strings and reference
  events. `3 months` and `3 months after surgery` are compatible, not field-exact.
- Baseline is distinct from follow-up. Explicit different anchors, ITT/PPS and statistic
  kinds remain contradictions. No unit arithmetic is performed.
- Only explicit source `mean ± SD` or count/percent structure can disambiguate `other`.
  The adapter masks all data-cell numbers into formatting shapes, and uses existing
  parser helpers for explicit Arm headers. Naked numbers cannot determine a statistic.
- Separate literal statistic wrappers from clinical constructs. Alias grouping needs
  a shared source row/block and compatible instruments, units and definitions; no fuzzy
  clinical synonyms. Uncertain source fields cannot authorize a merge.
- Parent/Outcome mappings must exist. Missing noncritical qualifiers may continue only
  when remaining identity is unique. An explicit unresolved `other` is not promoted to
  `mean`. Unknown qualifiers never override contradictions.
- Both endpoints must have exactly one viable, safe candidate. Unsafe competitors and
  duplicate children still block selection. There is no maximum matching or value-based
  tiebreaker, and no new result, Arm, Outcome or Comparison is added to the source graph.

`evaluation_replay.py` retains frozen parent matches and FIELD judgments. Newly linked
fields lacking a frozen FIELD judgment remain `JUDGE_UNAVAILABLE`, with zero attempts.
Identity decisions are not repurposed as field grades. The seven frozen PR5E artifacts
must reproduce byte-for-byte before the experiment runs.

## Offline replay

From the repository root in the Agent conda environment:

```powershell
D:\Application\Anaconda\envs\Agent\python.exe scripts/pr5f1_result_identity_acceptance.py `
  --source-context benchmarks/2015-06/result_identity_v1/SOURCE_IDENTITY_CONTEXT.json
```

Alternatively, `--source-markdown` reads the existing production Markdown locally using
the unchanged table parser. The CLI verifies the baseline, then runs twice and compares
all eight output artifacts byte-for-byte. `--snapshot` publishes a new immutable audit
snapshot; it refuses to overwrite a different one.

The experiment measures recovered identity links, not newly extracted clinical values.
All input hashes, raw identities, source rules, candidate dimensions and unmatched
reasons are available in the audit artifacts. Scoring denominators and Gold/Registry/
judge contracts are unchanged.
