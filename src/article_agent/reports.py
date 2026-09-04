from __future__ import annotations

import json
from pathlib import Path

from .schemas import EvidenceSpan, ReviewRecord, StudyRecord


def write_json(path: Path, studies: list[StudyRecord], evidence: list[EvidenceSpan], review: list[ReviewRecord]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "studies": [s.model_dump(mode="json") for s in studies],
        "evidence": [e.model_dump(mode="json") for e in evidence],
        "needs_review": [r.model_dump(mode="json") for r in review],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_evidence_report(path: Path, studies: list[StudyRecord]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = ["# Evidence Report", ""]
    for study in studies:
        lines.extend([f"## {study.study_id}", ""])
        for field in [study.title, study.year, study.journal, study.language, study.first_author, study.corresponding_author_email, study.doi, study.disease_name, study.country, study.intervention_name, study.control_name, study.randomized_n, study.primary_outcome, study.treatment_sessions]:
            lines.append(f"### {field.field_name}")
            lines.append(f"Extracted value: {field.value}")
            lines.append(f"Code: {field.code}")
            lines.append(f"Confidence: {field.confidence}")
            lines.append(f"Needs review: {'yes' if field.needs_review else 'no'}")
            lines.append(f"Reason: {field.reason}")
            if field.evidence:
                ev = field.evidence[0]
                lines.append(f"Page: {ev.page}")
                lines.append(f"Section: {ev.section}")
                lines.append(f"Evidence: {ev.evidence_text}")
            else:
                lines.append("Evidence: NR")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_run_log(path: Path, logs: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in logs) + "\n", encoding="utf-8")
    return path
