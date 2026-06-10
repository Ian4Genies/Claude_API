# Claude API Starter

Minimal Python starter for Anthropic Claude API calls.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -e .
copy .env.example .env
```

Set `ANTHROPIC_API_KEY` in `.env`.

## Usage

```bash
python examples/basic_chat.py
python examples/streaming.py
```

```python
from src import message, stream_message

text = message("Summarize REST in one line.")
for chunk in stream_message("List 3 Python tips."):
    print(chunk, end="")
```

## Config

| Variable | Default |
|----------|---------|
| `ANTHROPIC_API_KEY` | required |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` |
| `ANTHROPIC_MAX_TOKENS` | `1024` |
