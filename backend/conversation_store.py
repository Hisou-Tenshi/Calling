import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

from backend.util import ensure_dir


@dataclass
class Conversation:
    conversation_id: str
    title: str
    updated_at: float
    messages: list[dict[str, Any]]
    uploaded_files: list[str]


class ConversationStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        ensure_dir(os.path.dirname(db_path))
        self._data: dict[str, Conversation] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.db_path):
            self._data = {}
            return
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                raw = json.load(f) or {}
        except Exception:
            raw = {}
        data: dict[str, Conversation] = {}
        for cid, c in (raw or {}).items():
            if not isinstance(c, dict):
                continue
            data[cid] = Conversation(
                conversation_id=cid,
                title=str(c.get("title") or "Untitled"),
                updated_at=float(c.get("updated_at") or 0.0),
                messages=list(c.get("messages") or []),
                uploaded_files=list(c.get("uploaded_files") or []),
            )
        self._data = data

    def _save(self) -> None:
        tmp = self.db_path + ".tmp"
        payload: dict[str, Any] = {}
        for cid, conv in self._data.items():
            payload[cid] = {
                "title": conv.title,
                "updated_at": conv.updated_at,
                "messages": conv.messages,
                "uploaded_files": conv.uploaded_files,
            }
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.db_path)

    def list_conversations(self) -> list[dict[str, Any]]:
        out = []
        for conv in self._data.values():
            out.append(
                {
                    "conversation_id": conv.conversation_id,
                    "title": conv.title,
                    "updated_at": conv.updated_at,
                    "message_count": len(conv.messages),
                    "uploaded_count": len(conv.uploaded_files),
                }
            )
        out.sort(key=lambda x: x["updated_at"], reverse=True)
        return out

    def get(self, conversation_id: str) -> Conversation:
        if conversation_id not in self._data:
            raise KeyError("conversation not found")
        return self._data[conversation_id]

    def create_new(self) -> Conversation:
        cid = uuid.uuid4().hex
        conv = Conversation(
            conversation_id=cid,
            title="New chat",
            updated_at=time.time(),
            messages=[],
            uploaded_files=[],
        )
        self._data[cid] = conv
        self._save()
        return conv

    def upsert_messages(self, conversation_id: str, messages: list[dict[str, Any]]) -> Conversation:
        if conversation_id not in self._data:
            # Auto-create if missing
            self._data[conversation_id] = Conversation(
                conversation_id=conversation_id,
                title="New chat",
                updated_at=time.time(),
                messages=[],
                uploaded_files=[],
            )
        conv = self._data[conversation_id]
        conv.messages = messages or []
        # Auto-title on first user message
        if conv.title == "New chat":
            first_user = None
            for m in conv.messages:
                if m.get("role") == "user":
                    first_user = (m.get("content") or "").strip()
                    break
            if first_user:
                conv.title = (first_user[:36] + ("..." if len(first_user) > 36 else "")).strip() or "New chat"
        conv.updated_at = time.time()
        self._save()
        return conv

    def set_uploaded_files(self, conversation_id: str, uploaded_files: list[str]) -> Conversation:
        if conversation_id not in self._data:
            self._data[conversation_id] = Conversation(
                conversation_id=conversation_id,
                title="New chat",
                updated_at=time.time(),
                messages=[],
                uploaded_files=[],
            )
        conv = self._data[conversation_id]
        conv.uploaded_files = uploaded_files or []
        conv.updated_at = time.time()
        self._save()
        return conv

    def delete_conversation(self, conversation_id: str) -> bool:
        if conversation_id in self._data:
            del self._data[conversation_id]
            self._save()
            return True
        return False

