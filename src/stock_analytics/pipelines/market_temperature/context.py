"""面向连续分析问答的市场温度查询上下文。"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.market_temperature.history import load_history_index
from stock_analytics.pipelines.market_temperature.snapshot import build_market_state_snapshot

DEFAULT_ARTIFACT_ROOT = Path("data/analytics/market_temperature")
_QUESTION_NAMES = {"overview", "trend", "risk", "history-extremes", "explain-date"}


@dataclass(frozen=True, slots=True)
class MarketAnalysisContext:
    """一次市场状态运行的只读查询上下文。"""

    artifact_root: Path
    run_dir: Path
    manifest: dict[str, Any]
    scores: dict[str, Any]
    snapshot: dict[str, Any]
    history: pl.DataFrame | None
    cache_status: dict[str, str]

    @classmethod
    def load(
        cls,
        artifact_root: Path | str = DEFAULT_ARTIFACT_ROOT,
        *,
        as_of: date | str | None = "latest",
        run_id: str | None = None,
    ) -> MarketAnalysisContext:
        """加载 latest 或指定观测日的已落盘运行。"""
        root = Path(artifact_root)
        run_dir = _resolve_run_dir(root, as_of=as_of, run_id=run_id)
        manifest = _read_json(run_dir / "manifest.json")
        scores = _read_json(run_dir / "scores.json")
        snapshot_path = run_dir / "snapshot.json"
        snapshot_exists = snapshot_path.exists()
        snapshot = (
            _read_json(snapshot_path)
            if snapshot_exists
            else build_market_state_snapshot(manifest=manifest, scores=scores, config_path=None)
        )
        history = load_history_index(root)
        return cls(
            artifact_root=root,
            run_dir=run_dir,
            manifest=manifest,
            scores=scores,
            snapshot=snapshot,
            history=history,
            cache_status={
                "snapshot": "hit" if snapshot_exists else "miss:snapshot_absent",
                "history_index": "hit" if history is not None else "miss:index_absent",
            },
        )

    @classmethod
    def load_latest(
        cls,
        artifact_root: Path | str = DEFAULT_ARTIFACT_ROOT,
    ) -> MarketAnalysisContext:
        """加载最近一次成功发布的运行。"""
        return cls.load(artifact_root, as_of="latest")

    def query(
        self,
        questions: Sequence[str],
        *,
        compare_date: date | str | None = None,
    ) -> dict[str, Any]:
        """按问题类型投影紧凑、可复用的分析证据。"""
        requested = {str(item).strip() for item in questions if str(item).strip()}
        if not requested:
            requested = {"overview"}
        unknown = requested - _QUESTION_NAMES
        if unknown:
            raise ValueError(f"不支持的问题类型: {', '.join(sorted(unknown))}")

        result: dict[str, Any] = {
            "as_of_date": self.snapshot.get("as_of_date"),
            "run_id": self.snapshot.get("run_id"),
            "current": {},
            "provenance": self.snapshot.get("provenance", {}),
            "identity": self.snapshot.get("identity", {}),
            "cache": self.cache_status,
        }
        if "overview" in requested:
            result["current"] = self.overview()
        if "trend" in requested:
            result["trend"] = self.trend()
        if "risk" in requested:
            result["risk"] = self.risk()
        if "history-extremes" in requested:
            result["history_extremes"] = self.history_extremes()
        if "explain-date" in requested:
            if compare_date is None:
                raise ValueError("explain-date 需要 --compare-date")
            result["explain_date"] = self.explain_date(compare_date)
        return result

    def overview(self) -> dict[str, Any]:
        """返回当前综合温度、维度和数据质量。"""
        return {
            "composite": self.snapshot.get("composite", {}),
            "dimensions": self.snapshot.get("dimensions", []),
            "dimension_groups": self.snapshot.get("dimension_groups", {}),
            "data_quality": self.snapshot.get("data_quality", {}),
        }

    def trend(self) -> dict[str, Any]:
        """返回 1/5/20 个交易日趋势，缺少索引时明确披露。"""
        snapshot_trend = self.snapshot.get("trend", {})
        result = dict(snapshot_trend) if isinstance(snapshot_trend, dict) else {}
        if self.history is None:
            return result
        rows = _latest_history_rows(self.history, self.snapshot.get("as_of_date"))
        if not rows:
            return result
        for name, offset in (("d5", 5), ("d20", 20)):
            result[name] = _window_trend(rows, offset, self.snapshot)
        return result

    def risk(self) -> dict[str, Any]:
        """返回系统性风险及其触发、缓冲信号。"""
        risk = self.snapshot.get("systemic_risk", {})
        return risk if isinstance(risk, dict) else {}

    def history_extremes(self) -> dict[str, Any]:
        """返回历史高低温和当前历史分位。"""
        if self.history is None:
            return {"status": "unavailable", "reason": "历史索引不存在"}
        rows = [
            row
            for row in _latest_history_rows(self.history, self.snapshot.get("as_of_date"))
            if row.get("composite_temperature") is not None
        ]
        if not rows:
            return {"status": "unavailable", "reason": "历史索引没有可用综合温度"}
        ordered = sorted(rows, key=lambda row: float(row["composite_temperature"]))
        current = _as_float(_mapping(self.snapshot.get("composite")).get("temperature"))
        percentile = None
        if current is not None:
            percentile = round(
                sum(float(row["composite_temperature"]) <= current for row in rows)
                / len(rows)
                * 100,
                2,
            )
        return {
            "status": "ok",
            "count": len(rows),
            "history_low": _history_summary(ordered[0]),
            "history_high": _history_summary(ordered[-1]),
            "current_percentile": percentile,
        }

    def explain_date(self, target_date: date | str) -> dict[str, Any]:
        """解释指定日期，并与当前运行比较。"""
        target = self.load(self.artifact_root, as_of=target_date)
        target_composite = _as_float(_mapping(target.snapshot.get("composite")).get("temperature"))
        current_composite = _as_float(_mapping(self.snapshot.get("composite")).get("temperature"))
        return {
            "target": {
                "as_of_date": target.snapshot.get("as_of_date"),
                "run_id": target.snapshot.get("run_id"),
                "composite": target.snapshot.get("composite", {}),
                "dimensions": target.snapshot.get("dimensions", []),
                "dimension_groups": target.snapshot.get("dimension_groups", {}),
                "risk": target.risk(),
                "data_quality": target.snapshot.get("data_quality", {}),
            },
            "compare_to_current": {
                "as_of_date": self.snapshot.get("as_of_date"),
                "composite_delta": (
                    round(target_composite - current_composite, 2)
                    if target_composite is not None and current_composite is not None
                    else None
                ),
                "current_composite": current_composite,
                "target_composite": target_composite,
            },
        }


def _resolve_run_dir(root: Path, *, as_of: date | str | None, run_id: str | None) -> Path:
    if as_of is None or str(as_of).lower() == "latest":
        manifest_path = root / "latest" / "manifest.json"
        manifest = _read_json(manifest_path)
        resolved_date_text = str(manifest.get("as_of_date") or "")
        resolved_run_id = run_id or str(manifest.get("run_id") or "")
        candidate = root / "runs" / f"as_of={resolved_date_text}" / resolved_run_id
        return candidate if candidate.is_dir() else manifest_path.parent

    resolved_trade_date: date = as_of if isinstance(as_of, date) else date.fromisoformat(as_of)
    date_root = root / "runs" / f"as_of={resolved_trade_date.isoformat()}"
    if run_id is not None:
        candidate = date_root / run_id
        if not candidate.is_dir():
            raise FileNotFoundError(f"未找到市场温度运行: {candidate}")
        return candidate
    candidates = sorted(
        path
        for path in date_root.glob("run_*")
        if path.is_dir() and (path / "manifest.json").exists()
    )
    if not candidates:
        raise FileNotFoundError(f"未找到市场温度观测日产物: {resolved_trade_date.isoformat()}")
    return candidates[-1]


def _latest_history_rows(history: pl.DataFrame, as_of: Any) -> list[dict[str, Any]]:
    rows = history.to_dicts()
    target = _as_date(as_of)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        row_date = _as_date(row.get("as_of_date"))
        if not bool(row.get("is_latest_for_date", True)):
            continue
        if target is not None and (row_date is None or row_date > target):
            continue
        filtered.append(row)
    return sorted(filtered, key=lambda row: _as_date(row.get("as_of_date")) or date.min)


def _window_trend(
    rows: list[dict[str, Any]],
    offset: int,
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    if len(rows) <= offset:
        return {"status": "unavailable", "reason": f"历史样本不足 {offset} 个交易日"}
    current = rows[-1]
    previous = rows[-offset - 1]
    current_value = _as_float(current.get("composite_temperature"))
    previous_value = _as_float(previous.get("composite_temperature"))
    return {
        "status": "ok" if current_value is not None and previous_value is not None else "partial",
        "from_date": str(previous.get("as_of_date")),
        "to_date": str(current.get("as_of_date") or snapshot.get("as_of_date")),
        "composite_delta": (
            round(current_value - previous_value, 2)
            if current_value is not None and previous_value is not None
            else None
        ),
        "from_composite": previous_value,
        "to_composite": current_value,
        "dimensions": _dimension_deltas(previous, current),
    }


def _dimension_deltas(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> list[dict[str, Any]]:
    previous_items = {
        str(item.get("dimension_id")): item
        for item in _json_list(previous.get("dimensions_json"))
        if item.get("dimension_id")
    }
    result: list[dict[str, Any]] = []
    for item in _json_list(current.get("dimensions_json")):
        dimension_id = str(item.get("dimension_id") or "")
        previous_item = previous_items.get(dimension_id)
        current_value = _as_float(item.get("temperature"))
        previous_value = (
            _as_float(previous_item.get("temperature")) if previous_item is not None else None
        )
        if dimension_id and current_value is not None and previous_value is not None:
            result.append(
                {
                    "dimension_id": dimension_id,
                    "delta": round(current_value - previous_value, 2),
                }
            )
    return result


def _history_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "as_of_date": str(row.get("as_of_date")),
        "run_id": row.get("run_id"),
        "composite_temperature": row.get("composite_temperature"),
        "risk_level": row.get("risk_level"),
    }


def _json_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return (
        [dict(item) for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, list)
        else []
    )


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"缺少市场温度产物: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"市场温度 JSON 产物必须是对象: {path}")
    return value


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


__all__ = ["DEFAULT_ARTIFACT_ROOT", "MarketAnalysisContext"]
