from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse


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
    return target.resolve() if target.is_absolute() else (root / target).resolve()


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
    path = Path(value)
    return str(path.resolve() if path.is_absolute() else (root / path).resolve())
