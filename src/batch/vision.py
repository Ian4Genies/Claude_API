import base64
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic
from anthropic import APIConnectionError, APITimeoutError, AuthenticationError

from src.config import Settings, get_settings

TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_RETRIES = 5
REQUEST_TIMEOUT_S = 600.0


@dataclass
class VisionResult:
    text: str
    usage: dict


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def _image_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": _media_type(path),
            "data": data,
        },
    }


def _text_block(text: str) -> dict:
    return {"type": "text", "text": text}


def build_content_blocks(
    static_files: list[Path],
    pair_files: list[Path],
    *,
    preamble: str | None = None,
    cache_static: bool = True,
) -> list[dict]:
    blocks: list[dict] = []

    if preamble:
        blocks.append(_text_block(preamble))

    for path in static_files:
        suffix = path.suffix.lower()
        if suffix in TEXT_SUFFIXES:
            blocks.append(_text_block(path.read_text(encoding="utf-8")))
        elif suffix in IMAGE_SUFFIXES:
            blocks.append(_image_block(path))
        else:
            blocks.append(_text_block(f"[Attached file: {path.name}]"))
            blocks.append(_image_block(path))

    if cache_static and blocks:
        blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}

    for path in pair_files:
        blocks.append(_text_block(f"Render: {path.name}"))
        blocks.append(_image_block(path))

    return blocks


def _usage_dict(response) -> dict:
    u = response.usage
    return {
        "input_tokens": u.input_tokens,
        "output_tokens": u.output_tokens,
        "cache_creation_input_tokens": getattr(u, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0) or 0,
    }


def vision_message(
    static_files: list[Path],
    pair_files: list[Path],
    *,
    preamble: str | None = None,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    settings: Settings | None = None,
) -> VisionResult:
    cfg = settings or get_settings()
    client = anthropic.Anthropic(api_key=cfg.api_key, timeout=REQUEST_TIMEOUT_S)
    content = build_content_blocks(static_files, pair_files, preamble=preamble)
    model_id = model or cfg.model

    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = client.messages.create(
                model=model_id,
                max_tokens=max_tokens or cfg.max_tokens,
                system=system or anthropic.NOT_GIVEN,
                messages=[{"role": "user", "content": content}],
            )
            parts = [b.text for b in response.content if b.type == "text"]
            return VisionResult(text="\n".join(parts), usage=_usage_dict(response))
        except AuthenticationError as exc:
            raise RuntimeError(
                "Invalid API key — open Settings and paste a current key from console.anthropic.com"
            ) from exc
        except (APIConnectionError, APITimeoutError) as exc:
            last_exc = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(min(2 ** attempt, 30))
                continue
            raise RuntimeError(
                "Network connection to Anthropic failed — check internet/VPN, then retry"
            ) from exc
        except anthropic.RateLimitError as exc:
            last_exc = exc
            time.sleep(min(2 ** attempt, 30))
        except anthropic.APIStatusError as exc:
            body = getattr(exc, "body", None) or str(exc)
            if isinstance(body, str) and "<html" in body.lower():
                last_exc = exc
                if attempt < MAX_RETRIES - 1:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise RuntimeError("Anthropic API gateway error (502) — retry shortly") from exc
            if exc.status_code in (529, 503, 502) and attempt < MAX_RETRIES - 1:
                last_exc = exc
                time.sleep(min(2 ** attempt, 30))
                continue
            raise

    raise last_exc or RuntimeError("API call failed")
