import threading
import uuid
from dataclasses import asdict
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.batch.pairing import scan_pair_folders
from src.batch.recipe import BatchRecipe, PairFolderConfig, load_recipe, save_recipe
from src.batch.runner import BatchRunner

ROOT = Path(__file__).resolve().parent.parent
STATIC = Path(__file__).resolve().parent / "static"
RECIPES = ROOT / "recipes"

app = FastAPI(title="Claude Batch Runner")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


class ScanRequest(BaseModel):
    left_folder: str
    right_folder: str
    suffix_pattern: str = r"_grp_head_view_\d+$"


class FolderInspectRequest(BaseModel):
    folder: str


class RecipePayload(BaseModel):
    name: str = "custom_recipe"
    static_files: list[str] = Field(default_factory=list)
    left_folder: str = ""
    right_folder: str = ""
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
    if payload.left_folder and payload.right_folder:
        pair_folders = PairFolderConfig(
            left=payload.left_folder,
            right=payload.right_folder,
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


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


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
    recipe = load_recipe(path)
    payload = RecipePayload(
        name=recipe.name,
        static_files=recipe.static_files,
        left_folder=recipe.pair_folders.left if recipe.pair_folders else "",
        right_folder=recipe.pair_folders.right if recipe.pair_folders else "",
        suffix_pattern=recipe.pair_folders.suffix_pattern if recipe.pair_folders else r"_grp_head_view_\d+$",
        output_dir=recipe.output_dir,
        output_naming=recipe.output_naming,
        skip_existing=recipe.skip_existing,
        preamble=recipe.preamble,
    )
    return payload.model_dump()


@app.post("/api/inspect-folder")
async def inspect_folder(req: FolderInspectRequest):
    folder = _resolve(req.folder)
    if not folder.is_dir():
        raise HTTPException(400, f"Not a directory: {folder}")

    files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    )
    stems = [p.stem for p in files]
    return {
        "folder": str(folder),
        "count": len(files),
        "files": [p.name for p in files[:100]],
        "sample_stems": stems[:20],
    }


@app.post("/api/scan-pairs")
async def scan_pairs(req: ScanRequest):
    left = _resolve(req.left_folder)
    right = _resolve(req.right_folder)
    if not left.is_dir() or not right.is_dir():
        raise HTTPException(400, "Both folders must exist")

    result = scan_pair_folders(left, right, suffix_pattern=req.suffix_pattern)
    return {
        "match_count": result.match_count,
        "left_only_count": len(result.left_only),
        "right_only_count": len(result.right_only),
        "is_clean": result.is_clean,
        "matches": [
            {"key": m.key, "left": str(m.left), "right": str(m.right)}
            for m in result.matches
        ],
        "left_only": [str(p) for p in result.left_only[:50]],
        "right_only": [str(p) for p in result.right_only[:50]],
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
async def run_batch(req: RunRequest, background: BackgroundTasks):
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
