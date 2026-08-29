"""申万行业轮动策略子包。

包含：
1. assembly: 行业因子面板与行情数据装配；
2. runner: 行业轮动多资产回测运行器；
3. report: 多策略横向对比研报与资金曲线；
4. audit: 跨周期稳定性审计与防退化 CI 门禁；
5. live: 14:50 盘尾实盘信号推演与 ETF 报单生成。
"""

from stock_strategy.industry.assembly import (
    assemble_industry_panel,
    load_industry_price_panel,
)
from stock_strategy.industry.audit import (
    load_macro_regimes,
    load_stress_tests,
    run_industry_strategy_audit,
)
from stock_strategy.industry.live import (
    IndustryLiveOrderInstruction,
    IndustryLiveSignalInspectionResult,
    inspect_live_industry_signal,
)
from stock_strategy.industry.report import (
    build_multi_industry_comparison_report,
    compute_metrics,
    load_all_industry_strategy_specs,
    load_industry_benchmarks,
)
from stock_strategy.industry.runner import IndustryStrategyRunner

__all__ = [
    "IndustryLiveOrderInstruction",
    "IndustryLiveSignalInspectionResult",
    "IndustryStrategyRunner",
    "assemble_industry_panel",
    "build_multi_industry_comparison_report",
    "compute_metrics",
    "inspect_live_industry_signal",
    "load_all_industry_strategy_specs",
    "load_industry_benchmarks",
    "load_industry_price_panel",
    "load_macro_regimes",
    "load_stress_tests",
    "run_industry_strategy_audit",
]
