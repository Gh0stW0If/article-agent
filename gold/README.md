# Canonical Gold boundary

This directory defines where evaluator-only canonical Gold records may be
mounted locally. No human annotations, source PDFs, spreadsheets, or converted
Gold rows are committed to the repository.

Gold records should validate against `schemas/article-extraction.schema.json`
and use the same entity IDs as candidate `ArticleExtraction` documents.
Evaluation may compare candidate and Gold values, but Gold must never be passed
to extraction prompts or used by the legacy-to-canonical adapter.

Recommended local layout (ignored when it contains spreadsheets or data under
the project `Datas/` directory):

```text
gold/
  README.md
  local/                 # user-managed, do not commit
    <article-id>.json
```

The evaluator field allow-list and comparison policies live in
`registry/evaluator-field-registry.json`.
