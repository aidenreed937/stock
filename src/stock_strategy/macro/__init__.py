"""宏观风控与大类资产配置策略子包。"""

from __future__ import annotations

from stock_strategy.macro.assembly import (
    assemble_macro_panel,
    load_price_panel,
)
from stock_strategy.macro.audit import (
    MACRO_REGIMES,
    STRESS_TEST_PERIODS,
    StabilityAuditResult,
    assert_stability_guardrails,
    load_macro_regimes,
    load_stress_tests,
    run_full_stability_audit,
)
from stock_strategy.macro.audit_calc import (
    compute_rolling_stats,
    compute_slice_metrics,
    compute_stress_test,
)
from stock_strategy.macro.live import (
    LiveOrderInstruction,
    LiveSignalInspectionResult,
    inspect_live_signal,
)
from stock_strategy.macro.report import (
    build_multi_strategy_comparison_report,
    build_v3_v4_comparison_report,
    compute_metrics,
    compute_stats,
    load_all_strategy_specs,
    load_benchmarks,
    load_strategy_spec,
    nav_from_close,
)
from stock_strategy.macro.runner import MacroRiskRunner
from stock_strategy.macro.walk_forward import (
    WalkForwardResult,
    WalkForwardSlice,
    render_walk_forward_markdown,
    run_walk_forward_analysis,
)

__all__ = [
    "MACRO_REGIMES",
    "STRESS_TEST_PERIODS",
    "LiveOrderInstruction",
    "LiveSignalInspectionResult",
    "MacroRiskRunner",
    "StabilityAuditResult",
    "WalkForwardResult",
    "WalkForwardSlice",
    "assemble_macro_panel",
    "assert_stability_guardrails",
    "build_multi_strategy_comparison_report",
    "build_v3_v4_comparison_report",
    "compute_metrics",
    "compute_rolling_stats",
    "compute_slice_metrics",
    "compute_stats",
    "compute_stress_test",
    "inspect_live_signal",
    "load_all_strategy_specs",
    "load_benchmarks",
    "load_macro_regimes",
    "load_price_panel",
    "load_strategy_spec",
    "load_stress_tests",
    "nav_from_close",
    "render_walk_forward_markdown",
    "run_full_stability_audit",
    "run_walk_forward_analysis",
]
