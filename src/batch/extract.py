import json
import re
from pathlib import Path


def output_name_from_pair_key(pair_key: str, *, extension: str = ".json") -> str:
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"{pair_key}{ext}"


def extract_json(text: str) -> tuple[dict | list, str]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("Empty model response")

    candidates = [stripped]

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped, re.IGNORECASE)
    if fence:
        candidates.insert(0, fence.group(1).strip())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            return parsed, json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"
        except json.JSONDecodeError:
            continue

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        snippet = stripped[start : end + 1]
        parsed = json.loads(snippet)
        return parsed, json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"

    raise ValueError("No valid JSON found in model response")


def save_json_output(data: dict | list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
