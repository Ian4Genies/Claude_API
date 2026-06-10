import re
from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_PAIR_SUFFIX = re.compile(r"_grp_head_view_\d+$", re.IGNORECASE)


@dataclass(frozen=True)
class PairMatch:
    key: str
    left: Path
    right: Path


@dataclass
class PairScanResult:
    matches: list[PairMatch] = field(default_factory=list)
    left_only: list[Path] = field(default_factory=list)
    right_only: list[Path] = field(default_factory=list)
    left_folder: Path | None = None
    right_folder: Path | None = None

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def is_clean(self) -> bool:
        return not self.left_only and not self.right_only


def _pair_key(stem: str, suffix_pattern: re.Pattern[str]) -> str:
    return suffix_pattern.sub("", stem)


def _index_folder(folder: Path, suffix_pattern: re.Pattern[str]) -> dict[str, Path]:
    index: dict[str, Path] = {}
    if not folder.is_dir():
        return index

    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        key = _pair_key(path.stem, suffix_pattern)
        index[key] = path
    return index


def scan_pair_folders(
    left_folder: Path | str,
    right_folder: Path | str,
    *,
    suffix_pattern: re.Pattern[str] | str | None = None,
) -> PairScanResult:
    left = Path(left_folder)
    right = Path(right_folder)
    pattern = (
        re.compile(suffix_pattern, re.IGNORECASE)
        if isinstance(suffix_pattern, str)
        else (suffix_pattern or DEFAULT_PAIR_SUFFIX)
    )

    left_index = _index_folder(left, pattern)
    right_index = _index_folder(right, pattern)

    left_keys = set(left_index)
    right_keys = set(right_index)
    shared = sorted(left_keys & right_keys)

    result = PairScanResult(
        matches=[
            PairMatch(key=key, left=left_index[key], right=right_index[key])
            for key in shared
        ],
        left_only=[left_index[k] for k in sorted(left_keys - right_keys)],
        right_only=[right_index[k] for k in sorted(right_keys - left_keys)],
        left_folder=left,
        right_folder=right,
    )
    return result
