from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from mineru_method import run_experiment


def main() -> int:
    parser = argparse.ArgumentParser(description="MinerU section-routed modular extraction experiment")
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--parser", choices=("auto", "mineru", "docling", "pymupdf"), default="auto")
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "outputs" / "mineru_method")
    parser.add_argument("--use-api", action="store_true")
    parser.add_argument("--no-vlm", action="store_true")
    parser.add_argument("--force-backend", choices=("docling", "mineru", "pymupdf"))
    args = parser.parse_args()
    result = run_experiment(
        pdf=args.pdf,
        project_root=PROJECT_ROOT,
        output_root=args.output_root,
        parser=args.parser,
        markdown_path=args.markdown,
        use_api=args.use_api,
        use_vlm=not args.no_vlm,
        force_backend=args.force_backend,
    )
    inferred_id = next(iter(__import__("re").findall(r"20\d{2}-\d+", args.pdf.stem)), args.pdf.stem.lstrip("-"))
    manifest_backend = args.parser
    manifest_path = args.output_root / inferred_id / "manifest.json"
    if manifest_path.exists():
        try:
            manifest_backend = json.loads(manifest_path.read_text(encoding="utf-8")).get("parser_backend", manifest_backend)
        except (OSError, ValueError):
            pass
    print(json.dumps({
        "status": "extracted" if result else "prepared",
        "article_id": result.article_id if result else inferred_id,
        "parser_backend": result.parser_backend if result else manifest_backend,
        "output_root": str(args.output_root.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
