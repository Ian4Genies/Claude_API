import argparse
from pathlib import Path

from src.batch.history import JobHistory
from src.batch.recipe import load_recipe
from src.batch.runner import BatchRunner

ROOT = Path(__file__).resolve().parent.parent
HISTORY = JobHistory(ROOT / "output" / "jobs.db")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claude batch jobs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Execute a recipe")
    run.add_argument("--recipe", required=True, help="Recipe name (without .yaml)")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--pair", action="append", dest="pairs", help="Run specific pair key(s)")
    run.add_argument("--retry-failed", action="store_true", help="Re-run failed pairs from last job")

    scan = sub.add_parser("scan", help="Scan pair folders from a recipe")
    scan.add_argument("--recipe", required=True)

    dry = sub.add_parser("dry-run", help="Validate recipe without API calls")
    dry.add_argument("--recipe", required=True)

    args = parser.parse_args()
    recipe_path = ROOT / "recipes" / f"{args.recipe}.yaml"
    recipe = load_recipe(recipe_path)

    if args.cmd == "scan":
        runner = BatchRunner(recipe, base_dir=ROOT)
        info = runner.dry_run()
        print(f"Pairs: {info['pair_count']}")
        for row in info["pairs_preview"][:10]:
            print(f"  {row['key']} -> {row['output']} ({'exists' if row['exists'] else 'pending'})")
        return

    if args.cmd == "dry-run":
        runner = BatchRunner(recipe, base_dir=ROOT)
        info = runner.dry_run()
        print(f"Recipe: {info['recipe']}")
        print(f"Model: {info.get('model') or '(env default)'}")
        print(f"Pairs: {info['pair_count']}")
        print(f"Output: {info['output_dir']}")
        if info["static_missing"]:
            print(f"Missing: {info['static_missing']}")
        return

    import uuid

    job_id = str(uuid.uuid4())
    runner = BatchRunner(
        recipe,
        base_dir=ROOT,
        limit=args.limit,
        pair_keys=args.pairs,
        retry_failed=args.retry_failed,
        job_id=job_id,
        history=HISTORY,
    )

    def on_progress(current, total, item):
        mark = "skip" if item.skipped else item.status
        cost = f" ${item.cost_usd:.4f}" if item.cost_usd else ""
        print(f"[{current}/{total}] {item.pair_key}: {mark}{cost}")

    result = runner.run_all(on_progress=on_progress)
    print(
        f"Done — ok={result.succeeded} skipped={result.skipped} failed={result.failed} "
        f"cost=${result.cost_usd:.4f} manifest={result.manifest_path}"
    )


if __name__ == "__main__":
    main()
