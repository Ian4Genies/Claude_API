import re
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_PAIR_SUFFIX = re.compile(r"_grp_head_view_\d+$", re.IGNORECASE)
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@dataclass(frozen=True)
class PairMatch:
    key: str
    files: dict[str, Path]

    @property
    def file_list(self) -> list[Path]:
        return list(self.files.values())

    @property
    def left(self) -> Path:
        values = list(self.files.values())
        return values[0] if values else Path()

    @property
    def right(self) -> Path:
        values = list(self.files.values())
        return values[1] if len(values) > 1 else Path()


@dataclass
class PairScanResult:
    matches: list[PairMatch] = field(default_factory=list)
    orphans: dict[str, list[Path]] = field(default_factory=dict)
    folders: list[tuple[str, Path]] = field(default_factory=list)
    left_only: list[Path] = field(default_factory=list)
    right_only: list[Path] = field(default_factory=list)

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def is_clean(self) -> bool:
        return all(not files for files in self.orphans.values())


def _pair_key(stem: str, suffix_pattern: re.Pattern[str]) -> str:
    return suffix_pattern.sub("", stem)


def _index_folder(folder: Path, suffix_pattern: re.Pattern[str]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    if not folder.is_dir():
        return index

    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        key = _pair_key(path.stem, suffix_pattern)
        index[key] = path
    return index


def _resolve_pattern(suffix_pattern: re.Pattern[str] | str | None) -> re.Pattern[str]:
    if isinstance(suffix_pattern, str):
        return re.compile(suffix_pattern, re.IGNORECASE)
    return suffix_pattern or DEFAULT_PAIR_SUFFIX


def scan_multi_folders(
    folders: list[tuple[str, Path | str]],
    *,
    suffix_pattern: re.Pattern[str] | str | None = None,
) -> PairScanResult:
    pattern = _resolve_pattern(suffix_pattern)
    resolved: list[tuple[str, Path]] = [(label, Path(path)) for label, path in folders]
    if len(resolved) < 2:
        raise ValueError("At least two folders are required for pairing")

    indexes = {label: _index_folder(folder, pattern) for label, folder in resolved}
    if not all(indexes.values()):
        missing = [label for label, idx in indexes.items() if not idx]
        raise ValueError(f"No pairable images found in: {', '.join(missing)}")

    shared = set.intersection(*(set(idx) for idx in indexes.values()))
    shared_keys = sorted(shared)

    orphans = {
        label: [indexes[label][k] for k in sorted(set(indexes[label]) - shared)]
        for label, _ in resolved
    }

    matches = [
        PairMatch(key=key, files={label: indexes[label][key] for label, _ in resolved})
        for key in shared_keys
    ]

    labels = [label for label, _ in resolved]
    result = PairScanResult(
        matches=matches,
        orphans=orphans,
        folders=resolved,
    )
    if len(labels) >= 1:
        result.left_only = orphans.get(labels[0], [])
    if len(labels) >= 2:
        result.right_only = orphans.get(labels[1], [])
    return result


def scan_pair_folders(
    left_folder: Path | str,
    right_folder: Path | str,
    *,
    suffix_pattern: re.Pattern[str] | str | None = None,
) -> PairScanResult:
    left = Path(left_folder)
    right = Path(right_folder)
    return scan_multi_folders(
        [("left", left), ("right", right)],
        suffix_pattern=suffix_pattern,
    )
