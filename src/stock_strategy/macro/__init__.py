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
from stock_strategy.macro.ic import (
    build_ic_panel,
    overall_ic,
    permutation_ic,
    trailing_ic,
    yearly_ic,
)
from stock_strategy.macro.ic_config import (
    IcConfig,
    load_ic_config,
)
from stock_strategy.macro.ic_report import build_ic_report
from stock_strategy.macro.ic_review import (
    StabilityThresholds,
    build_stability_review,
    compare_with_previous,
    compute_sign_stability,
    load_snapshot,
    report_new_drift,
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
from stock_strategy.macro.sensitivity import (
    SensitivityConfig,
    load_sensitivity_config,
    run_sensitivity_sweep,
)
from stock_strategy.macro.walk_forward import (
    WalkForwardResult,
    WalkForwardSlice,
    render_walk_forward_markdown,
    run_walk_forward_analysis,
)

__all__ = [
    "MACRO_REGIMES",
    "STRESS_TEST_PERIODS",
    "IcConfig",
    "LiveOrderInstruction",
    "LiveSignalInspectionResult",
    "MacroRiskRunner",
    "SensitivityConfig",
    "StabilityAuditResult",
    "StabilityThresholds",
    "WalkForwardResult",
    "WalkForwardSlice",
    "assemble_macro_panel",
    "assert_stability_guardrails",
    "build_ic_panel",
    "build_ic_report",
    "build_multi_strategy_comparison_report",
    "build_stability_review",
    "build_v3_v4_comparison_report",
    "compare_with_previous",
    "compute_metrics",
    "compute_rolling_stats",
    "compute_sign_stability",
    "compute_slice_metrics",
    "compute_stats",
    "compute_stress_test",
    "inspect_live_signal",
    "load_all_strategy_specs",
    "load_benchmarks",
    "load_ic_config",
    "load_macro_regimes",
    "load_price_panel",
    "load_sensitivity_config",
    "load_snapshot",
    "load_strategy_spec",
    "load_stress_tests",
    "nav_from_close",
    "overall_ic",
    "permutation_ic",
    "render_walk_forward_markdown",
    "report_new_drift",
    "run_full_stability_audit",
    "run_sensitivity_sweep",
    "run_walk_forward_analysis",
    "trailing_ic",
    "yearly_ic",
]
