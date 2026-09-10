"""Evaluation contracts plus backwards-compatible legacy helpers."""
import importlib.util
import sys
from pathlib import Path

from .gold_contract import GoldStandardV2, MissingnessAssessment, EntityMatchAlias
from .registry import EvaluatorRegistryV3
from .models import EvaluationReportV2


def evaluate_article(prediction, gold, registry):
    """Lazy public entry point; keep legacy APIs and module CLI independent."""
    from .engine import evaluate_article as evaluate
    return evaluate(prediction, gold, registry)

# ``evaluation.py`` predates this package and is still imported by the pipeline.
# Load it under a private name so introducing the contract package is additive.
_legacy_path = Path(__file__).resolve().parents[1] / "evaluation.py"
_spec = importlib.util.spec_from_file_location("_article_agent_legacy_evaluation", _legacy_path)
_legacy = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_legacy.__package__ = "article_agent"
sys.modules[_spec.name] = _legacy
_spec.loader.exec_module(_legacy)

EVALUATION_HEADERS = _legacy.EVALUATION_HEADERS
build_evaluation_rows = _legacy.build_evaluation_rows
compute_evaluation_summary = _legacy.compute_evaluation_summary
write_evaluation_summary = _legacy.write_evaluation_summary

__all__ = [
    "GoldStandardV2", "MissingnessAssessment", "EntityMatchAlias",
    "EvaluatorRegistryV3", "EVALUATION_HEADERS", "build_evaluation_rows",
    "compute_evaluation_summary", "write_evaluation_summary",
    "evaluate_article", "EvaluationReportV2",
]
