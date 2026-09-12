import copy
import io
import json

import pytest

from article_agent import models


@pytest.fixture(autouse=True)
def isolated_client_config(monkeypatch):
    # Never read local credentials or let a developer's protocol affect tests.
    monkeypatch.setattr(models, "load_env_file", lambda *_: None)
    for key in (
        "ARTICLE_AGENT_API_MODE",
        "ARTICLE_AGENT_API_FALLBACK_URLS",
        "ARTICLE_AGENT_API_BASE_URLS",
        "ARTICLE_AGENT_API_FALLBACK_URL",
        "ARTICLE_AGENT_REASONING_EFFORT",
        "ARTICLE_AGENT_VISION_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(models, "_prefer_curl_transport", lambda: True)


def responses_body(text='{"ok": true}'):
    return {
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            },
        ],
    }


def client(**kwargs):
    return models.OpenAICompatibleClient(
        api_key="test-key", base_url="https://primary.example.com", model="test-model", **kwargs
    )


def test_build_base_url_candidates_normalizes_and_deduplicates() -> None:
    candidates = models._build_base_url_candidates(
        "https://primary.example.com/v1/",
        "https://backup-1.example.com/, https://backup-1.example.com/v1;https://backup-2.example.com",
    )
    assert candidates == [
        "https://primary.example.com/v1",
        "https://backup-1.example.com/v1",
        "https://backup-2.example.com/v1",
    ]


def test_chat_json_fails_over_and_pins_successful_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("ARTICLE_AGENT_HTTP_TRANSPORT", "curl")
    monkeypatch.setenv(
        "ARTICLE_AGENT_API_FALLBACK_URLS",
        "https://backup-1.example.com,https://backup-2.example.com",
    )
    calls: list[str] = []

    def fake_curl(url, payload, api_key, timeout, *, label):
        calls.append(url)
        if "primary.example.com" in url:
            raise RuntimeError("simulated primary outage")
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    monkeypatch.setattr(models, "_curl_json", fake_curl)
    client = models.OpenAICompatibleClient(
        api_key="test-key",
        base_url="https://primary.example.com",
        timeout=1,
    )

    assert client.chat_json([{"role": "user", "content": "ping"}]) == {"ok": True}
    assert calls == [
        "https://primary.example.com/v1/chat/completions",
        "https://backup-1.example.com/v1/chat/completions",
    ]
    assert client.base_url == "https://backup-1.example.com/v1"

    calls.clear()
    assert client.chat_json([{"role": "user", "content": "ping"}]) == {"ok": True}
    assert calls == ["https://backup-1.example.com/v1/chat/completions"]


def test_api_mode_defaults_and_explicit_override(monkeypatch):
    assert client().api_mode == "chat_completions"
    monkeypatch.setenv("ARTICLE_AGENT_API_MODE", "responses")
    assert client().api_mode == "responses"
    assert client(api_mode="chat_completions").api_mode == "chat_completions"
    with pytest.raises(ValueError, match="API_MODE"):
        client(api_mode="unknown")


def test_responses_text_payload_preserves_full_input(monkeypatch):
    captured = []
    monkeypatch.setenv("ARTICLE_AGENT_REASONING_EFFORT", "low")
    monkeypatch.setattr(
        models, "_curl_json",
        lambda url, payload, *a, **kw: captured.append((url, payload)) or responses_body(),
    )
    messages = [
        {"role": "system", "content": "Return JSON, preserve evidence."},
        {"role": "user", "content": "完整表格\n" * 20000},
    ]
    original = copy.deepcopy(messages)
    assert client(api_mode="responses").chat_json(messages, temperature=0.2) == {"ok": True}
    assert messages == original
    assert captured == [("https://primary.example.com/v1/responses", {
        "model": "test-model",
        "input": original,
        "temperature": 0.2,
        "text": {"format": {"type": "json_object"}},
        "reasoning": {"effort": "low"},
        "store": False,
        "truncation": "disabled",
    })]


def test_responses_failover_keeps_protocol_and_pins_endpoint(monkeypatch):
    monkeypatch.setenv("ARTICLE_AGENT_API_FALLBACK_URLS", "https://backup.example.com")
    calls = []

    def fake_curl(url, *args, **kwargs):
        calls.append(url)
        if "primary" in url:
            return responses_body('{"incomplete":')
        return responses_body()

    monkeypatch.setattr(models, "_curl_json", fake_curl)
    c = client(api_mode="responses")
    assert c.chat_json([{"role": "user", "content": "Return JSON"}]) == {"ok": True}
    assert calls == [
        "https://primary.example.com/v1/responses",
        "https://backup.example.com/v1/responses",
    ]
    assert len(c.last_request_errors) == 1
    calls.clear()
    assert c.chat_json([{"role": "user", "content": "Return JSON"}]) == {"ok": True}
    assert calls == ["https://backup.example.com/v1/responses"]


@pytest.mark.parametrize("vision", [False, True])
def test_responses_urllib_request_and_parse(monkeypatch, vision):
    monkeypatch.setattr(models, "_prefer_curl_transport", lambda: False)
    captured = []

    def fake_urlopen(request, **kwargs):
        captured.append(request)
        return io.BytesIO(json.dumps(responses_body()).encode())

    monkeypatch.setattr(models.urllib.request, "urlopen", fake_urlopen)
    c = client(api_mode="responses")
    result = c.chat_vision_json("Return JSON", b"image") if vision else c.chat_json([
        {"role": "user", "content": "Return JSON"}
    ])
    assert result == {"ok": True}
    assert len(captured) == 1
    assert captured[0].full_url == "https://primary.example.com/v1/responses"
    payload = json.loads(captured[0].data)
    assert "input" in payload and "messages" not in payload and "response_format" not in payload


def test_responses_vision_payload(monkeypatch):
    monkeypatch.setenv("ARTICLE_AGENT_VISION_MODEL", "test-vision")
    captured = []
    monkeypatch.setattr(
        models, "_curl_json",
        lambda url, payload, *a, **kw: captured.append((url, payload)) or responses_body(),
    )
    assert client(api_mode="responses").chat_vision_json("Return JSON", b"image") == {"ok": True}
    url, payload = captured[0]
    assert url.endswith("/v1/responses")
    assert payload["model"] == "test-vision"
    assert payload["input"] == [{"role": "user", "content": [
        {"type": "input_text", "text": "Return JSON"},
        {"type": "input_image", "image_url": "data:image/png;base64,aW1hZ2U="},
    ]}]


def test_responses_input_preserves_image_detail():
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "Return JSON"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,eA==", "detail": "high"}},
    ]}]
    original = copy.deepcopy(messages)
    result = models._responses_input(messages)
    assert result[0]["content"][1] == {
        "type": "input_image", "image_url": "data:image/png;base64,eA==", "detail": "high"
    }
    assert messages == original


@pytest.mark.parametrize("message", [
    {"role": "tool", "content": "unknown tool result"},
    {"role": "user", "content": [{"type": "unknown", "text": "do not drop"}]},
    {"role": "user", "content": "Return JSON", "name": "do not drop"},
])
def test_responses_input_rejects_unsupported_content(message):
    with pytest.raises((ValueError, RuntimeError)):
        models._responses_input([message])


def test_responses_reads_text_after_reasoning_and_combines_parts():
    body = responses_body()
    body["output"][1]["content"] = [
        {"type": "output_text", "text": '{"ok":'},
        {"type": "output_text", "text": 'true}'},
    ]
    assert models._responses_content_json(body) == {"ok": True}


@pytest.mark.parametrize("status", [None, "incomplete", "failed", "in_progress", "cancelled"])
def test_responses_rejects_non_completed_even_with_valid_json(status):
    body = responses_body()
    body["status"] = status
    with pytest.raises(RuntimeError):
        models._responses_content_json(body)


@pytest.mark.parametrize("patch", [
    {"incomplete_details": {"reason": "max_output_tokens"}},
    {"error": {"code": "upstream_error", "message": "failed"}},
    {"output": []},
    {"output": [{"type": "message", "role": "assistant", "status": "incomplete", "content": []}]},
    {"output": [{"type": "message", "role": "assistant", "content": [{"type": "refusal", "refusal": "no"}]}]},
])
def test_responses_rejects_error_partial_empty_and_refused(patch):
    body = responses_body()
    body.update(patch)
    with pytest.raises(RuntimeError):
        models._responses_content_json(body)


@pytest.mark.parametrize("text", ["", '{"ok":', "[]", "null", "true", "not JSON"])
def test_responses_rejects_non_json_object(text):
    with pytest.raises(RuntimeError):
        models._responses_content_json(responses_body(text))
