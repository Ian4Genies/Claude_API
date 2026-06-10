import time
from dataclasses import dataclass, field
from pathlib import Path

from src.batch.extract import extract_json, output_name_from_pair_key, save_json_output
from src.batch.pairing import PairMatch, scan_pair_folders
from src.batch.recipe import BatchRecipe
from src.batch.vision import vision_message
from src.config import Settings, get_settings


@dataclass
class RunItemResult:
    pair_key: str
    status: str
    output_path: str | None = None
    error: str | None = None
    duration_s: float = 0.0
    skipped: bool = False


@dataclass
class BatchRunResult:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    items: list[RunItemResult] = field(default_factory=list)


class BatchRunner:
    def __init__(
        self,
        recipe: BatchRecipe,
        *,
        base_dir: Path | None = None,
        settings: Settings | None = None,
        limit: int | None = None,
        pair_keys: list[str] | None = None,
    ) -> None:
        self.recipe = recipe
        self.base_dir = base_dir or Path.cwd()
        self._settings = settings
        self.limit = limit
        self.pair_keys = set(pair_keys) if pair_keys else None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _output_path(self, pair_key: str) -> Path:
        name = self.recipe.output_naming.format(pair_key=pair_key)
        return self.recipe.resolved_output_dir(self.base_dir) / name

    def _resolve_pairs(self) -> list[PairMatch]:
        if not self.recipe.pair_folders:
            raise ValueError("Recipe has no pair_folders configured")

        cfg = self.recipe.pair_folders
        left = Path(cfg.left)
        right = Path(cfg.right)
        if not left.is_absolute():
            left = self.base_dir / left
        if not right.is_absolute():
            right = self.base_dir / right

        scan = scan_pair_folders(left, right, suffix_pattern=cfg.suffix_pattern)
        matches = scan.matches

        if self.pair_keys:
            matches = [m for m in matches if m.key in self.pair_keys]

        if self.limit is not None:
            matches = matches[: self.limit]

        return matches

    def run_one(self, match: PairMatch) -> RunItemResult:
        output_path = self._output_path(match.key)

        if self.recipe.skip_existing and output_path.exists():
            return RunItemResult(
                pair_key=match.key,
                status="skipped",
                output_path=str(output_path),
                skipped=True,
            )

        started = time.perf_counter()
        try:
            static_files = self.recipe.resolved_static_files(self.base_dir)
            missing = [p for p in static_files if not p.exists()]
            if missing:
                raise FileNotFoundError(f"Missing static files: {', '.join(str(p) for p in missing)}")

            raw = vision_message(
                static_files,
                [match.left, match.right],
                preamble=self.recipe.preamble,
                settings=self.settings,
            )
            try:
                parsed, _ = extract_json(raw)
            except ValueError:
                raw_path = output_path.with_suffix(".raw.txt")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(raw, encoding="utf-8")
                raise
            save_json_output(parsed, output_path)

            return RunItemResult(
                pair_key=match.key,
                status="ok",
                output_path=str(output_path),
                duration_s=time.perf_counter() - started,
            )
        except Exception as exc:
            return RunItemResult(
                pair_key=match.key,
                status="error",
                error=str(exc),
                duration_s=time.perf_counter() - started,
            )

    def run_all(self, on_progress=None) -> BatchRunResult:
        matches = self._resolve_pairs()
        result = BatchRunResult(total=len(matches))

        for index, match in enumerate(matches, start=1):
            item = self.run_one(match)
            result.items.append(item)

            if item.skipped:
                result.skipped += 1
            elif item.status == "ok":
                result.succeeded += 1
            else:
                result.failed += 1

            if on_progress:
                on_progress(index, len(matches), item)

        return result

    def dry_run(self) -> dict:
        matches = self._resolve_pairs()
        static_files = self.recipe.resolved_static_files(self.base_dir)
        output_dir = self.recipe.resolved_output_dir(self.base_dir)

        return {
            "recipe": self.recipe.name,
            "pair_count": len(matches),
            "static_files": [str(p) for p in static_files],
            "static_missing": [str(p) for p in static_files if not p.exists()],
            "output_dir": str(output_dir),
            "pairs_preview": [
                {
                    "key": m.key,
                    "left": str(m.left),
                    "right": str(m.right),
                    "output": str(self._output_path(m.key)),
                    "exists": self._output_path(m.key).exists(),
                }
                for m in matches[:50]
            ],
        }
