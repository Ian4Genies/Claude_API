import argparse
from pathlib import Path

from src.batch.recipe import load_recipe
from src.batch.runner import BatchRunner

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Claude batch jobs")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Execute a recipe")
    run.add_argument("--recipe", required=True, help="Recipe name (without .yaml)")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--pair", action="append", dest="pairs", help="Run specific pair key(s)")

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
        print(f"Pairs: {info['pair_count']}")
        print(f"Output: {info['output_dir']}")
        if info["static_missing"]:
            print(f"Missing: {info['static_missing']}")
        return

    runner = BatchRunner(
        recipe,
        base_dir=ROOT,
        limit=args.limit,
        pair_keys=args.pairs,
    )

    def on_progress(current, total, item):
        mark = "skip" if item.skipped else item.status
        print(f"[{current}/{total}] {item.pair_key}: {mark}")

    result = runner.run_all(on_progress=on_progress)
    print(f"Done — ok={result.succeeded} skipped={result.skipped} failed={result.failed}")


if __name__ == "__main__":
    main()
