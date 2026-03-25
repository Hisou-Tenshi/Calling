import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
from openai import OpenAI


def _stable_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


@dataclass
class LlmClient:
    openai: OpenAI
    chat_model: str
    embedding_model: str | None
    _embedding_cache: dict[str, np.ndarray]

    @classmethod
    def create(
        cls,
        *,
        chat_model: str,
        embedding_model: str | None,
        api_key: str | None,
        base_url: str | None,
    ) -> "LlmClient":
        # OpenAI client requires a key string at init time.
        # We still allow the app to start with a dummy key so GUI/API routes work.
        # Real calls will fail with auth errors until you set OPENAI_API_KEY properly.
        safe_key = api_key or "DUMMY_KEY_FOR_DEV_ONLY"
        openai_client = OpenAI(api_key=safe_key, base_url=base_url)
        return cls(
            openai=openai_client,
            chat_model=chat_model,
            embedding_model=embedding_model,
            _embedding_cache={},
        )

    def embed(self, text: str) -> np.ndarray:
        if not self.embedding_model:
            raise RuntimeError("EMBEDDING_MODEL is not configured.")
        key = _stable_hash(text)
        cached = self._embedding_cache.get(key)
        if cached is not None:
            return cached
        emb = self.openai.embeddings.create(model=self.embedding_model, input=text)
        values = emb.data[0].embedding
        vec = np.array(values, dtype=np.float32)
        self._embedding_cache[key] = vec
        return vec

    def chat_completion_with_tools(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ):
        return self.openai.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )


def tool_result_as_content(result_obj: Any) -> str:
    if isinstance(result_obj, str):
        return result_obj
    return json.dumps(result_obj, ensure_ascii=False)

