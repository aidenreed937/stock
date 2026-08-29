"""中观产业量化诊断核心引擎单元测试。"""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.industry_diagnostics import (
    ArchetypeConfig,
    IndustryConstituentsSnapshot,
    IndustryDiagnosticsPipeline,
    IndustryDiagnosticsResult,
    IndustryFinancialsSnapshot,
    IndustryScoreBreakdown,
    IndustryTechnicalsSnapshot,
    IndustryThresholdsConfig,
    IndustryValuationSnapshot,
    IndustryValueChainSnapshot,
    ValuationWeightsConfig,
    VetoRulesConfig,
    calculate_industry_scores,
    load_industry_diagnostics_config,
    run_industry_diagnostics,
)
from stock_analytics.pipelines.industry_diagnostics.scoring import (
    calculate_crowding_penalty,
    calculate_fundamental_score,
    calculate_momentum_score,
    calculate_valuation_score,
    classify_pb_roe_quadrant,
)
from stock_analytics.pipelines.industry_diagnostics.sources import (
    resolve_industry_meta,
)
from stock_analytics.pipelines.industry_diagnostics.value_chain import (
    load_value_chain_map,
)
from stock_reporting.templates.industry_diagnostics_report import (
    render_industry_diagnostics_report,
)


def test_resolve_industry_meta_mock() -> None:
    mock_ic = pl.DataFrame(
        {
            "index_code": ["801120.SI", "801125.SI"],
            "industry_name": ["食品饮料", "白酒Ⅱ"],
            "level": ["L1", "L2"],
            "industry_code": ["340000", "340500"],
        }
    )

    class _MockCatalog:
        def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
            if dataset == "index_classify":
                return mock_ic
            return pl.DataFrame()

    catalog = _MockCatalog()
    c1, n1, l1, _ = resolve_industry_meta(catalog, "食品饮料")  # type: ignore
    assert c1 == "801120.SI"
    assert n1 == "食品饮料"
    assert l1 == "申万一级"

    c2, n2, l2, _ = resolve_industry_meta(catalog, "白酒")  # type: ignore
    assert c2 == "801125.SI"
    assert n2 == "白酒Ⅱ"
    assert l2 == "申万二级"


def test_load_value_chain_map() -> None:
    # 1. 测试 L1 宏观行业基线加载
    vc_l1 = load_value_chain_map("食品饮料")
    assert len(vc_l1.upstream) > 0
    assert "高粱/小麦/大麦等农产品" in vc_l1.upstream[0]
    assert len(vc_l1.high_frequency_indicators) > 0

    # 2. 测试 L2 二级行业专属加载与父级级联继承合并 (白酒继承食品饮料)
    vc_l2 = load_value_chain_map("白酒")
    assert len(vc_l2.upstream) > 0
    # 专属指标排在第一位
    assert any("飞天茅台" in ind["name"] for ind in vc_l2.high_frequency_indicators)
    # 父级通用指标也被级联继承合并
    assert any("餐饮社零" in ind["name"] for ind in vc_l2.high_frequency_indicators)
    # 上游环节合并
    assert any("酿酒专用" in u for u in vc_l2.upstream)
    assert any("包材" in u for u in vc_l2.upstream)

    # 3. 测试 L2 半导体继承电子
    vc_semi = load_value_chain_map("半导体")
    assert any("SIA" in ind["name"] for ind in vc_semi.high_frequency_indicators)
    assert any("DRAM" in ind["name"] for ind in vc_semi.high_frequency_indicators)


def test_config_archetypes_loading() -> None:
    cfg = load_industry_diagnostics_config()
    assert "cyclical" in cfg.archetypes
    assert "consumption" in cfg.archetypes
    assert "growth" in cfg.archetypes
    assert "dividend" in cfg.archetypes

    # 测试原型匹配
    arch_coal = cfg.resolve_archetype("煤炭开采")
    assert arch_coal.title == "强周期资源与大宗"
    assert arch_coal.valuation_weights.pb_weight == 0.80

    arch_bev = cfg.resolve_archetype("食品饮料")
    assert arch_bev.title == "大消费与核心资产"
    assert arch_bev.valuation_weights.pe_weight == 0.70

    arch_semi = cfg.resolve_archetype("半导体芯片")
    assert arch_semi.title == "科技成长与创新"

    arch_bank = cfg.resolve_archetype("国有大型银行")
    assert arch_bank.title == "稳定红利与大金融"


def test_industry_scoring_logic_with_archetypes() -> None:
    thresholds = IndustryThresholdsConfig(
        momentum_bias_limit=10.0,
        roe_high=18.0,
        roe_mid=12.0,
        roe_low=6.0,
        scissors_positive=5.0,
    )

    # 1. 动量多头排列打分
    tech_bull = IndustryTechnicalsSnapshot(close=100.0, ma20=95.0, ma60=90.0, rsi14=60.0)
    mom_score = calculate_momentum_score(tech_bull, thresholds=thresholds)
    assert mom_score >= 70.0

    # 2. 周期品估值赔率 (PB 80% 高位自适应低分)
    val_cyclical = IndustryValuationSnapshot(pe_percentile_5y=5.0, pb_percentile_5y=80.0)
    cyclical_arch = ArchetypeConfig(
        title="强周期资源与大宗",
        valuation_weights=ValuationWeightsConfig(pb_weight=0.80, pe_weight=0.20),
    )
    val_score_cyc = calculate_valuation_score(val_cyclical, archetype=cyclical_arch)
    assert val_score_cyc < 50.0

    # 3. 消费核心资产估值赔率 (PE 15% 低位自适应高分)
    consumption_arch = ArchetypeConfig(
        title="大消费与核心资产",
        valuation_weights=ValuationWeightsConfig(pb_weight=0.30, pe_weight=0.70),
    )
    val_bev = IndustryValuationSnapshot(pe_percentile_5y=15.0, pb_percentile_5y=60.0)
    val_score_bev = calculate_valuation_score(val_bev, archetype=consumption_arch)
    assert val_score_bev >= 70.0

    # 4. 基本面优质与剪刀差打分
    fin_good = IndustryFinancialsSnapshot(
        roe_avg=18.5, revenue_yoy=15.0, netprofit_yoy=25.0, profit_scissors=10.0
    )
    fund_score = calculate_fundamental_score(fin_good, thresholds=thresholds)
    assert fund_score >= 75.0

    # 5. 拥挤度扣分 (含广度背离)
    const_crowded = IndustryConstituentsSnapshot(cr5_concentration=85.0, above_ma20_ratio=20.0)
    penalty = calculate_crowding_penalty(
        const_crowded,
        turnover_p5y=95.0,
        overheat_threshold=90.0,
        momentum_score=80.0,
        thresholds=thresholds,
    )
    assert penalty > 10.0

    # 6. PB-ROE 象限划分
    quadrant = classify_pb_roe_quadrant(roe=16.0, pb_p5y=25.0, pe_p5y=20.0)
    assert "核心资产·高性价比" in quadrant

    # 7. 一票否决门禁
    fin_decay = IndustryFinancialsSnapshot(roe_avg=3.0, revenue_yoy=-20.0, netprofit_yoy=-40.0)
    scores = calculate_industry_scores(
        industry_name="煤炭",
        technicals=tech_bull,
        valuation=val_cyclical,
        financials=fin_decay,
        constituents=const_crowded,
        archetype=cyclical_arch,
        thresholds=thresholds,
        veto_rules=VetoRulesConfig(),
    )
    assert scores.veto_triggered is True
    assert len(scores.veto_reasons) > 0
    assert scores.industry_type == "强周期资源与大宗"


def test_industry_diagnostics_serialization_and_reporting() -> None:
    res = IndustryDiagnosticsResult(
        industry_code="801120.SI",
        industry_name="食品饮料",
        level="申万一级",
        as_of_date="2026-08-21",
        technicals=IndustryTechnicalsSnapshot(close=13788.89, pct_chg=-1.36),
        valuation=IndustryValuationSnapshot(pe_ttm=19.76, pe_percentile_5y=12.5),
        financials=IndustryFinancialsSnapshot(report_date="2026-06-30", profit_scissors=5.2),
        constituents=IndustryConstituentsSnapshot(
            total_count=120,
            top_market_cap_leaders=[
                {"symbol": "600519.SH", "name": "贵州茅台", "total_mv_billion": 15911.4}
            ],
            cr5_concentration=65.2,
        ),
        value_chain=IndustryValueChainSnapshot(upstream=["农产品"], downstream=["消费终端"]),
        scores=IndustryScoreBreakdown(
            industry_type="大消费与核心资产",
            composite_score=78.5,
            momentum_score=80.0,
            valuation_score=85.0,
            fundamental_score=75.0,
            quadrant="核心资产·高性价比 (高ROE/低估值)",
        ),
    )

    d = res.to_dict()
    assert d["industry_code"] == "801120.SI"
    assert d["valuation"]["pe_ttm"] == 19.76
    assert d["scores"]["composite_score"] == 78.5
    assert d["financials"]["profit_scissors"] == 5.2

    md = res.to_markdown()
    assert "食品饮料" in md
    assert "801120.SI" in md
    assert "大消费与核心资产" in md
    assert "78.5/100" in md

    rendered = render_industry_diagnostics_report(res)
    assert rendered == md


def test_industry_diagnostics_pipeline_and_artifacts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    trade_dates = [date(2026, 8, d) for d in range(1, 21)]
    mock_sw_df = pl.DataFrame(
        {
            "symbol": ["801120.SI"] * 20,
            "trade_date": trade_dates,
            "close": [10000.0 + i * 10 for i in range(20)],
            "pct_change": [1.0] * 20,
            "pe": [20.0 + i * 0.1 for i in range(20)],
            "pb": [3.0] * 20,
        }
    )

    mock_ic = pl.DataFrame(
        {
            "index_code": ["801120.SI"],
            "industry_name": ["食品饮料"],
            "level": ["L1"],
            "industry_code": ["340000"],
        }
    )

    class _MockCatalog:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
            if dataset == "index_classify":
                return mock_ic
            if dataset == "sw_daily":
                return mock_sw_df
            return pl.DataFrame()

    from stock_analytics.pipelines.industry_diagnostics import pipeline

    monkeypatch.setattr(pipeline, "DataCatalog", _MockCatalog)

    output_dir = tmp_path / "analytics" / "industry_diagnostics"
    custom_cfg = load_industry_diagnostics_config()
    pipe = IndustryDiagnosticsPipeline(config=custom_cfg)

    result = pipe.run(
        "食品饮料",
        target_date=date(2026, 8, 20),
        output_dir=output_dir,
        update_latest=True,
    )

    assert result.industry_code == "801120.SI"
    assert result.industry_name == "食品饮料"
    assert result.technicals.close == 10190.0
    assert result.valuation.pe_ttm is not None
    assert result.scores.composite_score > 0
    assert result.scores.industry_type == "大消费与核心资产"

    # 验证标准产物落盘 (文件系统与质量审计)
    as_of_dir = output_dir / "runs" / "as_of=2026-08-20"
    run_dirs = list(as_of_dir.glob("run_*"))
    assert len(run_dirs) == 1
    actual_run_dir = run_dirs[0]

    assert (actual_run_dir / "diagnostics.json").exists()
    assert (actual_run_dir / "scores.json").exists()
    assert (actual_run_dir / "report.md").exists()
    assert (actual_run_dir / "quality_report.md").exists()
    assert (actual_run_dir / "quality_report.json").exists()
    assert (actual_run_dir / "manifest.json").exists()

    latest_dir = output_dir / "latest"
    assert (latest_dir / "diagnostics.json").exists()
    assert (latest_dir / "scores.json").exists()
    assert (latest_dir / "report.md").exists()
    assert (latest_dir / "manifest.json").exists()


def test_run_industry_diagnostics_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    trade_dates = [date(2026, 8, d) for d in range(1, 21)]
    mock_sw_df = pl.DataFrame(
        {
            "symbol": ["801120.SI"] * 20,
            "trade_date": trade_dates,
            "close": [10000.0 + i * 10 for i in range(20)],
            "pct_change": [1.0] * 20,
            "pe": [20.0 + i * 0.1 for i in range(20)],
            "pb": [3.0] * 20,
        }
    )

    mock_ic = pl.DataFrame(
        {
            "index_code": ["801120.SI"],
            "industry_name": ["食品饮料"],
            "level": ["L1"],
            "industry_code": ["340000"],
        }
    )

    class _MockCatalog:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def load_dataset(self, dataset: str, **kwargs: object) -> pl.DataFrame:
            if dataset == "index_classify":
                return mock_ic
            if dataset == "sw_daily":
                return mock_sw_df
            return pl.DataFrame()

    from stock_analytics.pipelines.industry_diagnostics import pipeline

    monkeypatch.setattr(pipeline, "DataCatalog", _MockCatalog)

    result = run_industry_diagnostics("食品饮料", target_date=date(2026, 8, 20))
    assert result.industry_code == "801120.SI"
    assert result.industry_name == "食品饮料"
    assert result.technicals.close == 10190.0
    assert result.valuation.pe_ttm is not None
    assert result.scores.composite_score > 0
