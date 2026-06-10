from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class FolderEntry:
    label: str
    path: str


@dataclass
class PairFolderConfig:
    folders: list[FolderEntry] = field(default_factory=list)
    suffix_pattern: str = r"_grp_head_view_\d+$"

    @property
    def left(self) -> str:
        return self.folders[0].path if self.folders else ""

    @property
    def right(self) -> str:
        return self.folders[1].path if len(self.folders) > 1 else ""


@dataclass
class BatchRecipe:
    name: str
    static_files: list[str] = field(default_factory=list)
    pair_folders: PairFolderConfig | None = None
    output_dir: str = "output"
    output_naming: str = "{pair_key}.json"
    skip_existing: bool = True
    preamble: str | None = None
    model: str | None = None
    max_workers: int | None = None

    def resolved_static_files(self, base: Path | None = None) -> list[Path]:
        root = base or Path.cwd()
        return [root / p if not Path(p).is_absolute() else Path(p) for p in self.static_files]

    def resolved_output_dir(self, base: Path | None = None) -> Path:
        root = base or Path.cwd()
        out = Path(self.output_dir)
        return out if out.is_absolute() else root / out

    def resolved_folder_entries(self, base: Path | None = None) -> list[tuple[str, Path]]:
        if not self.pair_folders:
            return []
        root = base or Path.cwd()
        entries: list[tuple[str, Path]] = []
        for entry in self.pair_folders.folders:
            path = Path(entry.path)
            if not path.is_absolute():
                path = root / path
            entries.append((entry.label, path))
        return entries


def _parse_folder_entry(raw: str | dict) -> FolderEntry:
    if isinstance(raw, str):
        label = Path(raw).name or "folder"
        return FolderEntry(label=label, path=raw)
    label = raw.get("label") or Path(raw["path"]).name or "folder"
    return FolderEntry(label=label, path=raw["path"])


def _parse_pair_folders(pair_data: dict) -> PairFolderConfig:
    suffix_pattern = pair_data.get("suffix_pattern", r"_grp_head_view_\d+$")

    if "folders" in pair_data:
        folders = [_parse_folder_entry(item) for item in pair_data["folders"]]
    elif "left" in pair_data and "right" in pair_data:
        folders = [
            FolderEntry(label="front", path=pair_data["left"]),
            FolderEntry(label="side", path=pair_data["right"]),
        ]
    else:
        raise ValueError("pair_folders requires 'folders' or legacy left/right keys")

    return PairFolderConfig(folders=folders, suffix_pattern=suffix_pattern)


def load_recipe(path: Path | str) -> BatchRecipe:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    pair_data = data.get("pair_folders")
    pair_folders = _parse_pair_folders(pair_data) if pair_data else None

    return BatchRecipe(
        name=data["name"],
        static_files=list(data.get("static_files", [])),
        pair_folders=pair_folders,
        output_dir=data.get("output_dir", "output"),
        output_naming=data.get("output_naming", "{pair_key}.json"),
        skip_existing=bool(data.get("skip_existing", True)),
        preamble=data.get("preamble"),
        model=data.get("model"),
        max_workers=data.get("max_workers"),
    )


def save_recipe(recipe: BatchRecipe, path: Path | str) -> None:
    payload: dict = {
        "name": recipe.name,
        "static_files": recipe.static_files,
        "output_dir": recipe.output_dir,
        "output_naming": recipe.output_naming,
        "skip_existing": recipe.skip_existing,
    }
    if recipe.model:
        payload["model"] = recipe.model
    if recipe.max_workers:
        payload["max_workers"] = recipe.max_workers
    if recipe.preamble:
        payload["preamble"] = recipe.preamble
    if recipe.pair_folders:
        payload["pair_folders"] = {
            "folders": [
                {"label": entry.label, "path": entry.path}
                for entry in recipe.pair_folders.folders
            ],
            "suffix_pattern": recipe.pair_folders.suffix_pattern,
        }

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
