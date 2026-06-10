from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class PairFolderConfig:
    left: str
    right: str
    suffix_pattern: str = r"_grp_head_view_\d+$"


@dataclass
class BatchRecipe:
    name: str
    static_files: list[str] = field(default_factory=list)
    pair_folders: PairFolderConfig | None = None
    output_dir: str = "output"
    output_naming: str = "{pair_key}.json"
    skip_existing: bool = True
    preamble: str | None = None

    def resolved_static_files(self, base: Path | None = None) -> list[Path]:
        root = base or Path.cwd()
        return [root / p if not Path(p).is_absolute() else Path(p) for p in self.static_files]

    def resolved_output_dir(self, base: Path | None = None) -> Path:
        root = base or Path.cwd()
        out = Path(self.output_dir)
        return out if out.is_absolute() else root / out


def load_recipe(path: Path | str) -> BatchRecipe:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    pair_data = data.get("pair_folders")
    pair_folders = PairFolderConfig(**pair_data) if pair_data else None

    return BatchRecipe(
        name=data["name"],
        static_files=list(data.get("static_files", [])),
        pair_folders=pair_folders,
        output_dir=data.get("output_dir", "output"),
        output_naming=data.get("output_naming", "{pair_key}.json"),
        skip_existing=bool(data.get("skip_existing", True)),
        preamble=data.get("preamble"),
    )


def save_recipe(recipe: BatchRecipe, path: Path | str) -> None:
    payload: dict = {
        "name": recipe.name,
        "static_files": recipe.static_files,
        "output_dir": recipe.output_dir,
        "output_naming": recipe.output_naming,
        "skip_existing": recipe.skip_existing,
    }
    if recipe.preamble:
        payload["preamble"] = recipe.preamble
    if recipe.pair_folders:
        payload["pair_folders"] = {
            "left": recipe.pair_folders.left,
            "right": recipe.pair_folders.right,
            "suffix_pattern": recipe.pair_folders.suffix_pattern,
        }

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
