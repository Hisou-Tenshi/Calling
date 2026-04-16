import json
import time
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int | None = None
    reset_in_seconds: int | None = None
    reason: str | None = None


class InMemorySlidingWindow:
    def __init__(self):
        # key -> list[timestamps]
        self._hits: dict[str, list[float]] = {}

    def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        now = time.time()
        cutoff = now - window_seconds
        arr = self._hits.get(key) or []
        # prune
        if arr:
            i = 0
            while i < len(arr) and arr[i] < cutoff:
                i += 1
            if i:
                arr = arr[i:]
        if len(arr) >= limit:
            oldest = arr[0] if arr else now
            reset_in = int(max(0, window_seconds - (now - oldest)))
            self._hits[key] = arr
            return RateLimitDecision(allowed=False, remaining=0, reset_in_seconds=reset_in, reason="rate_limited")
        arr.append(now)
        self._hits[key] = arr
        remaining = max(0, limit - len(arr))
        oldest = arr[0] if arr else now
        reset_in = int(max(0, window_seconds - (now - oldest)))
        return RateLimitDecision(allowed=True, remaining=remaining, reset_in_seconds=reset_in)


class UpstashFixedWindow:
    """
    Uses Upstash Redis REST API to implement a simple fixed-window rate limiter.
    It's not perfect (fixed window != sliding), but good enough for abuse protection.
    """

    def __init__(self, *, rest_url: str, rest_token: str):
        self.rest_url = rest_url.rstrip("/")
        self.rest_token = rest_token

    def _call(self, command: list[str]):
        url = f"{self.rest_url}/pipeline"
        headers = {"Authorization": f"Bearer {self.rest_token}", "Content-Type": "application/json"}
        payload = [{"command": command}]
        r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        r.raise_for_status()
        return r.json()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        # key should include the window bucket.
        now = int(time.time())
        bucket = now // window_seconds
        rk = f"{key}:{bucket}"
        try:
            # INCR + EXPIRE (best-effort). Use pipeline to reduce RTT.
            url = f"{self.rest_url}/pipeline"
            headers = {"Authorization": f"Bearer {self.rest_token}", "Content-Type": "application/json"}
            payload = [
                {"command": ["INCR", rk]},
                {"command": ["EXPIRE", rk, str(window_seconds)]},
                {"command": ["TTL", rk]},
            ]
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
            r.raise_for_status()
            data = r.json() or []

            incr_val = int((data[0] or {}).get("result") or 0)
            ttl = int((data[2] or {}).get("result") or window_seconds)
            if incr_val > limit:
                return RateLimitDecision(allowed=False, remaining=0, reset_in_seconds=max(0, ttl), reason="rate_limited")
            return RateLimitDecision(
                allowed=True,
                remaining=max(0, limit - incr_val),
                reset_in_seconds=max(0, ttl),
            )
        except Exception:
            # Fail open for rate limiter errors to avoid breaking the app.
            return RateLimitDecision(allowed=True, reason="rate_limiter_error_fail_open")

