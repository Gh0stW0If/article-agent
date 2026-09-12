"""One production attempt, unchanged sources, explicitly authorized input isolation.

No extraction logic lives here. No label/Gold input is copied or read.
The --child path runs the existing run.py with a fail-closed file-read audit.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_SHA = "eefa90ff85935af980c2fedcc2917d4771a94e5e"
ISOLATED = ROOT / "outputs/pr5d1_2015_06_isolated_workspace"
OUTPUT = ROOT / "outputs/pr5d1_2015_06_production"
BENCH = ROOT / "outputs/pr5d1_2015_06_benchmark"
PDF_REL = "datas/articles/2015/-2015-06.pdf"


def attempt_paths(root, attempt):
    if attempt < 1:
        raise ValueError("Attempt must be positive")
    suffix = "" if attempt == 1 else f"_retry{attempt:02d}"
    return tuple(Path(root) / f"outputs/pr5d1_2015_06_{kind}{suffix}"
                 for kind in ("isolated_workspace", "production", "benchmark"))


def failed_predecessors(root, attempt):
    """A retry may follow technical failures only, never a successful baseline."""
    previous = []
    for number in range(1, attempt):
        _, _, directory = attempt_paths(root, number)
        path = directory / "PRODUCTION_RUN.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if (record["status"] != "BENCHMARK_NOT_RUN"
                or (directory / "prediction.json").exists()
                or (directory / "evaluation.json").exists()):
            raise ValueError("Cannot retry a successful or frozen baseline")
        previous.append({"attempt": number, "manifest": str(path.relative_to(root)),
                         "sha256": digest(path), "status": record["status"]})
    return previous


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_source_changes(root, changed_files, responses_client_sha256=None):
    """Default remains clean main; explicit retry permits only the pinned API adapter."""
    if not changed_files:
        return {}
    allowed = {"src/article_agent/models.py", "tests/test_models.py", ".env.example", "README.md"}
    if not responses_client_sha256 or set(changed_files) - allowed:
        raise ValueError("Production changes exceed the authorized Responses transport patch")
    actual = digest(Path(root) / "src/article_agent/models.py")
    if actual != responses_client_sha256.lower():
        raise ValueError("Responses client differs from the authorized SHA256")
    return {"path": "src/article_agent/models.py", "sha256": actual,
            "changed_files": sorted(changed_files),
            "authorization": "User authorized Responses endpoint switch and all-sol full retry",
            "extraction_prompts_and_algorithms_changed": False}


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def redact(text, env_path):
    # Read configuration only to remove secrets, never publish the configuration.
    values = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    for key, value in values.items():
        if re.search(r"KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION", key, re.I) and len(value) > 7:
            text = text.replace(value, "[REDACTED]")
    return re.sub(r"(?:sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+)", "[REDACTED]", text)


def technical_failure_summary(run, isolation, parser_backend, topology_errors):
    """Technical non-run is not an evaluator failure and never has zero accuracy."""
    if run["status"] != "BENCHMARK_NOT_RUN":
        raise ValueError("Only a failed production attempt belongs in this report")
    return {
        "benchmark_id": run["benchmark_id"], "article_id": run["article_id"],
        "status": "BENCHMARK_NOT_RUN", "production_git_sha": run["production_git_sha"],
        "actual_parser_backend": parser_backend, "prediction_sha256": None,
        "metrics": None, "entity_metrics": None, "field_failure_counts": None,
        "entity_failure_counts": None, "evaluator_executed": False,
        "technical_failure": {"stage": "trial_topology", "http_401_invalid_token":
                              sum(len(re.findall(r"API HTTP 401", text)) for text in topology_errors),
                              "http_status_counts": dict(sorted(Counter(
                                  status for text in topology_errors
                                  for status in re.findall(r"API HTTP (\d{3})", text)).items())),
                              "upstream_messages": dict(sorted(Counter(
                                  message for text in topology_errors
                                  for message in re.findall(r'"message"\s*:\s*"([^"\n]+)"', text)).items()))},
        "requests": {"production_attempts": run.get("attempt", 1), "topology_attempts": len(topology_errors),
                     "topology_retries": max(0, len(topology_errors) - 1),
                     "successful_topology_responses": 0},
        "model_configuration": isolation["model_configuration"],
        "model_execution_note": "Only trial_topology was reached; other roles are configured, not executed.",
        "forbidden_read_attempts": isolation["forbidden_read_attempts"],
        "production_modified": bool(run.get("authorized_transport_patch")),
        "authorized_transport_patch": run.get("authorized_transport_patch", {}),
        "reference_or_evaluator_modified": False,
    }


def finalize_topology_failure(root, attempt):
    """Report a completed technical failure, without annotation/evaluator access."""
    isolated, output, bench = attempt_paths(root, attempt)
    run = json.loads((bench / "PRODUCTION_RUN.json").read_text(encoding="utf-8"))
    isolation = json.loads((bench / "PRODUCTION_ISOLATION.json").read_text(encoding="utf-8"))
    source = json.loads((bench / "ISOLATED_SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    article_dir = output / "2015-06"
    errors = sorted((article_dir / "trial_topology").glob("topology.error-*.txt"))
    assert errors and not (article_dir / "trial_topology/trial_topology.json").exists()
    assert not (bench / "prediction.json").exists() and not (bench / "evaluation.json").exists()
    mismatches = [name for name, expected in source["files"].items()
                  if digest(isolated / name) != expected or digest(Path(root) / name) != expected]
    assert not mismatches and not isolation["forbidden_read_attempts"]
    assert not (isolated / "gold").exists() and not (isolated / "datas/label").exists()
    pipeline = json.loads((article_dir / "manifest.json").read_text(encoding="utf-8"))
    messages = [redact(p.read_text(encoding="utf-8"), isolated / ".env") for p in errors]
    summary = technical_failure_summary(run, isolation, pipeline["parser_backend"], messages)
    statuses = summary["technical_failure"]["http_status_counts"]
    upstream_messages = summary["technical_failure"]["upstream_messages"]
    configuration_path = bench / "CONFIGURATION_CHANGE.json"
    configuration = json.loads(configuration_path.read_text(encoding="utf-8")) if configuration_path.exists() else None
    summary["authorized_configuration_change"] = configuration
    summary["source_integrity"] = {"verified_files": len(source["files"]), "mismatches": mismatches}
    summary["previous_failed_attempts"] = run.get("previous_failed_attempts", [])
    manifest = {**run, "prediction_sha256": None, "evaluator_executed": False,
                "actual_parser_backend": pipeline["parser_backend"],
                "model_configuration": isolation["model_configuration"],
                "requests": summary["requests"], "technical_failure": summary["technical_failure"],
                "source_integrity": summary["source_integrity"], "forbidden_read_attempts": [],
                "authorized_configuration_change": configuration}
    report = ["# PR5D-1 — 2015-06 技术重试报告", "", "状态：BENCHMARK_NOT_RUN（未评分，不是 0 分）。", "",
              f"本次为 attempt {attempt}；之前失败记录保留，未覆盖。",
              f"Production SHA：{run['production_git_sha']}",
              f"解析：{pipeline['parser_backend']}，已生成 Markdown / 表格结构。",
              "停止阶段：TrialTopology；后续 ArmDetails、metadata、outcome、VLM 未执行。",
              f"模型：{isolation['model_configuration']['trial_topology']}。",
              f"Topology 尝试 {len(errors)} 次（含 {max(0, len(errors)-1)} 次既有自动重试）。",
              "HTTP 响应计数：" + json.dumps(summary["technical_failure"]["http_status_counts"]), "",
              "API 返回的上游错误：" + json.dumps(upstream_messages, ensure_ascii=False), "",
              "没有合法 prediction，故实体数量、匹配、HARD exact、coverage、value/status accuracy、evidence grounding、冲突评分及 evaluator determinism 均不适用。",
              "未生成正式 baseline snapshot；没有执行评分或参考旧分数。", "",
              "## 隔离与完整性", "",
              f"{len(source['files'])} 个 production / 依赖文件哈希与隔离副本一致。",
              "未修改提取算法、Gold、Registry、evaluator。未读取 Gold/标签。",
              "通信层授权改动：" + json.dumps(run.get("authorized_transport_patch", {}), ensure_ascii=False),
              "模型是否变更以授权配置记录为准；prompt 和 production 既有 retry 策略未改。",
              "已授权配置变更：" + json.dumps(configuration, ensure_ascii=False),
              "原始 output、请求错误文件和脱敏日志均保留在本地。", "",
              "## 错误日志", "", "```text", *messages, "```", ""]
    cause = (
        "服务端返回 HTTP 502 / upstream_error。其报文报告上游访问被禁止或暂不可用；这是供应商返回的原因，未独立验证其内部路由。它不是本地 PDF 解析失败，也不能单凭该报文判断 Key 权限或模型是否存在。"
        if "502" in statuses else
        "若响应为 404 且正文为空，可能来自接口路径/网关路由或模型路由；仅凭 404 不能区分。它不证明凭据有效，也不证明模型不存在。其他错误以本次保存的原始错误文件为准。"
    )
    analysis = ["# Failure Analysis — Technical non-run", "",
                "正式 evaluator failure taxonomy 不适用：production 在拓扑提取阶段终止，尚无 prediction。", "",
                "## 已确认", "",
                "MinerU 转换成功。所有已记录 topology 请求都失败，没有可验证的 topology 响应。",
                "HTTP 计数：" + json.dumps(summary["technical_failure"]["http_status_counts"]), "",
                "API 上游报文及次数：" + json.dumps(upstream_messages, ensure_ascii=False), "",
                "## 原因边界", "",
                cause,
                "只使用本次配置的 base URL 和既有 retry；未增加测试请求。服务地址变更见 CONFIGURATION_CHANGE.json（若存在）。",
                "若日志含 MinerU 子进程文本解码异常：Markdown 已生成且流程随后进入 API，因此它不是最终阻断点。", "",
                "## 下一步所需信息", "",
                f"需要按本次 API 错误确认服务可用性及 {isolation['model_configuration']['trial_topology']} 路由；若要进一步更换模型，须另获授权。",
                "本次不修 extraction，不制造 prediction，不运行 Gold 评分。", ""]
    write_json(bench / "SUMMARY.json", summary)
    write_json(bench / "RUN_MANIFEST.json", manifest)
    (bench / "REPORT.md").write_text("\n".join(report), encoding="utf-8")
    (bench / "FAILURE_ANALYSIS.md").write_text("\n".join(analysis), encoding="utf-8")
    return summary


def child():
    denied = []
    def audit(event, args):
        if event != "open" or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = Path(os.fsdecode(args[0]))
        parts = {p.casefold() for p in path.parts}
        if parts.intersection({"gold", "label", "labels", "json_gold"}) or path.suffix.casefold() in {".xlsx", ".xls", ".xlsm"}:
            denied.append(str(path))
            raise PermissionError("Benchmark isolation forbids Gold/label/Excel reads")
    sys.addaudithook(audit)
    os.chdir(ISOLATED)
    sys.path.insert(0, str(ISOLATED / "src"))
    sys.argv = [str(ISOLATED / "MinerU method/run.py"), "--pdf", PDF_REL,
                "--parser", "auto", "--use-api", "--output-root", str(OUTPUT)]
    code = 0
    try:
        runpy.run_path(sys.argv[0], run_name="__main__")
    except SystemExit as exc:
        code = exc.code or 0
    except Exception:
        traceback.print_exc()
        code = 1
    finally:
        # Only model names/roles, never API endpoints, credentials or headers.
        default = os.getenv("ARTICLE_AGENT_MODEL") or "gpt-5.5"
        model_roles = {
            "default": default,
            "trial_topology": os.getenv("ARTICLE_AGENT_TOPOLOGY_MODEL", "gpt-5.6-luna"),
            "arm_details": os.getenv("ARTICLE_AGENT_ARM_DETAILS_MODEL", "gpt-5.6-sol"),
            "structured_metadata_protocol_risk": os.getenv("ARTICLE_AGENT_STRUCTURED_MODEL") or default,
            "table_classification": os.getenv("ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL") or os.getenv("ARTICLE_AGENT_BASIC_MATCH_MODEL") or "gpt-5.6-luna",
            "outcomes_postprocess": default,
            "vlm": os.getenv("ARTICLE_AGENT_VISION_MODEL") or default,
            "retry": os.getenv("ARTICLE_AGENT_RETRY_MODEL") or default,
        }
        write_json(BENCH / "PRODUCTION_ISOLATION.json", {
            "forbidden_read_attempts": denied, "model_configuration": model_roles,
            "api_mode": os.getenv("ARTICLE_AGENT_API_MODE", "chat_completions"),
            "gold_or_label_inputs_present": False, "loader_monkeypatched": False,
            "unchanged_entrypoint": "MinerU method/run.py", "child_exit_code": code,
        })
    return code


def main():
    global ISOLATED, OUTPUT, BENCH
    parser = argparse.ArgumentParser()
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--attempt", type=int, default=1,
                        help="Explicitly authorized technical retry; uses fresh directories")
    parser.add_argument("--failure-report-only", action="store_true",
                        help="Write a technical non-run report from existing local logs; no API")
    parser.add_argument("--responses-client-sha256",
                        help="Explicitly pin the previously authorized Responses transport patch")
    args = parser.parse_args()
    ISOLATED, OUTPUT, BENCH = attempt_paths(ROOT, args.attempt)
    if args.failure_report_only:
        print(json.dumps(finalize_topology_failure(ROOT, args.attempt), ensure_ascii=False))
        return 0
    if args.child:
        return child()
    assert Path(sys.executable).resolve() == Path(r"D:\Application\Anaconda\envs\Agent\python.exe").resolve()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tracked = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True)
    assert sha == PRODUCTION_SHA, "Production must start from the requested main commit"
    changed_files = subprocess.check_output(
        ["git", "diff", "HEAD", "--name-only", "-z"], cwd=ROOT
    ).decode().split("\0")
    transport_patch = validate_source_changes(ROOT, [p for p in changed_files if p], args.responses_client_sha256)
    previous_attempts = failed_predecessors(ROOT, args.attempt)
    assert not ISOLATED.exists() and not OUTPUT.exists(), "Never repeat or overwrite baseline production"
    assert not (BENCH / "PRODUCTION_RUN.json").exists(), "A production attempt is already recorded"
    ISOLATED.mkdir(parents=True)
    BENCH.mkdir(parents=True, exist_ok=True)
    files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    prefixes = ("src/", "MinerU method/mineru_method/", "registry/legacy-excel/", "baml_src/", "skills/")
    exact = {"MinerU method/run.py", "pyproject.toml", ".gitignore"}
    copied = {}
    for name in files:
        if name and (name.startswith(prefixes) or name in exact):
            source, dest = ROOT / name, ISOLATED / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            assert digest(source) == digest(dest)
            copied[name] = digest(dest)
    # Preserve the generated dependency used by this workspace if it is not tracked.
    generated = ROOT / "baml_client"
    if generated.is_dir():
        for source in sorted(generated.rglob("*.py")):
            dest = ISOLATED / source.relative_to(ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest)
            copied[str(source.relative_to(ROOT)).replace("\\", "/")] = digest(dest)
    env_file = ROOT / ".env"
    if env_file.exists():
        shutil.copy2(env_file, ISOLATED / ".env")
    isolated_pdf = ISOLATED / PDF_REL
    isolated_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / PDF_REL, isolated_pdf)
    assert not (ISOLATED / "gold").exists() and not (ISOLATED / "datas/label").exists()
    source_manifest = {"production_git_sha": sha, "files": copied, "authorized_transport_patch": transport_patch}
    source_manifest["source_files_sha256"] = hashlib.sha256(
        json.dumps(copied, sort_keys=True).encode("utf-8")
    ).hexdigest()
    write_json(BENCH / "ISOLATED_SOURCE_MANIFEST.json", source_manifest)
    command = [sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--child",
               "--attempt", str(args.attempt)]
    production_command = [sys.executable, "MinerU method/run.py", "--pdf", PDF_REL,
                          "--parser", "auto", "--use-api", "--output-root", str(OUTPUT)]
    run = {"benchmark_id": "2015-06-baseline-v1", "article_id": "2015-06", "status": "RUNNING",
           "production_git_sha": sha, "tracked_git_status_at_start": tracked,
           "source_pdf_sha256": digest(isolated_pdf), "requested_parser": "auto",
           "production_command": production_command, "production_output_root": str(OUTPUT),
           "input_isolation": "isolated hashed source snapshot; no Gold/labels; declared transport patch only",
           "authorized_transport_patch": transport_patch,
           "source_files_sha256": source_manifest["source_files_sha256"],
           "attempt": args.attempt, "previous_failed_attempts": previous_attempts}
    configuration_path = BENCH / "CONFIGURATION_CHANGE.json"
    if configuration_path.exists():
        run["authorized_configuration_change"] = json.loads(configuration_path.read_text(encoding="utf-8"))
    write_json(BENCH / "PRODUCTION_RUN.json", run)
    env = dict(os.environ)
    runtime = Path(sys.executable).parent
    runtime_paths = [runtime, runtime / "Library/mingw-w64/bin", runtime / "Library/usr/bin",
                     runtime / "Library/bin", runtime / "Scripts", runtime / "bin"]
    env["PATH"] = os.pathsep.join(map(str, runtime_paths)) + os.pathsep + env.get("PATH", "")
    env["CONDA_PREFIX"] = str(runtime)
    env["CONDA_DEFAULT_ENV"] = "Agent"
    env["PYTHONPATH"] = str(ISOLATED / "src")
    print("One isolated production attempt started; no Gold/label input, existing retry policies only.", flush=True)
    result = subprocess.run(command, cwd=ISOLATED, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    (BENCH / "production.stdout.log").write_text(redact(result.stdout, env_file), encoding="utf-8")
    (BENCH / "production.stderr.log").write_text(redact(result.stderr, env_file), encoding="utf-8")
    complete = result.returncode == 0 and (OUTPUT / "2015-06/extraction.json").exists()
    run.update(status="PRODUCTION_COMPLETE" if complete else "BENCHMARK_NOT_RUN", exit_code=result.returncode)
    write_json(BENCH / "PRODUCTION_RUN.json", run)
    print(json.dumps({"status": run["status"], "exit_code": result.returncode, "logs": str(BENCH)}, ensure_ascii=False))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
