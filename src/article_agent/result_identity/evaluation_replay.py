"""Opt-in integration with unchanged Hybrid field semantics; no live API capability."""
from ..evaluation.hybrid.engine import evaluate_article_hybrid
from ..evaluation.hybrid.models import JudgmentArtifact
from ..evaluation.hybrid.prompts import SEMANTIC_PROMPT_SHA256, SEMANTIC_PROMPT_VERSION
from ..evaluation.hybrid.semantic_judge import CachedSemanticJudge, CacheMissError, digest
from .matcher import link_outcomes, link_results
from .projection import canonicalize_source_outcomes, project_results


class FrozenFieldJudge(CachedSemanticJudge):
    """Previously unscorable targets have no frozen FIELD judgment.

    Keep these explicitly unjudged instead of inventing a grade, reusing a differently
    scoped identity judgment, or making unapproved API calls. Existing cache is immutable.
    """
    def judge(self, request):
        try:
            return super().judge(request)
        except CacheMissError:
            canonical = self.canonical_input(request)
            key = digest(canonical)
            artifact = JudgmentArtifact(judgment_id="J-" + key, input_sha256=key,
                prompt_version=SEMANTIC_PROMPT_VERSION, prompt_sha256=SEMANTIC_PROMPT_SHA256,
                model=self.model, judge_type=request["judge_type"], field_id=request["field_id"],
                entity_type=request["entity_type"], canonical_input=canonical,
                gold_representation=request["gold"], prediction_representation=request["prediction"],
                status="JUDGE_UNAVAILABLE", error_code="SEMANTIC_JUDGE_ERROR", attempts=0,
                technical_errors=["FROZEN_FIELD_JUDGMENT_ABSENT_API_DISABLED"])
            self.used[key] = artifact
            return artifact


def evaluate_with_canonical_identity(prediction, gold, registry, overlay, baseline, context, *,
                                     prediction_sha256, gold_sha256):
    # Normalization is independently source-side: no Gold parameter or mapping is passed.
    prediction_outcomes = canonicalize_source_outcomes(prediction, context)
    prediction_projection = project_results(prediction, context, prediction_outcomes)
    reference_outcomes = canonicalize_source_outcomes(gold.truth)
    reference_projection = project_results(gold.truth, outcomes=reference_outcomes)
    parent_matches = [m.model_dump(mode="json") for m in baseline.entity_matches
                      if m.entity_type not in {"Outcome", "ArmResult", "ComparisonResult"}]
    parent_mapping = {(m.entity_type, m.prediction_entity_id): m.gold_entity_id
                      for m in baseline.entity_matches if m.match_status == "MATCHED"
                      and m.entity_type in {"Arm", "Comparison"}}
    study_mapping = {m.prediction_entity_id: m.gold_entity_id for m in baseline.entity_matches
                     if m.entity_type == "Study" and m.match_status == "MATCHED"}
    outcome_matches, outcome_mapping = link_outcomes(
        prediction_outcomes, reference_outcomes, baseline.entity_matches, study_mapping)
    linking = link_results(prediction_projection, reference_projection, parent_mapping,
                           outcome_mapping, baseline.entity_matches)
    judge = FrozenFieldJudge(artifacts=[j.model_dump(mode="json") for j in baseline.semantic_judgments],
                             model=baseline.semantic_judge["model"])
    report = evaluate_article_hybrid(prediction, gold, registry, overlay, judge,
        prediction_sha256=prediction_sha256, gold_sha256=gold_sha256,
        precomputed_matches=parent_matches + outcome_matches + linking.matches)
    return report, linking, prediction_projection, reference_projection, prediction_outcomes
