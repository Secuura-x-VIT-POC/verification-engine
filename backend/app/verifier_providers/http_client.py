from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request


class SafeHttpClientError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class HttpJsonResponse:
    payload: dict[str, Any]
    http_status: int | None
    retry_count: int


class SafeHttpJsonClient:
    def __init__(
        self,
        *,
        request_size_limit_bytes: int,
        response_size_limit_bytes: int,
    ):
        self.request_size_limit_bytes = request_size_limit_bytes
        self.response_size_limit_bytes = response_size_limit_bytes

    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        timeout_ms: int,
        retry_budget: int,
        domain_allowlist: tuple[str, ...],
    ) -> HttpJsonResponse:
        self._validate_url(url, domain_allowlist)
        body = json.dumps(payload).encode("utf-8")
        if len(body) > self.request_size_limit_bytes:
            raise SafeHttpClientError("request_too_large", "Outbound provider request exceeded the configured size limit.")

        attempts = max(int(retry_budget), 0) + 1
        last_error: SafeHttpClientError | None = None
        for attempt in range(attempts):
            try:
                req = request.Request(
                    url=url,
                    data=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        **(headers or {}),
                    },
                    method="POST",
                )
                with request.urlopen(req, timeout=max(timeout_ms / 1000, 0.001)) as response:
                    status = getattr(response, "status", None)
                    raw_body = response.read(self.response_size_limit_bytes + 1)
                    if len(raw_body) > self.response_size_limit_bytes:
                        raise SafeHttpClientError(
                            "response_too_large",
                            "Provider response exceeded the configured size limit.",
                            http_status=status,
                        )
                    return HttpJsonResponse(
                        payload=_parse_json(raw_body),
                        http_status=status,
                        retry_count=attempt,
                    )
            except error.HTTPError as exc:
                raw_body = exc.read(self.response_size_limit_bytes + 1)
                if len(raw_body) > self.response_size_limit_bytes:
                    raise SafeHttpClientError(
                        "response_too_large",
                        "Provider response exceeded the configured size limit.",
                        http_status=exc.code,
                    ) from exc
                message = _safe_error_message(_parse_json(raw_body), fallback=str(exc))
                last_error = SafeHttpClientError("http_error", message, http_status=exc.code)
                if exc.code < 500 or attempt == attempts - 1:
                    raise last_error from exc
            except error.URLError as exc:
                code = "timeout" if isinstance(exc.reason, socket.timeout) else "network_error"
                last_error = SafeHttpClientError(code, str(exc.reason or exc))
                if attempt == attempts - 1:
                    raise last_error from exc
            except socket.timeout as exc:
                last_error = SafeHttpClientError("timeout", str(exc))
                if attempt == attempts - 1:
                    raise last_error from exc

        if last_error is not None:
            raise last_error
        raise SafeHttpClientError("unknown_error", "Provider request failed before a response was produced.")

    def _validate_url(self, url: str, domain_allowlist: tuple[str, ...]) -> None:
        parsed = parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise SafeHttpClientError("blocked_domain", "Only HTTP and HTTPS provider URLs are allowed.")
        host = (parsed.hostname or "").lower()
        if not host:
            raise SafeHttpClientError("blocked_domain", "Provider URL is missing a hostname.")
        normalized_allowlist = tuple(item.lower() for item in domain_allowlist if item)
        if normalized_allowlist and host not in normalized_allowlist:
            raise SafeHttpClientError("blocked_domain", f"Provider host '{host}' is not allowlisted.")


def _parse_json(raw_body: bytes) -> dict[str, Any]:
    if not raw_body:
        return {}
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise SafeHttpClientError("invalid_json", "Provider returned a non-JSON response.") from exc
    if isinstance(payload, dict):
        return payload
    return {"data": payload}


def _safe_error_message(payload: dict[str, Any], *, fallback: str) -> str:
    for key in ("error", "message", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:240]
    return fallback[:240]
