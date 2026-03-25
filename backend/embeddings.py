import hashlib
import numpy as np
from google import genai
from google.genai import types


def _stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def make_gemini_embedding_fn(*, gemini_api_key: str | None):
    if not gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    client = genai.Client(api_key=gemini_api_key)
    cache: dict[str, np.ndarray] = {}
    models_to_try = ["models/gemini-embedding-001", "models/embedding-001"]

    def embed(text: str) -> np.ndarray:
        if not text:
            return np.zeros(768, dtype=np.float32)
        h = _stable_hash(text)
        if h in cache:
            return cache[h]

        last_err: Exception | None = None
        for model in models_to_try:
            try:
                result = client.models.embed_content(
                    model=model,
                    contents=text,
                    config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
                )
                vec = np.array(result.embeddings[0].values, dtype=np.float32)
                cache[h] = vec
                return vec
            except Exception as e:
                last_err = e
                continue

        # If all models fail, keep deterministic-ish empty vec
        # (so RAG retrieval is simply skipped rather than crashing).
        if last_err:
            # No logging here to keep module minimal.
            pass
        return np.zeros(768, dtype=np.float32)

    return embed

