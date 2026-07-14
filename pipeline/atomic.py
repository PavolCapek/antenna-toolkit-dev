from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from uuid import uuid4


class AtomicPublishError(RuntimeError):
    pass


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


class StageWorkspace:
    """Same-volume staging area with grouped publish and rollback."""

    def __init__(self, final_root: str | Path, stage_key: str):
        self.final_root = Path(final_root).resolve()
        self.final_root.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix=f".{stage_key}-staging-", dir=self.final_root))
        self._published = False

    def __enter__(self) -> "StageWorkspace":
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def __del__(self) -> None:
        root = getattr(self, "root", None)
        if isinstance(root, Path) and root.exists():
            shutil.rmtree(root, ignore_errors=True)

    def path(self, relative: str | Path) -> Path:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Stage path must be relative: {relative}")
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def publish(
        self,
        required: list[str | Path],
        *,
        obsolete: list[str | Path] | None = None,
        validate: list[str | Path] | None = None,
    ) -> None:
        required_paths = [Path(item) for item in required]
        obsolete_paths = [Path(item) for item in (obsolete or [])]
        validation_paths = [Path(item) for item in (validate or [])]
        for relative in required_paths + obsolete_paths + validation_paths:
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"Publish path must be relative: {relative}")
        missing = [
            str(relative)
            for relative in required_paths + validation_paths
            if not (self.root / relative).exists()
        ]
        if missing:
            raise AtomicPublishError(f"Stage did not produce required outputs: {', '.join(missing)}")

        backup_root = self.final_root / f".publish-backup-{uuid4().hex}"
        moved_old: list[Path] = []
        published: list[Path] = []
        all_targets: list[Path] = []
        seen: set[Path] = set()
        for relative in required_paths + obsolete_paths:
            if relative not in seen:
                seen.add(relative)
                all_targets.append(relative)

        publish_succeeded = False
        rollback_errors: list[str] = []
        try:
            for relative in all_targets:
                final_path = self.final_root / relative
                if not (final_path.exists() or final_path.is_symlink()):
                    continue
                backup_path = backup_root / relative
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                final_path.replace(backup_path)
                moved_old.append(relative)

            for relative in required_paths:
                staged_path = self.root / relative
                final_path = self.final_root / relative
                final_path.parent.mkdir(parents=True, exist_ok=True)
                staged_path.replace(final_path)
                published.append(relative)
        except Exception as exc:
            for relative in reversed(published):
                _remove_path(self.final_root / relative)
            for relative in reversed(moved_old):
                backup_path = backup_root / relative
                final_path = self.final_root / relative
                try:
                    final_path.parent.mkdir(parents=True, exist_ok=True)
                    backup_path.replace(final_path)
                except Exception as restore_exc:
                    rollback_errors.append(f"{relative}: {restore_exc}")
            detail = f"; backups retained at {backup_root}; rollback errors: {'; '.join(rollback_errors)}" if rollback_errors else ""
            raise AtomicPublishError(f"Could not publish stage outputs: {exc}{detail}") from exc
        else:
            publish_succeeded = True
        finally:
            if backup_root.exists() and (publish_succeeded or not rollback_errors):
                shutil.rmtree(backup_root, ignore_errors=True)

        self._published = True
