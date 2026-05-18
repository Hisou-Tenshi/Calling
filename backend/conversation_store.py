import json
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any

import requests

from backend.util import ensure_dir

logger = logging.getLogger("calling.conversation_store")


@dataclass
class Conversation:
    conversation_id: str
    title: str
    updated_at: float
    messages: list[dict[str, Any]]
    uploaded_files: list[str]
    owner: str = "local"


def _normalize_messages(messages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        item: dict[str, Any] = {"role": role, "content": str(m.get("content") or "")}
        if role == "assistant":
            if m.get("model"):
                item["model"] = str(m.get("model"))
            if m.get("thinking"):
                item["thinking"] = str(m.get("thinking"))
            if m.get("interrupted"):
                item["interrupted"] = bool(m.get("interrupted"))
            if m.get("failed"):
                item["failed"] = bool(m.get("failed"))
        out.append(item)
    return out


def _auto_title(messages: list[dict[str, Any]], current: str) -> str:
    if current and current != "New chat":
        return current
    for m in messages:
        if m.get("role") == "user":
            first_user = (m.get("content") or "").strip()
            if first_user:
                return (first_user[:36] + ("..." if len(first_user) > 36 else "")).strip() or "New chat"
    return current or "New chat"


class ConversationStore:
    """Conversation persistence with optional Upstash Redis; falls back to local JSON file."""

    def __init__(
        self,
        db_path: str,
        *,
        upstash_rest_url: str | None = None,
        upstash_rest_token: str | None = None,
        redis_key_prefix: str = "calling:conversations",
    ):
        self.db_path = db_path
        self._redis_key_prefix = redis_key_prefix.rstrip(":")
        self._redis_configured = bool(upstash_rest_url and upstash_rest_token)
        self._redis_disabled = False
        self._upstash_url = (upstash_rest_url or "").rstrip("/")
        self._upstash_token = upstash_rest_token or ""
        self._redis_cache: dict[str, dict[str, Conversation]] = {}
        ensure_dir(os.path.dirname(db_path))
        self._data: dict[str, Conversation] = self._load_file()

    @property
    def _use_redis(self) -> bool:
        return self._redis_configured and not self._redis_disabled

    def _disable_redis(self, reason: Exception | str) -> None:
        if self._redis_disabled:
            return
        self._redis_disabled = True
        self._redis_cache.clear()
        logger.warning(
            "Upstash Redis unavailable (%s). Conversation storage will use local file: %s",
            reason,
            self.db_path,
        )

    def _owner_key(self, owner: str | None) -> str:
        o = (owner or "local").strip() or "local"
        return o.replace(":", "_")

    def _redis_key(self, owner: str | None) -> str:
        return f"{self._redis_key_prefix}:{self._owner_key(owner)}"

    def _redis_call(self, command: list[str]) -> Any:
        if not self._use_redis:
            return None
        url = f"{self._upstash_url}/pipeline"
        headers = {
            "Authorization": f"Bearer {self._upstash_token}",
            "Content-Type": "application/json",
        }
        payload = [{"command": command}]
        try:
            r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=8)
            r.raise_for_status()
            data = r.json() or []
            if not data:
                return None
            return (data[0] or {}).get("result")
        except requests.RequestException as e:
            self._disable_redis(e)
            return None

    def _load_owner_from_redis(self, owner: str | None) -> dict[str, Conversation]:
        raw = self._redis_call(["GET", self._redis_key(owner)])
        if not raw:
            return {}
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="ignore")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw) or {}
            except Exception:
                parsed = {}
        elif isinstance(raw, dict):
            parsed = raw
        else:
            parsed = {}
        return self._parse_payload(parsed, owner)

    def _save_owner_to_redis(self, owner: str | None, data: dict[str, Conversation]) -> None:
        if not self._use_redis:
            return
        payload: dict[str, Any] = {}
        for cid, conv in data.items():
            payload[cid] = {
                "title": conv.title,
                "updated_at": conv.updated_at,
                "messages": conv.messages,
                "uploaded_files": conv.uploaded_files,
                "owner": conv.owner,
            }
        encoded = json.dumps(payload, ensure_ascii=False)
        self._redis_call(["SET", self._redis_key(owner), encoded])

    def _parse_payload(self, raw: dict[str, Any], owner: str | None) -> dict[str, Conversation]:
        owner_norm = (owner or "local").strip() or "local"
        data: dict[str, Conversation] = {}
        for cid, c in (raw or {}).items():
            if not isinstance(c, dict):
                continue
            conv_owner = str(c.get("owner") or owner_norm)
            data[cid] = Conversation(
                conversation_id=cid,
                title=str(c.get("title") or "Untitled"),
                updated_at=float(c.get("updated_at") or 0.0),
                messages=_normalize_messages(c.get("messages")),
                uploaded_files=list(c.get("uploaded_files") or []),
                owner=conv_owner,
            )
        return data

    def _load_file(self) -> dict[str, Conversation]:
        if not os.path.exists(self.db_path):
            return {}
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                raw = json.load(f) or {}
        except Exception:
            raw = {}
        return self._parse_payload(raw, None)

    def _save_file(self) -> None:
        payload: dict[str, Any] = {}
        for cid, conv in self._data.items():
            payload[cid] = {
                "title": conv.title,
                "updated_at": conv.updated_at,
                "messages": conv.messages,
                "uploaded_files": conv.uploaded_files,
                "owner": conv.owner,
            }
        tmp = self.db_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.db_path)

    def _owner_data_file(self, owner: str | None) -> dict[str, Conversation]:
        owner_norm = (owner or "local").strip() or "local"
        return {cid: c for cid, c in self._data.items() if c.owner == owner_norm}

    def _owner_data(self, owner: str | None) -> dict[str, Conversation]:
        if not self._use_redis:
            return self._owner_data_file(owner)
        cache_key = self._owner_key(owner)
        if cache_key not in self._redis_cache:
            self._redis_cache[cache_key] = self._load_owner_from_redis(owner)
            if not self._use_redis:
                return self._owner_data_file(owner)
        return self._redis_cache[cache_key]

    def _commit_owner(self, owner: str | None, data: dict[str, Conversation]) -> None:
        owner_norm = (owner or "local").strip() or "local"

        if self._use_redis:
            cache_key = self._owner_key(owner)
            self._redis_cache[cache_key] = data
            self._save_owner_to_redis(owner, data)

        # Always mirror to local file so chat works when Redis is down or on single-node deploy.
        for cid in list(self._data.keys()):
            if self._data[cid].owner == owner_norm and cid not in data:
                del self._data[cid]
        for cid, conv in data.items():
            self._data[cid] = conv
        try:
            self._save_file()
        except Exception as e:
            logger.error("Failed to save conversations to %s: %s", self.db_path, e)

    def list_conversations(self, owner: str | None = None) -> list[dict[str, Any]]:
        data = self._owner_data(owner)
        out = []
        for conv in data.values():
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

    def get(self, conversation_id: str, owner: str | None = None) -> Conversation:
        data = self._owner_data(owner)
        if conversation_id not in data:
            raise KeyError("conversation not found")
        return data[conversation_id]

    def create_new(self, owner: str | None = None) -> Conversation:
        owner_norm = (owner or "local").strip() or "local"
        cid = uuid.uuid4().hex
        conv = Conversation(
            conversation_id=cid,
            title="New chat",
            updated_at=time.time(),
            messages=[],
            uploaded_files=[],
            owner=owner_norm,
        )
        data = self._owner_data(owner)
        data[cid] = conv
        self._commit_owner(owner, data)
        return conv

    def upsert_messages(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        owner: str | None = None,
    ) -> Conversation:
        owner_norm = (owner or "local").strip() or "local"
        data = self._owner_data(owner)
        if conversation_id not in data:
            data[conversation_id] = Conversation(
                conversation_id=conversation_id,
                title="New chat",
                updated_at=time.time(),
                messages=[],
                uploaded_files=[],
                owner=owner_norm,
            )
        conv = data[conversation_id]
        conv.messages = _normalize_messages(messages)
        conv.title = _auto_title(conv.messages, conv.title)
        conv.updated_at = time.time()
        self._commit_owner(owner, data)
        return conv

    def set_uploaded_files(
        self,
        conversation_id: str,
        uploaded_files: list[str],
        owner: str | None = None,
    ) -> Conversation:
        owner_norm = (owner or "local").strip() or "local"
        data = self._owner_data(owner)
        if conversation_id not in data:
            data[conversation_id] = Conversation(
                conversation_id=conversation_id,
                title="New chat",
                updated_at=time.time(),
                messages=[],
                uploaded_files=[],
                owner=owner_norm,
            )
        conv = data[conversation_id]
        conv.uploaded_files = list(uploaded_files or [])
        conv.updated_at = time.time()
        self._commit_owner(owner, data)
        return conv

    def delete_conversation(self, conversation_id: str, owner: str | None = None) -> bool:
        data = self._owner_data(owner)
        if conversation_id in data:
            del data[conversation_id]
            self._commit_owner(owner, data)
            return True
        return False

    def export_bundle(
        self,
        owner: str | None = None,
        *,
        conversation_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        owner_norm = (owner or "local").strip() or "local"
        data = self._owner_data(owner)
        items: list[dict[str, Any]] = []
        wanted = set(conversation_ids or [])
        for conv in data.values():
            if wanted and conv.conversation_id not in wanted:
                continue
            items.append(
                {
                    "conversation_id": conv.conversation_id,
                    "title": conv.title,
                    "updated_at": conv.updated_at,
                    "messages": list(conv.messages),
                    "uploaded_files": list(conv.uploaded_files),
                    "owner": conv.owner,
                }
            )
        items.sort(key=lambda x: float(x.get("updated_at") or 0.0), reverse=True)
        return {
            "format": "calling-conversations",
            "version": 1,
            "exported_at": time.time(),
            "owner": owner_norm,
            "conversations": items,
        }

    def import_bundle(
        self,
        bundle: dict[str, Any],
        owner: str | None = None,
        *,
        mode: str = "merge",
    ) -> dict[str, Any]:
        owner_norm = (owner or "local").strip() or "local"
        mode_norm = (mode or "merge").strip().lower()
        if mode_norm not in ("merge", "replace", "import_as_new"):
            raise ValueError("mode must be merge, replace, or import_as_new")

        raw_items = bundle.get("conversations")
        if not isinstance(raw_items, list):
            raise ValueError("conversations must be a list")

        data = self._owner_data(owner)
        if mode_norm == "replace":
            data = {}

        imported = 0
        skipped = 0
        id_map: dict[str, str] = {}

        for item in raw_items:
            if not isinstance(item, dict):
                skipped += 1
                continue
            src_id = str(item.get("conversation_id") or "").strip()
            messages = _normalize_messages(item.get("messages"))
            uploaded_files = list(item.get("uploaded_files") or [])
            title = str(item.get("title") or "Imported chat")
            updated_at = float(item.get("updated_at") or time.time())

            if mode_norm == "import_as_new" or not src_id:
                cid = uuid.uuid4().hex
            else:
                cid = src_id

            conv = Conversation(
                conversation_id=cid,
                title=title,
                updated_at=updated_at,
                messages=messages,
                uploaded_files=uploaded_files,
                owner=owner_norm,
            )
            conv.title = _auto_title(conv.messages, conv.title)
            data[cid] = conv
            if src_id:
                id_map[src_id] = cid
            imported += 1

        self._commit_owner(owner, data)
        return {
            "imported": imported,
            "skipped": skipped,
            "mode": mode_norm,
            "id_map": id_map,
        }
