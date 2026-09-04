# Canonical schemas

`article-extraction.schema.json` is generated from
`article_agent.domain.ArticleExtraction.model_json_schema()` and contains the
complete definitions for Article, Study, Arm, Intervention, Outcome,
ArmResult, Comparison, ComparisonResult, and Evidence.

Regenerate it after an intentional domain-model change:

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -c "import json; from pathlib import Path; from article_agent.domain import ArticleExtraction; Path('schemas/article-extraction.schema.json').write_text(json.dumps(ArticleExtraction.model_json_schema(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')"
```

The canonical schema is additive. It does not replace or modify the legacy
`ExtractionBundle` schema used by the current extraction pipeline.
