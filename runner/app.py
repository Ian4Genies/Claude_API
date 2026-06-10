import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.batch.pairing import scan_multi_folders
from src.batch.recipe import BatchRecipe, FolderEntry, PairFolderConfig, load_recipe, save_recipe
from src.batch.runner import BatchRunner

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
RECIPES = ROOT / "recipes"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}

app = FastAPI(title="Claude Batch Runner")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


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


class RunRequest(RecipePayload):
    limit: int | None = None
    pair_keys: list[str] | None = None


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
    ).model_dump()


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


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


def _run_job(job_id: str, req: RunRequest) -> None:
    recipe = _to_recipe(req)
    runner = BatchRunner(
        recipe,
        base_dir=ROOT,
        limit=req.limit,
        pair_keys=req.pair_keys,
    )

    def on_progress(current: int, total: int, item) -> None:
        with _jobs_lock:
            job = _jobs[job_id]
            job["current"] = current
            job["total"] = total
            job["items"].append(asdict(item))
            if item.status == "ok":
                job["succeeded"] += 1
            elif item.skipped:
                job["skipped"] += 1
            else:
                job["failed"] += 1

    try:
        result = runner.run_all(on_progress=on_progress)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["result"] = {
                "total": result.total,
                "succeeded": result.succeeded,
                "failed": result.failed,
                "skipped": result.skipped,
            }
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"
            _jobs[job_id]["error"] = str(exc)


@app.post("/api/run")
async def run_batch(req: RunRequest):
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "current": 0,
            "total": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "items": [],
        }

    thread = threading.Thread(target=_run_job, args=(job_id, req), daemon=True)
    thread.start()
    return {"job_id": job_id}


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
