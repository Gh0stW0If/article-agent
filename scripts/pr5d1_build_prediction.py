"""Production artifacts -> existing converters -> immutable canonical prediction.

This module has no evaluator dependency and takes no reference-annotation input.
No clinical normalization or identity rule is implemented here.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from article_agent.domain.models import ArticleExtraction, CanonicalField, merge_field_observation
from article_agent.domain.legacy_adapter import legacy_bundle_to_canonical
from article_agent.outcome_canonicalizer import canonicalize_outcomes
from article_agent.outcome_source_normalizer import normalize_outcome_sources
from article_agent.trial_topology_agent import TrialTopology


def sha(data):
    return hashlib.sha256(data).hexdigest()


def assemble(bundle, topology, arm_graph):
    """Pure object wiring; original modules and all original outcome records survive."""
    bundle = deepcopy(bundle)
    aid = bundle["article_id"]
    topology = TrialTopology.model_validate(topology)
    arm_graph = ArticleExtraction.model_validate(arm_graph)
    records = bundle.get("outcomes", {}).get("outcomes", [])
    normalized, normalization = normalize_outcome_sources(aid, topology, records)
    graph = canonicalize_outcomes(aid, topology, arm_graph, normalized)
    # PR3 owns Arm/Intervention/flow; PR4 owns Outcome/Result/Comparison.
    # The legacy adapter is used solely for its existing Article/Study projection.
    module_input = {k: deepcopy(bundle[k]) for k in (
        "article_id", "parser_backend", "metadata", "risk_of_bias", "consort_flow") if k in bundle}
    legacy = legacy_bundle_to_canonical(module_input, topology=topology)
    for dest, source in ((graph.article, legacy.article), (graph.studies[0], legacy.studies[0])):
        for name, field in source:
            if isinstance(field, CanonicalField):
                setattr(dest, name, merge_field_observation(getattr(dest, name), field))
        dest.legacy_fields["legacy_module_projection"] = deepcopy(source.legacy_fields)
    graph.article.legacy_fields["production_source_bundle"] = bundle
    # Keep only evidence for the Article/Study projection actually wired above.
    existing = {e.evidence_id for e in graph.evidence}
    for evidence in legacy.evidence:
        targets = [t for t in evidence.targets if t.entity_type in {"Article", "Study"}]
        if targets:
            if evidence.evidence_id in existing:
                raise ValueError("Unexpected converter evidence ID collision")
            graph.evidence.append(evidence.model_copy(update={"targets": targets}, deep=True))
            existing.add(evidence.evidence_id)
    graph.parser_backend = bundle.get("parser_backend")
    graph.source_format = "legacy_extraction_bundle"
    graph.source_record_id = aid
    graph.adapter_warnings.extend(w for w in legacy.adapter_warnings if w not in graph.adapter_warnings)
    graph = ArticleExtraction.model_validate_json(graph.model_dump_json())
    assert graph.arms == arm_graph.arms and graph.interventions == arm_graph.interventions
    assert [r["_pr41_original"] for r in normalized] == records
    return graph, normalization


def build_prediction(production_dir: Path, output: Path):
    production_dir, output = Path(production_dir), Path(output)
    run = json.loads((output / "PRODUCTION_RUN.json").read_text(encoding="utf-8"))
    isolation = json.loads((output / "PRODUCTION_ISOLATION.json").read_text(encoding="utf-8"))
    assert run["status"] == "PRODUCTION_COMPLETE" and run["exit_code"] == 0
    assert not isolation["forbidden_read_attempts"]
    if (output / "prediction.json").exists() or (output / "evaluation.json").exists():
        raise FileExistsError("The baseline prediction must not be overwritten")
    names = ("extraction.json", "trial_topology/trial_topology.json", "arm_details/arm_details.canonical.json")
    payloads = [(production_dir / name).read_bytes() for name in names]
    graph, normalization = assemble(*(json.loads(data) for data in payloads))
    serialized = (graph.model_dump_json(indent=2) + "\n").encode("utf-8")
    ArticleExtraction.model_validate_json(serialized)
    with (output / "prediction.json").open("xb") as handle:
        handle.write(serialized)
    manifest = {**run, "status": "PREDICTION_FROZEN", "prediction_sha256": sha(serialized),
                "article_schema_version": graph.schema_version,
                "assembly_input_sha256": {name: sha(data) for name, data in zip(names, payloads)},
                "model_configuration": isolation["model_configuration"],
                "forbidden_read_attempts": isolation["forbidden_read_attempts"],
                "assembly_functions": ["normalize_outcome_sources", "canonicalize_outcomes",
                                       "legacy_bundle_to_canonical", "merge_field_observation"],
                "prediction_frozen_before_evaluation": True}
    (output / "RUN_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "ASSEMBLY.json").write_text(json.dumps(normalization, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_prediction(args.production_dir, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
