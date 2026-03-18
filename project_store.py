from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECTS_DIRNAME = "Projects"
PROJECT_FILE_NAME = "project.json"


def sanitize_project_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_")
    return slug or "project"


def serialize_workspace_path(root: Path, path: str | Path | None) -> str:
    if not path:
        return ""
    resolved = Path(path)
    resolved = resolved if resolved.is_absolute() else (root / resolved)
    resolved = resolved.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def resolve_project_path(root: Path, value: str | Path | None) -> str:
    if not value:
        return ""
    path = Path(value)
    return str(path.resolve() if path.is_absolute() else (root / path).resolve())


@dataclass
class ProjectRecord:
    name: str
    slug: str
    ffs_files: list[str] = field(default_factory=list)
    touchstone_file: str = ""
    settings: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectRecord":
        name = str(payload.get("name", "")).strip()
        slug = sanitize_project_slug(str(payload.get("slug", name)))
        ffs_files = [str(item) for item in payload.get("ffs_files", []) if str(item).strip()]
        touchstone_file = str(payload.get("touchstone_file", "")).strip()
        settings = payload.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        return cls(name=name or slug, slug=slug, ffs_files=ffs_files, touchstone_file=touchstone_file, settings=settings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "slug": self.slug,
            "ffs_files": self.ffs_files,
            "touchstone_file": self.touchstone_file,
            "settings": self.settings,
        }

    def project_dir(self, root: Path) -> Path:
        return root / PROJECTS_DIRNAME / self.slug

    def workbook_path(self, root: Path) -> Path:
        return self.project_dir(root) / f"{self.slug}.xlsx"

    def extract_path(self, root: Path) -> Path:
        return self.project_dir(root) / f"{self.slug}_extracted_data.xlsx"

    def vswr_path(self, root: Path) -> Path:
        return self.project_dir(root) / f"{self.slug}_vswr.svg"


class ProjectStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.projects_dir = self.root / PROJECTS_DIRNAME

    def list_projects(self) -> list[ProjectRecord]:
        if not self.projects_dir.exists():
            return []
        projects: list[ProjectRecord] = []
        for directory in sorted((path for path in self.projects_dir.iterdir() if path.is_dir()), key=lambda item: item.name.lower()):
            project_file = directory / PROJECT_FILE_NAME
            if not project_file.exists():
                continue
            try:
                payload = json.loads(project_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            projects.append(ProjectRecord.from_dict(payload))
        return sorted(projects, key=lambda item: (item.name.lower(), item.slug.lower()))

    def load_project(self, slug: str) -> ProjectRecord:
        project_file = self.projects_dir / slug / PROJECT_FILE_NAME
        payload = json.loads(project_file.read_text(encoding="utf-8"))
        return ProjectRecord.from_dict(payload)

    def save_project(self, project: ProjectRecord, previous_slug: str | None = None) -> Path:
        self.projects_dir.mkdir(parents=True, exist_ok=True)
        target_dir = project.project_dir(self.root)
        if previous_slug and previous_slug != project.slug:
            source_dir = self.projects_dir / previous_slug
            if target_dir.exists():
                raise FileExistsError(f"Project '{project.name}' already exists.")
            if source_dir.exists():
                source_dir.rename(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        project_file = target_dir / PROJECT_FILE_NAME
        project_file.write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")
        return target_dir

    def delete_project(self, slug: str) -> None:
        target_dir = self.projects_dir / slug
        if target_dir.exists():
            shutil.rmtree(target_dir)
