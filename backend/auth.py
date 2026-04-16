import os
import secrets
import urllib.parse
from typing import Any

import requests
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse

from backend.config import Settings
from backend.security import (
    AuthResult,
    get_device_id,
    parse_csv_set,
    require_secret_present,
    sign_token,
    verify_token,
)


SESSION_COOKIE_NAME = "calling_session"


def _cookie_params(*, request: Request) -> dict[str, Any]:
    # Vercel uses HTTPS; for local dev it's HTTP.
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").lower()
    is_https = forwarded_proto == "https" or request.url.scheme == "https"
    return {
        "httponly": True,
        "secure": bool(is_https),
        "samesite": "lax",
        "path": "/",
    }


def get_session_payload(request: Request, *, settings: Settings) -> dict[str, Any] | None:
    secret = require_secret_present(settings.auth_secret)
    token = request.cookies.get(SESSION_COOKIE_NAME) or ""
    if not token:
        authz = (request.headers.get("authorization") or "").strip()
        if authz.lower().startswith("bearer "):
            token = authz.split(" ", 1)[1].strip()
    if not token:
        return None
    return verify_token(token, secret=secret)


def authenticate_request(request: Request, *, settings: Settings) -> AuthResult:
    mode = (settings.auth_mode or "none").strip().lower()
    if mode == "none":
        return AuthResult(ok=True, user_id="anon", method="none")

    # API key mode (header)
    if mode == "apikey":
        want = (settings.api_key or "").strip()
        if not want:
            return AuthResult(ok=False, detail="CALLING_API_KEY is not set")
        got = (request.headers.get("x-api-key") or "").strip()
        if got and secrets.compare_digest(got, want):
            return AuthResult(ok=True, user_id="apikey", method="apikey")
        return AuthResult(ok=False, detail="missing or invalid x-api-key")

    # password / github modes rely on session cookie (plus optional apikey header as bypass)
    if settings.api_key:
        got = (request.headers.get("x-api-key") or "").strip()
        if got and secrets.compare_digest(got, (settings.api_key or "").strip()):
            return AuthResult(ok=True, user_id="apikey", method="apikey")

    payload = get_session_payload(request, settings=settings)
    if not payload:
        return AuthResult(ok=False, detail="not authenticated")

    device = get_device_id(dict(request.headers))
    bound = (payload.get("device") or "").strip()
    if bound and device and bound != device:
        return AuthResult(ok=False, detail="device mismatch")

    uid = (payload.get("uid") or "").strip() or None
    login = (payload.get("login") or "").strip() or None
    method = (payload.get("m") or "").strip() or "session"
    return AuthResult(ok=True, user_id=uid or login or "user", user_login=login, method=method)


def require_auth(request: Request, *, settings: Settings) -> AuthResult:
    r = authenticate_request(request, settings=settings)
    if not r.ok:
        raise HTTPException(status_code=401, detail=r.detail or "unauthorized")
    return r


def issue_session_response(
    request: Request,
    *,
    settings: Settings,
    user_id: str,
    login: str | None,
    method: str,
    device: str | None,
    redirect_to: str = "/",
) -> RedirectResponse:
    secret = require_secret_present(settings.auth_secret)
    token = sign_token(
        {"uid": user_id, "login": login, "m": method, "device": device or ""},
        secret=secret,
        ttl_seconds=int(os.getenv("CALLING_SESSION_TTL_SECONDS") or 60 * 60 * 24 * 14),
    )
    resp = RedirectResponse(url=redirect_to, status_code=302)
    resp.set_cookie(SESSION_COOKIE_NAME, token, **_cookie_params(request=request))
    return resp


def logout_response(request: Request) -> RedirectResponse:
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return resp


def password_login(request: Request, *, settings: Settings, password: str, device: str | None) -> RedirectResponse:
    want = (settings.auth_password or "").strip()
    if not want:
        raise HTTPException(status_code=500, detail="CALLING_PASSWORD is not set")
    if not password or not secrets.compare_digest(password, want):
        raise HTTPException(status_code=401, detail="invalid password")
    return issue_session_response(
        request,
        settings=settings,
        user_id="pw",
        login=None,
        method="password",
        device=device,
        redirect_to="/",
    )


def github_oauth_start(request: Request, *, settings: Settings) -> RedirectResponse:
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(status_code=500, detail="GITHUB_CLIENT_ID/SECRET not set")
    secret = require_secret_present(settings.auth_secret)
    # State carries csrf + optional device binding
    device = get_device_id(dict(request.headers)) or ""
    state = sign_token({"csrf": secrets.token_urlsafe(16), "device": device}, secret=secret, ttl_seconds=600)

    origin = str(request.base_url).rstrip("/")
    redirect_uri = f"{origin}/api/auth/github/callback"
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": redirect_uri,
        "scope": "read:user read:org",
        "state": state,
    }
    url = "https://github.com/login/oauth/authorize?" + urllib.parse.urlencode(params)
    return RedirectResponse(url=url, status_code=302)


def _github_exchange_code(*, code: str, settings: Settings, redirect_uri: str) -> str:
    r = requests.post(
        "https://github.com/login/oauth/access_token",
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    r.raise_for_status()
    data = r.json() or {}
    token = (data.get("access_token") or "").strip()
    if not token:
        raise HTTPException(status_code=401, detail="GitHub token exchange failed")
    return token


def _github_get_user(*, access_token: str) -> dict[str, Any]:
    r = requests.get(
        "https://api.github.com/user",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json() or {}


def _github_user_orgs(*, access_token: str) -> set[str]:
    r = requests.get(
        "https://api.github.com/user/orgs",
        headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if r.status_code != 200:
        return set()
    orgs = r.json() or []
    out: set[str] = set()
    for o in orgs:
        login = (o.get("login") or "").strip().lower()
        if login:
            out.add(login)
    return out


def _github_allowed(*, settings: Settings, user_login: str, access_token: str) -> bool:
    allow_users = parse_csv_set(settings.github_allowed_users)
    allow_orgs = parse_csv_set(settings.github_allowed_orgs)
    if not allow_users and not allow_orgs:
        # Default secure behavior: require explicit allow-list.
        return False
    if user_login.lower() in allow_users:
        return True
    if allow_orgs:
        orgs = _github_user_orgs(access_token=access_token)
        if orgs.intersection(allow_orgs):
            return True
    return False


def github_oauth_callback(request: Request, *, settings: Settings) -> RedirectResponse:
    code = (request.query_params.get("code") or "").strip()
    state = (request.query_params.get("state") or "").strip()
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code/state")

    secret = require_secret_present(settings.auth_secret)
    st = verify_token(state, secret=secret)
    if not st:
        raise HTTPException(status_code=400, detail="invalid state")

    origin = str(request.base_url).rstrip("/")
    redirect_uri = f"{origin}/api/auth/github/callback"
    access_token = _github_exchange_code(code=code, settings=settings, redirect_uri=redirect_uri)
    user = _github_get_user(access_token=access_token)
    login = (user.get("login") or "").strip()
    uid = str(user.get("id") or "").strip() or login
    if not login:
        raise HTTPException(status_code=401, detail="GitHub login missing")

    if not _github_allowed(settings=settings, user_login=login, access_token=access_token):
        raise HTTPException(status_code=403, detail="GitHub user not allowed (set allow-list env vars)")

    device = (st.get("device") or "").strip() or None
    return issue_session_response(
        request,
        settings=settings,
        user_id=uid,
        login=login,
        method="github",
        device=device,
        redirect_to="/",
    )

