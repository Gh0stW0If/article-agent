from article_agent import models


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
