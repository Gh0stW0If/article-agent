"""Replay non-table structured modules with the correctness model (5.6-sol).

The lossless outcome batch keeps table classification on 5.6-luna, but all
metadata/acupuncture/risk fields must use 5.6-sol.  This repair pass operates
in an isolated raw directory and updates only those three source modules; it
never rewrites outcome records or Gold values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from article_agent.models import OpenAICompatibleClient
from mineru_method.llm import ValidatedExtractor
from mineru_method.pipeline import _normalize_acupuncture, _normalize_primary_analysis
from mineru_method.prompts import PROMPT_SPECS
from mineru_method.routing import contexts_for_modules
from mineru_method.schemas import AcupunctureProtocol, MetadataExtraction, RiskOfBiasExtraction


def read_json(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return fallback


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def delay_seconds() -> float:
    try:
        value = float(os.getenv("ARTICLE_AGENT_OUTCOME_REQUEST_DELAY_SECONDS", "0.01"))
    except ValueError:
        value = 0.01
    return max(0.0, min(value, 60.0))


def run_article(article_dir: Path, client: OpenAICompatibleClient, retries: int) -> dict:
    markdown_path = article_dir / "article.md"
    extraction_path = article_dir / "extraction.json"
    if not markdown_path.exists() or not extraction_path.exists():
        return {"status": "failed", "error": "missing article.md or extraction.json"}
    markdown = markdown_path.read_text(encoding="utf-8")
    contexts = contexts_for_modules(markdown)
    retry_dir = article_dir / "raw_module_responses" / "structured_sol_retry"
    retry_dir.mkdir(parents=True, exist_ok=True)
    extractor = ValidatedExtractor(client, retry_dir, retries=retries)
    extraction = read_json(extraction_path, {}) or {}
    result = {
        "status": "success",
        "model": client.model,
        "raw_dir": str(retry_dir),
        "modules": {},
    }

    def call(name: str, schema):
        time.sleep(delay_seconds())
        return extractor.extract(name, schema, contexts[name], PROMPT_SPECS[name])

    try:
        metadata = call("metadata", MetadataExtraction)
        metadata, _ = __import__("mineru_method.pipeline", fromlist=["enrich_metadata"]).enrich_metadata(
            metadata, markdown, article_dir / "bibliographic_lookup.json"
        )
        extraction["metadata"] = metadata.model_dump(mode="json")
        result["modules"]["metadata"] = "success"
    except Exception as exc:
        result["modules"]["metadata"] = {"status": "failed", "error": str(exc)}

    try:
        acupuncture = call("acupuncture", AcupunctureProtocol)
        extraction["acupuncture"] = _normalize_acupuncture(acupuncture, contexts["acupuncture"]).model_dump(mode="json")
        result["modules"]["acupuncture"] = "success"
    except Exception as exc:
        result["modules"]["acupuncture"] = {"status": "failed", "error": str(exc)}

    try:
        risk = call("risk_of_bias", RiskOfBiasExtraction)
        extraction["risk_of_bias"] = _normalize_primary_analysis(risk, contexts["risk_of_bias"]).model_dump(mode="json")
        result["modules"]["risk_of_bias"] = "success"
    except Exception as exc:
        result["modules"]["risk_of_bias"] = {"status": "failed", "error": str(exc)}

    if all(value == "success" for value in result["modules"].values()):
        write_json(extraction_path, extraction)
    else:
        result["status"] = "partial"
        # Preserve successfully repaired fields while never replacing a
        # failed module with an empty/guessed value.
        write_json(extraction_path, extraction)
    manifest_path = article_dir / "manifest.json"
    manifest = read_json(manifest_path, {}) or {}
    manifest["structured_module_model"] = client.model
    manifest["structured_module_retry"] = result
    write_json(manifest_path, manifest)
    write_json(article_dir / "STRUCTURED_SOL_RETRY.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay metadata/acupuncture/risk using gpt-5.6-sol")
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--articles", nargs="*", default=None)
    args = parser.parse_args()
    output_root = args.output_root.resolve()
    article_dirs = [output_root / item for item in args.articles] if args.articles else sorted(output_root.glob("2015-*"))
    article_dirs = [path for path in article_dirs if path.is_dir()]
    try:
        retries = max(0, min(int(os.getenv("ARTICLE_AGENT_EXTRACT_RETRIES", "1")), 5))
    except ValueError:
        retries = 1
    client = OpenAICompatibleClient(
        model=os.getenv("ARTICLE_AGENT_STRUCTURED_MODEL") or os.getenv("ARTICLE_AGENT_MODEL") or "gpt-5.6-sol",
        timeout=max(10, int(os.getenv("ARTICLE_AGENT_API_TIMEOUT", "120"))),
    )
    summary = {"model": client.model, "retries": retries, "articles": {}}
    for article_dir in article_dirs:
        summary["articles"][article_dir.name] = run_article(article_dir, client, retries)
    write_json(output_root / "STRUCTURED_SOL_RETRY_SUMMARY.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if all(item.get("status") == "success" for item in summary["articles"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
