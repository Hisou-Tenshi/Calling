import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    project_root: str
    data_dir: str
    uploads_dir: str
    rag_db_path: str

    default_chat_model: str
    gemini_api_key: str | None
    claude_api_key: str | None
    grok_api_key: str | None
    tavily_key: str | None

    # Optional Claude proxies (same env var names as Tenshi; may be empty)
    claude_proxy_key: str | None
    claude_proxy_base_url: str | None
    claude_proxy_key_2: str | None
    claude_proxy_base_url_2: str | None

    host: str
    port: int

    rag_chunk_size: int
    rag_chunk_overlap: int
    rag_top_k: int

    web_search_max_results: int


def load_settings() -> Settings:
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # Load local .env (override is desired for local dev).
    load_dotenv()
    env_path = os.path.join(project_root, ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=True)

    # If the official CLAUDE key is used, but an external ANTHROPIC_BASE_URL is set
    # (e.g. a proxy endpoint that expects a different key format),
    # clear it so the SDK uses the official anthropic endpoint.
    _claude_key = os.getenv("CLAUDE_API_KEY", "")
    _anthropic_base = os.getenv("ANTHROPIC_BASE_URL", "")
    if _claude_key.startswith("sk-ant-") and _anthropic_base and "anthropic.com" not in _anthropic_base:
        os.environ.pop("ANTHROPIC_BASE_URL", None)

    data_dir = os.path.join(project_root, "data")
    uploads_dir = os.path.join(data_dir, "uploads")
    rag_db_path = os.path.join(data_dir, "rag.sqlite3")

    return Settings(
        project_root=project_root,
        data_dir=data_dir,
        uploads_dir=uploads_dir,
        rag_db_path=rag_db_path,
        default_chat_model=os.getenv("DEFAULT_CHAT_MODEL") or "claude-3-5-sonnet-20241022",
        gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
        claude_api_key=os.getenv("CLAUDE_API_KEY") or None,
        grok_api_key=os.getenv("GROK_API_KEY") or None,
        tavily_key=os.getenv("TAVILY_KEY") or None,
        claude_proxy_key=os.getenv("CLAUDE_PROXY_KEY") or None,
        claude_proxy_base_url=os.getenv("CLAUDE_PROXY_BASE_URL") or None,
        claude_proxy_key_2=os.getenv("CLAUDE_PROXY_KEY_2") or None,
        claude_proxy_base_url_2=os.getenv("CLAUDE_PROXY_BASE_URL_2") or None,
        host=os.getenv("HOST") or "127.0.0.1",
        port=int(os.getenv("PORT") or 8000),
        rag_chunk_size=int(os.getenv("RAG_CHUNK_SIZE") or 1200),
        rag_chunk_overlap=int(os.getenv("RAG_CHUNK_OVERLAP") or 150),
        rag_top_k=int(os.getenv("RAG_TOP_K") or 5),
        web_search_max_results=int(os.getenv("WEB_SEARCH_MAX_RESULTS") or 5),
    )

