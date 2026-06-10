import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path

from src.batch.cost import estimate_cost
from src.batch.extract import extract_json, save_json_output
from src.batch.history import JobHistory
from src.batch.pairing import PairMatch, scan_multi_folders
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
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class BatchRunResult:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0
    manifest_path: str | None = None
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
        retry_failed: bool = False,
        job_id: str | None = None,
        history: JobHistory | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.recipe = recipe
        self.base_dir = base_dir or Path.cwd()
        self._settings = settings
        self.limit = limit
        self.pair_keys = set(pair_keys) if pair_keys else None
        self.retry_failed = retry_failed
        self.job_id = job_id
        self.history = history
        self.cancel_event = cancel_event
        self._lock = threading.Lock()
        self._static_files: list[Path] | None = None

    @property
    def settings(self) -> Settings:
        if self._settings is None:
            self._settings = get_settings()
        return self._settings

    def _output_path(self, pair_key: str) -> Path:
        name = self.recipe.output_naming.format(pair_key=pair_key)
        return self.recipe.resolved_output_dir(self.base_dir) / name

    def _failed_keys_from_manifest(self) -> list[str]:
        manifest = self.recipe.resolved_output_dir(self.base_dir) / "latest_manifest.json"
        if not manifest.is_file():
            return []
        data = json.loads(manifest.read_text(encoding="utf-8"))
        return [i["pair_key"] for i in data.get("items", []) if i.get("status") == "error"]

    def _resolve_pair_keys(self) -> set[str] | None:
        if self.pair_keys:
            return self.pair_keys
        if not self.retry_failed:
            return None

        keys: list[str] = []
        if self.history:
            keys = self.history.failed_keys(self.recipe.name)
        if not keys:
            keys = self._failed_keys_from_manifest()
        if not keys:
            raise ValueError("No failed pairs to retry — run a batch first or check manifest")
        return set(keys)

    def _resolve_pairs(self) -> list[PairMatch]:
        if not self.recipe.pair_folders:
            raise ValueError("Recipe has no pair_folders configured")

        cfg = self.recipe.pair_folders
        folder_entries = self.recipe.resolved_folder_entries(self.base_dir)
        if len(folder_entries) < 2:
            raise ValueError("Recipe needs at least two pair folders")

        scan = scan_multi_folders(folder_entries, suffix_pattern=cfg.suffix_pattern)
        matches = scan.matches

        keys = self._resolve_pair_keys()
        if keys is not None:
            matches = [m for m in matches if m.key in keys]

        if self.limit is not None and not self.retry_failed:
            matches = matches[: self.limit]

        return matches

    def _get_static_files(self) -> list[Path]:
        if self._static_files is None:
            static = self.recipe.resolved_static_files(self.base_dir)
            missing = [p for p in static if not p.exists()]
            if missing:
                raise FileNotFoundError(f"Missing static files: {', '.join(str(p) for p in missing)}")
            self._static_files = static
        return self._static_files

    def run_one(self, match: PairMatch) -> RunItemResult:
        output_path = self._output_path(match.key)

        if self.recipe.skip_existing and output_path.exists() and not self.retry_failed:
            return RunItemResult(
                pair_key=match.key,
                status="skipped",
                output_path=str(output_path),
                skipped=True,
            )

        started = time.perf_counter()
        model = self.recipe.model or self.settings.model
        try:
            result = vision_message(
                self._get_static_files(),
                match.file_list,
                preamble=self.recipe.preamble,
                model=model,
                settings=self.settings,
            )
            try:
                parsed, _ = extract_json(result.text)
            except ValueError:
                raw_path = output_path.with_suffix(".raw.txt")
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(result.text, encoding="utf-8")
                raise
            save_json_output(parsed, output_path)

            cost = estimate_cost(model, result.usage)
            return RunItemResult(
                pair_key=match.key,
                status="ok",
                output_path=str(output_path),
                duration_s=time.perf_counter() - started,
                input_tokens=result.usage["input_tokens"],
                output_tokens=result.usage["output_tokens"],
                cache_read_input_tokens=result.usage["cache_read_input_tokens"],
                cost_usd=cost,
            )
        except Exception as exc:
            return RunItemResult(
                pair_key=match.key,
                status="error",
                error=str(exc),
                duration_s=time.perf_counter() - started,
            )

    def _apply_item(self, result: BatchRunResult, item: RunItemResult) -> None:
        result.items.append(item)
        result.input_tokens += item.input_tokens
        result.output_tokens += item.output_tokens
        result.cache_read_input_tokens += item.cache_read_input_tokens
        result.cost_usd += item.cost_usd
        if item.skipped:
            result.skipped += 1
        elif item.status == "ok":
            result.succeeded += 1
        else:
            result.failed += 1

    def _write_manifest(self, result: BatchRunResult) -> Path:
        out_dir = self.recipe.resolved_output_dir(self.base_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "job_id": self.job_id,
            "recipe": self.recipe.name,
            "model": self.recipe.model or self.settings.model,
            "finished_at": time.time(),
            "summary": {
                "total": result.total,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "skipped": result.skipped,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_read_input_tokens": result.cache_read_input_tokens,
                "cost_usd": round(result.cost_usd, 6),
            },
            "items": [asdict(i) for i in result.items],
        }
        json_path = out_dir / "latest_manifest.json"
        json_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        csv_path = out_dir / "latest_manifest.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "pair_key", "status", "skipped", "output_path", "error", "duration_s",
                    "input_tokens", "output_tokens", "cache_read_input_tokens", "cost_usd",
                ],
            )
            writer.writeheader()
            for item in result.items:
                writer.writerow(asdict(item))

        result.manifest_path = str(json_path)
        return json_path

    def run_all(self, on_progress=None) -> BatchRunResult:
        matches = self._resolve_pairs()
        result = BatchRunResult(total=len(matches))
        workers = self.recipe.max_workers or self.settings.max_workers
        done = 0

        if self.job_id and self.history:
            self.history.abandon_running(self.recipe.name)
            self.history.start_job(self.job_id, self.recipe.name)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.run_one, m): m for m in matches}
            for future in as_completed(futures):
                if self.cancel_event and self.cancel_event.is_set():
                    for f in futures:
                        f.cancel()
                    break
                item = future.result()
                with self._lock:
                    self._apply_item(result, item)
                    done += 1
                    if self.history and self.job_id:
                        self.history.add_item(self.job_id, asdict(item))
                    if on_progress:
                        on_progress(done, result.total, item)

        if self.cancel_event and self.cancel_event.is_set():
            result.total = done

        manifest_path = self._write_manifest(result)
        if self.history and self.job_id:
            status = "cancelled" if self.cancel_event and self.cancel_event.is_set() else "done"
            self.history.finish_job(
                self.job_id,
                {
                    "status": status,
                    "total": result.total,
                    "succeeded": result.succeeded,
                    "failed": result.failed,
                    "skipped": result.skipped,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cache_read_input_tokens": result.cache_read_input_tokens,
                    "cost_usd": result.cost_usd,
                },
                str(manifest_path),
            )
        return result

    def dry_run(self) -> dict:
        matches = self._resolve_pairs()
        static_files = self.recipe.resolved_static_files(self.base_dir)
        output_dir = self.recipe.resolved_output_dir(self.base_dir)

        return {
            "recipe": self.recipe.name,
            "model": self.recipe.model or None,
            "pair_count": len(matches),
            "static_files": [str(p) for p in static_files],
            "static_missing": [str(p) for p in static_files if not p.exists()],
            "output_dir": str(output_dir),
            "pairs_preview": [
                {
                    "key": m.key,
                    "files": {label: str(path) for label, path in m.files.items()},
                    "output": str(self._output_path(m.key)),
                    "exists": self._output_path(m.key).exists(),
                }
                for m in matches[:50]
            ],
        }
