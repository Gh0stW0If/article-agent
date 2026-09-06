"""PR3 acceptance run v2: frozen topology + arm details for 2015-01..06.

Mirrors the integrated pipeline order (Markdown -> TrialTopology -> Arm Details)
on the batch MinerU markdown, persisting every stage artifact per article.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from article_agent.arm_details_agent import run_arm_details
from article_agent.models import OpenAICompatibleClient, load_env_file
from article_agent.trial_topology_agent import TrialTopology, run_topology

ARTICLES = [f"2015-0{i}" for i in range(1, 7)]
MARKDOWN_ROOT = Path("outputs/mineru_method_2015_batch")
OUTPUT_ROOT = Path("outputs/pr3_arm_details_online_v2")


def summarize(canonical) -> dict:
    return {
        "article_id": canonical.studies[0].study_id,
        "status": "success",
        "arms": [
            {
                "id": arm.arm_id,
                "label": arm.label.value,
                "intervention_ids": arm.intervention_ids,
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


def main() -> int:
    load_env_file()
    timeout = int(os.getenv("ARTICLE_AGENT_API_TIMEOUT", "180"))
    topology_client = OpenAICompatibleClient(
        model=os.getenv("ARTICLE_AGENT_TOPOLOGY_MODEL", "gpt-5.6-luna"), timeout=timeout
    )
    details_client = OpenAICompatibleClient(
        model=os.getenv("ARTICLE_AGENT_ARM_DETAILS_MODEL", "gpt-5.6-sol"), timeout=timeout
    )
    summary = []
    started = time.time()
    for aid in ARTICLES:
        article_dir = OUTPUT_ROOT / aid
        article_dir.mkdir(parents=True, exist_ok=True)
        entry: dict = {"article_id": aid}
        try:
            markdown = (MARKDOWN_ROOT / aid / "article.md").read_text(encoding="utf-8")
            run_topology(aid, markdown, article_dir / "trial_topology", topology_client)
            topology = TrialTopology.model_validate_json(
                (article_dir / "trial_topology" / "trial_topology.json").read_text(encoding="utf-8")
            )
            entry["number_of_arms"] = topology.number_of_arms
            canonical = run_arm_details(
                aid, markdown, topology, article_dir / "arm_details", details_client
            )
            entry.update(summarize(canonical))
        except Exception as exc:  # keep the batch going; record the failure
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            (article_dir / "runner_error.json").write_text(
                traceback.format_exc(), encoding="utf-8"
            )
        summary.append(entry)
        (OUTPUT_ROOT / "SUMMARY.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[{time.time() - started:7.1f}s] {aid}: {entry['status']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
