from dataclasses import dataclass
import os

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    max_tokens: int
    max_workers: int


def get_settings() -> Settings:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Copy .env.example to .env.")

    return Settings(
        api_key=api_key,
        model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        max_tokens=int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096")),
        max_workers=int(os.getenv("ANTHROPIC_MAX_WORKERS", "3")),
    )
