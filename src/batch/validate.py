import os

import anthropic
from dotenv import load_dotenv

from src.env_file import ENV_PATH, KEY


def validate_api_key(api_key: str | None = None, model: str | None = None) -> dict:
    load_dotenv(ENV_PATH, override=True)
    key = (api_key or os.getenv(KEY, "")).strip()
    if not key or key == "your_api_key_here":
        return {"valid": False, "error": "API key is not set"}

    model_id = model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    try:
        client = anthropic.Anthropic(api_key=key, timeout=30.0)
        client.messages.create(
            model=model_id,
            max_tokens=5,
            messages=[{"role": "user", "content": "hi"}],
        )
        return {"valid": True, "model": model_id}
    except anthropic.AuthenticationError:
        return {"valid": False, "error": "Invalid API key — paste a current key from console.anthropic.com"}
    except anthropic.APIConnectionError:
        return {"valid": False, "error": "Could not reach Anthropic — check internet or VPN"}
    except anthropic.APIStatusError as exc:
        return {"valid": False, "error": f"Anthropic API error ({exc.status_code})"}
    except Exception as exc:
        return {"valid": False, "error": str(exc)}
