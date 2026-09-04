"""Evidence-only conflict grouping and canonical outcome projection.

This module deliberately does not read the Excel gold workbook.  It builds a
second, smaller view from the article-derived source rows and optional
normalisation annotations.  Every canonical row points back to all source
indices; disagreements are represented as conflict groups instead of silently
overwriting one value with another.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Iterable

from .schemas import (
    CanonicalOutcomeRecord,
    OutcomeCanonicalDataset,
    OutcomeConflictGroup,
    OutcomePostProcessRecord,
    OutcomeStatistic,
)


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"[\u2010-\u2015\-_/]+", " ", text)
    text = re.sub(r"[^\w\s.]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip() or "nr"


def _display(value: object) -> str:
    text = str(value or "").strip()
    return text if text and text.upper() != "NR" else "NR"


def _annotation(record: OutcomePostProcessRecord, field: str, source_value: object) -> str:
    value = getattr(record, field, None)
    if value not in (None, "", "NR"):
        return _norm(value)
    return _norm(source_value)


def _arm_identity(outcome: OutcomeStatistic) -> tuple:
    arms = []
    for arm in outcome.arm:
        # Prefer the explicit arm_id.  When MinerU/LLM did not supply one,
        # the verbatim label is the only available identity.  Keeping both
        # in the key would split harmless formatting differences (for
        # example, an ID reused with a shortened display label).
        arm_key = _norm(arm.arm_id)
        if arm_key == "nr":
            arm_key = _norm(arm.arm_label)
        arms.append((
            arm_key,
            _norm(arm.role),
        ))
    return tuple(sorted(arms))


def identity_key(record: OutcomePostProcessRecord) -> tuple:
    """Return a formatting-normalized identity key, never a guessed synonym."""

    outcome = record.source_outcome
    comparison = outcome.comparison
    relation = record.comparison_relation if record.comparison_relation not in ("", "NR") else comparison.relation
    comparison_key = (
        _norm(relation),
        _norm(comparison.intervention_arm_id),
        _norm(comparison.control_arm_id),
        tuple(sorted(_norm(value) for value in comparison.comparator_arm_ids)),
    )
    return (
        _annotation(record, "normalized_outcome_name", outcome.outcome_name),
        _annotation(record, "normalized_measurement_instrument", outcome.measurement_instrument),
        _annotation(record, "normalized_timepoint", outcome.outcome_observation_timepoint_raw),
        _norm(outcome.analysis_set),
        _norm(outcome.record_role),
        comparison_key,
        _arm_identity(outcome),
    )


def _key_text(key: tuple) -> str:
    return json.dumps(key, ensure_ascii=False, separators=(",", ":"), default=list)


def _group_id(key_text: str) -> str:
    return f"cg-{hashlib.sha1(key_text.encode('utf-8')).hexdigest()[:12]}"


def _canonical_id(key_text: str) -> str:
    return f"co-{hashlib.sha1(key_text.encode('utf-8')).hexdigest()[:12]}"


_COMPARISON_FIELDS = (
    "intervention_estimate", "intervention_variance_lower", "intervention_variance_upper",
    "intervention_n", "control_estimate", "control_variance_lower", "control_variance_upper",
    "control_n", "between_group_measure", "outcome_between_group_estimate",
    "outcome_between_group_lower", "outcome_between_group_upper", "outcome_p_value",
    "outcome_p_value_comparator", "effect_size_name",
)


def _same_value(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return abs(float(left) - float(right)) <= 1e-9
    return _norm(left) == _norm(right)


def _conflicting_fields(records: list[OutcomePostProcessRecord]) -> list[str]:
    if len(records) < 2:
        return []
    fields: list[str] = []
    for field in _COMPARISON_FIELDS:
        values = [getattr(record.source_outcome, field) for record in records]
        present = [value for value in values if value is not None and value != "NR"]
        if len(present) > 1 and any(not _same_value(present[0], value) for value in present[1:]):
            fields.append(field)
    identity_fields = (
        ("outcome_name", lambda item: _annotation(item, "normalized_outcome_name", item.source_outcome.outcome_name)),
        ("measurement_instrument", lambda item: _annotation(item, "normalized_measurement_instrument", item.source_outcome.measurement_instrument)),
        ("timepoint", lambda item: _annotation(item, "normalized_timepoint", item.source_outcome.outcome_observation_timepoint_raw)),
        ("analysis_set", lambda item: item.source_outcome.analysis_set),
        ("record_role", lambda item: item.source_outcome.record_role),
    )
    for name, getter in identity_fields:
        values = [_norm(getter(record)) for record in records]
        if len(set(value for value in values if value != "nr")) > 1:
            fields.append(name)
    arm_values = [_arm_identity(record.source_outcome) for record in records]
    if len(set(arm_values)) > 1:
        fields.append("arm")
    comparison_values = [
        (
            record.source_outcome.comparison.relation,
            record.source_outcome.comparison.intervention_arm_id,
            record.source_outcome.comparison.control_arm_id,
            tuple(record.source_outcome.comparison.comparator_arm_ids),
        )
        for record in records
    ]
    if len(set(comparison_values)) > 1:
        fields.append("comparison")
    return sorted(set(fields))


def _completeness(record: OutcomePostProcessRecord) -> tuple[int, int, int, int]:
    outcome = record.source_outcome
    numeric = sum(getattr(outcome, field) is not None for field in _COMPARISON_FIELDS)
    identity = sum(
        value not in (None, "", "NR")
        for value in (
            outcome.table_id,
            outcome.row_id,
            outcome.analysis_set,
            outcome.record_role,
            outcome.comparison.relation,
            bool(outcome.arm),
        )
    )
    evidence = len(outcome.evidence)
    # Primary/direct-source rows win only when the source explicitly says so;
    # this is a deterministic tie-breaker, not a medical priority inference.
    primary = int(outcome.record_role == "primary")
    return numeric, evidence, identity, primary


def _selection_basis(records: list[OutcomePostProcessRecord], chosen: OutcomePostProcessRecord) -> tuple[str, str]:
    if len(records) == 1:
        return "single_source", "该语义身份只有一个来源记录。"
    ordered = sorted(records, key=lambda item: (-_completeness(item)[0], -_completeness(item)[1], -_completeness(item)[2], -_completeness(item)[3], item.source_index))
    if ordered[0].source_index == chosen.source_index:
        return "most_complete_evidence", "同一语义身份的重复记录保留信息最完整且证据最多的来源行；其余来源仍保留在 conflict group。"
    return "direct_source_priority", "按稳定 source_index 选择代表行；没有使用金标准或跨行补值。"


def build_canonical_outcome_dataset(records: Iterable[OutcomePostProcessRecord]) -> OutcomeCanonicalDataset:
    """Build a canonical projection while retaining every source row."""

    all_records = sorted(list(records), key=lambda item: item.source_index)
    base_grouped: dict[tuple, list[OutcomePostProcessRecord]] = defaultdict(list)
    for record in all_records:
        base_grouped[identity_key(record)].append(record)

    # ``duplicate_group`` is an optional LLM annotation from the separate
    # post-processing pass.  Treat it as a grouping hint, never as a value
    # correction: if it joins otherwise different semantic keys, the merged
    # group is explicitly marked conflict by ``_conflicting_fields`` below.
    # This catches repeated rows whose labels/timepoint formatting differ while
    # still retaining every source record and all disagreements.
    parent = {key: key for key in base_grouped}

    def find(key: tuple) -> tuple:
        root = parent[key]
        while parent[root] != root:
            parent[root] = parent[parent[root]]
            root = parent[root]
        parent[key] = root
        return root

    def union(left: tuple, right: tuple) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            # Stable union direction keeps component IDs independent of
            # dictionary insertion order.
            if _key_text(left_root) > _key_text(right_root):
                left_root, right_root = right_root, left_root
            parent[right_root] = left_root

    duplicate_to_keys: dict[str, set[tuple]] = defaultdict(set)
    for key, group in base_grouped.items():
        for record in group:
            duplicate_group = _norm(record.duplicate_group)
            if duplicate_group != "nr":
                duplicate_to_keys[duplicate_group].add(key)
    for keys in duplicate_to_keys.values():
        keys = sorted(keys, key=_key_text)
        for key in keys[1:]:
            union(keys[0], key)

    component_records: dict[tuple, list[OutcomePostProcessRecord]] = defaultdict(list)
    component_keys: dict[tuple, set[tuple]] = defaultdict(set)
    for key, group in base_grouped.items():
        root = find(key)
        component_records[root].extend(group)
        component_keys[root].add(key)

    grouped: dict[tuple, list[OutcomePostProcessRecord]] = {}
    for root, group in component_records.items():
        base_keys = sorted(component_keys[root], key=_key_text)
        if len(base_keys) == 1:
            combined_key = base_keys[0]
        else:
            duplicate_ids = sorted(
                duplicate_group
                for duplicate_group, keys in duplicate_to_keys.items()
                if any(key in component_keys[root] for key in keys)
            )
            combined_key = (
                "explicit_duplicate_group",
                tuple(duplicate_ids),
                tuple(base_keys),
            )
        grouped[combined_key] = sorted(group, key=lambda item: item.source_index)

    canonical_records: list[CanonicalOutcomeRecord] = []
    conflict_groups: list[OutcomeConflictGroup] = []
    for key, group in sorted(grouped.items(), key=lambda pair: _key_text(pair[0])):
        key_text = _key_text(key)
        source_indices = [item.source_index for item in group]
        source_row_ids = [item.source_outcome.row_id for item in group]
        conflicts = _conflicting_fields(group)
        def contains_unknown(value: object) -> bool:
            if isinstance(value, str):
                return _norm(value) == "nr"
            if isinstance(value, (tuple, list)):
                return any(contains_unknown(item) for item in value)
            return False

        has_unknown_identity = contains_unknown(key)
        if len(group) == 1:
            group_status = None
        elif conflicts:
            group_status = "conflict"
        elif has_unknown_identity:
            group_status = "unresolved"
        else:
            group_status = "duplicate"
        conflict_group_id = _group_id(key_text) if len(group) > 1 else None
        if conflict_group_id:
            reason = (
                "同一规范化结局身份的来源行包含不同统计值，保留各版本并标记冲突。"
                if group_status == "conflict" else
                "同一规范化结局身份在多个来源表/行重复出现，未删除任何来源。"
            )
            if group_status == "unresolved":
                reason = "结局身份字段存在NR，无法确认重复是否为同一分析；保留各来源并要求人工复核。"
            conflict_groups.append(OutcomeConflictGroup(
                conflict_group_id=conflict_group_id,
                source_indices=source_indices,
                source_row_ids=source_row_ids,
                identity_key=key_text,
                group_status=group_status or "unresolved",
                conflict_fields=conflicts,
                reason=reason,
            ))
        chosen = sorted(group, key=lambda item: (-_completeness(item)[0], -_completeness(item)[1], -_completeness(item)[2], -_completeness(item)[3], item.source_index))[0]
        basis, selection_reason = _selection_basis(group, chosen)
        if group_status == "conflict":
            selection_status = "conflict"
        elif group_status == "unresolved":
            selection_status = "unresolved"
            basis = "unresolved"
            selection_reason = "来源记录存在无法由证据消解的身份或数值冲突；canonical 行仅作代表，不表示已判定正确。"
        else:
            selection_status = "selected"
        canonical_records.append(CanonicalOutcomeRecord(
            canonical_id=_canonical_id(key_text),
            source_indices=source_indices,
            conflict_group_id=conflict_group_id,
            selection_status=selection_status,
            selection_basis=basis,
            selection_reason=selection_reason,
            outcome=chosen.source_outcome,
        ))

    return OutcomeCanonicalDataset(
        source_outcome_count=len(all_records),
        canonical_outcome_count=len(canonical_records),
        conflict_group_count=len(conflict_groups),
        gold_used=False,
        records=canonical_records,
        conflict_groups=conflict_groups,
        notes=[
            "canonical dataset 仅依据论文来源行及无损规范化注释生成。",
            "未读取或使用金标准值；每个 canonical 行通过 source_indices 回指原始记录。",
            "重复/冲突来源不会被删除，冲突组中的代表行不等于已确认正确值。",
        ],
    )
