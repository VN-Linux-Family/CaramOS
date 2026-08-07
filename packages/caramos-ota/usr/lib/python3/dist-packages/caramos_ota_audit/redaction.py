"""Redact secrets and identifying data from audit evidence."""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Mapping, Sequence
from typing import Any

_PLACEHOLDER = "[REDACTED]"
_EMAIL_PLACEHOLDER = "[REDACTED_EMAIL]"
_KEY_PLACEHOLDER = "[REDACTED_PRIVATE_KEY]"
_TOKEN_PLACEHOLDER = "[REDACTED_TOKEN]"

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN(?: [A-Z0-9 ]+)? PRIVATE KEY-----.*?-----END(?: [A-Z0-9 ]+)? PRIVATE KEY-----",
    re.IGNORECASE | re.DOTALL,
)
_URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)([^\s/@:]+)(?::[^\s/@]*)?@")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")
_JWT_RE = re.compile(r"\beyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
_MAC_RE = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![0-9a-f])")
_SENSITIVE_LINE_RE = re.compile(
    r"(?i)\b(?P<key>password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|authorization|cookie|session|client[_-]?secret|private[_-]?key|psk)\b"
    r"(?P<sep>\s*[:=]\s*)(?P<value>[^\s,;]+)"
)
_LONG_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z0-9+/=_-]{32,})(?![A-Za-z0-9])")

_SENSITIVE_KEYS = {
    "authorization", "auth", "cookie", "password", "passwd", "pwd", "secret", "token",
    "access_token", "refresh_token", "api_key", "apikey", "access_key", "client_secret",
    "private_key", "session", "sessionid", "psk", "ssid",
}


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or any(
        marker in normalized for marker in ("password", "secret", "token", "cookie", "session", "private_key", "api_key")
    )


def redact_text(text: str) -> str:
    """Redact obvious secrets, PII, network identifiers, and local paths."""

    if not text:
        return text
    redacted = _PRIVATE_KEY_RE.sub(_KEY_PLACEHOLDER, text)
    redacted = _URL_CREDENTIAL_RE.sub(r"\1[REDACTED_URL]@", redacted)
    redacted = _BEARER_RE.sub(_TOKEN_PLACEHOLDER, redacted)
    redacted = _JWT_RE.sub(_TOKEN_PLACEHOLDER, redacted)
    redacted = _SENSITIVE_LINE_RE.sub(lambda match: f"{match.group('key')}{match.group('sep')}{_PLACEHOLDER}", redacted)
    redacted = _EMAIL_RE.sub(_EMAIL_PLACEHOLDER, redacted)
    redacted = _MAC_RE.sub("[REDACTED_MAC]", redacted)
    redacted = _IPV4_RE.sub("[REDACTED_IP]", redacted)
    home = os.path.realpath(os.path.expanduser("~"))
    if home and home != "/":
        redacted = redacted.replace(home, "[REDACTED_HOME]")
    hostname = socket.gethostname()
    if hostname:
        redacted = re.sub(re.escape(hostname), "[REDACTED_HOST]", redacted, flags=re.IGNORECASE)
    return _LONG_TOKEN_RE.sub(_TOKEN_PLACEHOLDER, redacted)


def redact_value(value: Any) -> Any:
    """Recursively redact secret-bearing values."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", errors="replace"))
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            redacted[key] = _PLACEHOLDER if _is_sensitive_key(key) else redact_value(item)
        return redacted
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, set):
        return {redact_value(item) for item in value}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return type(value)(redact_value(item) for item in value)
    return value
