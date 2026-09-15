#!/usr/bin/env python3
"""Claude 代理可达性检测（Calling 仓库专用，与 Tenshi 完全隔离）。

## 为什么单独一个脚本

Tenshi / Elaina 的回复链在 GitHub Actions 里跑，Claude 走的是「代理1 三档 key
（Base/Prime/Max）→ 代理2 → 官方」这条路（因为 Calling 代跑 Tenshi 的工作流，
两边环境变量名完全一致，本脚本直接读同一套 CLAUDE_* / CLAUDE_PROXY_*）。
代理是否可用，取决于两件**在本地机器上看不到**的事：GitHub 托管 runner 的出网
路径能不能连上代理，以及代理端的 key 还有没有额度。线上表现却只是「Claude 一路
降级」，很难判断到底是网络、证书、鉴权还是配额。

本脚本只用**标准库**（不装依赖、不 import Tenshi 任何代码）对每一档做分层探测：

    1) DNS    —— 域名能不能解析、解析到哪些 IP
    2) TCP    —— 端口能不能建连（区分 timeout / refused / unreachable）
    3) TLS    —— 握手版本、加密套件、证书主体/签发者/到期剩余天数
                 （区分「握手就断了」与「只是证书不受信」）
    4) HTTP   —— GET /v1/models 与 POST /v1/messages（max_tokens=1）的真实状态码、
                 延迟分布、错误体；区分「连得上但 key 被拒」「被 WAF 拦」
                 「模型不存在」「限流/欠费」「上游 5xx」
    5) 出口    —— 记录 runner 的公网出口 IP（要求代理方加白名单时用的就是它）

产出：`latest.md`（人读报告）、`latest.json`（机读原始数据）、`latest.log`（完整日志）、
`history.jsonl`（每次一行摘要，便于看趋势）。所有 key 只以掩码形式出现，日志落盘前
统一做一次原文擦除。

用法：
    python3 scripts/claude_proxy_reachability.py [--models claude-opus-4-6,...]
        [--attempts 3] [--timeout 20] [--no-messages] [--fail-on-unreachable]

退出码：0 = 检测完成且已配置的通路全部可用（或没有任何通路被配置）；
        1 = 存在不可用通路，且传了 --fail-on-unreachable；
        2 = 一个通路都没配置（secrets 缺失），无法检测。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import socket
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODELS = "claude-opus-4-6,claude-sonnet-4-6,claude-3-5-sonnet-20241022"
USER_AGENT = "Calling-claude-proxy-reachability/1.0 (+github.com/Hisou-Tenshi/Calling)"
OFFICIAL_BASE_URL = "https://api.anthropic.com"
BODY_EXCERPT_LIMIT = 600
HISTORY_LIMIT = 500

# 通路定义：(标签, base_url 环境变量(空=用官方), 取 key 的环境变量序列(先命中先用), 说明)
PROXY_SPECS: list[tuple[str, str, tuple[str, ...], str]] = [
    ("Proxy1/Base", "CLAUDE_PROXY_BASE_URL", ("CLAUDE_PROXY_KEY_BASE", "CLAUDE_PROXY_KEY"), "代理1 base 档"),
    ("Proxy1/Prime", "CLAUDE_PROXY_BASE_URL", ("CLAUDE_PROXY_KEY_PRIME",), "代理1 prime 档"),
    ("Proxy1/Max", "CLAUDE_PROXY_BASE_URL", ("CLAUDE_PROXY_KEY_MAX",), "代理1 max 档"),
    ("Proxy2", "CLAUDE_PROXY_BASE_URL_2", ("CLAUDE_PROXY_KEY_2",), "代理2（独立域名）"),
    ("Official", "", ("CLAUDE_API_KEY",), "Anthropic 官方（对照组）"),
]

_LOG_LINES: list[str] = []
_SECRETS: list[str] = []


# ============================================================
# 基础工具
# ============================================================


def log(message: str = "") -> None:
    """打印到 stdout（Actions 日志）并累计进 latest.log。"""
    text = redact(message)
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        # Windows 本地控制台可能是 GBK：结论里的 ✅/❌ 会炸，降级成可编码字符而不是崩掉
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(text.encode(encoding, errors="replace").decode(encoding, errors="replace"), flush=True)
    _LOG_LINES.append(text)


def force_utf8_streams() -> None:
    """尽量把 stdout/stderr 切成 UTF-8（Actions 本来就是；本地 Windows 控制台常常不是）。"""
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001  (老 Python / 被重定向过的流)
            pass


def redact(text: str) -> str:
    """落盘/打印前把 key 原文擦掉（代理返回体里若回显 key 也不会泄漏）。"""
    out = str(text)
    for secret in _SECRETS:
        if secret and len(secret) >= 8:
            out = out.replace(secret, "<redacted>")
    return out


def mask(secret: str | None) -> str:
    """key 只显示首尾少量字符，用于人工核对「是哪一把」。"""
    if not secret:
        return ""
    value = secret.strip()
    if len(value) <= 10:
        return "***"
    return f"{value[:4]}…{value[-4:]}（len={len(value)}）"


def sanitize_url(url: str | None) -> str:
    """去掉 userinfo / query（base_url 里可能带 token 之类的敏感参数）。"""
    if not url:
        return ""
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return "<无法解析的 URL>"
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme or "https", netloc, parts.path.rstrip("/"), "", ""))


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(ts: dt.datetime) -> str:
    return ts.replace(microsecond=0).isoformat()


def elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 1)


def _secret_shape(value: str | None) -> dict:
    """只看「形态」，绝不输出内容：长度、首尾空白、控制字符、非 ASCII。

    为什么需要这个：2026-09-15 的运行时故障里，Tenshi 在容器内对**每一个** Claude 通路
    都得到 `APIConnectionError: Connection error.`（已入库日志 268/268），却从来没有出现过
    任何 HTTP 状态码错误；而同一镜像里本脚本用 strip 过的值探测却一切正常。
    `APIConnectionError` 是 anthropic SDK 对**本地构造请求失败**的统一包装——
    最常见的原因就是 secret 里带了首尾空白/换行/控制字符（从网页粘贴 secret 的经典产物），
    导致 httpx 直接拒绝构造请求，根本没上网。这里把这种形态显式报出来。
    """
    raw = value or ""
    stripped = raw.strip()
    return {
        "length": len(raw),
        "stripped_length": len(stripped),
        "has_surrounding_whitespace": raw != stripped,
        "control_chars": sum(1 for ch in raw if ord(ch) < 32),
        "non_ascii": sum(1 for ch in raw if ord(ch) > 126),
    }


def shape_note(shape: dict | None) -> str:
    if not shape or not shape.get("length"):
        return "—"
    flags = []
    if shape.get("has_surrounding_whitespace"):
        flags.append("❌首尾空白")
    if shape.get("control_chars"):
        flags.append(f"❌控制字符×{shape['control_chars']}")
    if shape.get("non_ascii"):
        flags.append(f"❌非ASCII×{shape['non_ascii']}")
    return f"len={shape['length']}" + (" · " + " · ".join(flags) if flags else " · 形态正常")


def has_shape_anomaly(shape: dict | None) -> bool:
    return bool(
        shape
        and shape.get("length")
        and (shape.get("has_surrounding_whitespace") or shape.get("control_chars") or shape.get("non_ascii"))
    )


def os_label() -> str:
    try:
        return f"{os.getenv('RUNNER_OS') or sys.platform} {os.uname().release}"  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001  (Windows 无 os.uname)
        return f"{os.getenv('RUNNER_OS') or sys.platform}"


def detect_environment() -> str:
    """本次探测跑在容器里还是宿主 runner 上。

    这一点是整套检测的关键：Tenshi 的回复任务跑在 `container:` 指定的 job 容器里
    （ghcr.io/hisou-tenshi/calling-tenshi:latest），容器与宿主 runner 的 DNS / 出网 /
    证书信任链并不相同。只在宿主上探测会得出「代理一切正常」的结论，而 Tenshi 在容器里
    每一轮都连不上——所以两边都要测，再对照。
    """
    try:
        if pathlib.Path("/.dockerenv").exists():
            return "容器（job container）"
        cgroup = pathlib.Path("/proc/1/cgroup")
        if cgroup.exists() and "docker" in cgroup.read_text(encoding="utf-8", errors="replace"):
            return "容器（job container）"
    except Exception:  # noqa: BLE001
        pass
    return "宿主 runner"


# ============================================================
# 分层探测
# ============================================================


def probe_dns(host: str, port: int) -> dict:
    start = time.perf_counter()
    result: dict = {"ok": False, "host": host, "port": port, "addresses": [], "error": None}
    try:
        seen: list[str] = []
        for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
            family = "IPv6" if info[0] == socket.AF_INET6 else "IPv4"
            entry = f"{info[4][0]} ({family})"
            if entry not in seen:
                seen.append(entry)
        result["addresses"] = seen
        result["ok"] = bool(seen)
    except socket.gaierror as exc:
        result["error"] = f"gaierror: {exc}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["latency_ms"] = elapsed_ms(start)
    return result


def probe_tcp(host: str, port: int, timeout: float) -> dict:
    start = time.perf_counter()
    result: dict = {"ok": False, "error": None, "peer": None}
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        peer = sock.getpeername()
        result["ok"] = True
        result["peer"] = f"{peer[0]}:{peer[1]}"
    except socket.timeout:
        result["error"] = f"timeout（{timeout}s 内未建连：出口被丢包或代理侧限流）"
    except ConnectionRefusedError as exc:
        result["error"] = f"connection refused：{exc}"
    except OSError as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    result["latency_ms"] = elapsed_ms(start)
    return result


def _cert_summary(cert: dict) -> dict:
    if not cert:
        return {}
    subject = {k: v for part in cert.get("subject", ()) for k, v in part}
    issuer = {k: v for part in cert.get("issuer", ()) for k, v in part}
    not_after = cert.get("notAfter")
    days_left = None
    if not_after:
        try:
            expiry = dt.datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)
            days_left = (expiry - now_utc()).days
        except ValueError:
            days_left = None
    return {
        "subject_cn": subject.get("commonName"),
        "issuer_cn": issuer.get("commonName"),
        "issuer_org": issuer.get("organizationName"),
        "not_before": cert.get("notBefore"),
        "not_after": not_after,
        "days_left": days_left,
        "san": [name for kind, name in cert.get("subjectAltName", ()) if kind == "DNS"][:8],
    }


def probe_tls(host: str, port: int, timeout: float) -> dict:
    """严格握手一次；失败再用宽松上下文握一次，用来区分「TLS 断了」与「证书不受信」。"""
    result: dict = {
        "ok": False,
        "error": None,
        "version": None,
        "cipher": None,
        "alpn": None,
        "cert": {},
        "cert_error": None,
        "unverified_handshake_ok": None,
    }

    def _handshake(context: ssl.SSLContext) -> tuple[bool, str | None, ssl.SSLSocket | None]:
        sock = None
        tls = None
        try:
            sock = socket.create_connection((host, port), timeout=timeout)
            tls = context.wrap_socket(sock, server_hostname=host)
            return True, None, tls
        except ssl.SSLCertVerificationError as exc:
            return False, f"证书校验失败：{exc.verify_message or exc}", None
        except ssl.SSLError as exc:
            return False, f"TLS 握手失败：{exc}", None
        except socket.timeout:
            return False, f"timeout（{timeout}s）", None
        except OSError as exc:
            return False, f"{type(exc).__name__}: {exc}", None
        finally:
            # 成功时把 socket 交给调用方（tls 非空），失败时自己收掉
            if tls is None and sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def _describe(tls: ssl.SSLSocket) -> None:
        result["version"] = tls.version()
        cipher = tls.cipher()
        result["cipher"] = f"{cipher[0]} ({cipher[1]}, {cipher[2]} bits)" if cipher else None
        result["alpn"] = tls.selected_alpn_protocol()
        result["cert"] = _cert_summary(tls.getpeercert())

    def _contexts() -> tuple[ssl.SSLContext, ssl.SSLContext]:
        strict = ssl.create_default_context()
        loose = ssl.create_default_context()
        loose.check_hostname = False
        loose.verify_mode = ssl.CERT_NONE
        for ctx in (strict, loose):
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except NotImplementedError:
                pass
        return strict, loose

    start = time.perf_counter()
    strict, loose = _contexts()
    ok, err, tls = _handshake(strict)
    if ok and tls is not None:
        try:
            result["ok"] = True
            _describe(tls)
        finally:
            try:
                tls.close()
            except OSError:
                pass
    else:
        result["error"] = err
        ok_loose, _err_loose, tls_loose = _handshake(loose)
        result["unverified_handshake_ok"] = bool(ok_loose)
        if ok_loose and tls_loose is not None:
            result["cert_error"] = err
            try:
                _describe(tls_loose)
            finally:
                try:
                    tls_loose.close()
                except OSError:
                    pass
    result["latency_ms"] = elapsed_ms(start)
    return result


def http_request(
    url: str,
    *,
    method: str = "GET",
    headers: dict | None = None,
    payload: dict | None = None,
    timeout: float = 20.0,
) -> dict:
    """一次 HTTP 请求；4xx/5xx 也要把响应体读出来（那才是最有信息量的部分）。"""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        if value:
            req.add_header(key, value)

    start = time.perf_counter()
    raw = b""
    result: dict = {
        "url": sanitize_url(url),
        "method": method,
        "status": None,
        "ok": False,
        "latency_ms": None,
        "body": "",
        "body_truncated": False,
        "error": None,
        "redirected_to": None,
        "server": None,
    }
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (URL 由调用方构造)
            raw = resp.read(4000)
            result["status"] = resp.status
            result["ok"] = 200 <= resp.status < 300
            result["server"] = resp.headers.get("server")
            if resp.geturl() != url:
                result["redirected_to"] = sanitize_url(resp.geturl())
    except urllib.error.HTTPError as exc:
        raw = exc.read(4000) if hasattr(exc, "read") else b""
        result["status"] = exc.code
        result["server"] = exc.headers.get("server") if exc.headers else None
        result["error"] = f"HTTP {exc.code} {exc.reason}"
    except urllib.error.URLError as exc:
        reason = exc.reason
        result["error"] = (
            f"timeout（{timeout}s）" if isinstance(reason, socket.timeout) else f"URLError: {reason}"
        )
    except (TimeoutError, socket.timeout):
        result["error"] = f"timeout（{timeout}s）"
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["latency_ms"] = elapsed_ms(start)

    text = raw.decode("utf-8", errors="replace") if raw else ""
    if len(text) > BODY_EXCERPT_LIMIT:
        text = text[:BODY_EXCERPT_LIMIT]
        result["body_truncated"] = True
    result["body"] = redact(text)
    return result


def anthropic_headers(api_key: str) -> dict:
    return {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}


def probe_egress(timeout: float) -> dict:
    """runner 的公网出口 IP —— 代理方要加白名单时用的就是它。"""
    last_error = None
    for url in ("https://api.ipify.org?format=json", "https://ifconfig.me/ip"):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read(200).decode("utf-8", errors="replace").strip()
            ip = json.loads(raw).get("ip") if url.endswith("json") else raw
            if ip:
                return {"ok": True, "ip": ip, "source": sanitize_url(url)}
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}: {exc}"
    return {"ok": False, "ip": None, "source": None, "error": last_error or "未知错误"}


# ============================================================
# 判定
# ============================================================


def _error_info(result: dict | None) -> tuple[str | None, str | None]:
    """从响应体里取出 Anthropic 风格的 error.type / error.message。"""
    if not result:
        return None, None
    try:
        data = json.loads(result.get("body") or "{}")
    except (ValueError, TypeError):
        return None, None
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return err.get("type"), err.get("message")
    if isinstance(err, str):
        return None, err
    return None, None


def is_model_level_error(result: dict | None) -> bool:
    """这个失败是不是「模型这一档不可用」（换模型就能继续验证）。"""
    if not result or result.get("status") not in (400, 404):
        return False
    err_type, err_msg = _error_info(result)
    blob = f"{err_type or ''} {err_msg or ''} {result.get('body') or ''}".lower()
    return "model" in blob


VERDICT_LABELS = {
    "ok": "✅ 可用",
    "flaky": "⚠️ 不稳定",
    "not_configured": "➖ 未配置",
    "dns_fail": "❌ DNS 失败",
    "tcp_fail": "❌ 连接失败",
    "tls_fail": "❌ TLS 失败",
    "tls_cert_invalid": "⚠️ 证书不受信",
    "auth_denied": "❌ key 被拒",
    "blocked": "❌ 被拦截",
    "model_not_found": "⚠️ 无可用模型",
    "endpoint_404": "❌ 路径 404",
    "rate_limited": "⚠️ 限流",
    "quota_exhausted": "❌ 额度问题",
    "bad_request": "❌ 请求被拒",
    "upstream_error": "❌ 上游错误",
    "timeout": "❌ 超时",
    "http_error": "❌ 请求异常",
    "probe_error": "❌ 探测异常",
    "unknown": "❓ 未判定",
}


def label(verdict: str) -> str:
    return VERDICT_LABELS.get(verdict, verdict)


def classify(endpoint: dict) -> tuple[str, str]:
    """把分层结果收敛成一个结论 + 一句人话。"""
    if not endpoint["configured"]:
        return "not_configured", "未配置（缺 secret / 环境变量）"

    dns, tcp, tls = endpoint.get("dns"), endpoint.get("tcp"), endpoint.get("tls")
    if dns and not dns["ok"]:
        return "dns_fail", f"DNS 解析失败：{dns.get('error')}"
    if tcp and not tcp["ok"]:
        return "tcp_fail", f"TCP 建连失败：{tcp.get('error')}"
    if tls and not tls["ok"]:
        if tls.get("unverified_handshake_ok"):
            return "tls_cert_invalid", f"TLS 可握手但证书不受信：{tls.get('cert_error')}"
        return "tls_fail", f"TLS 握手失败：{tls.get('error')}"

    messages = endpoint.get("messages") or {}
    models = endpoint.get("models") or {}
    attempts = messages.get("attempts") or []
    statuses = [a.get("status") for a in attempts if a.get("status") is not None]
    last = attempts[-1] if attempts else models
    status = statuses[-1] if statuses else last.get("status")
    err_type, err_msg = _error_info(last)
    detail = f"HTTP {status}" + (f"（{err_type}）" if err_type else "")
    if err_msg:
        detail += f"：{err_msg[:160]}"

    success = [s for s in statuses if 200 <= (s or 0) < 300]
    if success or models.get("ok"):
        if statuses and not success:
            return "model_not_found", f"鉴权通过但 messages 无可用模型：{detail}"
        if len(set(statuses)) > 1:
            return "flaky", f"多次探测结果不一致（{statuses}）：{detail}"
        if len(success) < len(statuses):
            return "flaky", f"多次探测部分失败（{statuses}）：{detail}"
        return "ok", "可达且可调用"

    if status in (401, 403):
        body_low = (last.get("body") or "").lower()
        blocked = status == 403 and any(
            word in body_low for word in ("cloudflare", "<html", "access denied", "forbidden by", "waf")
        )
        if blocked:
            return "blocked", f"被代理侧 / WAF 拒绝（403）：{detail}"
        return "auth_denied", f"key 被拒（{status}）：{detail}"
    if status == 404:
        if is_model_level_error(last):
            return "model_not_found", f"模型不存在或未开通：{detail}"
        return "endpoint_404", f"路径不存在（404）：{detail}"
    if status == 429:
        return "rate_limited", f"限流（429）：{detail}"
    if status in (402, 451):
        return "quota_exhausted", f"额度 / 风控（{status}）：{detail}"
    if status == 400 and err_msg and any(
        word in err_msg.lower() for word in ("credit", "balance", "quota", "额度", "余额", "欠费")
    ):
        return "quota_exhausted", f"额度 / 欠费（400）：{detail}"
    if status == 400:
        return "bad_request", f"请求被拒（400）：{detail}"
    if status and status >= 500:
        return "upstream_error", f"代理上游错误（{status}）：{detail}"
    if last and "timeout" in str(last.get("error") or "").lower():
        return "timeout", f"HTTP 请求超时：{detail}"
    if last and last.get("error"):
        return "http_error", f"{last.get('error')}：{detail}"
    return "unknown", detail


# ============================================================
# 通路检测
# ============================================================


def build_endpoints() -> list[dict]:
    endpoints: list[dict] = []
    for tag, base_env, key_envs, note in PROXY_SPECS:
        raw_base = OFFICIAL_BASE_URL if tag == "Official" else (os.getenv(base_env) or "")
        base_url = raw_base.strip()
        api_key = ""
        raw_key = ""
        key_source = None
        for env_name in key_envs:
            value = os.getenv(env_name) or ""
            if value.strip():
                api_key = value.strip()
                raw_key = value
                key_source = env_name
                break
        missing = []
        if tag != "Official" and not base_url:
            missing.append(base_env)
        if not api_key:
            missing.append(" / ".join(key_envs))
        key_shape = _secret_shape(raw_key)
        base_shape = _secret_shape(raw_base) if tag != "Official" else None
        endpoints.append(
            {
                "tag": tag,
                "note": note,
                "base_env": base_env,
                "base_url": sanitize_url(base_url),
                "key_source": key_source,
                "key_masked": mask(api_key) if api_key else "",
                "key_shape": key_shape,
                "base_url_shape": base_shape,
                "shape_anomaly": has_shape_anomaly(key_shape) or has_shape_anomaly(base_shape),
                "configured": bool(base_url and api_key),
                "missing": missing,
                "dns": None,
                "tcp": None,
                "tls": None,
                "models": None,
                "messages": None,
                "chosen_model": None,
                "model_probes": [],
                "verdict": "unknown",
                "verdict_text": "",
                "_base_url_raw": base_url,
                "_api_key": api_key,
            }
        )
    return endpoints


def _probe_messages_with_models(endpoint: dict, args: argparse.Namespace, headers: dict) -> None:
    """先用一串候选模型各试一次（只对「模型不可用」继续换），再对可用模型重复测稳定性。"""
    url = f"{endpoint['_base_url_raw'].rstrip('/')}/v1/messages"
    log(f"    POST {endpoint['base_url']}/v1/messages  max_tokens=1  候选模型 {args.models}")

    chosen = None
    for model in args.models:
        result = http_request(
            url,
            method="POST",
            headers=headers,
            payload={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]},
            timeout=args.timeout,
        )
        result["model"] = model
        endpoint["model_probes"].append(result)
        log(
            f"      [model={model}] status={result['status']} {result['latency_ms']}ms"
            + (f" error={result['error']}" if result["error"] else "")
            + (f" body={result['body'][:200]}" if result["body"] else "")
        )
        if not is_model_level_error(result):
            chosen = model
            break
        log(f"      ↳ 该模型在代理侧不可用，换下一个候选")

    if chosen is None:
        endpoint["messages"] = {
            "attempts": endpoint["model_probes"][-1:],
            "attempt_count": 1,
            "statuses": [endpoint["model_probes"][-1].get("status")] if endpoint["model_probes"] else [],
            "latency_ms": {},
            "model": None,
        }
        return

    endpoint["chosen_model"] = chosen
    attempts = [p for p in endpoint["model_probes"] if p.get("model") == chosen][:1]
    remaining = max(0, args.attempts - len(attempts))
    for index in range(remaining):
        time.sleep(args.retry_sleep)
        result = http_request(
            url,
            method="POST",
            headers=headers,
            payload={"model": chosen, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]},
            timeout=args.timeout,
        )
        result["model"] = chosen
        result["attempt"] = len(attempts) + index + 1
        attempts.append(result)
        log(
            f"      [复测 {index + 2}/{args.attempts}] status={result['status']} {result['latency_ms']}ms"
            + (f" error={result['error']}" if result["error"] else "")
        )
    latencies = [a["latency_ms"] for a in attempts if a.get("latency_ms") is not None]
    endpoint["messages"] = {
        "attempts": attempts,
        "attempt_count": len(attempts),
        "statuses": [a.get("status") for a in attempts],
        "latency_ms": {
            "min": min(latencies) if latencies else None,
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "model": chosen,
    }


def probe_endpoint(endpoint: dict, args: argparse.Namespace) -> dict:
    if not endpoint["configured"]:
        endpoint["verdict"], endpoint["verdict_text"] = classify(endpoint)
        log(f"  [跳过] {endpoint['tag']}：{endpoint['verdict_text']}（缺 {', '.join(endpoint['missing'])}）")
        return endpoint

    base_url = endpoint["_base_url_raw"]
    parsed = urllib.parse.urlsplit(base_url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme != "http" else 80)
    log(f"  → {endpoint['tag']}  {endpoint['base_url']}  key={endpoint['key_masked']}（来源 {endpoint['key_source']}）")

    if not host:
        endpoint["verdict"], endpoint["verdict_text"] = "bad_request", "base_url 无法解析出主机名"
        log(f"    [失败] {endpoint['verdict_text']}")
        return endpoint

    endpoint["dns"] = probe_dns(host, port)
    log(f"    DNS : {'/'.join(endpoint['dns']['addresses']) or endpoint['dns'].get('error')}  {endpoint['dns']['latency_ms']}ms")

    if endpoint["dns"]["ok"]:
        endpoint["tcp"] = probe_tcp(host, port, args.timeout)
        detail = f"OK {endpoint['tcp'].get('peer')}" if endpoint["tcp"]["ok"] else str(endpoint["tcp"].get("error"))
        log(f"    TCP : {detail}  {endpoint['tcp']['latency_ms']}ms")

    if endpoint["tcp"] and endpoint["tcp"]["ok"]:
        endpoint["tls"] = probe_tls(host, port, args.timeout)
        cert = endpoint["tls"].get("cert") or {}
        if endpoint["tls"]["ok"]:
            log(
                f"    TLS : {endpoint['tls']['version']} / {endpoint['tls']['cipher']}"
                f" · 证书 {cert.get('subject_cn')} ← {cert.get('issuer_cn')}"
                f" · {cert.get('days_left')} 天后到期 · {endpoint['tls']['latency_ms']}ms"
            )
        else:
            log(
                f"    TLS : 失败 {endpoint['tls'].get('error')}"
                f"（宽松握手={'可行' if endpoint['tls'].get('unverified_handshake_ok') else '不可行'}）"
            )

    network_ok = bool(
        endpoint.get("dns") and endpoint["dns"]["ok"] and endpoint.get("tcp") and endpoint["tcp"]["ok"]
    )
    if not network_ok:
        log("    [跳过] 网络层已不可达，不再发 HTTP 请求（结论已确定）")
        endpoint["verdict"], endpoint["verdict_text"] = classify(endpoint)
        log(f"    [结论] {label(endpoint['verdict'])} —— {endpoint['verdict_text']}")
        return endpoint

    headers = anthropic_headers(endpoint["_api_key"])
    endpoint["models"] = http_request(
        f"{base_url.rstrip('/')}/v1/models", headers=headers, timeout=args.timeout
    )
    log(
        f"    GET  {endpoint['base_url']}/v1/models → status={endpoint['models']['status']}"
        f" {endpoint['models']['latency_ms']}ms" + (f" error={endpoint['models']['error']}" if endpoint["models"]["error"] else "")
    )

    if args.probe_messages:
        _probe_messages_with_models(endpoint, args, headers)

    endpoint["verdict"], endpoint["verdict_text"] = classify(endpoint)
    log(f"    [结论] {label(endpoint['verdict'])} —— {endpoint['verdict_text']}")
    return endpoint


# ============================================================
# 报告
# ============================================================


def statuses_cell(statuses: list) -> str:
    """状态码展示：None（没发出去/没拿到响应）不能写成 "None"。"""
    shown = [str(s) for s in statuses if s is not None]
    return "、".join(shown) if shown else "—（无响应）"


def latency_cell(endpoint: dict) -> str:
    lat = (endpoint.get("messages") or {}).get("latency_ms") or {}
    if lat.get("median") is not None:
        return f"{lat['min']} / {lat['median']} / {lat['max']} ms"
    models = endpoint.get("models") or {}
    if models.get("latency_ms") is not None:
        return f"{models['latency_ms']} ms"
    return "—"


def build_markdown(context: dict, endpoints: list[dict]) -> str:
    configured = [e for e in endpoints if e["configured"]]
    failing = [e for e in configured if e["verdict"] != "ok"]
    ok_configured = [e for e in configured if e["verdict"] == "ok"]

    lines: list[str] = []
    lines.append("# Claude 代理可达性检测报告")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|---|---|")
    lines.append(f"| 检测时间（UTC） | `{context['started_at']}` |")
    lines.append(
        f"| 运行环境 | **{context.get('environment') or '未标注'}** · `{context['runner']}`"
        f" / `{context['os']}` / Python `{context['python']}` |"
    )
    if context["github"]:
        lines.append(
            f"| GitHub | run `{context['github'].get('run_id')}` · workflow `{context['github'].get('workflow')}`"
            f" · event `{context['github'].get('event')}` · sha `{str(context['github'].get('sha'))[:8]}` |"
        )
    else:
        lines.append("| GitHub | 本地运行（非 Actions 环境，结论不代表 GitHub runner） |")
    lines.append(f"| Runner 出口 IP | `{context['egress'].get('ip') or '未知'}` |")
    lines.append(f"| 探测模型 | `{'、'.join(context['models'])}`（max_tokens=1，每通路最多 {context['attempts']} 次） |")
    lines.append("")

    lines.append("## 结论")
    lines.append("")
    if not configured:
        lines.append("> ❌ **一个通路都没配置**：环境里没有任何 `CLAUDE_PROXY_*` / `CLAUDE_API_KEY`，无法检测。")
    elif not failing:
        lines.append(f"> ✅ **{len(ok_configured)}/{len(configured)} 个已配置通路全部可用**：GitHub runner 出网正常，key 可用。")
    else:
        lines.append(f"> ⚠️ **{len(ok_configured)}/{len(configured)} 个已配置通路可用**，异常通路：")
        lines.append(">")
        for endpoint in failing:
            lines.append(f"> - `{endpoint['tag']}`：{label(endpoint['verdict'])} —— {endpoint['verdict_text']}")

    anomalies = [e for e in endpoints if e.get("shape_anomaly")]
    if anomalies:
        lines.append(">")
        lines.append("> 🧪 **检测到 secret 形态异常**（下列只是长度/空白/控制字符，不是内容）：")
        for endpoint in anomalies:
            lines.append(
                f"> - `{endpoint['tag']}`：key {shape_note(endpoint.get('key_shape'))}"
                f"；base_url {shape_note(endpoint.get('base_url_shape'))}"
            )
        lines.append(">")
        lines.append(
            "> 这类值会被 anthropic SDK 在**本地**就拒绝构造请求，表现为"
            " `APIConnectionError: Connection error.` —— 与网络、代理、key 是否有效都无关；"
            "重新粘贴一遍 secret（去掉首尾空白/换行）即可。"
        )
    lines.append("")

    lines.append("## 一览")
    lines.append("")
    lines.append("| 通路 | 说明 | 配置 | DNS | TCP | TLS | HTTP(messages) | 延迟 min/中位/max | 结论 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for endpoint in endpoints:
        dns = endpoint.get("dns") or {}
        tcp = endpoint.get("tcp") or {}
        tls = endpoint.get("tls") or {}
        statuses = (endpoint.get("messages") or {}).get("statuses") or []
        lines.append(
            "| `{tag}` | {note} | {conf} | {dns} | {tcp} | {tls} | {http} | {lat} | {verdict} |".format(
                tag=endpoint["tag"],
                note=endpoint["note"],
                conf="✅" if endpoint["configured"] else "➖",
                dns="✅" if dns.get("ok") else ("❌" if dns else "—"),
                tcp="✅" if tcp.get("ok") else ("❌" if tcp else "—"),
                tls="✅" if tls.get("ok") else ("⚠️" if tls.get("unverified_handshake_ok") else ("❌" if tls else "—")),
                http=statuses_cell(statuses),
                lat=latency_cell(endpoint),
                verdict=label(endpoint["verdict"]),
            )
        )
    lines.append("")

    lines.append("## 通路明细")
    lines.append("")
    for endpoint in endpoints:
        lines.append(f"### `{endpoint['tag']}`（{endpoint['note']}）")
        lines.append("")
        if not endpoint["configured"]:
            lines.append(f"- 未配置，缺少：`{'`、`'.join(endpoint['missing'])}`")
            lines.append("")
            continue
        lines.append(f"- base_url：`{endpoint['base_url']}`")
        lines.append(f"- key：`{endpoint['key_masked']}`（来自 `{endpoint['key_source']}`）")
        lines.append(f"- 结论：**{label(endpoint['verdict'])}** —— {endpoint['verdict_text']}")
        dns = endpoint.get("dns") or {}
        if dns:
            err = f" · {dns['error']}" if dns.get("error") else ""
            lines.append(f"- DNS：{'、'.join(dns.get('addresses') or []) or '无记录'}（{dns.get('latency_ms')} ms）{err}")
        tcp = endpoint.get("tcp") or {}
        if tcp:
            state = f"连通 {tcp.get('peer')}" if tcp.get("ok") else str(tcp.get("error"))
            lines.append(f"- TCP：{state}（{tcp.get('latency_ms')} ms）")
        tls = endpoint.get("tls") or {}
        if tls:
            if tls.get("ok"):
                cert = tls.get("cert") or {}
                lines.append(f"- TLS：{tls.get('version')} · {tls.get('cipher')} · ALPN={tls.get('alpn')}（{tls.get('latency_ms')} ms）")
                lines.append(
                    f"- 证书：`{cert.get('subject_cn')}` ← `{cert.get('issuer_cn')}`（{cert.get('issuer_org')}）"
                    f" · 到期 `{cert.get('not_after')}`（剩 {cert.get('days_left')} 天）"
                    f" · SAN：{', '.join(cert.get('san') or []) or '—'}"
                )
            else:
                lines.append(
                    f"- TLS：❌ {tls.get('error')}"
                    f"（宽松握手={'可行' if tls.get('unverified_handshake_ok') else '不可行'}）"
                )
        models = endpoint.get("models") or {}
        if models:
            err = f" · {models.get('error')}" if models.get("error") else ""
            lines.append(f"- `GET /v1/models`：HTTP `{models.get('status')}` · {models.get('latency_ms')} ms{err}")
        messages = endpoint.get("messages") or {}
        if messages:
            lat = messages.get("latency_ms") or {}
            lines.append(
                f"- `POST /v1/messages`：状态码 {statuses_cell(messages.get('statuses') or [])}"
                f" · 延迟 {lat.get('min')}/{lat.get('median')}/{lat.get('max')} ms"
                f" · 实际使用模型 `{messages.get('model') or '—'}`"
            )
        if endpoint.get("model_probes"):
            lines.append("- 模型探测记录：")
            for probe in endpoint["model_probes"]:
                lines.append(
                    f"  - `{probe.get('model')}` → HTTP `{probe.get('status')}` · {probe.get('latency_ms')} ms"
                )
        last = ((messages.get("attempts") or [{}])[-1]) if messages else {}
        if last and last.get("body"):
            lines.append("")
            lines.append("  <details><summary>最后一次响应体（截断）</summary>")
            lines.append("")
            lines.append("  ```json")
            for chunk in (last.get("body") or "").splitlines()[:20]:
                lines.append(f"  {chunk}")
            lines.append("  ```")
            lines.append("")
            lines.append("  </details>")
        lines.append("")

    lines.append("## 密钥形态体检")
    lines.append("")
    lines.append("> 只统计「形态」（长度 / 首尾空白 / 控制字符 / 非 ASCII），**不输出任何密钥内容**。")
    lines.append("> secret 里带换行或首尾空白时，anthropic SDK 会在本地就构造失败，症状正是")
    lines.append("> `APIConnectionError: Connection error.`，很容易被误判成网络/代理故障。")
    lines.append("")
    lines.append("| 通路 | 来源变量 | key（掩码） | key 形态 | base_url 形态 |")
    lines.append("|---|---|---|---|---|")
    for endpoint in endpoints:
        lines.append(
            "| `{tag}` | {src} | `{masked}` | {ks} | {bs} |".format(
                tag=endpoint["tag"],
                src=endpoint.get("key_source") or "—",
                masked=endpoint.get("key_masked") or "—",
                ks=shape_note(endpoint.get("key_shape")),
                bs=shape_note(endpoint.get("base_url_shape")),
            )
        )
    lines.append("")

    lines.append("## 判定口径与建议")
    lines.append("")
    lines.append("- **DNS / TCP / TLS 全绿但 HTTP 401/403**：GitHub 出网没问题，问题在 key 或代理端授权。"
                 "把本页的 runner 出口 IP 交给代理方，确认是否在许可范围。")
    lines.append("- **TLS 握手失败 / 证书不受信**：代理换了证书或域名，或缺中间证书；SDK 侧同样会失败，应换通路。")
    lines.append("- **TCP timeout / refused**：GitHub runner 到代理的链路不可达（被墙或代理侧限流），本机可能完全正常。")
    lines.append("- **429 / 额度类错误**：网络与鉴权正常，按套餐/额度处理。")
    lines.append("- **`Official` 是对照组**：官方与代理同时失败 → 看 runner 出网；只有代理失败 → 看代理侧。")
    lines.append("- 原始数据 `latest.json` · 完整日志 `latest.log` · 历史趋势 `history.jsonl`")
    lines.append("")
    return "\n".join(lines)


def build_summary_record(context: dict, endpoints: list[dict]) -> dict:
    return {
        "ts": context["started_at"],
        "run_id": (context["github"] or {}).get("run_id"),
        "runner": context["runner"],
        "environment": context.get("environment"),
        "egress_ip": context["egress"].get("ip"),
        "models": context["models"],
        "endpoints": {
            endpoint["tag"]: {
                "verdict": endpoint["verdict"],
                "statuses": (endpoint.get("messages") or {}).get("statuses") or [],
                "latency_ms": ((endpoint.get("messages") or {}).get("latency_ms") or {}).get("median")
                or (endpoint.get("models") or {}).get("latency_ms"),
                "model": (endpoint.get("messages") or {}).get("model"),
            }
            for endpoint in endpoints
            if endpoint["configured"]
        },
    }


# ============================================================
# 宿主 vs 容器 对照（Tenshi 的真实运行环境是容器）
# ============================================================


def _load_latest(path: str) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def _env_title(payload: dict, fallback: str) -> str:
    context = payload.get("context") or {}
    env = context.get("environment") or "未知环境"
    runner = context.get("runner") or "?"
    return f"{env}（{fallback}：{runner}）"


def _failure_hint(endpoint: dict) -> str:
    """给出一条失败通路最有信息量的那句。"""
    if not endpoint:
        return "未探测"
    for key in ("tls", "tcp", "dns"):
        layer = endpoint.get(key) or {}
        if layer and not layer.get("ok") and layer.get("error"):
            return f"{key.upper()}: {layer['error']}"
    messages = endpoint.get("messages") or {}
    statuses = [s for s in (messages.get("statuses") or []) if s is not None]
    if statuses:
        detail = endpoint.get("verdict_text") or ""
        return f"HTTP {statuses[-1]}" + (f" · {detail[:120]}" if detail else "")
    return (endpoint.get("verdict_text") or "")[:160]


def build_compare_markdown(a_payload: dict, b_payload: dict, a_label: str, b_label: str) -> str:
    a_env, b_env = _env_title(a_payload, a_label), _env_title(b_payload, b_label)
    a_label = (a_payload.get("context") or {}).get("environment") or a_label
    b_label = (b_payload.get("context") or {}).get("environment") or b_label
    a_endpoints = {e["tag"]: e for e in (a_payload.get("endpoints") or [])}
    b_endpoints = {e["tag"]: e for e in (b_payload.get("endpoints") or [])}
    tags = [t for t in dict.fromkeys(list(a_endpoints) + list(b_endpoints))]

    only_b_fail: list[str] = []
    only_a_fail: list[str] = []
    both_fail: list[str] = []
    rows: list[str] = []
    for tag in tags:
        a, b = a_endpoints.get(tag), b_endpoints.get(tag)
        if not (a or {}).get("configured") and not (b or {}).get("configured"):
            continue
        av = (a or {}).get("verdict", "not_configured")
        bv = (b or {}).get("verdict", "not_configured")
        if av == "ok" and bv == "ok":
            note = "两边一致可用"
        elif av == "ok" and bv != "ok":
            note = f"**只有 {b_label} 不可达** → 问题在该环境（容器出网/DNS/证书），代理本身没毛病"
            only_b_fail.append(tag)
        elif av != "ok" and bv == "ok":
            note = f"只有 {a_label} 不可达"
            only_a_fail.append(tag)
        elif av == bv:
            note = f"两边一致失败（{label(av)}）→ 偏代理侧 / 配置侧问题"
            both_fail.append(tag)
        else:
            note = f"两边失败原因不同：{_failure_hint(a)} / {_failure_hint(b)}"
            both_fail.append(tag)
        rows.append(
            "| `{tag}` | {a} | {b} | {note} |".format(
                tag=tag,
                a=label(av) if (a or {}).get("configured") else "➖ 未配置",
                b=label(bv) if (b or {}).get("configured") else "➖ 未配置",
                note=note,
            )
        )

    lines: list[str] = []
    lines.append("# Claude 代理可达性对照报告（两种运行环境）")
    lines.append("")
    lines.append(f"- A（基线）：{a_env}")
    lines.append(f"- B（对照）：{b_env}")
    lines.append("")
    lines.append("## 结论")
    lines.append("")
    if only_b_fail:
        lines.append(
            f"> ⚠️ **{len(only_b_fail)} 个通路只在 B（Tenshi 运行环境）不可达**："
            + "、".join(f"`{t}`" for t in only_b_fail)
        )
        lines.append(">")
        lines.append("> 这就是「Tenshi 运行时 Claude 全链失败、但在别处测又一切正常」的**说法**：")
        lines.append("> 故障在 B 所处环境的出网 / DNS / 证书信任链上，不在代理端口上。")
        lines.append("> 下一步看下表里 B 的具体失败层（DNS / TCP / TLS / HTTP），再决定是修镜像、修解析还是修网络策略。")
    elif both_fail:
        lines.append(
            "> ⚠️ 两边都失败的通路：" + "、".join(f"`{t}`" for t in both_fail) + " → 更像代理侧 / 配置侧问题。"
        )
    else:
        lines.append("> ✅ 两种环境结论一致，没有「只在某一侧失败」的通路。")
    lines.append("")
    lines.append("## 逐通路对照")
    lines.append("")
    lines.append(f"| 通路 | A：{a_label} | B：{b_label} | 说明 |")
    lines.append("|---|---|---|---|")
    lines.extend(rows)
    lines.append("")
    lines.append("## 失败细节")
    lines.append("")
    for tag in only_b_fail + only_a_fail + both_fail:
        a, b = a_endpoints.get(tag) or {}, b_endpoints.get(tag) or {}
        lines.append(f"- `{tag}`")
        lines.append(f"  - A {a_label}：{label(a.get('verdict', 'not_configured'))} —— {_failure_hint(a)}")
        lines.append(f"  - B {b_label}：{label(b.get('verdict', 'not_configured'))} —— {_failure_hint(b)}")
    if not (only_b_fail or only_a_fail or both_fail):
        lines.append("- 无失败通路。")
    lines.append("")
    lines.append("- 完整数据：两侧各自的 `latest.json` / `latest.md` / `latest.log`")
    lines.append("")
    return "\n".join(lines)


def write_outputs(out_dir: pathlib.Path, context: dict, endpoints: list[dict], markdown: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    public_endpoints = [{k: v for k, v in e.items() if not k.startswith("_")} for e in endpoints]
    payload = {
        "context": context,
        "endpoints": public_endpoints,
        "verdicts": {e["tag"]: e["verdict"] for e in endpoints},
    }
    (out_dir / "latest.md").write_text(markdown, encoding="utf-8")
    (out_dir / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    history_path = out_dir / "history.jsonl"
    lines: list[str] = []
    if history_path.exists():
        lines = [ln for ln in history_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    lines.append(json.dumps(build_summary_record(context, endpoints), ensure_ascii=False))
    history_path.write_text("\n".join(lines[-HISTORY_LIMIT:]) + "\n", encoding="utf-8")


# ============================================================
# 入口
# ============================================================


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Claude 代理可达性检测（GitHub Actions / 本地均可运行）")
    parser.add_argument(
        "--models",
        default=DEFAULT_MODELS,
        help=f"messages 探测的候选模型（逗号分隔，依次尝试；默认 {DEFAULT_MODELS}）",
    )
    parser.add_argument("--attempts", type=int, default=3, help="每个通路的 messages 探测次数（默认 3）")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次网络操作超时秒数（默认 20）")
    parser.add_argument("--retry-sleep", type=float, default=1.0, help="重复探测之间的间隔秒数（默认 1）")
    parser.add_argument(
        "--no-messages",
        dest="probe_messages",
        action="store_false",
        help="只探测网络与 /v1/models，不发 messages（零 token 消耗）",
    )
    parser.add_argument("--out-dir", default="reports/claude-proxy-reachability", help="报告输出目录")
    parser.add_argument("--fail-on-unreachable", action="store_true", help="存在不可用通路时以退出码 1 结束")
    parser.add_argument(
        "--env-label",
        default=None,
        help="覆盖报告里的运行环境标签（默认自动识别：容器 / 宿主 runner）",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("A_JSON", "B_JSON"),
        help="只做对照：把两份 latest.json 合成对照报告（不发起任何网络请求）",
    )
    parser.add_argument("--compare-out", default=None, help="对照报告输出路径（默认打印到 stdout）")
    parser.set_defaults(probe_messages=True)
    args = parser.parse_args(argv)
    args.models = [m.strip() for m in str(args.models).split(",") if m.strip()] or [DEFAULT_MODELS.split(",")[0]]
    args.attempts = max(1, int(args.attempts))
    return args


def main(argv: list[str] | None = None) -> int:
    force_utf8_streams()
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if args.compare:
        a_path, b_path = args.compare
        markdown = build_compare_markdown(_load_latest(a_path), _load_latest(b_path), "A", "B")
        if args.compare_out:
            out = pathlib.Path(args.compare_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(markdown, encoding="utf-8")
            print(f"对照报告已写入：{out}")
        else:
            print(markdown)
        return 0

    started = now_utc()

    for env_name in (
        "CLAUDE_API_KEY",
        "CLAUDE_PROXY_KEY_BASE",
        "CLAUDE_PROXY_KEY_PRIME",
        "CLAUDE_PROXY_KEY_MAX",
        "CLAUDE_PROXY_KEY",
        "CLAUDE_PROXY_KEY_2",
    ):
        value = (os.getenv(env_name) or "").strip()
        if value:
            _SECRETS.append(value)

    github = None
    if os.getenv("GITHUB_ACTIONS") == "true":
        github = {
            "run_id": os.getenv("GITHUB_RUN_ID"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
            "workflow": os.getenv("GITHUB_WORKFLOW"),
            "event": os.getenv("GITHUB_EVENT_NAME"),
            "repository": os.getenv("GITHUB_REPOSITORY"),
            "sha": os.getenv("GITHUB_SHA"),
        }

    context = {
        "started_at": iso(started),
        "finished_at": None,
        "runner": os.getenv("RUNNER_NAME") or os.getenv("COMPUTERNAME") or socket.gethostname(),
        "os": os_label(),
        "environment": args.env_label or detect_environment(),
        "python": sys.version.split()[0],
        "github": github,
        "models": args.models,
        "attempts": args.attempts,
        "timeout_sec": args.timeout,
        "probe_messages": args.probe_messages,
        "egress": {},
        "script": "scripts/claude_proxy_reachability.py",
    }

    log("=" * 78)
    log("Claude 代理可达性检测（Calling）")
    log(f"  时间(UTC) : {context['started_at']}")
    log(f"  运行环境  : {context['environment']} · {context['runner']} / {context['os']} / Python {context['python']}")
    log(f"  GitHub    : {github or '本地运行（结论不代表 GitHub runner）'}")
    log(f"  探测模型  : {'、'.join(args.models)} · messages × {args.attempts}（{'开启' if args.probe_messages else '关闭'}）")
    log("=" * 78)

    log("[出口] 探测 runner 公网出口 IP…")
    context["egress"] = probe_egress(args.timeout)
    log(f"  → {context['egress'].get('ip') or context['egress'].get('error')}")

    endpoints = build_endpoints()
    log(f"[通路] 共 {len(endpoints)} 个，其中已配置 {sum(1 for e in endpoints if e['configured'])} 个")
    for endpoint in endpoints:
        try:
            probe_endpoint(endpoint, args)
        except Exception as exc:  # noqa: BLE001
            # 单条通路的意外异常不能带走整份报告：如实记录，继续测下一条
            endpoint["verdict"] = "probe_error"
            endpoint["verdict_text"] = f"探测过程异常：{type(exc).__name__}: {exc}"
            log(f"    [异常] {endpoint['verdict_text']}")

    context["finished_at"] = iso(now_utc())
    markdown = build_markdown(context, endpoints)
    out_dir = pathlib.Path(args.out_dir)
    write_outputs(out_dir, context, endpoints, markdown)

    configured = [e for e in endpoints if e["configured"]]
    failing = [e for e in configured if e["verdict"] != "ok"]
    log("=" * 78)
    log(f"汇总：已配置 {len(configured)} 个 · 可用 {len(configured) - len(failing)} 个 · 异常 {len(failing)} 个")
    for endpoint in endpoints:
        log(f"  - {endpoint['tag']:<14} {label(endpoint['verdict'])}")
    log(f"报告：{out_dir / 'latest.md'}")
    log(f"数据：{out_dir / 'latest.json'}")
    log("=" * 78)

    (out_dir / "latest.log").write_text("\n".join(_LOG_LINES) + "\n", encoding="utf-8")

    if not configured:
        return 2
    if failing and args.fail_on_unreachable:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
