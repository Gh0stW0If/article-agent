# Canonical schemas

`article-extraction.schema.json` is generated from
`article_agent.domain.ArticleExtraction.model_json_schema()` and contains the
complete definitions for Article, Study, Arm, Intervention, Outcome,
ArmResult, Comparison, ComparisonResult, and Evidence.

Regenerate it after an intentional domain-model change:

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -c "import json; from pathlib import Path; from article_agent.domain import ArticleExtraction; Path('schemas/article-extraction.schema.json').write_text(json.dumps(ArticleExtraction.model_json_schema(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')"
```

## ARTICLE_EXTRACTION/2.0 (breaking canonical change)

Clinical fields are now `CanonicalField[T]` objects containing `status`, `value`,
`raw_value`, `evidence_ids`, and `conflict_candidates`. Entity IDs and references
remain scalars/lists. Missing legacy `NR` and legacy not-reported enum defaults
map to `UNRESOLVED`; they do not establish absence in the paper.

`SOURCE_CONFLICT` exposes no chosen value and retains at least two distinct
normalized candidates. Repeated values merge evidence even when raw spellings
differ. The first raw spelling is retained on the candidate; adapter source
observations remain available in `legacy_fields` for auditing all spellings.
No Gold values participate in this conversion.

Field evidence links point to `Evidence`, whose `targets` identify the entity
type, entity ID and field name (for example `Arm`, `A02`, `randomized_n`).
The adapter only attaches field-specific quotes or explicitly shared row
evidence. A title quote is never attached to unrelated metadata fields.

Study now represents randomization, concealment, blinding, primary analysis and
missing-data methods. Legacy codes retain their raw spelling while coded
blinding/analysis/missing-data values use their legacy enum names. Randomization
and concealment codes remain integers. Fields not supplied by legacy remain
unresolved. Outcome sample sizes stay on `ArmResult.n`; they are not assumed to
be randomized counts. Conflicting explicit risk/flow randomized counts merge.

Result `timepoint_raw` is now `timepoint`; normalized numeric `timepoint_value`
and `timepoint_unit` are retained as canonical fields. Entity-wide evidence IDs
are replaced by field-level links. Study's v1 `analysis_sets` aggregation is
replaced by `primary_analysis_set`; each result retains its analysis set and the
complete source row. Entity `legacy_fields` preserve original source projections.

The evaluator registry is `EVALUATOR_FIELD_REGISTRY/2.0.0`. `pathPattern` uses
JSONPath syntax and addresses the field object, not its `.value`. Evaluators must
inspect status before comparing values and must not implicitly choose a source
conflict candidate. Its clinical fields are enabled CORE entries; retained v1
reference/provenance entries are disabled SUPPORT entries. This registry change
does not switch the existing extraction/evaluation pipeline to the new domain.

The legacy `ExtractionBundle`, prompts, document parsers, BAML and API model
behavior are unchanged; conversion remains an explicit opt-in adapter call.
