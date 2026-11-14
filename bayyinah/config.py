"""Configuration. One place, environment-driven, no magic."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # storage
    db_path: Path = field(default_factory=lambda: REPO_ROOT / "var" / "bayyinah.db")
    # security
    api_key: str | None = None
    rate_limit_per_min: int = 60
    max_upload_bytes: int = 5 * 1024 * 1024
    # models
    llm_base_url: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    embedder: str = "hashing"          # hashing | bge-m3
    # behaviour
    min_evidence: float = 0.25
    min_term_idf: float = 0.85
    top_k: int = 5
    request_timeout_s: int = 60
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        db = os.getenv("BAYYINAH_DB_PATH")
        return cls(
            db_path=Path(db) if db else REPO_ROOT / "var" / "bayyinah.db",
            api_key=os.getenv("BAYYINAH_API_KEY") or None,
            rate_limit_per_min=int(os.getenv("BAYYINAH_RATE_LIMIT", "60")),
            max_upload_bytes=int(os.getenv("BAYYINAH_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024))),
            llm_base_url=os.getenv("BAYYINAH_LLM_BASE_URL") or None,
            llm_model=os.getenv("BAYYINAH_LLM_MODEL", "gpt-4o-mini"),
            llm_api_key=os.getenv("BAYYINAH_LLM_API_KEY", ""),
            embedder=os.getenv("BAYYINAH_EMBEDDER", "hashing"),
            min_evidence=float(os.getenv("BAYYINAH_MIN_EVIDENCE", "0.25")),
            min_term_idf=float(os.getenv("BAYYINAH_MIN_TERM_IDF", "0.85")),
            top_k=int(os.getenv("BAYYINAH_TOP_K", "5")),
            log_level=os.getenv("BAYYINAH_LOG_LEVEL", "INFO"),
        )

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_base_url or self.llm_api_key)


def ensure_dirs(settings: Settings) -> None:
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
