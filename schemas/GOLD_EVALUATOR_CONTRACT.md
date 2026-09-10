# PR5A Gold and evaluator contract

Gold is `GOLD_STANDARD/2.0.0` and embeds `ArticleExtraction/2.0`; it does not
create a parallel gold-arm/outcome schema. Gold permits only `PRESENT`,
`NOT_REPORTED`, `NOT_APPLICABLE`, `SOURCE_CONFLICT`, and `REVIEW_REQUIRED`.
Runtime-only `UNRESOLVED` and `INSUFFICIENT_CONTEXT` are rejected.

`NOT_REPORTED` requires a complete `MissingnessAssessment`; `SOURCE_CONFLICT`
keeps at least two candidates and their evidence. `REVIEW_REQUIRED` is
non-scorable. Production extraction never imports Gold.

The registry is `EVALUATOR_FIELD_REGISTRY/3.0.0`. HARD fields must be
SUPPORTED and have a deterministic comparator. Conflict values are scored in a
separate metric, not ordinary value accuracy. Future denominators distinguish
Gold target, production coverage, supported value accuracy, hard exact and
conflict metrics. This PR defines contracts only; it does not score predictions.

Entity matching never relies solely on ordinal IDs for Intervention, Outcome or
results. Outcome uses normalized name + instrument plus human Gold aliases;
Arm uses frozen arm identity with exact normalized source-label fallback;
Comparison preserves ordered participants. Fuzzy, embedding and LLM matching
are forbidden in the baseline.
