import os
import warnings
from typing import Any

import requests
from duckduckgo_search import DDGS

from backend.util import safe_join_under_root

warnings.filterwarnings("ignore", category=RuntimeWarning, module="duckduckgo_search")

TAVILY_KEY = os.getenv("TAVILY_KEY") or os.getenv("Tavily_KEY") or None


def web_search_tool(query: str, *, max_results: int = 5) -> dict[str, Any]:
    query = (query or "").strip()
    if not query:
        return {"query": query, "results": []}
    max_results = max(1, min(10, int(max_results)))

    # 1) Prefer TAVILY
    if TAVILY_KEY:
        try:
            # Tavily API: https://tavily.com/docs
            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_KEY,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                    "include_answer": False,
                },
                timeout=25,
            )
            if resp.status_code == 200:
                data = resp.json() or {}
                tavily_results = data.get("results") or data.get("organic_results") or []
                results: list[dict[str, str]] = []
                for r in tavily_results[:max_results]:
                    title = r.get("title") or ""
                    href = r.get("url") or r.get("href") or ""
                    body = r.get("content") or r.get("snippet") or r.get("body") or ""
                    results.append({"title": title, "href": href, "body": body})
                if results:
                    return {"query": query, "results": results}
        except Exception:
            # Fall back to DDGS
            pass

    # 2) Fallback: ddgs (duckduckgo-search)
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            if not r:
                continue
            title = r.get("title") or ""
            href = r.get("href") or ""
            body = r.get("body") or r.get("snippet") or ""
            results.append({"title": title, "href": href, "body": body})

    return {"query": query, "results": results}


def project_tree(root_abs: str, *, max_depth: int = 3, max_entries: int = 220) -> dict[str, Any]:
    root_abs = os.path.abspath(root_abs)
    out: list[str] = []
    count = 0

    for dirpath, dirnames, filenames in os.walk(root_abs):
        rel_dir = os.path.relpath(dirpath, root_abs)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth > max_depth:
            dirnames[:] = []
            continue

        # Stable ordering
        dirnames.sort()
        filenames.sort()

        for name in dirnames:
            if count >= max_entries:
                return {"root": os.path.basename(root_abs), "entries": out[:max_entries], "truncated": True}
            rel_path = os.path.join(rel_dir, name) if rel_dir != "." else name
            out.append(rel_path.replace("\\", "/") + "/")
            count += 1

        for name in filenames:
            if count >= max_entries:
                return {"root": os.path.basename(root_abs), "entries": out[:max_entries], "truncated": True}
            rel_path = os.path.join(rel_dir, name) if rel_dir != "." else name
            out.append(rel_path.replace("\\", "/"))
            count += 1

    return {"root": os.path.basename(root_abs), "entries": out, "truncated": False}


def read_file_tool(*, project_root_abs: str, relative_path: str, max_chars: int = 20000) -> dict[str, Any]:
    rel = (relative_path or "").strip()
    if rel in ("", "__TREE__", "__TREE"):
        tree = project_tree(project_root_abs)
        return {"type": "project_tree", "tree": tree}

    if ":" in rel:
        return {"type": "error", "error": "absolute/drive paths are not allowed"}
    if rel.startswith("~"):
        return {"type": "error", "error": "tilde paths are not allowed"}
    if rel.startswith("/") or rel.startswith("\\"):
        return {"type": "error", "error": "absolute paths are not allowed"}
    rel = rel.replace("\\", "/")
    if ".." in rel.split("/"):
        return {"type": "error", "error": "path traversal is not allowed"}

    abs_path = safe_join_under_root(project_root_abs, rel)
    if not os.path.exists(abs_path):
        return {"type": "error", "error": "file not found", "relative_path": rel}
    if os.path.isdir(abs_path):
        return {"type": "error", "error": "directories are not supported", "relative_path": rel}
    size = os.path.getsize(abs_path)
    if size > 2_500_000:
        return {"type": "file_too_large", "relative_path": rel, "bytes": int(size)}

    with open(abs_path, "rb") as f:
        raw = f.read()

    if b"\x00" in raw[:20000]:
        return {"type": "binary_file_unsupported", "relative_path": rel, "bytes": int(size)}

    try:
        text = raw.decode("utf-8", errors="ignore")
    except Exception:
        text = raw.decode("latin-1", errors="ignore")

    text = text[:max_chars]
    return {"type": "file_text", "relative_path": rel, "chars": len(text), "content": text}

