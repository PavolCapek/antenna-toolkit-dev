from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


INPUT_DATA_DIRNAME = "Input data"
INPUT_SUBDIRECTORIES = {
    ".ffs": "Far-field",
    ".s1p": "Touchstone",
    ".s2p": "Touchstone",
}


def input_directory(root: Path, suffix: str = "") -> Path:
    input_root = root / INPUT_DATA_DIRNAME
    subdirectory = INPUT_SUBDIRECTORIES.get(suffix.lower())
    return input_root / subdirectory if subdirectory else input_root


def is_url(value: str | Path | None) -> bool:
    if value is None:
        return False
    parsed = urlparse(str(value).strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def resolve_workspace_path(root: Path, path: str | Path | None) -> Path:
    if not path:
        return root
    if is_url(path):
        return Path(str(path))
    target = Path(path)
    resolved = target.resolve() if target.is_absolute() else (root / target).resolve()
    input_root = input_directory(root)
    if resolved.suffix.lower() in INPUT_SUBDIRECTORIES and resolved.parent == input_root.resolve() and not resolved.exists():
        moved = input_directory(root, resolved.suffix) / resolved.name
        if moved.is_file():
            return moved.resolve()
    return resolved


def display_workspace_path(root: Path, path: str | Path | None) -> str:
    if not path:
        return ""
    if is_url(path):
        return str(path)
    resolved = resolve_workspace_path(root, path)
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def serialize_workspace_path(root: Path, path: str | Path | None) -> str:
    if not path:
        return ""
    if is_url(path):
        return str(path).strip()
    resolved = resolve_workspace_path(root, path)
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def resolve_project_path(root: Path, value: str | Path | None) -> str:
    if not value:
        return ""
    if is_url(value):
        return str(value).strip()
    return str(resolve_workspace_path(root, value))
