"""每日复盘 quant_brief 上下文装配测试。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_analytics.pipelines.artifact_reader import ArtifactUnavailableError
from stock_analytics.pipelines.daily_review.quant_brief_context import (
    _project_brief,
    resolve_quant_brief_context,
)


def _brief() -> dict:
    return {
        "manifest": {"as_of_date": "2026-08-21", "run_id": "brief_run"},
        "risk_gates": {
            "status": "watch",
            "hard_stop": False,
            "summary": "存在需要观察的风险闸门。",
        },
        "veto": {"crowded_industries": []},
        "extreme_state": {
            "rules_version": "extreme-route-v1",
            "windows": ["crowded_window"],
            "composite_window_rank": "crowded_only",
            "position_bias_pp": 0.0,
            "action": "拥挤窗口：1 个行业达硬阈值。",
        },
        "position_policy": {"effective_band": "40%-50%", "temperature_band": "40%-50%"},
        "cross_cycle": {
            "rules_version": "odds-matrix-v1",
            "win_level": "中",
            "win_score": -5.0,
            "odds_level": "中",
            "odds_score": -5.0,
            "quadrature": "standard",
            "quadrature_label": "O 中或 S 中：标准档",
            "position_adjustment_pp": 0.0,
            "table": {"long": {}},
            "trajectory": {"divergence_transition": "extreme->synchronized 收敛确认"},
            "upgrade_triggers": ["60日扩散回升至 30% 以上"],
        },
        "sector": {
            "priority": [
                {
                    "industry_name": "银行",
                    "tags": "资金确认",
                    "reason": "结构分靠前。",
                    "structure_score": 56.02,
                    "crowding_temperature": 48.17,
                }
            ],
            "avoid": [{"industry_name": "通信"}],
        },
        "data_quality_notes": ["外盘风险只作宏观背景。"],
    }


def test_project_brief_extracts_l1_l4_fields() -> None:
    projected = _project_brief(_brief())

    assert projected["run_id"] == "brief_run"
    assert projected["rules_version"] == {
        "cross_cycle": "odds-matrix-v1",
        "extreme_state": "extreme-route-v1",
    }
    assert projected["risk_gates"]["status"] == "watch"
    assert projected["position_policy"]["effective_band"] == "40%-50%"
    assert projected["cross_cycle"]["win_level"] == "中"
    assert projected["cross_cycle"]["quadrature_label"] == "O 中或 S 中：标准档"
    assert projected["cross_cycle"]["trajectory"]["divergence_transition"].startswith(
        "extreme->synchronized"
    )
    assert projected["sector_priority"][0]["industry_name"] == "银行"
    assert projected["sector_avoid"] == ["通信"]
    assert projected["data_quality_notes"] == ["外盘风险只作宏观背景。"]


def test_resolve_uses_validated_product_when_available(monkeypatch) -> None:
    def fake_resolve(root, *, as_of_date, expected_artifact_type, run_id=None):
        class Run:
            run_dir = Path("tmp/fake_run")

            def read_json(self, filename: str) -> dict:
                return _brief()

            def path(self, filename: str) -> Path:
                return Path("tmp/fake_run") / filename

        return Run()

    monkeypatch.setattr(
        "stock_analytics.pipelines.daily_review.quant_brief_context.resolve_artifact_run",
        fake_resolve,
    )
    ran = []

    def fake_run_brief(as_of_date, analytics_base, *, storage_dir):
        ran.append(as_of_date)
        return _brief()

    monkeypatch.setattr(
        "stock_analytics.pipelines.daily_review.quant_brief_context._run_brief",
        fake_run_brief,
    )

    result = resolve_quant_brief_context(date(2026, 8, 21), analytics_base="tmp/analytics")

    assert result is not None
    assert result["run_id"] == "brief_run"
    assert ran == []


def test_resolve_falls_back_to_run_and_returns_none_on_failure(monkeypatch) -> None:
    def fake_resolve(root, *, as_of_date, expected_artifact_type, run_id=None):
        raise ArtifactUnavailableError("missing")

    monkeypatch.setattr(
        "stock_analytics.pipelines.daily_review.quant_brief_context.resolve_artifact_run",
        fake_resolve,
    )

    def fake_run_brief(as_of_date, analytics_base, *, storage_dir):
        return None

    monkeypatch.setattr(
        "stock_analytics.pipelines.daily_review.quant_brief_context._run_brief",
        fake_run_brief,
    )

    result = resolve_quant_brief_context(date(2026, 8, 21), analytics_base="tmp/analytics")

    assert result is None
