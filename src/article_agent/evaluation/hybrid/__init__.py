"""Opt-in evaluation only; never imported by production extraction."""
from .engine import evaluate_article_hybrid
from .models import HybridEvaluationReportV1, SemanticJudgment, SemanticEntityJudgment, SemanticGrade
from .registry import load_semantic_registry
from .semantic_judge import CachedSemanticJudge, FakeSemanticJudge, LiveSemanticJudge

__all__ = [
    "evaluate_article_hybrid", "HybridEvaluationReportV1", "SemanticJudgment",
    "SemanticEntityJudgment", "SemanticGrade", "load_semantic_registry",
    "CachedSemanticJudge", "FakeSemanticJudge", "LiveSemanticJudge",
]
