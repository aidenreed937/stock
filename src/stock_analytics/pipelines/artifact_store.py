"""业务管线运行产物的共享存储生命周期。"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import TYPE_CHECKING, Any, Literal
from uuid import uuid4

from stock_analytics.pipelines.artifact_contracts import RunClass, normalize_run_class
from stock_analytics.pipelines.artifact_index import rebuild_run_index
from stock_analytics.pipelines.artifact_integrity import build_artifact_integrity
from stock_analytics.pipelines.artifact_validator import ArtifactValidator

if TYPE_CHECKING:
    import polars as pl


_ARTIFACT_VALIDATOR = ArtifactValidator()


@dataclass(frozen=True, slots=True)
class ArtifactRunPaths:
    """一次管线运行的通用路径。"""

    root: Path
    run_dir: Path
    latest_dir: Path
    artifact_type: str | None = None
    run_class: RunClass = "official"


class ArtifactStore:
    """构造运行路径并以事务方式发布管线产物。"""

    def __init__(self, paths: ArtifactRunPaths) -> None:
        self.paths = paths

    @staticmethod
    def build_run_paths(
        as_of_date: date,
        artifact_root: Path | str,
        run_id: str | None = None,
        *,
        latest_root: Path | str | None = None,
        run_class: RunClass = "official",
    ) -> ArtifactRunPaths:
        """按业务日期和运行 ID 构造通用运行路径。"""
        root = Path(artifact_root)
        actual_run_id = run_id or (
            f"run_{datetime.now().astimezone().strftime('%Y%m%dT%H%M%S%f')}_{uuid4().hex[:8]}"
        )
        run_dir = root / "runs" / f"as_of={as_of_date.isoformat()}" / actual_run_id
        latest_dir = (Path(latest_root) if latest_root is not None else root) / "latest"
        return ArtifactRunPaths(
            root=root,
            run_dir=run_dir,
            latest_dir=latest_dir,
            run_class=normalize_run_class(run_class),
        )

    def transaction(self, *, update_latest: bool = True) -> ArtifactWriteSession:
        """创建临时写入事务，成功退出上下文后发布运行产物。"""
        return ArtifactWriteSession(self.paths, update_latest=update_latest)


class ArtifactWriteSession(AbstractContextManager["ArtifactWriteSession"]):
    """在临时目录写入并原子发布一组管线产物。"""

    def __init__(self, paths: ArtifactRunPaths, *, update_latest: bool) -> None:
        self.paths = paths
        self.update_latest = update_latest
        self._staging_dir: Path | None = None
        self._written_names: list[str] = []
        self._manifest_payload: dict[str, Any] | None = None

    def __enter__(self) -> ArtifactWriteSession:
        if self.paths.run_dir.exists():
            raise FileExistsError(f"运行产物目录已存在: {self.paths.run_dir}")
        self.paths.run_dir.parent.mkdir(parents=True, exist_ok=True)
        self._staging_dir = Path(
            mkdtemp(prefix=f".{self.paths.run_dir.name}.", dir=self.paths.run_dir.parent)
        )
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> Literal[False]:
        try:
            if exc_type is None:
                self._publish()
        finally:
            if self._staging_dir is not None:
                _remove_path(self._staging_dir)
                self._staging_dir = None
        return False

    def write_json(self, name: str, payload: Mapping[str, Any]) -> None:
        path = self._prepare_path(name)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default),
            encoding="utf-8",
        )
        normalized = Path(name).as_posix()
        self._written_names.append(normalized)
        if normalized == "manifest.json":
            self._manifest_payload = payload if isinstance(payload, dict) else dict(payload)

    def write_text(self, name: str, content: str) -> None:
        path = self._prepare_path(name)
        path.write_text(content, encoding="utf-8")
        self._written_names.append(Path(name).as_posix())

    def write_parquet(self, name: str, frame: pl.DataFrame) -> None:
        path = self._prepare_path(name)
        frame.write_parquet(path)
        self._written_names.append(Path(name).as_posix())

    def write_csv(self, name: str, frame: pl.DataFrame) -> None:
        path = self._prepare_path(name)
        frame.write_csv(path)
        self._written_names.append(Path(name).as_posix())

    def _prepare_path(self, name: str) -> Path:
        if self._staging_dir is None:
            raise RuntimeError("Artifact 写入事务尚未开始")
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"Artifact 文件名必须是运行目录内的相对路径: {name}")
        path = self._staging_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _publish(self) -> None:
        if self._staging_dir is None:
            raise RuntimeError("Artifact 写入事务尚未开始")
        if self._manifest_payload is not None:
            self._manifest_payload["artifact_files"] = list(dict.fromkeys(self._written_names))
            self._manifest_payload["run_class"] = self.paths.run_class
            self._manifest_payload["artifact_integrity"] = build_artifact_integrity(
                self._staging_dir,
                self._written_names,
            )
            (self._staging_dir / "manifest.json").write_text(
                json.dumps(
                    self._manifest_payload,
                    ensure_ascii=False,
                    indent=2,
                    default=_json_default,
                ),
                encoding="utf-8",
            )
        _ARTIFACT_VALIDATOR.validate_or_raise(
            self._staging_dir,
            check_path=False,
            expected_artifact_type=self.paths.artifact_type,
            expected_run_class=self.paths.run_class,
            require_integrity=True,
        )
        os.replace(self._staging_dir, self.paths.run_dir)
        self._staging_dir = None
        try:
            _ARTIFACT_VALIDATOR.validate_or_raise(
                self.paths.run_dir,
                expected_artifact_type=self.paths.artifact_type,
                expected_run_class=self.paths.run_class,
                require_integrity=True,
            )
            rebuild_run_index(self.paths.root)
            if not self.update_latest:
                return
            self._publish_latest()
        except Exception:
            try:
                shutil.rmtree(self.paths.run_dir)
            except FileNotFoundError:
                pass
            except OSError as rollback_error:
                raise RuntimeError(
                    f"latest 发布失败且运行目录回滚失败: {self.paths.run_dir}"
                ) from rollback_error
            try:
                rebuild_run_index(self.paths.root)
            except Exception as index_error:
                raise RuntimeError(
                    f"运行目录回滚后索引恢复失败: {self.paths.root}"
                ) from index_error
            raise

    def _publish_latest(self) -> None:
        latest_dir = self.paths.latest_dir
        latest_dir.parent.mkdir(parents=True, exist_ok=True)
        staging_latest = Path(mkdtemp(prefix=f".{latest_dir.name}.", dir=latest_dir.parent))
        staging_latest_published = False
        preserve_backup = False
        backup_latest: Path | None = None
        try:
            for name in self._written_names:
                target = staging_latest / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.paths.run_dir / name, target)
            _ARTIFACT_VALIDATOR.validate_latest_or_raise(
                staging_latest,
                source_dir=self.paths.run_dir,
                expected_artifact_type=self.paths.artifact_type,
                expected_run_class=self.paths.run_class,
                require_integrity=True,
            )

            if latest_dir.exists() or latest_dir.is_symlink():
                backup_latest = latest_dir.with_name(f".{latest_dir.name}.old-{uuid4().hex}")
                os.replace(latest_dir, backup_latest)
            try:
                os.replace(staging_latest, latest_dir)
                staging_latest_published = True
            except Exception:
                if backup_latest is None:
                    raise
                try:
                    os.replace(backup_latest, latest_dir)
                except Exception as restore_error:
                    preserve_backup = True
                    raise RuntimeError(
                        f"latest 发布失败且旧版本恢复失败，备份保留在: {backup_latest}"
                    ) from restore_error
                backup_latest = None
                raise
        finally:
            if not staging_latest_published:
                _remove_path(staging_latest)
            if backup_latest is not None and not preserve_backup:
                _remove_path(backup_latest)


def _remove_path(path: Path | None) -> None:
    if path is None or (not path.exists() and not path.is_symlink()):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _json_default(value: object) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return str(value)


__all__ = ["ArtifactRunPaths", "ArtifactStore", "ArtifactWriteSession"]
