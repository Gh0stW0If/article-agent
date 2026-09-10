import json
import pytest
from pydantic import ValidationError
from article_agent.evaluation.gold_contract import GoldStandardV2
from article_agent.domain import Article, ArticleExtraction, Arm, Study, CanonicalField, FieldStatus

def base():
    a=Article(article_id="a1")
    for name in ("title","doi","publication_year","journal","language","authors","correspondence"):
        setattr(a,name,CanonicalField(status=FieldStatus.NOT_APPLICABLE))
    s=Study(study_id="s1",article_id="a1")
    for name,field in Study.model_fields.items():
        if isinstance(getattr(s,name,None),CanonicalField):
            setattr(s,name,CanonicalField(status=FieldStatus.NOT_APPLICABLE))
    return ArticleExtraction(article=a, studies=[s])
def gold(truth=None, **kw):
    params=dict(gold_version="GOLD_STANDARD/2.0.0",article_schema_version="ARTICLE_EXTRACTION/2.0",gold_id="g1",article_id="a1",state="DRAFT",source_lineage={"documents":[{"source_id":"article","role":"PRIMARY_ARTICLE"}]},truth=truth or base())
    params.update(kw)
    return GoldStandardV2(**params)
def test_valid_minimal_gold(): assert gold().gold_version=="GOLD_STANDARD/2.0.0"
def test_article_mismatch(): 
    with pytest.raises(ValidationError): gold(article_id="wrong")
def test_runtime_status_rejected():
    t=base();t.article.title=CanonicalField(status=FieldStatus.UNRESOLVED)
    with pytest.raises(ValidationError): gold(t)
def test_insufficient_context_rejected():
    t=base();t.article.title=CanonicalField(status=FieldStatus.INSUFFICIENT_CONTEXT)
    with pytest.raises(ValidationError): gold(t)
def test_not_reported_requires_assessment():
    t=base();t.article.title=CanonicalField(status=FieldStatus.NOT_REPORTED)
    with pytest.raises(ValidationError): gold(t)
    a={"entity_type":"Article","entity_id":"a1","field_id":"title","status":"NOT_REPORTED","coverage_complete":True,"rationale":"searched"}
    assert gold(t,missingness_assessments=[a])
