"""个股排雷决策合并测试。"""

import polars as pl

from stock_analytics.pipelines.stock_screen.decision import (
    RuleEvaluation,
    build_decision_tables,
)
from stock_reporting.interpretation.stock_screen.config import RuleConfig


def test_three_warnings_upgrade_to_temporary_exclusion() -> None:
    universe = pl.DataFrame({"symbol": ["000001.SZ"], "name": ["测试公司"], "list_date": [None]})
    rules = [
        RuleEvaluation(
            RuleConfig(rule_id=f"warn_{index}", enabled=True, scope="all_market"),
            "yellow_warn",
            pl.DataFrame(
                {
                    "symbol": ["000001.SZ"],
                    "rule_id": [f"warn_{index}"],
                    "status": ["warn"],
                    "reason": ["测试预警"],
                    "note": [""],
                    "value": [None],
                }
            ),
        )
        for index in range(3)
    ]

    result = build_decision_tables(universe, rules, as_of_date="2026-08-20")

    assert result["excluded"]["symbol"].to_list() == ["000001.SZ"]
    assert any("warn_count=3" in reason for reason in result["excluded"]["reasons"].item())


def test_hard_failure_takes_precedence_over_warning_count() -> None:
    universe = pl.DataFrame({"symbol": ["000001.SZ"], "name": ["测试公司"]})
    evaluation = RuleEvaluation(
        RuleConfig(rule_id="st_marked", enabled=True, scope="all_market"),
        "hard_exclusion",
        pl.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "rule_id": ["st_marked"],
                "status": ["fail"],
                "reason": ["名称 ST测试"],
                "note": [""],
                "value": [None],
            }
        ),
    )

    result = build_decision_tables(universe, [evaluation])

    assert result["excluded"]["level"].item() == "excluded"


def test_hard_rule_data_missing_downgrades_to_warned() -> None:
    universe = pl.DataFrame({"symbol": ["000001.SZ"], "name": ["测试公司"]})
    evaluation = RuleEvaluation(
        RuleConfig(rule_id="negative_equity", enabled=True, scope="all_market"),
        "hard_exclusion",
        pl.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "rule_id": ["negative_equity"],
                "status": ["not_evaluated"],
                "reason": ["缺少 balancesheet.total_hldr_eqy_exc_min_int"],
                "note": [""],
                "value": [None],
            }
        ),
    )

    result = build_decision_tables(universe, [evaluation])

    assert result["passed"]["symbol"].to_list() == []
    assert result["warned"]["level"].item() == "warned"
    assert result["warned"]["reasons"].to_list() == [["核心排雷规则数据缺失未评估，降级观察"]]
    assert result["warned"]["missing_rules"].to_list() == [["negative_equity"]]


def test_yellow_rule_data_missing_keeps_passed() -> None:
    universe = pl.DataFrame({"symbol": ["000001.SZ"], "name": ["测试公司"]})
    evaluation = RuleEvaluation(
        RuleConfig(rule_id="forecast_plunge", enabled=True, scope="all_market"),
        "yellow_warn",
        pl.DataFrame(
            {
                "symbol": ["000001.SZ"],
                "rule_id": ["forecast_plunge"],
                "status": ["not_evaluated"],
                "reason": ["缺少 forecast.p_change_min"],
                "note": [""],
                "value": [None],
            }
        ),
    )

    result = build_decision_tables(universe, [evaluation])

    assert result["passed"]["symbol"].to_list() == ["000001.SZ"]
    assert result["warned"]["symbol"].to_list() == []
