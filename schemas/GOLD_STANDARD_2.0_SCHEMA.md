# Gold Standard 2.0 contract

`GOLD_STANDARD/2.0.0` embeds an `ARTICLE_EXTRACTION/2.0` truth graph.
Gold permits only `PRESENT`, `NOT_REPORTED`, `NOT_APPLICABLE`,
`SOURCE_CONFLICT`, and `REVIEW_REQUIRED`; runtime `UNRESOLVED` and
`INSUFFICIENT_CONTEXT` are invalid. `NOT_REPORTED` requires complete coverage
evidence in `MissingnessAssessment`. Gold conflicts remain candidates and are
excluded from ordinary hard-value denominators. This PR freezes contracts only;
it does not score predictions or create real article labels.
