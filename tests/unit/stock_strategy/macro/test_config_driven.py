"""测试宏观策略、审计与研报的全面配置驱动 (Config-Driven) 机制。"""

import tempfile
from datetime import date
from pathlib import Path

from stock_reporting.interpretation.macro_risk.logic import (
    evaluate_macro_risk,
)
from stock_strategy.macro.audit import (
    load_macro_regimes,
    load_stress_tests,
)
from stock_strategy.macro.report import (
    _runner_for,
    load_benchmarks,
)


def test_load_benchmarks_from_yaml() -> None:
    custom_yaml = """
benchmarks:
  - symbol: "000985.CSI"
    name: "中证全指"
  - symbol: "000852.SH"
    name: "中证1000"
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(custom_yaml)
        tmp_p = f.name

    try:
        benches = load_benchmarks(tmp_p)
        assert len(benches) == 2
        assert benches[0] == ("000985.CSI", "中证全指")
        assert benches[1] == ("000852.SH", "中证1000")
    finally:
        Path(tmp_p).unlink(missing_ok=True)


def test_load_macro_regimes_from_yaml() -> None:
    custom_yaml = """
macro_regimes:
  - name: "自定义测试范式"
    start_date: "2020-01-01"
    end_date: "2020-12-31"
    description: "测试范式描述"
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(custom_yaml)
        tmp_p = f.name

    try:
        regimes = load_macro_regimes(tmp_p)
        assert len(regimes) == 1
        assert regimes[0] == (
            "自定义测试范式",
            date(2020, 1, 1),
            date(2020, 12, 31),
            "测试范式描述",
        )
    finally:
        Path(tmp_p).unlink(missing_ok=True)


def test_load_stress_tests_from_yaml() -> None:
    custom_yaml = """
stress_tests:
  - name: "测试极端危机"
    start_date: "2020-02-01"
    end_date: "2020-03-01"
    description: "危机描述"
"""
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(custom_yaml)
        tmp_p = f.name

    try:
        st = load_stress_tests(tmp_p)
        assert len(st) == 1
        assert st[0] == ("测试极端危机", date(2020, 2, 1), date(2020, 3, 1), "危机描述")
    finally:
        Path(tmp_p).unlink(missing_ok=True)


def test_runner_for_thresholds_transparency() -> None:
    spec = {
        "strategy_class": "MacroRiskV3Strategy",
        "benchmark_symbol": "000300.SH",
        "symbols": ["000300.SH"],
        "initial_weights": {"000300.SH": 1.0},
        "ma_window": 30,
        "thresholds": {
            "panic_threshold": 82.5,
            "panic_entry_threshold": 68.0,
            "overheat_threshold": 72.0,
        },
    }
    runner, benchmark = _runner_for(spec)
    assert benchmark == "000300.SH"
    strat = runner.strategy
    assert strat.ma_window == 30
    assert strat.panic_threshold == 82.5
    assert strat.panic_entry_threshold == 68.0
    assert strat.overheat_threshold == 72.0


def test_reporting_config_driven_evaluation() -> None:
    row = {
        "trade_date": "2026-08-28",
        "overheat_index": 68.0,
        "panic_index": 30.0,
        "dim_crowding": 88.0,  # 严重过热 >= 85
        "dim_leverage": 25.0,  # 杠杆健康 <= 30
        "dim_sentiment": 15.0,  # 极度自满 <= 20
        "dim_valuation": 45.0,  # 估值合理 default
        "dim_breadth": 35.0,
        "dim_flow": 50.0,
    }
    res = evaluate_macro_risk(row)
    assert res["level"] == "danger"
    assert "极度狂热" in res["status"]

    tiers = {t["name"]: {m["name"]: m for m in t["metrics"]} for t in res["risk_tiers"]}
    assert tiers["生存与毁灭级风险 (硬约束 / 强平与失速)"]["换手拥挤"]["status"] == "严重过热"
    assert tiers["生存与毁灭级风险 (硬约束 / 强平与失速)"]["换手拥挤"]["badge"] == "🔴"
    assert tiers["生存与毁灭级风险 (硬约束 / 强平与失速)"]["两融杠杆"]["status"] == "杠杆健康"
    assert tiers["生存与毁灭级风险 (硬约束 / 强平与失速)"]["两融杠杆"]["badge"] == "🟢"
    assert tiers["拐点与博弈级信号 (快变量 / 情绪与超跌)"]["期权情绪"]["status"] == "极度自满"
    assert tiers["拐点与博弈级信号 (快变量 / 情绪与超跌)"]["期权情绪"]["badge"] == "🔴"
