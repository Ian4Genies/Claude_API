from collections.abc import Iterator
from typing import Any

import anthropic

from .config import Settings, get_settings


def create_client(settings: Settings | None = None) -> anthropic.Anthropic:
    cfg = settings or get_settings()
    return anthropic.Anthropic(api_key=cfg.api_key)


def message(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    settings: Settings | None = None,
    **kwargs: Any,
) -> str:
    cfg = settings or get_settings()
    client = create_client(cfg)

    response = client.messages.create(
        model=model or cfg.model,
        max_tokens=max_tokens or cfg.max_tokens,
        system=system or anthropic.NOT_GIVEN,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    )

    return response.content[0].text


def stream_message(
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int | None = None,
    settings: Settings | None = None,
    **kwargs: Any,
) -> Iterator[str]:
    cfg = settings or get_settings()
    client = create_client(cfg)

    with client.messages.stream(
        model=model or cfg.model,
        max_tokens=max_tokens or cfg.max_tokens,
        system=system or anthropic.NOT_GIVEN,
        messages=[{"role": "user", "content": prompt}],
        **kwargs,
    ) as stream:
        for text in stream.text_stream:
            yield text
