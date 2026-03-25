import os
from typing import Iterable


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def safe_join_under_root(root: str, relative_path: str) -> str:
    rel = (relative_path or "").replace("\\", "/").lstrip("/")
    abs_path = os.path.abspath(os.path.join(root, rel))
    root_abs = os.path.abspath(root)
    if os.path.commonpath([abs_path, root_abs]) != root_abs:
        raise ValueError("path escapes project root")
    return abs_path


def chunk_text(text: str, *, chunk_size: int, overlap: int) -> list[str]:
    if not text:
        return []
    if chunk_size <= 0:
        return [text]
    overlap = max(0, min(overlap, chunk_size - 1)) if chunk_size > 1 else 0

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + chunk_size)
        chunks.append(text[start:end])
        if end >= n:
            break
        start = max(0, end - overlap)
    return chunks


def clamp_int(value: int, *, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))

