import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    s = (s or "").strip()
    if not s:
        return b""
    pad = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def sign_token(payload: dict[str, Any], *, secret: str, ttl_seconds: int) -> str:
    now = int(time.time())
    body = dict(payload)
    body["iat"] = now
    body["exp"] = now + int(ttl_seconds)
    payload_bytes = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    p = _b64url_encode(payload_bytes)
    sig = _b64url_encode(_hmac_sha256(secret.encode("utf-8"), payload_bytes))
    return f"{p}.{sig}"


def verify_token(token: str, *, secret: str) -> dict[str, Any] | None:
    token = (token or "").strip()
    if not token or "." not in token:
        return None
    p, sig = token.split(".", 1)
    try:
        payload_bytes = _b64url_decode(p)
    except Exception:
        return None
    expect_sig = _b64url_encode(_hmac_sha256(secret.encode("utf-8"), payload_bytes))
    if not hmac.compare_digest(sig, expect_sig):
        return None
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None
    now = int(time.time())
    if int(payload.get("exp") or 0) <= now:
        return None
    return payload


def parse_csv_set(v: str | None) -> set[str]:
    if not v:
        return set()
    return {x.strip().lower() for x in v.split(",") if x.strip()}


def get_request_ip(headers: dict[str, str], fallback: str = "unknown") -> str:
    # Vercel typically sets x-forwarded-for, first is original client.
    xff = (headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if xff:
        return xff
    xrip = (headers.get("x-real-ip") or "").strip()
    if xrip:
        return xrip
    return fallback


def get_device_id(headers: dict[str, str]) -> str | None:
    did = (headers.get("x-calling-device") or "").strip()
    return did or None


@dataclass(frozen=True)
class AuthResult:
    ok: bool
    user_id: str | None = None
    user_login: str | None = None
    method: str | None = None
    detail: str | None = None


def require_secret_present(secret: str | None) -> str:
    if secret and secret.strip():
        return secret.strip()
    # If user didn't set a secret, generate a deterministic-but-local fallback for dev.
    # On Vercel you MUST set CALLING_AUTH_SECRET, otherwise sessions can't be trusted.
    return (os.getenv("CALLING_DEV_FALLBACK_SECRET") or "dev-only-secret-change-me").strip()

