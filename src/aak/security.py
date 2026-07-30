"""Deny-by-default security boundary for the read-only architecture MCP."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
CORRELATION_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|cookie)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"(?i)(postgres(?:ql)?://)[^\s]+"),
    re.compile(r"(?i)([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|KEY))=([^\s]+)"),
]


@dataclass(frozen=True)
class Claims:
    subject: str
    project: str
    tenant: str
    role: str
    tools: frozenset[str]
    expires_at: int
    jti: str
    key_id: str


class SecurityError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable

    def response(self, correlation_id: str) -> dict:
        return {"error": {"code": self.code, "message": self.message,
                          "retryable": self.retryable, "correlationId": correlation_id}}


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(key_id: str, key: bytes, claims: dict) -> str:
    """Test/local issuer. Production identity integration is intentionally external."""
    payload = _b64(json.dumps(claims, sort_keys=True, separators=(",", ":")).encode())
    signature = _b64(hmac.new(key, f"{key_id}.{payload}".encode(), hashlib.sha256).digest())
    return f"{key_id}.{payload}.{signature}"


def redact(value):
    if isinstance(value, dict):
        return {str(k): redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if not isinstance(value, str):
        return value
    result = value
    for pattern in SECRET_PATTERNS:
        result = pattern.sub(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", result)
    result = re.sub(r"/(?:home|Users)/[^/\s]+", "/[USER]", result)
    return result


class SecurityBoundary:
    ROLES = {"reader", "auditor", "admin"}

    def __init__(
        self, keys: dict[str, bytes], *, revoked: set[str] | None = None,
        audit_path: Path | None = None, clock: Callable[[], float] = time.time,
        rate_limit: int = 120, response_limit: int = 1_000_000,
    ):
        self._keys = dict(keys)
        self._revoked = set(revoked or set())
        self._audit_path = audit_path
        self._clock = clock
        self._rate_limit = rate_limit
        self._response_limit = response_limit
        self._rates: dict[tuple[str, int], int] = {}
        self.events: list[dict] = []

    @classmethod
    def from_environment(cls, repo_root: Path) -> "SecurityBoundary":
        raw = os.environ.get("AAK_MCP_AUTH_KEYS", "")
        keys: dict[str, bytes] = {}
        if raw:
            try:
                parsed = json.loads(raw)
                keys = {str(k): str(v).encode() for k, v in parsed.items() if v}
            except (json.JSONDecodeError, AttributeError):
                keys = {}
        revoked = {jti for jti in os.environ.get("AAK_MCP_REVOKED_JTIS", "").split(",") if jti}
        audit = os.environ.get("AAK_MCP_AUDIT_PATH")
        audit_path = Path(audit).resolve() if audit else None
        return cls(keys, revoked=revoked, audit_path=audit_path)

    def _correlation(self, supplied: str | None) -> str:
        return supplied if isinstance(supplied, str) and CORRELATION_RE.fullmatch(supplied) else uuid.uuid4().hex

    def _audit(self, event: dict) -> None:
        safe = redact({**event, "at": int(self._clock())})
        self.events.append(safe)
        if self._audit_path is None:
            return
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(self._audit_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, line.encode())
        finally:
            os.close(fd)

    def _decode(self, token: str | None) -> Claims:
        if token is None or token == "":
            raise SecurityError("AUTHENTICATION_REQUIRED", "valid authentication is required")
        if not isinstance(token, str) or not TOKEN_RE.fullmatch(token):
            raise SecurityError("AUTHENTICATION_INVALID", "authentication is invalid")
        kid, encoded, signature = token.split(".")
        key = self._keys.get(kid)
        if key is None:
            raise SecurityError("AUTHENTICATION_INVALID", "authentication is invalid")
        expected = _b64(hmac.new(key, f"{kid}.{encoded}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, signature):
            raise SecurityError("AUTHENTICATION_INVALID", "authentication is invalid")
        try:
            raw = json.loads(_unb64(encoded))
            claims = Claims(
                subject=str(raw["sub"]), project=str(raw["project"]), tenant=str(raw["tenant"]),
                role=str(raw["role"]), tools=frozenset(str(v) for v in raw["tools"]),
                expires_at=int(raw["exp"]), jti=str(raw["jti"]), key_id=kid,
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            raise SecurityError("AUTHENTICATION_INVALID", "authentication is invalid")
        if claims.expires_at <= int(self._clock()):
            raise SecurityError("AUTHENTICATION_EXPIRED", "authentication has expired")
        if claims.jti in self._revoked:
            raise SecurityError("AUTHENTICATION_REVOKED", "authentication has been revoked")
        if claims.role not in self.ROLES or not TENANT_RE.fullmatch(claims.tenant):
            raise SecurityError("AUTHENTICATION_INVALID", "authentication is invalid")
        return claims

    def authorize(
        self, *, token: str | None, tool: str, project: str, tenant: str | None,
        correlation_id: str | None,
    ) -> tuple[Claims | None, str, dict | None]:
        correlation = self._correlation(correlation_id)
        try:
            claims = self._decode(token)
            if not isinstance(tenant, str) or not TENANT_RE.fullmatch(tenant):
                raise SecurityError("AUTHORIZATION_DENIED", "access is denied")
            if claims.project != project or claims.tenant != tenant or tool not in claims.tools:
                raise SecurityError("AUTHORIZATION_DENIED", "access is denied")
            window = int(self._clock()) // 60
            key = (claims.jti, window)
            self._rates[key] = self._rates.get(key, 0) + 1
            if self._rates[key] > self._rate_limit:
                raise SecurityError("RATE_LIMITED", "request rate exceeded", retryable=True)
            self._audit({"correlationId": correlation, "subject": claims.subject,
                         "project": project, "tenant": tenant, "tool": tool, "decision": "allow"})
            return claims, correlation, None
        except SecurityError as exc:
            self._audit({"correlationId": correlation, "tool": tool, "decision": "deny", "code": exc.code})
            return None, correlation, exc.response(correlation)

    def protect_response(self, value, correlation_id: str):
        safe = redact(value)
        encoded = json.dumps(safe, separators=(",", ":"), default=str).encode()
        if len(encoded) > self._response_limit:
            return SecurityError("RESPONSE_TOO_LARGE", "response exceeds the configured limit").response(correlation_id)
        return safe


def safe_child(root: Path, relative: str, *, suffix: str = "") -> Path:
    """Resolve a user-derived child without traversal, absolute paths, NUL or symlink escape."""
    if not isinstance(relative, str) or not relative or "\x00" in relative:
        raise SecurityError("INPUT_INVALID", "path input is invalid")
    if os.path.isabs(relative) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", relative):
        raise SecurityError("INPUT_INVALID", "path input is invalid")
    canonical_root = root.resolve()
    candidate = (canonical_root / f"{relative}{suffix}").resolve()
    if candidate.parent != canonical_root:
        raise SecurityError("INPUT_INVALID", "path input is invalid")
    return candidate
