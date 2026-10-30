"""Settings read from environment variables (or a .env file)."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

DB_PATH = os.getenv("FAULTLINE_DB", str(ROOT / "data" / "faultline.db"))

# "rules" = fully offline, deterministic. "llm" = use Claude for the investigator & fixer.
MODE = os.getenv("FAULTLINE_MODE", "rules")
CLAUDE_MODEL = os.getenv("FAULTLINE_MODEL", "claude-opus-5-5")

LANGFUSE_HOST = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")

LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "default")


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def effective_mode() -> str:
    if MODE == "llm" and llm_available():
        return "llm"
    return "rules"
