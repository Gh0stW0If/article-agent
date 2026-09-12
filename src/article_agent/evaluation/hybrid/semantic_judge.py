"""Pair-only judging, immutable hash cache, and API-free frozen replay."""
import hashlib
import json
from pathlib import Path
import time
from typing import Callable, Protocol

from .models import JudgmentArtifact, SemanticEntityJudgment, SemanticJudgment
from .prompts import SEMANTIC_PROMPT_SHA256, SEMANTIC_PROMPT_VERSION, SYSTEM_PROMPT


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def field_representation(graph, field, *, identity_only=False):
    """No source replacement; result-identity requests never expose numerical rows."""
    evidence = []
    if not identity_only:
        by_id = {e.evidence_id: e for e in graph.evidence}
        for eid in sorted(set(field.evidence_ids)):
            e = by_id[eid]
            evidence.append({k: getattr(e, k) for k in (
                "evidence_id", "quote", "source_type", "source_id", "page",
                "section", "table_id", "row_id", "support_type", "derivation")})
    return {"value": field.value,
            "raw_value": None if identity_only else field.raw_value, "evidence": evidence}


def field_request(spec, gold, prediction, *, identity=False):
    return {
        "judge_type": "RESULT_IDENTITY_FIELD" if identity else "FIELD",
        "field_id": spec.field_id, "entity_type": None,
        "field_definition": spec.definition, "judge_focus": spec.judge_focus,
        "gold": gold, "prediction": prediction,
    }


def entity_request(kind, gold, prediction):
    return json.loads(canonical_json({
        "judge_type": "ENTITY", "field_id": None, "entity_type": kind,
        "field_definition": "Entity identity within the supplied, prevalidated structural context.",
        "gold": gold, "prediction": prediction}))


def parse_result(request, raw, *, stored=False):
    payload = dict(raw)
    if request["judge_type"] == "ENTITY":
        return SemanticEntityJudgment.model_validate(payload).model_dump(mode="json")
    score = payload.pop("score", None) if stored else None
    parsed = SemanticJudgment.model_validate(payload)
    if stored and score != parsed.score:
        raise ValueError("Cached grade/score mismatch")
    return parsed.model_dump(mode="json")


class SemanticJudge(Protocol):
    model: str

    def judge(self, request: dict) -> JudgmentArtifact: ...


class CacheMissError(RuntimeError):
    pass


class CachedSemanticJudge:
    """Offline only: never constructs a client and never falls through to the network."""
    def __init__(self, cache_dir=None, *, artifacts=None, model="gpt-5.6-sol"):
        self.model = model
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.frozen = {}
        for value in artifacts or []:
            item = JudgmentArtifact.model_validate(value)
            if item.input_sha256 in self.frozen:
                raise ValueError("Duplicate frozen judgment hash")
            self.frozen[item.input_sha256] = item
        self.used = {}

    def canonical_input(self, request):
        return {**request, "prompt_version": SEMANTIC_PROMPT_VERSION,
                "prompt_sha256": SEMANTIC_PROMPT_SHA256, "model": self.model, "temperature": 0}

    def _validate(self, item, canonical):
        expected = digest(canonical)
        if (item.canonical_input != canonical or item.input_sha256 != expected
                or item.judgment_id != "J-" + expected or item.model != self.model
                or item.prompt_sha256 != SEMANTIC_PROMPT_SHA256
                or item.prompt_version != SEMANTIC_PROMPT_VERSION
                or item.gold_representation != canonical["gold"]
                or item.prediction_representation != canonical["prediction"]
                or item.judge_type != canonical["judge_type"]
                or item.field_id != canonical["field_id"]
                or item.entity_type != canonical["entity_type"]):
            raise ValueError("Frozen judgment input/provenance mismatch")
        if item.status == "SUCCESS":
            if item.error_code or item.result is None:
                raise ValueError("Invalid successful judgment")
            parse_result(canonical, item.result, stored=True)
        elif item.result is not None or item.error_code != "SEMANTIC_JUDGE_ERROR":
            raise ValueError("Invalid failure artifact")
        return item

    def _lookup(self, canonical):
        key = digest(canonical)
        item = self.used.get(key) or self.frozen.get(key)
        path = self.cache_dir / (key + ".json") if self.cache_dir else None
        if item is None and path and path.exists():
            item = JudgmentArtifact.model_validate_json(path.read_text(encoding="utf-8"))
        if item is None:
            raise CacheMissError(f"No frozen semantic judgment for {key}; API disabled")
        return self._validate(item, canonical)

    def judge(self, request):
        canonical = self.canonical_input(request)
        item = self._lookup(canonical)
        self.used[item.input_sha256] = item
        return item.model_copy(deep=True)


class LiveSemanticJudge(CachedSemanticJudge):
    """Serial, temperature zero; only technical failures receive bounded retries."""
    def __init__(self, client, cache_dir, *, retries=2, progress: Callable | None = None):
        super().__init__(cache_dir, model=client.model)
        if client.api_mode != "responses":
            raise ValueError("Hybrid V1 live judge requires the existing Responses adapter")
        if retries < 0:
            raise ValueError("retries must be nonnegative")
        self.client, self.retries, self.progress = client, retries, progress

    def judge(self, request):
        canonical = self.canonical_input(request)
        try:
            return super().judge(request)
        except CacheMissError:
            pass
        key = digest(canonical)
        errors, result = [], None
        for attempt in range(1, self.retries + 2):
            if self.progress:
                self.progress({"input_sha256": key, "judge_type": request["judge_type"],
                               "field_id": request["field_id"], "entity_type": request["entity_type"],
                               "attempt": attempt})
            time.sleep(0.01)
            try:
                raw = self.client.chat_json([
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": canonical_json(request)},
                ], temperature=0)
                result = parse_result(request, raw)
                break
            except Exception as exc:
                # Never persist raw HTTP bodies, headers, credentials or exception messages.
                errors.append(type(exc).__name__)
        item = JudgmentArtifact(
            judgment_id="J-" + key, input_sha256=key,
            prompt_version=SEMANTIC_PROMPT_VERSION, prompt_sha256=SEMANTIC_PROMPT_SHA256,
            model=self.model, judge_type=request["judge_type"],
            field_id=request["field_id"], entity_type=request["entity_type"],
            canonical_input=canonical, gold_representation=request["gold"],
            prediction_representation=request["prediction"], result=result,
            status="SUCCESS" if result is not None else "JUDGE_UNAVAILABLE",
            error_code=None if result is not None else "SEMANTIC_JUDGE_ERROR",
            attempts=attempt, technical_errors=errors,
        )
        path = self.cache_dir / (key + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Fail instead of overwriting a previously frozen observation.
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n")
        self.used[key] = item
        return item.model_copy(deep=True)


class FakeSemanticJudge(CachedSemanticJudge):
    """Injected deterministic test decisions; contains no client/network implementation."""
    def __init__(self, responder):
        super().__init__(model="fake-semantic-judge")
        self.responder, self.calls = responder, []

    def judge(self, request):
        canonical = self.canonical_input(request)
        key = digest(canonical)
        if key in self.used:
            return self.used[key].model_copy(deep=True)
        self.calls.append(request)
        raw = self.responder(request)
        result = parse_result(request, raw) if raw is not None else None
        item = JudgmentArtifact(
            judgment_id="J-" + key, input_sha256=key, model=self.model,
            prompt_version=SEMANTIC_PROMPT_VERSION, prompt_sha256=SEMANTIC_PROMPT_SHA256,
            judge_type=request["judge_type"], field_id=request["field_id"], entity_type=request["entity_type"],
            canonical_input=canonical, gold_representation=request["gold"],
            prediction_representation=request["prediction"], result=result,
            status="SUCCESS" if result is not None else "JUDGE_UNAVAILABLE",
            error_code=None if result is not None else "SEMANTIC_JUDGE_ERROR",
        )
        self.used[key] = item
        return item.model_copy(deep=True)


class JudgeSession:
    """Collect only this evaluation's judgments, even when a judge is reused."""
    def __init__(self, judge):
        self.judge_impl, self.model, self.used = judge, judge.model, {}

    def judge(self, request):
        item = self.judge_impl.judge(request)
        self.used[item.input_sha256] = item
        return item

    def artifacts(self):
        return [self.used[key] for key in sorted(self.used)]
