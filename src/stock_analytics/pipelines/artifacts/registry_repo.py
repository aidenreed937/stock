"""分析产物运行索引、数据血统、量化指标与生命周期控制面仓储 (ArtifactRegistryRepository)。"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path
from typing import Any

from stock_core.storage.sqlite_engine import SQLiteEngine, get_sqlite_engine


def _extract_metrics(
    manifest: Mapping[str, Any], explicit: Mapping[str, float] | None
) -> dict[str, float]:
    """从 Manifest 与显式字典提取所有数值型指标。"""
    res: dict[str, float] = {}
    if explicit:
        for k, v in explicit.items():
            if isinstance(v, int | float):
                res[str(k)] = float(v)

    for container_key in ("summary", "metrics", "outputs"):
        container = manifest.get(container_key)
        if isinstance(container, Mapping):
            for k, v in container.items():
                if isinstance(v, int | float) and not isinstance(v, bool):
                    res[str(k)] = float(v)
    return res


def _extract_watermarks(
    manifest: Mapping[str, Any],
) -> list[tuple[str, str, str | None, str | None]]:
    """提取上游数据源与水位。"""
    res: list[tuple[str, str, str | None, str | None]] = []
    wm_map = manifest.get("watermarks")
    if isinstance(wm_map, Mapping):
        for key, info in wm_map.items():
            if isinstance(info, Mapping):
                src = str(info.get("data_source") or key.split(".")[0])
                ds = str(info.get("dataset") or key.split(".")[-1])
                wm_date = info.get("upstream_watermark") or info.get("value_text")
                synced_at = info.get("upstream_synced_at") or info.get("synced_at")
                res.append(
                    (
                        src,
                        ds,
                        str(wm_date) if wm_date else None,
                        str(synced_at) if synced_at else None,
                    )
                )
    return res


def _extract_files(
    run_dir: Path, files: list[Mapping[str, Any]] | list[str] | None
) -> list[tuple[str, str, int, str]]:
    """收集产物文件清单、类型、大小与哈希。"""
    res: list[tuple[str, str, int, str]] = []
    if not run_dir.is_dir():
        return res

    file_names: list[str] = []
    if files:
        for f in files:
            file_names.append(f["rel_path"] if isinstance(f, Mapping) else str(f))
    else:
        file_names = [p.name for p in run_dir.glob("*") if p.is_file()]

    for name in file_names:
        p = run_dir / name
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        f_type = (
            "REPORT_MD"
            if ext == ".md"
            else (
                "CHART_PNG"
                if ext in {".png", ".jpg"}
                else (
                    "PANEL_PARQUET"
                    if ext == ".parquet"
                    else ("MANIFEST_JSON" if name == "manifest.json" else "DATA_JSON")
                )
            )
        )
        size = p.stat().st_size
        sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        res.append((f_type, name, size, sha))
    return res


def _persist_run_bundle(
    conn: sqlite3.Connection,
    manifest: Mapping[str, Any],
    r_dir: Path,
    files: list[Mapping[str, Any]] | list[str] | None,
    explicit_metrics: Mapping[str, float] | None,
    is_latest: bool,
) -> str:
    """在事务内将运行元数据、水位、指标与文件清单写入数据库。"""
    run_id = str(manifest["run_id"])
    pipe_name = str(manifest.get("artifact_type") or manifest.get("pipeline_name", "unknown"))
    as_of_d = str(manifest["as_of_date"])
    run_cls = str(manifest.get("run_class", "official"))
    cursor = conn.cursor()

    if is_latest:
        cursor.execute(
            "UPDATE pipeline_runs SET is_latest = 0 WHERE pipeline_name = ? AND as_of_date = ?;",
            (pipe_name, as_of_d),
        )

    cursor.execute(
        """
        INSERT INTO pipeline_runs (
            run_id, pipeline_name, as_of_date, run_class, status, is_latest,
            git_commit, artifact_root, duration_ms, generated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            status = excluded.status,
            is_latest = excluded.is_latest,
            duration_ms = excluded.duration_ms;
        """,
        (
            run_id,
            pipe_name,
            as_of_d,
            run_cls,
            str(manifest.get("run_status", "succeeded")),
            1 if is_latest else 0,
            str(manifest.get("provenance", {}).get("git_commit", "")),
            str(r_dir),
            int(manifest.get("duration_ms", 0)),
            str(manifest.get("generated_at", datetime.now().isoformat())),
        ),
    )

    for src, ds, wm_date, synced_at in _extract_watermarks(manifest):
        cursor.execute(
            """
            INSERT OR REPLACE INTO run_watermarks (run_id, data_source, dataset_name, upstream_watermark, upstream_synced_at)
            VALUES (?, ?, ?, ?, ?);
            """,
            (run_id, src, ds, wm_date, synced_at),
        )

    for m_key, m_val in _extract_metrics(manifest, explicit_metrics).items():
        cursor.execute(
            "INSERT OR REPLACE INTO run_metrics (run_id, metric_key, metric_value) VALUES (?, ?, ?);",
            (run_id, m_key, m_val),
        )

    for f_type, rel_p, size, sha in _extract_files(r_dir, files):
        cursor.execute(
            """
            INSERT INTO run_files (run_id, file_type, rel_path, file_size_bytes, sha256_hash)
            VALUES (?, ?, ?, ?, ?);
            """,
            (run_id, f_type, rel_p, size, sha),
        )

    return run_id


class ArtifactRegistryRepository:
    """分析产物元数据与指标仓储。"""

    def __init__(self, engine: SQLiteEngine | None = None) -> None:
        self.engine = engine or get_sqlite_engine()

    def record_run(
        self,
        manifest: Mapping[str, Any],
        run_dir: Path | str,
        files: list[Mapping[str, Any]] | list[str] | None = None,
        explicit_metrics: Mapping[str, float] | None = None,
        is_latest: bool = True,
    ) -> str:
        """记录单次管线运行及其水位、指标和文件清单 (ACID)。"""
        with self.engine.transaction() as conn:
            return _persist_run_bundle(
                conn, manifest, Path(run_dir), files, explicit_metrics, is_latest
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        """获取指定运行详情 (含指标与水位)。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pipeline_runs WHERE run_id = ?;", (run_id,))
            row = cursor.fetchone()
            if not row:
                return None
            res = dict(row)

            cursor.execute(
                "SELECT metric_key, metric_value FROM run_metrics WHERE run_id = ?;", (run_id,)
            )
            res["metrics"] = {r[0]: r[1] for r in cursor.fetchall()}

            cursor.execute(
                "SELECT data_source, dataset_name, upstream_watermark, upstream_synced_at FROM run_watermarks WHERE run_id = ?;",
                (run_id,),
            )
            res["watermarks"] = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM run_files WHERE run_id = ?;", (run_id,))
            res["files"] = [dict(r) for r in cursor.fetchall()]
            return res

    def list_runs(
        self,
        pipeline_name: str | None = None,
        as_of_date: date | str | None = None,
        run_class: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """多维条件查询运行列表。"""
        query = "SELECT * FROM pipeline_runs WHERE 1=1"
        params: list[Any] = []
        if pipeline_name:
            query += " AND pipeline_name = ?"
            params.append(pipeline_name)
        if as_of_date:
            query += " AND as_of_date = ?"
            params.append(str(as_of_date))
        if run_class:
            query += " AND run_class = ?"
            params.append(run_class)

        query += " ORDER BY as_of_date DESC, generated_at DESC LIMIT ?;"
        params.append(limit)

        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def find_stale_runs(
        self, dataset_name: str, upstream_watermark: date | str, cutoff_synced_at: str | None = None
    ) -> list[dict[str, Any]]:
        """反查因上游数据重刷而过时的下游产物。"""
        query = """
            SELECT r.run_id, r.pipeline_name, r.as_of_date, r.artifact_root, w.data_source, w.upstream_watermark, w.upstream_synced_at
            FROM pipeline_runs r
            JOIN run_watermarks w ON r.run_id = w.run_id
            WHERE w.dataset_name = ? AND w.upstream_watermark = ?
        """
        params: list[Any] = [dataset_name, str(upstream_watermark)]
        if cutoff_synced_at:
            query += " AND (w.upstream_synced_at IS NULL OR w.upstream_synced_at < ?)"
            params.append(cutoff_synced_at)

        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def diff_runs(self, run_id_a: str, run_id_b: str) -> dict[str, Any]:
        """横向比对两个 Run 的量化指标差异。"""
        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    COALESCE(a.metric_key, b.metric_key) as metric_key,
                    a.metric_value as val_a,
                    b.metric_value as val_b
                FROM (SELECT * FROM run_metrics WHERE run_id = ?) a
                FULL OUTER JOIN (SELECT * FROM run_metrics WHERE run_id = ?) b
                ON a.metric_key = b.metric_key;
                """,
                (run_id_a, run_id_b),
            )
            metric_diffs = []
            for row in cursor.fetchall():
                va = row["val_a"]
                vb = row["val_b"]
                delta = (vb - va) if (va is not None and vb is not None) else None
                metric_diffs.append(
                    {
                        "metric_key": row["metric_key"],
                        "val_a": va,
                        "val_b": vb,
                        "delta": round(delta, 4) if delta is not None else None,
                    }
                )
            return {"run_id_a": run_id_a, "run_id_b": run_id_b, "metrics": metric_diffs}

    def set_pinned(self, run_id: str, is_pinned: bool) -> bool:
        """设置产物锁定保护状态。"""
        with self.engine.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE pipeline_runs SET is_pinned = ? WHERE run_id = ?;",
                (1 if is_pinned else 0, run_id),
            )
            return cursor.rowcount > 0

    def collect_pruning_candidates(
        self,
        pipeline_name: str | None = None,
        older_than_days: float = 30.0,
        run_class: str | None = None,
    ) -> list[dict[str, Any]]:
        """基于安全策略筛选待清理产物 (排除 is_pinned=1 和 is_latest=1)。"""
        query = """
            SELECT run_id, pipeline_name, as_of_date, run_class, artifact_root, generated_at
            FROM pipeline_runs
            WHERE is_pinned = 0
              AND is_latest = 0
              AND generated_at < DATETIME('now', ?)
        """
        params: list[Any] = [f"-{int(older_than_days)} days"]
        if pipeline_name:
            query += " AND pipeline_name = ?"
            params.append(pipeline_name)
        if run_class:
            query += " AND run_class = ?"
            params.append(run_class)

        with self.engine.connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]


__all__ = ["ArtifactRegistryRepository"]
