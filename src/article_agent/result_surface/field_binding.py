"""Structural field-to-cell binding. No Gold, value search or approximate matching."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import re

from ..result_identity.source_context import source_blocks_for_result
from .surface_normalization import contrast_parts, surface_text

P_NUMBER = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
P_SURFACE = re.compile(rf"^\s*(p\s*)?(<=|>=|<|>|=|≤|≥)?\s*({P_NUMBER})\s*$", re.I)


def parse_p_surface(value):
    """Preserve the exact scalar and operator; strip only the statistical P label."""
    if not isinstance(value, str):
        return None
    match = P_SURFACE.fullmatch(value)
    if not match or (match[1] and not match[2]):
        return None
    try:
        number = Decimal(match[3])
    except InvalidOperation:
        return None
    if not number.is_finite() or not 0 <= number <= 1:
        return None
    operator = {"≤": "<=", "≥": ">="}.get(match[2], match[2]) or "="
    numeric_text = format(number, "f")
    if "." in numeric_text:
        numeric_text = numeric_text.rstrip("0").rstrip(".")
    return {"raw_scalar": value, "operator": operator, "numeric_value": float(number),
            "canonical_scalar": ("" if operator == "=" else operator) + numeric_text}


def unwrap_surface(value):
    """Only a true singleton wrapper may be unwrapped without a column mapping."""
    original, operations = deepcopy(value), []
    if isinstance(value, str) and value.strip().startswith(("[", "{")):
        try:
            value = json.loads(value)
        except ValueError:
            return original, operations, "SOURCE_CONTAINER_INVALID"
    while isinstance(value, list) and len(value) == 1:
        value = value[0]
        operations.append("SINGLETON_SOURCE_WRAPPER_UNWRAPPED")
    if isinstance(value, (list, dict)):
        return value, operations, "SOURCE_BINDING_AMBIGUOUS"
    return value, operations, None


def arm_alias_index(graph):
    aliases = {}
    for arm in graph.arms:
        topology = arm.legacy_fields.get("topology", {})
        labels = [arm.arm_id, arm.label.value if arm.label.status == "PRESENT" else None,
                  topology.get("name"), topology.get("source_label"), *topology.get("aliases", [])]
        for label in labels:
            if isinstance(label, str) and label.strip():
                aliases.setdefault(surface_text(label), set()).add(arm.arm_id)
    return aliases


def resolve_pair(text, aliases):
    parts = contrast_parts(text)
    if not parts:
        return None
    found = [aliases.get(part, set()) for part in parts]
    if any(len(ids) != 1 for ids in found):
        return None
    result = tuple(next(iter(ids)) for ids in found)
    return result if result[0] != result[1] else None


def comparison_definitions(table, graph):
    """Read explicitly labelled contrasts in header/caption/adjacent footnote only."""
    aliases = arm_alias_index(graph)
    definitions = {}
    for column in table["column_map"]:
        for header in column.get("header_path", []):
            key = surface_text(header)
            candidates = []
            direct = resolve_pair(header, aliases)
            if direct:
                candidates.append({"arm_ids": list(direct), "quote": header, "source": "header"})
            for source in ("caption", "footnote"):
                # The actual header supplies the label; there is no assumed P order.
                pattern = r"(?<!\w)" + re.escape(header.strip()) + r"\s*[:=]\s*([^;\n]+)"
                for match in re.finditer(pattern, table.get(source, ""), re.I):
                    wording = match[1].strip().rstrip(".")
                    pair = resolve_pair(wording, aliases)
                    # A second unresolved label definition cannot silently disappear.
                    candidates.append({"arm_ids": list(pair) if pair else [],
                                       "quote": match[0], "source": source})
            if candidates:
                definitions.setdefault(key, []).extend(candidates)
    return definitions


def row_cells(table, row_id):
    cells = []
    for column in table["column_map"]:
        for raw in column.get("source_cells", []):
            if raw["row_id"] == row_id:
                cells.append({"column_index": column["column_index"],
                              "header_path": column.get("header_path", []),
                              "arm_label": column.get("arm_label"),
                              "statistic": column.get("statistic"),
                              "raw_cell": deepcopy(raw)})
    return sorted(cells, key=lambda c: c["column_index"])


def linked_rows(result, context, field=None, evidence=()):
    pairs = set(source_blocks_for_result(result))
    # Field evidence narrows, but cannot silently supply a contradictory result row.
    field_pairs = {(e.table_id, e.row_id) for e in evidence
                   if field and e.evidence_id in field.evidence_ids and e.table_id and e.row_id}
    if pairs and field_pairs and not field_pairs <= pairs:
        return []
    if field_pairs:
        pairs = field_pairs
    return [(table, rid, row_cells(table, rid)) for tid, rid in sorted(pairs)
            for table in context["tables"] if table["table_id"] == tid and row_cells(table, rid)]


def arm_cell(result, graph, table, cells):
    aliases = arm_alias_index(graph)
    choices = []
    for cell in cells:
        labels = [cell["arm_label"]] if cell["arm_label"] not in {None, "", "NR"} else []
        matches = {aid for label in labels for aid in aliases.get(surface_text(label), set())}
        if matches == {result.arm_id}:
            choices.append(cell)
    return choices[0] if len(choices) == 1 else None


def bind_comparison_scalar(result, graph, context):
    """Only fields already PRESENT are candidates; this never fills missing fields."""
    field = result.raw_value
    saved_source = result.legacy_fields.get("result_surface", {}).get("raw_fields", {}).get("raw_value")
    if saved_source:
        # Re-projecting must bind the immutable source, not treat yesterday's
        # canonical scalar as a newly reported raw surface.
        field = type(field).model_validate(saved_source)
    audit = {
        "entity_id": result.comparison_result_id, "entity_type": "ComparisonResult", "field": "raw_value",
        "raw_source_container": field.value, "raw_field": field.model_dump(mode="json"),
        "selected_source_scalar": None, "binding_result": "UNAVAILABLE",
        "binding_confidence": "NO_BINDING", "binding_rule": None, "blockers": [],
        "comparison_id": result.comparison_id, "outcome_id": result.outcome_id,
        "timepoint": result.timepoint.model_dump(mode="json"), "operations": [],
        "evidence_ids": list(field.evidence_ids),
    }
    if field.status != "PRESENT":
        audit["blockers"] = ["FIELD_NOT_PRESENT"]
        return audit
    if result.p_value.status != "PRESENT" or not field.evidence_ids:
        audit["blockers"] = ["P_FIELD_OR_SOURCE_EVIDENCE_NOT_PRESENT"]
        return audit
    if any(getattr(result, name).status == "PRESENT" for name in
           ("estimate", "confidence_interval_lower", "confidence_interval_upper")):
        audit.update(binding_result="AMBIGUOUS", binding_confidence="AMBIGUOUS_BINDING",
                     blockers=["MULTI_STATISTIC_RAW_ROLE_AMBIGUOUS"])
        return audit
    comparison = next(c for c in graph.comparisons if c.comparison_id == result.comparison_id)
    if len(comparison.arm_ids) != 2:
        audit["blockers"] = ["COMPARISON_NOT_EXPLICIT_BINARY"]
        return audit
    parent_ids = set(comparison.arm_ids)
    rows = linked_rows(result, context, field, graph.evidence)
    if rows:
        options = []
        for table, rid, cells in rows:
            definitions = comparison_definitions(table, graph)
            matching_columns = []
            for cell in cells:
                is_p = cell["statistic"] == "p_value" or any(
                    re.fullmatch(r"p\s*(?:[- ]?value)?\s*\d*", h, re.I) for h in cell["header_path"])
                if not is_p:
                    continue
                facts = [d for h in cell["header_path"] for d in definitions.get(surface_text(h), [])]
                participants = {tuple(d["arm_ids"]) for d in facts}
                # Conflicting footnotes make this column unusable, even if one agrees.
                if len(participants) == 1 and set(next(iter(participants))) == parent_ids:
                    matching_columns.append((cell, facts))
            if len(matching_columns) == 1:
                cell, facts = matching_columns[0]
                raw_cell = cell["raw_cell"]
                if raw_cell.get("colspan", 1) != 1 or raw_cell.get("rowspan", 1) != 1:
                    continue
                parsed = parse_p_surface(str(raw_cell["raw_value"]))
                if parsed:
                    options.append({**parsed, "table_id": table["table_id"], "row_id": rid,
                        "column_index": cell["column_index"], "header_path": cell["header_path"],
                        "raw_source_row": cells, "source_ref": table["source_ref"],
                        "comparison_definition": facts})
        # Multiple source locations are not arbitrated by their values.
        if len(rows) != 1 or len(options) != 1:
            audit.update(binding_result="AMBIGUOUS", binding_confidence="AMBIGUOUS_BINDING",
                         blockers=["SOURCE_BINDING_AMBIGUOUS"])
            return audit
        audit.update(options[0], selected_source_scalar=options[0]["raw_scalar"],
                     binding_result="BOUND", binding_confidence="EXACT_STRUCTURAL_BINDING",
                     binding_rule="COMPARISON_HEADER_SOURCE_CELL")
        return audit
    # Narrative/scalar wrappers require their own field evidence to establish scope.
    scalar, operations, blocker = unwrap_surface(field.value)
    if blocker:
        audit.update(operations=operations, blockers=[blocker],
                     binding_result="AMBIGUOUS", binding_confidence="AMBIGUOUS_BINDING")
        return audit
    parsed = parse_p_surface(scalar)
    if not parsed:
        audit["blockers"] = ["P_SURFACE_NOT_SCALAR"]
        return audit
    aliases = arm_alias_index(graph)
    proof = []
    for evidence in graph.evidence:
        if evidence.evidence_id not in field.evidence_ids:
            continue
        # Match the named ordered contrast BEFORE reading its local statistic.
        for segment_index, segment in enumerate(re.split(r"[;\n]", evidence.quote)):
            for name, ids in aliases.items():
                if len(ids) != 1:
                    continue
                for other, other_ids in aliases.items():
                    if len(other_ids) != 1 or ids == other_ids or ids | other_ids != parent_ids:
                        continue
                    pattern = r"(?<!\w)" + re.escape(name) + r"\s+vs\.?\s+" + re.escape(other)
                    pattern += rf"\s*[:,]\s*(p\s*(?:<=|>=|<|>|=|≤|≥)\s*{P_NUMBER})(?![\w.])"
                    for match in re.finditer(pattern, segment, re.I):
                        observed = parse_p_surface(match[1])
                        if observed:
                            proof.append({"evidence_id": evidence.evidence_id, "quote": evidence.quote,
                                          "source_id": evidence.source_id, "raw_scalar": match[1],
                                          "segment_index": segment_index, "span_in_segment": list(match.span()),
                                          "operator": observed["operator"], "numeric_value": observed["numeric_value"]})
    distinct = {(p["operator"], p["numeric_value"]) for p in proof}
    locations = {(p["source_id"], p["quote"], p["segment_index"], tuple(p["span_in_segment"])) for p in proof}
    # Numerical agreement only verifies an already scoped local scalar; it never selects one.
    if len(locations) != 1 or distinct != {(parsed["operator"], parsed["numeric_value"])}:
        audit.update(binding_result="AMBIGUOUS", binding_confidence="AMBIGUOUS_BINDING",
                     blockers=["LOCAL_COMPARISON_EVIDENCE_MISSING_OR_CONFLICTING"])
        return audit
    audit.update(parsed, selected_source_scalar=scalar, operations=operations, source_proof=proof,
                 binding_result="BOUND", binding_confidence="DETERMINISTIC_NORMALIZED_BINDING",
                 binding_rule="EXPLICIT_LOCAL_COMPARISON_SCALAR")
    return audit
