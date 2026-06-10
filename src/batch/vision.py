import base64
import mimetypes
from pathlib import Path

import anthropic

from src.config import Settings, get_settings

TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


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


def _text_block(path: Path) -> dict:
    return {"type": "text", "text": path.read_text(encoding="utf-8")}


def build_content_blocks(
    static_files: list[Path],
    pair_files: list[Path],
    *,
    preamble: str | None = None,
) -> list[dict]:
    blocks: list[dict] = []

    if preamble:
        blocks.append({"type": "text", "text": preamble})

    for path in static_files:
        suffix = path.suffix.lower()
        if suffix in TEXT_SUFFIXES:
            blocks.append(_text_block(path))
        elif suffix in IMAGE_SUFFIXES:
            blocks.append(_image_block(path))
        else:
            blocks.append(
                {
                    "type": "text",
                    "text": f"[Attached file: {path.name}]",
                }
            )
            blocks.append(_image_block(path))

    for path in pair_files:
        blocks.append({"type": "text", "text": f"Render: {path.name}"})
        blocks.append(_image_block(path))

    return blocks


def vision_message(
    static_files: list[Path],
    pair_files: list[Path],
    *,
    preamble: str | None = None,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    settings: Settings | None = None,
) -> str:
    cfg = settings or get_settings()
    client = anthropic.Anthropic(api_key=cfg.api_key)

    content = build_content_blocks(static_files, pair_files, preamble=preamble)
    response = client.messages.create(
        model=model or cfg.model,
        max_tokens=max_tokens or cfg.max_tokens,
        system=system or anthropic.NOT_GIVEN,
        messages=[{"role": "user", "content": content}],
    )

    parts = [block.text for block in response.content if block.type == "text"]
    return "\n".join(parts)
