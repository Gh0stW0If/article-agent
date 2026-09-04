from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "Datas"
ARTICLES_DIR = DATA_DIR / "articles"
LABELS_DIR = DATA_DIR / "label"
TEMPLATE_PATH = PROJECT_ROOT / "optimized_article_extraction_template.xlsx"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
