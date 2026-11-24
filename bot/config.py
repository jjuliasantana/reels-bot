"""Carrega config.yaml + variáveis de ambiente. Segredos nunca ficam no YAML."""
import os
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("BOT_STATE_DIR", ROOT / "state"))
OUTPUT_DIR = Path(os.environ.get("BOT_OUTPUT_DIR", ROOT / "output"))
STATE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


class Secrets:
    """Acesso centralizado às credenciais (todas opcionais; o bot degrada com dados simulados)."""

    @property
    def youtube(self): return env("YOUTUBE_API_KEY")
    @property
    def gemini(self): return env("GEMINI_API_KEY")
    @property
    def anthropic(self): return env("ANTHROPIC_API_KEY")
    @property
    def openai(self): return env("OPENAI_API_KEY")
    @property
    def ig_token(self): return env("IG_ACCESS_TOKEN")
    @property
    def ig_user_id(self): return env("IG_USER_ID")
    @property
    def buffer_token(self): return env("BUFFER_ACCESS_TOKEN")
    @property
    def buffer_profile(self): return env("BUFFER_PROFILE_ID")
    @property
    def github_token(self): return env("GITHUB_TOKEN")
    @property
    def github_repo(self): return env("GITHUB_REPOSITORY")  # owner/repo
    @property
    def telegram_token(self): return env("TELEGRAM_BOT_TOKEN")
    @property
    def telegram_chat(self): return env("TELEGRAM_CHAT_ID")
    @property
    def webhook(self): return env("ALERT_WEBHOOK_URL")
    @property
    def publish_enabled_env(self): return (env("PUBLISH_ENABLED", "false") or "").lower() == "true"


SECRETS = Secrets()
