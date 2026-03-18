from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECTS_DIRNAME = "Projects"
PROJECT_FILE_NAME = "project.json"
CURRENT_PROJECT_SCHEMA_VERSION = 2


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_ffs_items(payload: object) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payload:
        if isinstance(raw, dict):
            path = str(raw.get("path", "")).strip()
            enabled = bool(raw.get("enabled", True))
        else:
            path = str(raw).strip()
            enabled = True
        if not path or path in seen:
            continue
        items.append({"path": path, "enabled": enabled})
        seen.add(path)
    return items


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
    schema_version: int = CURRENT_PROJECT_SCHEMA_VERSION
    ffs_items: list[dict[str, Any]] = field(default_factory=list)
    touchstone_file: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    presets: dict[str, dict[str, Any]] = field(default_factory=dict)
    active_preset: str = ""
    run_state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProjectRecord":
        name = str(payload.get("name", "")).strip()
        slug = sanitize_project_slug(str(payload.get("slug", name)))
        schema_version = int(payload.get("schema_version", 1) or 1)
        ffs_items = _normalize_ffs_items(payload.get("ffs_items", []))
        if not ffs_items:
            ffs_items = _normalize_ffs_items(payload.get("ffs_files", []))
        touchstone_file = str(payload.get("touchstone_file", "")).strip()
        settings = payload.get("settings", {})
        if not isinstance(settings, dict):
            settings = {}
        presets = payload.get("presets", {})
        if not isinstance(presets, dict):
            presets = {}
        active_preset = str(payload.get("active_preset", "")).strip()
        run_state = payload.get("run_state", payload.get("run_metadata", {}))
        if not isinstance(run_state, dict):
            run_state = {}
        return cls(
            name=name or slug,
            slug=slug,
            schema_version=max(1, schema_version),
            ffs_items=ffs_items,
            touchstone_file=touchstone_file,
            settings=settings,
            presets={str(key): value for key, value in presets.items() if isinstance(value, dict)},
            active_preset=active_preset,
            run_state=run_state,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CURRENT_PROJECT_SCHEMA_VERSION,
            "name": self.name,
            "slug": self.slug,
            "ffs_items": self.ffs_items,
            "touchstone_file": self.touchstone_file,
            "settings": self.settings,
            "presets": self.presets,
            "active_preset": self.active_preset,
            "run_state": self.run_state,
        }

    @property
    def ffs_files(self) -> list[str]:
        return [str(item.get("path", "")).strip() for item in self.ffs_items if str(item.get("path", "")).strip()]

    @property
    def enabled_ffs_files(self) -> list[str]:
        return [
            str(item.get("path", "")).strip()
            for item in self.ffs_items
            if str(item.get("path", "")).strip() and bool(item.get("enabled", True))
        ]

    def project_dir(self, root: Path) -> Path:
        return root / PROJECTS_DIRNAME / self.slug

    def project_file(self, root: Path) -> Path:
        return self.project_dir(root) / PROJECT_FILE_NAME

    def record_activity(self, action: str, **extra: Any) -> None:
        history = self.run_state.setdefault("history", [])
        if not isinstance(history, list):
            history = []
            self.run_state["history"] = history
        entry = {"action": action, "at": utc_now_iso()}
        entry.update(extra)
        history.insert(0, entry)
        del history[20:]

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

    def _rename_slugged_outputs(self, project_dir: Path, original_slug: str, new_slug: str) -> None:
        if not original_slug or original_slug == new_slug or not project_dir.exists():
            return
        candidates = sorted((path for path in project_dir.rglob("*") if path.is_file()), key=lambda path: len(path.parts), reverse=True)
        for path in candidates:
            if not path.name.startswith(original_slug):
                continue
            renamed = path.with_name(path.name.replace(original_slug, new_slug, 1))
            if renamed == path:
                continue
            renamed.parent.mkdir(parents=True, exist_ok=True)
            path.rename(renamed)

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
        project.schema_version = CURRENT_PROJECT_SCHEMA_VERSION
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

    def unique_slug(self, desired_name: str, exclude_slug: str = "") -> str:
        base_slug = sanitize_project_slug(desired_name)
        slug = base_slug
        suffix = 2
        existing = {project.slug for project in self.list_projects() if project.slug != exclude_slug}
        while slug in existing:
            slug = f"{base_slug}_{suffix}"
            suffix += 1
        return slug

    def duplicate_project(self, source_slug: str, new_name: str) -> ProjectRecord:
        source = self.load_project(source_slug)
        new_slug = self.unique_slug(new_name)
        duplicate = ProjectRecord(
            name=new_name,
            slug=new_slug,
            schema_version=CURRENT_PROJECT_SCHEMA_VERSION,
            ffs_items=[dict(item) for item in source.ffs_items],
            touchstone_file=source.touchstone_file,
            settings=dict(source.settings),
            presets={key: dict(value) for key, value in source.presets.items()},
            active_preset=source.active_preset,
            run_state={},
        )
        source_dir = source.project_dir(self.root)
        target_dir = duplicate.project_dir(self.root)
        shutil.copytree(source_dir, target_dir)
        self._rename_slugged_outputs(target_dir, source.slug, duplicate.slug)
        duplicate.record_activity("duplicated", source_slug=source_slug)
        self.save_project(duplicate)
        return duplicate

    def export_project_bundle(self, slug: str, bundle_path: Path) -> Path:
        project = self.load_project(slug)
        project_dir = project.project_dir(self.root)
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in project_dir.rglob("*"):
                if path.is_file():
                    archive.write(path, arcname=f"{project.slug}/{path.relative_to(project_dir).as_posix()}")
        return bundle_path

    def import_project_bundle(self, bundle_path: Path) -> ProjectRecord:
        with zipfile.ZipFile(bundle_path, "r") as archive:
            members = [name for name in archive.namelist() if name and not name.endswith("/")]
            if not members:
                raise ValueError("Bundle is empty.")
            root_prefix = members[0].split("/", 1)[0]
            project_member = next((name for name in members if name.endswith(f"/{PROJECT_FILE_NAME}")), "")
            if not project_member:
                raise ValueError("Bundle does not contain a project.json file.")
            payload = json.loads(archive.read(project_member).decode("utf-8"))
            project = ProjectRecord.from_dict(payload)
            original_slug = project.slug or sanitize_project_slug(root_prefix)
            project.slug = self.unique_slug(project.name, exclude_slug="")
            if not project.name:
                project.name = project.slug
            target_dir = project.project_dir(self.root)
            target_dir.mkdir(parents=True, exist_ok=True)
            for member in members:
                relative = member.split("/", 1)[1] if "/" in member else ""
                if not relative:
                    continue
                out_path = target_dir / relative
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(archive.read(member))
            self._rename_slugged_outputs(target_dir, original_slug, project.slug)
            project.record_activity("imported", source_slug=original_slug, bundle_name=bundle_path.name)
            self.save_project(project)
            return project
