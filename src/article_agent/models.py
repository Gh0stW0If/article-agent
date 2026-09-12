from __future__ import annotations

import base64
import json
import os
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable


def load_env_file(path: Path | None = None) -> None:
    path = path or Path.cwd() / ".env"
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def normalize_base_url(url: str) -> str:
    url = url.rstrip("/")
    return url if url.endswith("/v1") else f"{url}/v1"


def _split_base_url_values(raw: str | None) -> list[str]:
    """Split a comma/semicolon/newline separated base URL setting."""

    if not raw:
        return []
    return [item.strip() for item in raw.replace(";", ",").replace("\n", ",").split(",") if item.strip()]


def _build_base_url_candidates(primary: str, fallback_values: str | None = None) -> list[str]:
    """Return normalized, de-duplicated endpoints in failover order."""

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip()
        if not value:
            return
        normalized = normalize_base_url(value)
        key = normalized.rstrip("/").lower()
        if key not in seen:
            seen.add(key)
            candidates.append(normalized)

    add(primary)
    for value in _split_base_url_values(fallback_values):
        add(value)
    return candidates


def _is_tls_error(error: BaseException) -> bool:
    """Return whether an urllib failure is caused by TLS/SSL negotiation.

    The Windows Anaconda OpenSSL build can reject servers that request TLS
    renegotiation through the local proxy (``record layer failure``), while
    the bundled Windows curl/Schannel client completes the same handshake.
    Walk the exception chain so both ``URLError(SSLError(...))`` and direct
    ``SSLError`` instances are handled without masking ordinary API errors.
    """

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLError):
            return True
        reason = getattr(current, "reason", None)
        if isinstance(reason, BaseException):
            current = reason
            continue
        current = current.__cause__ or current.__context__
    return "SSL" in str(error).upper() or "TLS" in str(error).upper()


def _curl_json(url: str, payload: dict[str, Any], api_key: str, timeout: int, *, label: str = "API") -> dict[str, Any]:
    """POST JSON through Windows curl/Schannel for TLS compatibility.

    This is a transport fallback only.  The payload and response contract are
    identical to the urllib path, and stderr is truncated before being
    surfaced so a proxy cannot flood the extraction log.
    """

    executable = shutil.which("curl.exe") or shutil.which("curl")
    if not executable:
        raise RuntimeError("curl executable is unavailable for TLS fallback")
    # Pass the JSON body through stdin instead of embedding it in the command
    # line. Windows has a relatively small command-line length limit and the
    # table-wise prompts can exceed it (WinError 206), even though curl can
    # send the same request successfully.
    command = [
        executable,
        "--silent",
        "--show-error",
        "--fail-with-body",
        "--location",
        # The Windows Schannel build can negotiate an unstable HTTP/2 path
        # through some local proxies. Keep the transport on HTTP/1.1 for
        # OpenAI-compatible endpoints; the payload and JSON contract are
        # unchanged, while this avoids intermittent SEC_E_* TLS failures.
        "--http1.1",
        "--max-time",
        str(max(1, int(timeout))),
        "-H",
        f"Authorization: Bearer {api_key}",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        "@-",
        url,
    ]
    body_text = json.dumps(payload, ensure_ascii=False)
    try:
        completed = subprocess.run(
            command,
            input=body_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(5, int(timeout) + 5),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{label} curl fallback failed: {exc}") from exc
    if completed.returncode != 0:
        # Preserve the complete transport diagnostic for the retry/SSL report.
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"{label} curl fallback HTTP/transport error: {detail}")
    try:
        body = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} curl fallback returned non-JSON content: {completed.stdout or ''}") from exc
    if not isinstance(body, dict):
        raise RuntimeError(f"{label} curl fallback returned a non-object JSON payload")
    return body


def _content_json(body: dict[str, Any], *, label: str = "API") -> dict[str, Any]:
    try:
        content = body["choices"][0]["message"].get("content") or "{}"
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"{label} response has no choices[0].message.content") from exc
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} returned non-JSON content: {str(content)}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{label} returned a non-object JSON content payload")
    return parsed


def _responses_content_json(body: dict[str, Any], *, label: str = "API") -> dict[str, Any]:
    """Read only complete Responses output; never accept a partial JSON result."""

    if not isinstance(body, dict):
        raise RuntimeError(f"{label} Responses payload is not an object")
    if body.get("error"):
        raise RuntimeError(f"{label} Responses error: {body['error']}")
    if body.get("status") != "completed" or body.get("incomplete_details") is not None:
        raise RuntimeError(
            f"{label} Responses result is not complete: status={body.get('status')}, "
            f"incomplete_details={body.get('incomplete_details')}"
        )
    output = body.get("output")
    if not isinstance(output, list):
        raise RuntimeError(f"{label} Responses payload has no output array")
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            raise RuntimeError(f"{label} Responses output item is not an object")
        if item.get("type") != "message":
            # Reasoning items may precede the assistant message.
            continue
        if item.get("role") != "assistant" or item.get("status") not in {None, "completed"}:
            raise RuntimeError(f"{label} Responses message is not a completed assistant message")
        parts = item.get("content")
        if not isinstance(parts, list):
            raise RuntimeError(f"{label} Responses message has no content array")
        for part in parts:
            if not isinstance(part, dict):
                raise RuntimeError(f"{label} Responses content part is not an object")
            if part.get("type") == "refusal":
                raise RuntimeError(f"{label} Responses refusal: {part.get('refusal', '')}")
            if part.get("type") != "output_text" or not isinstance(part.get("text"), str):
                raise RuntimeError(f"{label} Responses content is not output_text")
            texts.append(part["text"])
    content = "".join(texts)
    if not content.strip():
        raise RuntimeError(f"{label} Responses result contains no output text")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} Responses returned non-JSON content: {content}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{label} Responses returned a non-object JSON content payload")
    return parsed


def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate existing text/image messages without changing their content."""

    inputs: list[dict[str, Any]] = []
    for message in messages:
        if set(message) - {"role", "content"}:
            raise ValueError("Responses input supports only role/content messages")
        role = message.get("role")
        if role not in {"system", "developer", "user", "assistant"}:
            raise ValueError(f"Unsupported Responses input role: {role}")
        content = message.get("content")
        if isinstance(content, str):
            inputs.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            raise ValueError("Responses input content must be text or a content list")
        parts: list[dict[str, Any]] = []
        for part in content:
            if not isinstance(part, dict):
                raise ValueError("Responses input content part must be an object")
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                parts.append({"type": "input_text", "text": part["text"]})
            elif part.get("type") == "image_url":
                image = part.get("image_url")
                if not isinstance(image, dict) or not isinstance(image.get("url"), str):
                    raise ValueError("Responses image input requires an image URL")
                converted = {"type": "input_image", "image_url": image["url"]}
                if "detail" in image:
                    converted["detail"] = image["detail"]
                parts.append(converted)
            else:
                raise ValueError(f"Unsupported Responses input content type: {part.get('type')}")
        inputs.append({"role": role, "content": parts})
    return inputs


def _prefer_curl_transport() -> bool:
    """Use Windows curl/Schannel when available unless explicitly disabled."""

    setting = os.getenv("ARTICLE_AGENT_HTTP_TRANSPORT", "auto").strip().lower()
    if setting in {"urllib", "python"}:
        return False
    if setting in {"curl", "schannel"}:
        return bool(shutil.which("curl.exe") or shutil.which("curl"))
    # Some gateways request TLS renegotiation through a local proxy. Anaconda
    # OpenSSL may time out while Windows Schannel handles the same endpoint.
    # Other platforms retain the original urllib transport by default.
    return os.name == "nt" and bool(shutil.which("curl.exe"))


def _urllib_ssl_context(endpoint: str) -> ssl.SSLContext | None:
    """Return the configured urllib TLS context for a custom API endpoint.

    A custom gateway may be reached through a local HTTP proxy. Some endpoints
    present the proxy's private CA,
    which is not installed in the Anaconda trust store.  An explicit
    ``ARTICLE_AGENT_TLS_VERIFY=0`` opt-in keeps the workaround scoped to the
    user-selected gateway; normal HTTPS requests remain certificate-verified.
    """

    verify = os.getenv("ARTICLE_AGENT_TLS_VERIFY", "1").strip().lower()
    if verify in {"0", "false", "no", "off"}:
        return ssl._create_unverified_context()
    return None


class OpenAICompatibleClient:
    def __init__(
        self, api_key: str | None = None, base_url: str | None = None,
        model: str | None = None, timeout: int = 90, *, api_mode: str | None = None,
    ):
        load_env_file(Path(__file__).resolve().parents[2] / ".env")
        self.api_mode = (
            api_mode if api_mode is not None else os.getenv("ARTICLE_AGENT_API_MODE", "chat_completions")
        ).strip().lower()
        if self.api_mode not in {"chat_completions", "responses"}:
            raise ValueError("ARTICLE_AGENT_API_MODE must be chat_completions or responses")
        self.api_key = api_key or os.getenv("ARTICLE_AGENT_API_KEY") or os.getenv("NEWAPI_API_KEY") or os.getenv("OPENAI_API_KEY")
        configured_base_url = base_url or os.getenv("ARTICLE_AGENT_API_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        fallback_values = (
            os.getenv("ARTICLE_AGENT_API_FALLBACK_URLS")
            or os.getenv("ARTICLE_AGENT_API_BASE_URLS")
            or os.getenv("ARTICLE_AGENT_API_FALLBACK_URL")
        )
        self.base_urls = _build_base_url_candidates(configured_base_url, fallback_values)
        self.base_url = self.base_urls[0]
        self.model = model or os.getenv("ARTICLE_AGENT_MODEL") or "gpt-5.5"
        self.timeout = timeout
        self.last_request_errors: list[str] = []
        if not self.api_key:
            raise RuntimeError("API key not configured. Set ARTICLE_AGENT_API_KEY, NEWAPI_API_KEY, or OPENAI_API_KEY.")

    @property
    def backend_name(self) -> str:
        host = self.base_url.replace("https://", "").replace("http://", "").split("/")[0]
        return f"{host}:{self.model}"

    def _ordered_base_urls(self) -> list[str]:
        """Try the currently healthy endpoint first, then configured fallbacks."""

        return [self.base_url, *[url for url in self.base_urls if url != self.base_url]]

    def _with_failover(self, label: str, request: Callable[[str], dict[str, Any]]) -> dict[str, Any]:
        candidates = self._ordered_base_urls()
        errors: list[str] = []
        for candidate in candidates:
            suffix = "responses" if self.api_mode == "responses" else "chat/completions"
            endpoint = f"{candidate}/{suffix}"
            try:
                result = request(endpoint)
            except Exception as exc:
                errors.append(f"{candidate}: {str(exc)}")
                continue
            # Keep the successful endpoint warm for subsequent shards.  This
            # avoids repeatedly hitting a degraded primary URL in a long run.
            self.base_url = candidate
            self.last_request_errors = errors
            return result
        self.last_request_errors = errors
        detail = " | ".join(errors) or "no endpoints configured"
        raise RuntimeError(f"{label} failed on all base URLs ({len(candidates)}): {detail}")

    def _parse_content(self, body: dict[str, Any], *, label: str) -> dict[str, Any]:
        if self.api_mode == "responses":
            return _responses_content_json(body, label=label)
        return _content_json(body, label=label)

    def _as_responses_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        converted = {
            "model": payload["model"],
            "input": _responses_input(payload["messages"]),
            "temperature": payload["temperature"],
            "text": {"format": {"type": "json_object"}},
            "store": False,
            "truncation": "disabled",
        }
        if "reasoning_effort" in payload:
            converted["reasoning"] = {"effort": payload["reasoning_effort"]}
        return converted

    def _chat_json_once(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if _prefer_curl_transport():
            body = _curl_json(endpoint, payload, self.api_key, self.timeout, label="API")
            return self._parse_content(body, label="API")
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_urllib_ssl_context(endpoint)) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            # When the caller explicitly selected urllib, do not silently
            # switch back to Windows curl/Schannel.  In this environment the
            # Schannel credential provider can fail with
            # ``SEC_E_NO_CREDENTIALS``; surfacing the urllib error lets the
            # normal base-URL failover try the next endpoint instead.
            if not _is_tls_error(exc) or os.getenv("ARTICLE_AGENT_HTTP_TRANSPORT", "auto").strip().lower() in {"urllib", "python"}:
                raise RuntimeError(f"API connection failed: {exc}") from exc
            body = _curl_json(endpoint, payload, self.api_key, self.timeout, label="API")
        return self._parse_content(body, label="API")

    def chat_json(self, messages: list[dict[str, Any]], temperature: float = 0.0) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        # OpenAI-compatible gateways that expose the reasoning control can
        # use it to keep long, row-wise audits responsive.  The setting is
        # opt-in so older gateways simply retain their default behaviour.
        reasoning_effort = os.getenv("ARTICLE_AGENT_REASONING_EFFORT")
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort.strip()
        if self.api_mode == "responses":
            payload = self._as_responses_payload(payload)
        return self._with_failover("API", lambda endpoint: self._chat_json_once(endpoint, payload))

    def _chat_vision_json_once(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        if _prefer_curl_transport():
            body = _curl_json(endpoint, payload, self.api_key, self.timeout, label="Vision API")
            return self._parse_content(body, label="Vision API")
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_urllib_ssl_context(endpoint)) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Vision API HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            if not _is_tls_error(exc) or os.getenv("ARTICLE_AGENT_HTTP_TRANSPORT", "auto").strip().lower() in {"urllib", "python"}:
                raise RuntimeError(f"Vision API connection failed: {exc}") from exc
            body = _curl_json(endpoint, payload, self.api_key, self.timeout, label="Vision API")
        return self._parse_content(body, label="Vision API")

    def chat_vision_json(self, prompt: str, image_bytes: bytes, mime_type: str = "image/png", temperature: float = 0.0) -> dict[str, Any]:
        model = os.getenv("ARTICLE_AGENT_VISION_MODEL") or self.model
        image_data = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                    ],
                }
            ],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        if self.api_mode == "responses":
            payload = self._as_responses_payload(payload)
        return self._with_failover("Vision API", lambda endpoint: self._chat_vision_json_once(endpoint, payload))
