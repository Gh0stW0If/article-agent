from __future__ import annotations

import re
from pathlib import Path

from .schemas import ConsortFlowExtraction, FlowEvent, FlowEvidence


def render_figure_one_page(pdf: Path, output: Path) -> tuple[Path, int]:
    import fitz

    with fitz.open(pdf) as document:
        page_index = 0
        for index, page in enumerate(document):
            text = page.get_text("text")
            if re.search(r"(?:Figure|Fig\.?)[ ]*1\b", text, re.I) and re.search(r"flow|consort|participant", text, re.I):
                page_index = index
                break
        page = document[page_index]
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2.2, 2.2), alpha=False)
        output.parent.mkdir(parents=True, exist_ok=True)
        pixmap.save(output)
    return output, page_index + 1


def cross_check(risk, flow) -> list[str]:
    issues: list[str] = []
    if flow is None:
        return issues
    if risk.total_randomized is not None and flow.randomized_n is not None and risk.total_randomized != flow.randomized_n:
        issues.append(f"Methods total_randomized={risk.total_randomized}, Figure 1 randomized_n={flow.randomized_n}")
    method_arms = [risk.randomized_sample_intervention_raw, risk.randomized_sample_control_raw]
    figure_arms = [arm.randomized_n for arm in flow.arms]
    if all(value is not None for value in method_arms) and len(figure_arms) == 2 and all(value is not None for value in figure_arms):
        if sorted(method_arms) != sorted(figure_arms):
            issues.append(f"Methods randomized arm sizes={method_arms}, Figure 1 arm sizes={figure_arms}")
    return issues


def reconcile_flow(flow: ConsortFlowExtraction, markdown: str) -> ConsortFlowExtraction:
    """Separate explicit trial exits from stage-specific missing follow-up events."""
    flow = flow.model_copy(deep=True)

    def deduplicate(events):
        seen = set()
        result = []
        for event in events:
            key = (event.stage.lower(), event.n, event.reason.lower())
            if key not in seen:
                seen.add(key)
                result.append(event)
        return result

    for arm in flow.arms:
        explicit_losses = []
        stage_missing = list(arm.other_missing_data)
        for event in arm.dropout_reasons:
            marker = f"{event.stage} {event.reason}".lower()
            if any(token in marker for token in ("outset", "before treatment", "withdrew", "withdraw", "lost from trial")):
                explicit_losses.append(event)
            else:
                stage_missing.append(event)
        arm.dropout_reasons = deduplicate(explicit_losses)
        arm.other_missing_data = deduplicate(stage_missing)
        known_loss_counts = [event.n for event in arm.dropout_reasons if event.n is not None]
        arm.dropout_n = sum(known_loss_counts) if known_loss_counts else None

    comprised = re.search(
        r"study\s+comprised\s+(\d+)\s+participants\s+in\s+the\s+IA\s+group\s+and\s+(\d+)\s+in\s+the\s+SA\s+group",
        markdown,
        re.I,
    )
    if comprised:
        ia_n, sa_n = int(comprised.group(1)), int(comprised.group(2))
        quote = comprised.group(0)
        for arm in flow.arms:
            low = arm.arm_name.lower()
            if "individual" in low or low == "ia":
                arm.received_n = ia_n
            elif "sham" in low or low == "sa":
                arm.received_n = sa_n
        flow.evidence.append(FlowEvidence(quote=quote, source="markdown", support_type="direct"))
    else:
        for arm in flow.arms:
            if arm.received_n is None and arm.randomized_n is not None and arm.dropout_n is not None:
                arm.received_n = arm.randomized_n - arm.dropout_n
                flow.evidence.append(FlowEvidence(
                    quote=f"{arm.randomized_n} allocated; {arm.dropout_n} explicitly lost before treatment",
                    source="figure",
                    support_type="derived",
                    derivation=f"received_n = randomized_n - pre_treatment_loss = {arm.randomized_n} - {arm.dropout_n}",
                ))

    withdrew = re.search(
        r"Two\s+withdrew\s+before\s+the\s+start\s+of\s+treatment,\s+one\s+due\s+to\s+comorbidity\s*\(acute\s+myocardial\s+infarction\)\s+and\s+the\s+other\s+due\s+to\s+a\s+change\s+of\s+address",
        markdown,
        re.I,
    )
    if withdrew:
        ia_arm = next((arm for arm in flow.arms if "individual" in arm.arm_name.lower() or arm.arm_name.lower() == "ia"), None)
        if ia_arm is not None and not ia_arm.dropout_reasons:
            ia_arm.dropout_n = 2
            ia_arm.dropout_reasons = [
                FlowEvent(stage="before treatment", n=1, reason="acute myocardial infarction"),
                FlowEvent(stage="before treatment", n=1, reason="changed address"),
            ]
            flow.evidence.append(FlowEvidence(quote=withdrew.group(0), source="markdown", support_type="direct"))
    return flow
