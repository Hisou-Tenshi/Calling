import hashlib
import os
from typing import Tuple

import numpy as np

from backend.rag_store import RagChunk, RagStore
from backend.util import chunk_text


def _hash_id(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="ignore")).hexdigest()


def decode_bytes_to_text(raw: bytes, *, max_chars: int = 3_000_000) -> Tuple[str, bool]:
    if not raw:
        return "", False
    if b"\x00" in raw[:20000]:
        return "", False
    try:
        t = raw.decode("utf-8", errors="ignore")
    except Exception:
        t = raw.decode("latin-1", errors="ignore")
    t = t[:max_chars]
    return t, True


def ingest_file_for_rag(
    *,
    rag_store: RagStore,
    relative_file_path: str,
    mime_type: str | None,
    file_bytes: bytes,
    embedding_fn,
    chunk_size: int,
    chunk_overlap: int,
) -> dict:
    text, ok = decode_bytes_to_text(file_bytes)
    if not ok or not text.strip():
        return {"embedded": False, "reason": "binary_or_empty_or_non_text"}

    chunks = chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
    if not chunks:
        return {"embedded": False, "reason": "no_chunks"}

    file_name = os.path.basename(relative_file_path)
    embedded_chunks: list[RagChunk] = []
    for idx, ch in enumerate(chunks):
        if not ch.strip():
            continue
        chunk_id = _hash_id(f"{relative_file_path}:{idx}:{_hash_id(ch)}")
        emb = embedding_fn(ch)
        embedded_chunks.append(
            RagChunk(
                chunk_id=chunk_id,
                file_path=relative_file_path,
                file_name=file_name,
                mime_type=mime_type,
                chunk_index=idx,
                text=ch,
                embedding=emb,
            )
        )

    rag_store.delete_file(relative_file_path)
    rag_store.upsert_chunks(embedded_chunks)
    return {"embedded": True, "chunks_indexed": len(embedded_chunks), "file": relative_file_path}

