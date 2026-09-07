"""PR3 acceptance run v2: frozen topology + arm details for 2015-01..06.

Reads accepted PR2 topology without API calls by default, then extracts only
ArmDetails. --rerun-topology explicitly enables a fresh topology API call.
Optional argv filters the articles to (re)run; SUMMARY.json is upserted so
partial reruns keep the other articles' entries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from article_agent.arm_details_agent import run_arm_details
from article_agent.domain import ArticleExtraction
from article_agent.models import OpenAICompatibleClient, load_env_file
from article_agent.trial_topology_agent import TrialTopology, run_topology

ARTICLES = [f"2015-0{i}" for i in range(1, 7)]
MARKDOWN_ROOT = Path("outputs/mineru_method_2015_batch")
OUTPUT_ROOT = Path("outputs/pr3_arm_details_online_v3")
TOPOLOGY_ROOT = Path("outputs/pr2_trial_topology_online_v2")
FLOW_FIELDS = ("randomized_n", "received_n", "analyzed_n", "dropout_n")


def summarize(canonical) -> dict:
    return {
        "article_id": canonical.article.article_id,
        "arm_count": len(canonical.arms),
        "status": "success",
        "arms": [
            {
                "id": arm.arm_id,
                "label": arm.label.value,
                "intervention_ids": arm.intervention_ids,
                "intervention_components": [i.name.value for iid in arm.intervention_ids for i in canonical.interventions if i.intervention_id == iid],
                "sample_flow": {name: getattr(arm, name).model_dump(mode="json") for name in FLOW_FIELDS},
                "randomized_n": {
                    "status": arm.randomized_n.status.value,
                    "value": arm.randomized_n.value,
                    "raw_value": arm.randomized_n.raw_value,
                    "evidence_ids": arm.randomized_n.evidence_ids,
                    "conflict_candidates": [
                        {
                            "value": c.value,
                            "raw_value": c.raw_value,
                            "evidence_ids": c.evidence_ids,
                        }
                        for c in arm.randomized_n.conflict_candidates
                    ],
                },
            }
            for arm in canonical.arms
        ],
        "components": {
            i.intervention_id: (i.name.value or "") for i in canonical.interventions
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ArmDetails-only acceptance using frozen PR2 topology")
    parser.add_argument("articles", nargs="*")
    parser.add_argument("--rerun-topology", action="store_true")
    parser.add_argument("--topology-root", type=Path, default=TOPOLOGY_ROOT)
    parser.add_argument("--markdown-root", type=Path, default=MARKDOWN_ROOT)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args(argv)
    if set(args.articles) - set(ARTICLES):
        parser.error("unknown article id")
    load_env_file()
    selected = [aid for aid in ARTICLES if not args.articles or aid in args.articles]
    summary_path = args.output_root / "SUMMARY.json"
    summary = (
        json.loads(summary_path.read_text(encoding="utf-8"))
        if summary_path.exists()
        else []
    )
    timeout = int(os.getenv("ARTICLE_AGENT_API_TIMEOUT", "180"))
    topology_client = OpenAICompatibleClient(
        model=os.getenv("ARTICLE_AGENT_TOPOLOGY_MODEL", "gpt-5.6-luna"), timeout=timeout
    ) if args.rerun_topology else None
    details_client = OpenAICompatibleClient(
        model=os.getenv("ARTICLE_AGENT_ARM_DETAILS_MODEL", "gpt-5.6-sol"), timeout=timeout
    )
    started = time.time()
    for aid in selected:
        article_dir = args.output_root / aid
        article_dir.mkdir(parents=True, exist_ok=True)
        entry: dict = {"article_id": aid}
        try:
            markdown = (args.markdown_root / aid / "article.md").read_text(encoding="utf-8")
            topology_path = args.topology_root / aid / "trial_topology.json"
            if args.rerun_topology:
                run_topology(aid, markdown, article_dir / "trial_topology", topology_client)
                topology_path = article_dir / "trial_topology" / "trial_topology.json"
            frozen = topology_path.read_bytes()
            topology = TrialTopology.model_validate_json(frozen)
            entry["topology_source"] = str(topology_path)
            entry["topology_sha256"] = hashlib.sha256(frozen).hexdigest()
            entry["topology_api_called"] = args.rerun_topology
            entry["number_of_arms"] = topology.number_of_arms
            attempt_root = article_dir / "arm_details" / time.strftime("%Y%m%d-%H%M%S")
            canonical = run_arm_details(
                aid, markdown, topology, attempt_root, details_client
            )
            ArticleExtraction.model_validate_json(canonical.model_dump_json())
            assert topology_path.read_bytes() == frozen
            assert [a.arm_id for a in canonical.arms] == [f"{aid}-S1-A{i:02d}" for i in range(1, topology.number_of_arms + 1)]
            assert not canonical.comparisons
            entry.update(summarize(canonical))
            entry["canonical_revalidation"] = "passed"
            entry["source_conflicts"] = [{"arm_id": a.arm_id, "field": f, "candidates": [c.model_dump(mode="json") for c in getattr(a, f).conflict_candidates]} for a in canonical.arms for f in FLOW_FIELDS if getattr(a, f).conflict_candidates]
        except Exception as exc:  # keep the batch going; record the failure
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            (article_dir / "runner_error.json").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
        if "attempt_root" in locals():
            entry["artifact_dir"] = str(attempt_root)
            entry["retries"] = max(0, len(list(attempt_root.glob("request-*.json"))) - 1)
            entry["validation_failures"] = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(attempt_root.glob("error-*.json"))]
            del attempt_root
        summary = [e for e in summary if e.get("article_id") != aid] + [entry]
        summary.sort(key=lambda e: e["article_id"])
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[{time.time() - started:7.1f}s] {aid}: {entry['status']}", flush=True)
    return int(any(e["status"] != "success" for e in summary if e["article_id"] in selected))


if __name__ == "__main__":
    raise SystemExit(main())
