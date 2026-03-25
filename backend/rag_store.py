import json
import os
import sqlite3
import time
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str
    file_path: str
    file_name: str
    mime_type: str | None
    chunk_index: int
    text: str
    embedding: np.ndarray


class RagStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_chunks (
                  chunk_id TEXT PRIMARY KEY,
                  file_path TEXT NOT NULL,
                  file_name TEXT NOT NULL,
                  mime_type TEXT,
                  chunk_index INTEGER NOT NULL,
                  text TEXT NOT NULL,
                  embedding BLOB NOT NULL,
                  created_at INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_chunks_file_path ON rag_chunks(file_path)")

    def delete_file(self, file_path: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM rag_chunks WHERE file_path = ?", (file_path,))

    def file_has_chunks(self, file_path: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("SELECT 1 FROM rag_chunks WHERE file_path = ? LIMIT 1", (file_path,))
            row = cur.fetchone()
            return row is not None

    def upsert_chunks(self, chunks: list[RagChunk]) -> None:
        if not chunks:
            return
        with self._connect() as conn:
            for c in chunks:
                conn.execute(
                    """
                    INSERT INTO rag_chunks (chunk_id, file_path, file_name, mime_type, chunk_index, text, embedding, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                      file_path=excluded.file_path,
                      file_name=excluded.file_name,
                      mime_type=excluded.mime_type,
                      chunk_index=excluded.chunk_index,
                      text=excluded.text,
                      embedding=excluded.embedding
                    """,
                    (
                        c.chunk_id,
                        c.file_path,
                        c.file_name,
                        c.mime_type,
                        c.chunk_index,
                        c.text,
                        c.embedding.astype(np.float32).tobytes(),
                        int(time.time()),
                    ),
                )

    def list_all(self) -> list[RagChunk]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT chunk_id, file_path, file_name, mime_type, chunk_index, text, embedding FROM rag_chunks"
            )
            rows = cur.fetchall()
        out: list[RagChunk] = []
        for (chunk_id, file_path, file_name, mime_type, chunk_index, text, emb_blob) in rows:
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            out.append(
                RagChunk(
                    chunk_id=chunk_id,
                    file_path=file_path,
                    file_name=file_name,
                    mime_type=mime_type,
                    chunk_index=int(chunk_index),
                    text=text,
                    embedding=emb,
                )
            )
        return out

    @staticmethod
    def _cosine_similarity(v1: np.ndarray, v2: np.ndarray) -> float:
        if v1 is None or v2 is None:
            return 0.0
        if v1.shape != v2.shape:
            return 0.0
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 == 0.0 or n2 == 0.0:
            return 0.0
        return float(np.dot(v1, v2) / (n1 * n2))

    def search(
        self,
        *,
        query_embedding: np.ndarray,
        file_paths: list[str] | None,
        top_k: int,
        threshold: float | None = None,
    ) -> list[tuple[RagChunk, float]]:
        top_k = max(1, int(top_k))
        threshold = threshold if threshold is not None else -1.0

        with self._connect() as conn:
            if file_paths:
                placeholders = ",".join(["?"] * len(file_paths))
                cur = conn.execute(
                    f"""
                    SELECT chunk_id, file_path, file_name, mime_type, chunk_index, text, embedding
                    FROM rag_chunks
                    WHERE file_path IN ({placeholders})
                    """,
                    tuple(file_paths),
                )
            else:
                cur = conn.execute(
                    """
                    SELECT chunk_id, file_path, file_name, mime_type, chunk_index, text, embedding
                    FROM rag_chunks
                    """
                )

            rows = cur.fetchall()

        scored: list[tuple[RagChunk, float]] = []
        for (chunk_id, file_path, file_name, mime_type, chunk_index, text, emb_blob) in rows:
            emb = np.frombuffer(emb_blob, dtype=np.float32)
            chunk = RagChunk(
                chunk_id=chunk_id,
                file_path=file_path,
                file_name=file_name,
                mime_type=mime_type,
                chunk_index=int(chunk_index),
                text=text,
                embedding=emb,
            )
            sim = self._cosine_similarity(query_embedding, emb)
            if sim >= threshold:
                scored.append((chunk, sim))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

