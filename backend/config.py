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

    # ----------------------------
    # Auth / Anti-abuse (Vercel-friendly)
    # ----------------------------
    # Modes: none | apikey | password | github
    auth_mode: str
    auth_secret: str | None

    # Shared API key (for header-based access)
    api_key: str | None

    # Password mode (simple shared password -> session cookie)
    auth_password: str | None

    # GitHub OAuth
    github_client_id: str | None
    github_client_secret: str | None
    github_allowed_users: str | None  # comma-separated logins
    github_allowed_orgs: str | None   # comma-separated orgs

    # Rate limit
    rate_limit_per_ip_per_min: int
    rate_limit_per_user_per_min: int
    upstash_redis_rest_url: str | None
    upstash_redis_rest_token: str | None


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

        auth_mode=(os.getenv("CALLING_AUTH_MODE") or "none").strip().lower(),
        auth_secret=(os.getenv("CALLING_AUTH_SECRET") or None),
        api_key=(os.getenv("CALLING_API_KEY") or None),
        auth_password=(os.getenv("CALLING_PASSWORD") or None),

        github_client_id=(os.getenv("GITHUB_CLIENT_ID") or None),
        github_client_secret=(os.getenv("GITHUB_CLIENT_SECRET") or None),
        github_allowed_users=(os.getenv("GITHUB_ALLOWED_USERS") or None),
        github_allowed_orgs=(os.getenv("GITHUB_ALLOWED_ORGS") or None),

        rate_limit_per_ip_per_min=int(os.getenv("CALLING_RL_IP_PER_MIN") or 60),
        rate_limit_per_user_per_min=int(os.getenv("CALLING_RL_USER_PER_MIN") or 120),
        upstash_redis_rest_url=(os.getenv("UPSTASH_REDIS_REST_URL") or None),
        upstash_redis_rest_token=(os.getenv("UPSTASH_REDIS_REST_TOKEN") or None),
    )

