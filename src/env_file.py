import os
import re
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
KEY = "ANTHROPIC_API_KEY"


def mask_key(key: str) -> str:
    if len(key) <= 8:
        return "••••"
    return f"{key[:7]}…{key[-4:]}"


def api_key_status() -> dict:
    load_dotenv(ENV_PATH, override=True)
    key = os.getenv(KEY, "")
    return {"configured": bool(key and key != "your_api_key_here"), "masked": mask_key(key) if key else None}


def save_api_key(api_key: str) -> None:
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("API key is empty")

    lines: list[str] = []
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()

    found = False
    out: list[str] = []
    for line in lines:
        if re.match(rf"^{KEY}=", line):
            out.append(f"{KEY}={api_key}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{KEY}={api_key}")

    ENV_PATH.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    load_dotenv(ENV_PATH, override=True)
