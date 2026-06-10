import asyncio
import json
import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.batch.history import JobHistory
from src.batch.validate import validate_api_key
from src.batch.pairing import scan_multi_folders
from src.batch.recipe import BatchRecipe, FolderEntry, PairFolderConfig, load_recipe, save_recipe
from src.batch.runner import BatchRunner
from src.env_file import api_key_status, save_api_key

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
RECIPES = ROOT / "recipes"
HISTORY_DB = ROOT / "output" / "jobs.db"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}

app = FastAPI(title="Claude Batch Runner")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_cancel: dict[str, threading.Event] = {}
_active_job_id: str | None = None
_history = JobHistory(HISTORY_DB)


class FolderSpec(BaseModel):
    label: str
    path: str


class ScanRequest(BaseModel):
    folders: list[FolderSpec]
    suffix_pattern: str = r"_grp_head_view_\d+$"


class FolderInspectRequest(BaseModel):
    folder: str


class RecipePayload(BaseModel):
    name: str = "custom_recipe"
    static_files: list[str] = Field(default_factory=list)
    folders: list[FolderSpec] = Field(default_factory=list)
    suffix_pattern: str = r"_grp_head_view_\d+$"
    output_dir: str = "output"
    output_naming: str = "{pair_key}.json"
    skip_existing: bool = True
    preamble: str | None = None
    model: str | None = None
    max_workers: int | None = None


class RunRequest(RecipePayload):
    limit: int | None = None
    pair_keys: list[str] | None = None
    retry_failed: bool = False


class ApiKeyPayload(BaseModel):
    api_key: str


def _to_recipe(payload: RecipePayload) -> BatchRecipe:
    pair_folders = None
    if len(payload.folders) >= 2:
        pair_folders = PairFolderConfig(
            folders=[FolderEntry(label=f.label, path=f.path) for f in payload.folders],
            suffix_pattern=payload.suffix_pattern,
        )
    return BatchRecipe(
        name=payload.name,
        static_files=payload.static_files,
        pair_folders=pair_folders,
        output_dir=payload.output_dir,
        output_naming=payload.output_naming,
        skip_existing=payload.skip_existing,
        preamble=payload.preamble,
        model=payload.model,
        max_workers=payload.max_workers,
    )


def _resolve(path_str: str) -> Path:
    path = Path(path_str)
    return path if path.is_absolute() else ROOT / path


def _rel_path(path: Path) -> str:
    root = ROOT.resolve()
    resolved = path.resolve()
    if resolved == root:
        return ""
    return str(resolved.relative_to(root)).replace("\\", "/")


SKIP_DIR_NAMES = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def _safe_path(path_str: str) -> Path:
    resolved = _resolve(path_str).resolve()
    root = ROOT.resolve()
    if resolved != root and root not in resolved.parents:
        raise HTTPException(403, "Path outside project root")
    return resolved


def _recipe_payload(recipe: BatchRecipe) -> dict:
    folders = []
    if recipe.pair_folders:
        folders = [
            {"label": entry.label, "path": entry.path}
            for entry in recipe.pair_folders.folders
        ]
    return RecipePayload(
        name=recipe.name,
        static_files=recipe.static_files,
        folders=folders,
        suffix_pattern=recipe.pair_folders.suffix_pattern if recipe.pair_folders else r"_grp_head_view_\d+$",
        output_dir=recipe.output_dir,
        output_naming=recipe.output_naming,
        skip_existing=recipe.skip_existing,
        preamble=recipe.preamble,
        model=recipe.model,
        max_workers=recipe.max_workers,
    ).model_dump()


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/config")
async def get_config():
    return api_key_status()


@app.post("/api/config/api-key")
async def set_api_key(payload: ApiKeyPayload):
    try:
        save_api_key(payload.api_key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    check = validate_api_key(payload.api_key)
    status = api_key_status()
    status["valid"] = check["valid"]
    if not check["valid"]:
        status["error"] = check["error"]
    return status


@app.post("/api/config/validate")
async def validate_key():
    check = validate_api_key()
    status = api_key_status()
    status["valid"] = check["valid"]
    if not check["valid"]:
        status["error"] = check["error"]
    return status


@app.get("/api/manifest")
async def get_manifest(output_dir: str = Query(default="output")):
    manifest_path = _resolve(output_dir) / "latest_manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(404, "No manifest found for this output directory")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@app.get("/api/browse")
async def browse(path: str = Query(default="")):
    target = ROOT.resolve() if not path else _safe_path(path)
    if not target.is_dir():
        raise HTTPException(400, "Not a directory")

    root = ROOT.resolve()
    rel = _rel_path(target)
    parent = _rel_path(target.parent) if target != root else None

    entries = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name in SKIP_DIR_NAMES:
            continue
        if item.is_dir() and item.name.startswith("."):
            continue
        entries.append({
            "name": item.name,
            "path": _rel_path(item),
            "kind": "dir" if item.is_dir() else "file",
            "is_image": item.suffix.lower() in IMAGE_SUFFIXES,
        })

    return {"path": rel, "parent": parent, "entries": entries}


@app.get("/api/recipes")
async def list_recipes():
    if not RECIPES.is_dir():
        return {"recipes": []}
    files = sorted(RECIPES.glob("*.yaml"))
    return {"recipes": [f.stem for f in files]}


@app.get("/api/recipes/{name}")
async def get_recipe(name: str):
    path = RECIPES / f"{name}.yaml"
    if not path.exists():
        raise HTTPException(404, "Recipe not found")
    return _recipe_payload(load_recipe(path))


@app.get("/api/media")
async def media(path: str = Query(...)):
    resolved = _safe_path(path)
    if not resolved.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(resolved)


@app.get("/api/file-meta")
async def file_meta(path: str = Query(...)):
    resolved = _safe_path(path)
    if not resolved.is_file():
        raise HTTPException(404, "File not found")
    suffix = resolved.suffix.lower()
    return {
        "path": path,
        "name": resolved.name,
        "kind": "image" if suffix in IMAGE_SUFFIXES else "text" if suffix in TEXT_SUFFIXES else "file",
        "preview_url": f"/api/media?path={path}" if suffix in IMAGE_SUFFIXES else None,
    }


@app.post("/api/inspect-folder")
async def inspect_folder(req: FolderInspectRequest):
    folder = _resolve(req.folder)
    if not folder.is_dir():
        raise HTTPException(400, f"Not a directory: {folder}")

    files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )
    rel = lambda p: str(p.relative_to(ROOT)).replace("\\", "/") if p.is_relative_to(ROOT) else str(p)
    stems = [p.stem for p in files]
    return {
        "folder": str(folder),
        "count": len(files),
        "files": [p.name for p in files[:100]],
        "sample_stems": stems[:20],
        "sample_previews": [
            {"name": p.name, "path": rel(p), "preview_url": f"/api/media?path={rel(p)}"}
            for p in files[:8]
        ],
    }


@app.post("/api/scan-pairs")
async def scan_pairs(req: ScanRequest):
    if len(req.folders) < 2:
        raise HTTPException(400, "At least two folders required")

    entries: list[tuple[str, Path]] = []
    for spec in req.folders:
        folder = _resolve(spec.path)
        if not folder.is_dir():
            raise HTTPException(400, f"Not a directory: {folder}")
        entries.append((spec.label, folder))

    result = scan_multi_folders(entries, suffix_pattern=req.suffix_pattern)
    rel = lambda p: str(p.relative_to(ROOT)).replace("\\", "/") if p.is_relative_to(ROOT) else str(p)

    return {
        "match_count": result.match_count,
        "orphan_counts": {label: len(files) for label, files in result.orphans.items()},
        "is_clean": result.is_clean,
        "folder_labels": [label for label, _ in result.folders],
        "matches": [
            {
                "key": m.key,
                "files": {label: rel(path) for label, path in m.files.items()},
            }
            for m in result.matches
        ],
        "orphans": {
            label: [rel(p) for p in files[:30]]
            for label, files in result.orphans.items()
        },
    }


@app.post("/api/dry-run")
async def dry_run(req: RecipePayload):
    recipe = _to_recipe(req)
    runner = BatchRunner(recipe, base_dir=ROOT)
    try:
        return runner.dry_run()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


def _failed_keys(recipe_name: str, output_dir: str) -> list[str]:
    keys = _history.failed_keys(recipe_name)
    if keys:
        return keys
    manifest = _resolve(output_dir) / "latest_manifest.json"
    if not manifest.is_file():
        return []
    data = json.loads(manifest.read_text(encoding="utf-8"))
    return [i["pair_key"] for i in data.get("items", []) if i.get("status") == "error"]


@app.get("/api/failed-count")
async def failed_count(
    recipe: str = Query(...),
    output_dir: str = Query(default="output"),
):
    return {"count": len(_failed_keys(recipe, output_dir))}


def _run_job(job_id: str, req: RunRequest, cancel_event: threading.Event) -> None:
    global _active_job_id
    recipe = _to_recipe(req)
    runner = BatchRunner(
        recipe,
        base_dir=ROOT,
        limit=req.limit,
        pair_keys=req.pair_keys,
        retry_failed=req.retry_failed,
        job_id=job_id,
        history=_history,
        cancel_event=cancel_event,
    )

    def on_progress(current: int, total: int, item) -> None:
        payload = asdict(item)
        with _jobs_lock:
            job = _jobs[job_id]
            job["current"] = current
            job["total"] = total
            job["items"].append(payload)
            job["input_tokens"] = job.get("input_tokens", 0) + item.input_tokens
            job["output_tokens"] = job.get("output_tokens", 0) + item.output_tokens
            job["cache_read_tokens"] = job.get("cache_read_tokens", 0) + item.cache_read_input_tokens
            job["cost_usd"] = round(job.get("cost_usd", 0) + item.cost_usd, 6)
            if item.skipped:
                job["skipped"] += 1
            elif item.status == "ok":
                job["succeeded"] += 1
            else:
                job["failed"] += 1

    try:
        with _jobs_lock:
            _jobs[job_id]["total"] = len(runner._resolve_pairs())
        result = runner.run_all(on_progress=on_progress)
        with _jobs_lock:
            cancelled = cancel_event.is_set()
            _jobs[job_id]["status"] = "cancelled" if cancelled else "done"
            _jobs[job_id]["result"] = {
                "total": result.total,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "skipped": result.skipped,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "cache_read_input_tokens": result.cache_read_input_tokens,
                "cost_usd": round(result.cost_usd, 6),
                "manifest_path": result.manifest_path,
            }
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)
    finally:
        with _jobs_lock:
            if _active_job_id == job_id:
                _active_job_id = None
            _cancel.pop(job_id, None)


@app.post("/api/run")
async def run_batch(req: RunRequest):
    global _active_job_id

    key_check = validate_api_key(model=req.model)
    if not key_check["valid"]:
        raise HTTPException(400, key_check["error"])

    if req.retry_failed:
        failed = _failed_keys(req.name, req.output_dir)
        if not failed:
            raise HTTPException(400, "No failed pairs to retry — run a batch first or check manifest")

    with _jobs_lock:
        if _active_job_id and _active_job_id in _cancel:
            _cancel[_active_job_id].set()

    job_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    with _jobs_lock:
        _active_job_id = job_id
        _cancel[job_id] = cancel_event
        _jobs[job_id] = {
            "status": "running",
            "current": 0,
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_tokens": 0,
            "cost_usd": 0.0,
            "items": [],
        }

    thread = threading.Thread(target=_run_job, args=(job_id, req, cancel_event), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.post("/api/run/{job_id}/cancel")
async def cancel_run(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job["status"] != "running":
            return {"job_id": job_id, "status": job["status"]}
        if job_id in _cancel:
            _cancel[job_id].set()
    return {"job_id": job_id, "status": "cancelling"}


@app.get("/api/run/{job_id}/stream")
async def stream_job(job_id: str):
    async def events():
        seen = 0
        while True:
            with _jobs_lock:
                job = _jobs.get(job_id)
            if not job:
                yield f"data: {json.dumps({'type': 'error', 'message': 'not found'})}\n\n"
                return
            if len(job["items"]) > seen:
                for item in job["items"][seen:]:
                    yield f"data: {json.dumps({'type': 'item', 'item': item})}\n\n"
                seen = len(job["items"])
            payload = {
                "type": "status",
                "status": job["status"],
                "current": job["current"],
                "total": job["total"],
                "succeeded": job["succeeded"],
                "failed": job["failed"],
                "skipped": job["skipped"],
                "input_tokens": job.get("input_tokens", 0),
                "output_tokens": job.get("output_tokens", 0),
                "cache_read_tokens": job.get("cache_read_tokens", 0),
                "cost_usd": job.get("cost_usd", 0),
            }
            if job.get("result"):
                payload["result"] = job["result"]
            if job.get("error"):
                payload["error"] = job["error"]
            yield f"data: {json.dumps(payload)}\n\n"
            if job["status"] in ("done", "error", "cancelled"):
                return
            await asyncio.sleep(0.25)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/history/{job_id}")
async def job_history(job_id: str):
    data = _history.get_job(job_id)
    if not data:
        raise HTTPException(404, "Job not found")
    return data


@app.get("/api/run/{job_id}")
async def run_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@app.post("/api/recipes/save")
async def save_recipe_endpoint(payload: RecipePayload):
    recipe = _to_recipe(payload)
    RECIPES.mkdir(parents=True, exist_ok=True)
    path = RECIPES / f"{recipe.name}.yaml"
    save_recipe(recipe, path)
    return {"saved": str(path)}
