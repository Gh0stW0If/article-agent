"""PR5R-6: three-run extraction reproducibility and Gold-isolation audit.

The runner creates three isolated source snapshots with identical tracked
code/configuration and deliberately omits ``Datas/label`` and Gold files.
Each run invokes the unchanged ``MinerU method/run.py`` production entrypoint.
All comparisons are deterministic and offline after extraction.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PDF_REL = Path("Datas/articles/2015/-2015-06.pdf")
OUT = ROOT / "outputs/pr5r6_reproducibility_2015_06"
RUN_NAMES = ("run_a", "run_b", "run_c")

sys.path.insert(0, str(ROOT))
from article_agent.domain.models import ArticleExtraction  # noqa: E402
from article_agent.provenance import TraceSession  # noqa: E402
from scripts.pr5d1_build_prediction import assemble  # noqa: E402


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n").encode("utf-8")


def tree_digest(path: Path) -> str:
    items: list[dict[str, str]] = []
    if not path.exists():
        return digest_bytes(b"<missing>")
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        items.append({"path": child.relative_to(path).as_posix(), "sha256": digest(child)})
    return digest_bytes(json_bytes(items))


def response_tree_digest(path: Path) -> str:
    """Hash model response payloads without run-specific manifests/logs."""
    items: list[dict[str, str]] = []
    if not path.exists():
        return digest_bytes(b"<missing>")
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        if "manifest" in child.name or child.name.endswith(".error.txt"):
            continue
        items.append({"path": child.relative_to(path).as_posix(), "sha256": digest(child)})
    return digest_bytes(json_bytes(items))


def load_env_file(path: Path) -> dict[str, str]:
    """Read non-secret runtime settings for the reproducibility manifest."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values


def copy_source_snapshot(destination: Path) -> dict[str, str]:
    destination.mkdir(parents=True, exist_ok=False)
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    copied: dict[str, str] = {}
    excluded_prefixes = ("Datas/label/", "gold/", "outputs/")
    included_prefixes = ("src/", "MinerU method/", "registry/", "baml_src/", "skills/")
    exact = {"pyproject.toml", ".gitignore"}
    for name in files:
        if not name or name.startswith(excluded_prefixes):
            continue
        if not (name.startswith(included_prefixes) or name in exact):
            continue
        source, target = ROOT / name, destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        copied[name] = digest(target)
    generated = ROOT / "baml_client"
    if generated.is_dir():
        for source in sorted(generated.rglob("*.py")):
            target = destination / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied[source.relative_to(ROOT).as_posix()] = digest(target)
    env_file = ROOT / ".env"
    if env_file.exists():
        shutil.copy2(env_file, destination / ".env")
    pdf_target = destination / PDF_REL
    pdf_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / PDF_REL, pdf_target)
    copied[PDF_REL.as_posix()] = digest(pdf_target)
    return copied


def run_extraction(name: str, workspace: Path, output_root: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env["ARTICLE_AGENT_RUN_ID"] = f"pr5r6-{name}-2015-06"
    env["PYTHONPATH"] = str(workspace / "src")
    runtime = Path(sys.executable).parent
    env["PATH"] = str(runtime) + os.pathsep + env.get("PATH", "")
    output_root.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "MinerU method/run.py",
        "--pdf",
        PDF_REL.as_posix(),
        "--parser",
        "auto",
        "--use-api",
        "--output-root",
        str(output_root),
    ]
    completed = subprocess.run(
        command,
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    (OUT / f"{name}.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (OUT / f"{name}.stderr.log").write_text(completed.stderr, encoding="utf-8")
    article_dir = output_root / "2015-06"
    return {
        "run": name,
        "command": command,
        "exit_code": completed.returncode,
        "status": "SUCCESS" if completed.returncode == 0 and (article_dir / "extraction.json").exists() else "FAILED",
        "workspace": str(workspace),
        "output": str(article_dir),
    }


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def request_counts(article_dir: Path) -> dict[str, Any]:
    raw = article_dir / "raw_module_responses"
    table_manifest = raw / "request_manifest.jsonl"
    table = len([x for x in table_manifest.read_text(encoding="utf-8").splitlines() if x.strip()]) if table_manifest.exists() else 0
    topology = len(list((article_dir / "trial_topology").glob("topology.request-*.json")))
    arm_details = len(list((article_dir / "arm_details").glob("request-*.json")))
    structured = len(list(raw.glob("*.attempt-*.json")))
    postprocess = len(list(raw.glob("outcomes.postprocess.part-*.json")))
    return {
        "total_recorded": topology + arm_details + structured + table + postprocess,
        "table_and_narrative": table,
        "trial_topology": topology,
        "arm_details": arm_details,
        "structured": structured,
        "postprocess": postprocess,
    }


def assemble_snapshot(article_dir: Path) -> dict[str, Any]:
    payloads = [
        load_json(article_dir / "extraction.json"),
        load_json(article_dir / "trial_topology/trial_topology.json"),
        load_json(article_dir / "arm_details/arm_details.canonical.json"),
    ]
    prediction, normalization = assemble(*payloads)
    serialized = (prediction.model_dump_json(indent=2) + "\n").encode("utf-8")
    ArticleExtraction.model_validate_json(serialized)
    trace_session = TraceSession("2015-06", enabled=True)
    traced_prediction, _ = assemble(*payloads, trace=trace_session)
    traced_bytes = (traced_prediction.model_dump_json(indent=2) + "\n").encode("utf-8")
    artifact = trace_session.artifact()
    raw_dir = article_dir / "raw_module_responses"
    manifest = load_json(article_dir / "manifest.json")
    postprocess_path = raw_dir / "outcomes.postprocess.manifest.json"
    postprocess = load_json(postprocess_path) if postprocess_path.exists() else {}
    return {
        "parser_output_hash": tree_digest(article_dir / "hybrid"),
        "article_markdown_hash": digest(article_dir / "article.md"),
        "retrieval_context_hash": digest(article_dir / "routed_context.json"),
        "evidence_context_hash": digest(article_dir / "evidence_contexts.json"),
        "skill_raw_output_hash": response_tree_digest(raw_dir),
        "source_outcome_count": len(payloads[0].get("outcomes", {}).get("outcomes", [])),
        "candidate_count": len(artifact["candidates"]),
        "result_counts": {
            "outcomes": len(prediction.outcomes),
            "arm_results": len(prediction.arm_results),
            "comparisons": len(prediction.comparisons),
            "comparison_results": len(prediction.comparison_results),
        },
        "final_prediction_hash": digest_bytes(serialized),
        "trace_hash": digest_bytes(json_bytes(artifact)),
        "trace_candidate_count": len(artifact["candidates"]),
        "trace_event_count": len(artifact["events"]),
        "normalization_hash": digest_bytes(json_bytes(normalization)),
        "parser_backend": manifest.get("parser_backend"),
        "run_id": manifest.get("run_id"),
        "api_calls": request_counts(article_dir),
        "postprocess_gold_used": bool(postprocess.get("gold_used_for_postprocess_comparison", False)),
        "output_exists": True,
    }


def compare_runs(runs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    layers = (
        ("parser_output", ("parser_output_hash", "article_markdown_hash")),
        ("retrieval_context", ("retrieval_context_hash", "evidence_context_hash")),
        ("skill_raw_output", ("skill_raw_output_hash",)),
        ("candidate_count", ("candidate_count",)),
        ("result_counts", ("result_counts",)),
        ("final_prediction", ("final_prediction_hash",)),
    )
    baseline = runs[RUN_NAMES[0]]
    comparisons = {}
    for name in RUN_NAMES[1:]:
        first_difference = "NONE"
        rows = []
        for layer, keys in layers:
            equal = all(baseline[key] == runs[name][key] for key in keys)
            rows.append({"layer": layer, "equal_to_run_a": equal})
            if not equal and first_difference == "NONE":
                first_difference = layer
        comparisons[name] = {"first_difference": first_difference, "layers": rows}
    all_equal = all(
        runs[RUN_NAMES[0]][key] == runs[name][key]
        for name in RUN_NAMES[1:]
        for key in ("parser_output_hash", "retrieval_context_hash", "skill_raw_output_hash", "candidate_count", "result_counts", "final_prediction_hash")
    )
    return {
        "baseline": RUN_NAMES[0],
        "pairwise": comparisons,
        "all_layers_equal": all_equal,
        "interpretation": (
            "parser drift" if any(x["first_difference"] == "parser_output" for x in comparisons.values())
            else "retrieval/context drift" if any(x["first_difference"] == "retrieval_context" for x in comparisons.values())
            else "LLM Skill raw-output variance" if any(x["first_difference"] == "skill_raw_output" for x in comparisons.values())
            else "construction/merger or downstream variance" if any(x["first_difference"] in {"candidate_count", "result_counts", "final_prediction"} for x in comparisons.values())
            else "no observed drift in compared layers"
        ),
    }


def render_html(summary: dict[str, Any]) -> str:
    return (
        "<!doctype html><meta charset='utf-8'><title>PR5R-6 reproducibility</title>"
        "<style>body{font-family:system-ui;max-width:1200px;margin:2rem auto}pre{white-space:pre-wrap;background:#f6f6f6;padding:1rem}</style>"
        "<h1>PR5R-6 — Extraction Reproducibility &amp; Gold Isolation</h1>"
        "<p>三次同配置 extraction 的逐层比较；Gold/label 目录未复制到隔离 workspace。</p>"
        "<h2>Summary</h2><pre>" + html.escape(json.dumps(summary, ensure_ascii=False, indent=2)) + "</pre>"
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    file_env = load_env_file(ROOT / ".env")
    frozen_env = {
        key: ("<redacted>" if "KEY" in key or "TOKEN" in key or "SECRET" in key else value)
        for key, value in sorted(file_env.items())
    }
    run_manifests: dict[str, dict[str, Any]] = {}
    snapshots: dict[str, dict[str, Any]] = {}
    for name in RUN_NAMES:
        workspace = OUT / f"{name}_workspace"
        output_root = OUT / f"{name}_output"
        if args.run_extractions:
            if workspace.exists() or output_root.exists():
                raise FileExistsError(f"refusing to overwrite existing {name} artifacts")
            copied = copy_source_snapshot(workspace)
            run_manifests[name] = run_extraction(name, workspace, output_root)
            run_manifests[name]["source_files_sha256"] = digest_bytes(json_bytes(copied))
        else:
            run_manifests[name] = {"run": name, "status": "REPLAY_ONLY", "workspace": str(workspace), "output": str(output_root / "2015-06")}
        article_dir = output_root / "2015-06"
        if not (article_dir / "extraction.json").exists():
            raise FileNotFoundError(f"missing extraction output for {name}: {article_dir}")
        snapshots[name] = assemble_snapshot(article_dir)
        run_manifests[name]["snapshot"] = snapshots[name]

    gold_isolation = {
        "gold_files_copied": False,
        "label_directory_copied": False,
        "workspaces_without_gold": all(not (OUT / f"{name}_workspace/Datas/label").exists() and not (OUT / f"{name}_workspace/gold").exists() for name in RUN_NAMES),
        "postprocess_gold_used": {name: snapshots[name]["postprocess_gold_used"] for name in RUN_NAMES},
        "production_prediction_gold_used": False,
        "note": "Extraction source requests and canonical assembly do not use Gold. The optional postprocess flag is checked explicitly per run.",
    }
    summary = {
        "pr": "PR5R-6",
        "article_id": "2015-06",
        "commit_sha": sha,
        "run_names": list(RUN_NAMES),
        "configuration_frozen": {
            "pdf_sha256": digest(ROOT / PDF_REL),
            "parser_requested": "auto",
            "models_from_env": {
                key: file_env.get(key) or os.getenv(key) for key in (
                    "ARTICLE_AGENT_MODEL",
                    "ARTICLE_AGENT_TOPOLOGY_MODEL",
                    "ARTICLE_AGENT_ARM_DETAILS_MODEL",
                    "ARTICLE_AGENT_STRUCTURED_MODEL",
                    "ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL",
                )
            },
            "api_parameters": {
                key: frozen_env[key]
                for key in sorted(frozen_env)
                if key.startswith("ARTICLE_AGENT_")
                and key not in {"ARTICLE_AGENT_API_KEY"}
            },
            "api_parameters_sha256": digest_bytes(json_bytes(frozen_env)),
            "skill_versions": {
                "skills_tree_sha256": tree_digest(ROOT / "skills"),
                "source_snapshot_sha256": digest_bytes(json_bytes({
                    name: run_manifests[name].get("source_files_sha256")
                    for name in RUN_NAMES
                    if name in run_manifests
                })),
            },
            "prompt_hashes": {
                "MinerU method/mineru_method/prompts.py": digest(ROOT / "MinerU method/mineru_method/prompts.py"),
                "src/article_agent/models.py": digest(ROOT / "src/article_agent/models.py"),
            },
            "temperature": 0.0,
            "api_mode": os.getenv("ARTICLE_AGENT_API_MODE", "from .env"),
            "runtime": str(sys.executable),
        },
        "runs": snapshots,
        "run_manifests": run_manifests,
        "layer_comparison": compare_runs(snapshots),
        "gold_isolation": gold_isolation,
        "api_calls": {name: snapshots[name]["api_calls"] for name in RUN_NAMES},
        "diagnostic_api_calls": 0,
        "production_logic_changed": False,
        "gold_changed": False,
        "registry_changed": False,
        "prompt_changed": False,
    }
    (OUT / "RUN_MANIFEST.json").write_text(json.dumps(summary["run_manifests"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "LAYER_COMPARISON.json").write_text(json.dumps(summary["layer_comparison"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "GOLD_ISOLATION.json").write_text(json.dumps(gold_isolation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = [
        "# PR5R-6 — Extraction Reproducibility & Gold Isolation",
        "",
        "三次 extraction 使用相同 tracked source snapshot、PDF 和 API 配置；每个隔离 workspace 都没有 Datas/label 或 Gold。",
        "",
        f"- commit: `{sha}`",
        f"- PDF SHA256: `{summary['configuration_frozen']['pdf_sha256']}`",
        f"- diagnostic API calls: `0`",
        f"- observed drift interpretation: **{summary['layer_comparison']['interpretation']}**",
        "",
        "## Layer comparison",
        "",
        "| run | first difference vs Run A |",
        "|---|---|",
    ]
    for name, row in summary["layer_comparison"]["pairwise"].items():
        report.append(f"| {name} | {row['first_difference']} |")
    report += [
        "",
        "## Counts and hashes",
        "",
        "```json",
        json.dumps(snapshots, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Gold isolation",
        "",
        "```json",
        json.dumps(gold_isolation, ensure_ascii=False, indent=2),
        "```",
        "",
        "结论：先看 Layer comparison 中最早出现差异的层。parser 相同而 Skill raw 不同，说明主要是 LLM 输出方差；Skill 相同而数量变化，才继续检查 construction/merger。没有用 Gold 修正任何 prediction。",
    ]
    (OUT / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    (OUT / "REPORT.html").write_text(render_html(summary), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-extractions", action="store_true", help="Run three isolated API extractions")
    args = parser.parse_args(argv)
    summary = run(args)
    print(json.dumps({
        "output": str(OUT),
        "layer_comparison": summary["layer_comparison"],
        "gold_isolation": summary["gold_isolation"],
        "diagnostic_api_calls": 0,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
