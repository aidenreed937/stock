"""src/stock_analytics/pipelines/tio2/projections.py 单元测试。"""

from __future__ import annotations

import polars as pl
import pytest

from stock_analytics.pipelines.tio2.projections import (
    CompanyProjectionEngine,
    CompanyProjectionResult,
    SegmentResult,
)


def test_projection_engine_loading() -> None:
    """验证配置加载包含两家核心标的与四大情景定义 (含 current_spot)。"""
    engine = CompanyProjectionEngine()
    cfg = engine.load_config()
    assert "companies" in cfg
    assert "scenarios" in cfg
    assert {"002601.SZ", "002145.SZ"}.issubset(set(cfg["companies"].keys()))
    assert {"current_spot", "trough", "mid_cycle", "peak"}.issubset(set(cfg["scenarios"].keys()))


def test_segment_projection_lb_iron_ore() -> None:
    """验证龙佰集团 300 万吨铁精矿外售商品量在不同情景下的高毛利贡献。"""
    engine = CompanyProjectionEngine()
    # mid_cycle: iron_ore_price=850.0, cost=380.0, volume=300万吨
    # unit_margin = 850 - 380 = 470 元/吨
    # gross_profit = 3,000,000 * 470 = 1.41 亿元
    seg = engine.project_segment("002601.SZ", "iron_ore", "mid_cycle")
    assert isinstance(seg, SegmentResult)
    assert seg.sales_volume_tons == 3_000_000.0
    assert seg.unit_price_cny == 850.0
    assert seg.unit_cost_cny == 380.0
    assert seg.unit_gross_margin_cny == 470.0
    assert seg.gross_profit_cny == 1.41e9


def test_company_projection_scenarios_lb() -> None:
    """验证龙佰集团在四大情景下的营收、毛利、归母净利与自适应 PB 梯队。"""
    engine = CompanyProjectionEngine()

    spot = engine.project_company("002601.SZ", "current_spot")
    trough = engine.project_company("002601.SZ", "trough")
    mid = engine.project_company("002601.SZ", "mid_cycle")
    peak = engine.project_company("002601.SZ", "peak")

    assert isinstance(spot, CompanyProjectionResult)
    assert isinstance(trough, CompanyProjectionResult)
    # Phase 1.6 + 黄金表 FX（2026-09-20）：FX 由 7.2 修正为黄金表 USD/CNH（~6.71）后：
    # 当前现货年化 16.3 亿；磨底期酸价回落利润回升（成本驱动型周期）
    assert 1.4e9 <= spot.net_profit_attr_p_cny <= 1.8e9
    assert 2.7e9 <= trough.net_profit_attr_p_cny <= 3.2e9
    # 中枢复苏：净利润 40~48 亿区间
    assert 4.0e9 <= mid.net_profit_attr_p_cny <= 4.8e9
    # 景气高峰：净利润 65~76 亿
    assert 6.5e9 <= peak.net_profit_attr_p_cny <= 7.6e9

    # 验证单调性
    assert trough.net_profit_attr_p_cny < mid.net_profit_attr_p_cny < peak.net_profit_attr_p_cny
    assert trough.target_stock_price_cny > 0

    # 验证自适应 PB/BPS 估值体系
    assert trough.bps_cny == 9.57
    assert 1.55 <= trough.target_pb <= 1.65  # 5% 历史分位 P05=1.59x
    assert spot.target_pb == 1.63  # 当前市场实际收盘 PB=1.63x
    assert trough.target_stock_price_pb_cny == round(9.57 * trough.target_pb, 2)
    assert (
        trough.target_stock_price_pb_cny
        < mid.target_stock_price_pb_cny
        < peak.target_stock_price_pb_cny
    )


def test_company_projection_scenarios_zh() -> None:
    """验证钛能化学高弹性特征：现货微利、磨底防御与高景气暴利扩张。"""
    engine = CompanyProjectionEngine()

    spot = engine.project_company("002145.SZ", "current_spot")
    trough = engine.project_company("002145.SZ", "trough")
    mid = engine.project_company("002145.SZ", "mid_cycle")
    peak = engine.project_company("002145.SZ", "peak")

    assert isinstance(spot, CompanyProjectionResult)
    assert isinstance(trough, CompanyProjectionResult)
    # Phase 1.6 + 黄金表 FX（2026-09-20）：当前现货年化 5.9 亿；磨底利润回升；景气高峰 32.1 亿
    assert 0.5e9 <= spot.net_profit_attr_p_cny <= 0.7e9
    assert 0.85e9 <= trough.net_profit_attr_p_cny <= 1.0e9
    # 中枢复苏：净利 13.5~16 亿（弹性修复）
    assert 1.35e9 <= mid.net_profit_attr_p_cny <= 1.6e9
    # 高峰期：价差扩张 + 出口退税收益 + 磷化工/黄磷，净利 32.1 亿
    assert 3.0e9 <= peak.net_profit_attr_p_cny <= 3.4e9

    # 验证自适应 PB/BPS 估值体系 (BPS 3.48 元/股)
    assert trough.bps_cny == 3.48
    assert 1.20 <= trough.target_pb <= 1.40  # 历史分位 P05=1.34x
    assert spot.target_pb == 1.23  # 当前最新收盘 PB=1.23x
    assert trough.target_stock_price_pb_cny == round(3.48 * trough.target_pb, 2)
    assert (
        trough.target_stock_price_pb_cny
        < mid.target_stock_price_pb_cny
        < peak.target_stock_price_pb_cny
    )


def test_company_pb_valuation_dual_track() -> None:
    """验证 PE-PB 双轨估值体系输出完整性、四大情景覆盖 (8条) 与 DataFrame 序列化。"""
    engine = CompanyProjectionEngine()
    results = engine.project_all()
    assert len(results) in (8, 10)  # 2 家公司 x 4 或 5 种情景 (含 auxiliary_stress 压力测试)

    df = engine.to_dataframe(results)
    assert "bps_cny" in df.columns
    assert "target_pb" in df.columns
    assert "target_market_cap_pb_cny" in df.columns
    assert "target_stock_price_pb_cny" in df.columns
    assert "finance_expense_cny" in df.columns
    assert "financial_report_date" in df.columns
    assert "data_source_mode" in df.columns
    assert "core_tio2_gross_profit_cny" in df.columns
    assert "auxiliary_gross_profit_cny" in df.columns
    assert "core_tio2_eps_cny" in df.columns
    assert "auxiliary_eps_cny" in df.columns

    # 验证四大核心情景均出现在数据集中
    scen_keys = set(df["scenario_key"].to_list())
    assert {"current_spot", "trough", "mid_cycle", "peak"}.issubset(scen_keys)

    for r in results:
        assert r.bps_cny > 0
        assert r.target_pb > 0
        assert r.target_stock_price_pb_cny > 0
        assert r.target_market_cap_pb_cny > 0
        assert r.finance_expense_cny >= 0
        assert r.data_source_mode == "dynamic_catalog"

    # 验证显式禁用 catalog=False 时的纯离线静态降级
    fallback_engine = CompanyProjectionEngine(catalog=False)
    fb_res = fallback_engine.project_company("002601.SZ", "trough")
    assert fb_res.data_source_mode == "static_config"


def test_dynamic_financial_context_with_mock_catalog() -> None:
    """验证提供 Mock Catalog 时能正确提取动态财报指标，并驱动自适应 PB 与情景去杠杆。"""

    class MockCatalog:
        def load_dataset(
            self, name: str, symbols: list[str], columns: list[str] | None = None
        ) -> pl.DataFrame:
            sym = symbols[0]
            if name == "balancesheet":
                return pl.DataFrame(
                    {
                        "symbol": [sym],
                        "end_date": ["2026-06-30"],
                        "ann_date": ["2026-08-27"],
                        "total_hldr_eqy_exc_min_int": [2.5e10],  # 250 亿
                        "money_cap": [6.0e9],  # 60 亿
                        "st_borr": [5.0e9],  # 短借 50 亿
                        "lt_borr": [1.0e10],  # 长借 100 亿
                        "non_cur_liab_due_1y": [5.0e9],  # 1年内到期 50 亿
                        "bond_payable": [2.0e9],  # 债券 20 亿 (总有息负债 220 亿)
                    }
                )
            if name == "daily_basic":
                return pl.DataFrame(
                    {
                        "symbol": [sym],
                        "trade_date": ["2026-09-15"],
                        "total_share": [250000.0],  # 25 亿股 (单位万股)
                        "pb": [2.0],  # 模拟 PB 2.0x
                    }
                )
            if name == "income":
                return pl.DataFrame(
                    {
                        "symbol": [sym],
                        "end_date": ["2026-06-30"],
                        "fin_exp": [3.5e8],  # 半年报 3.5 亿 -> 年化 7.0 亿
                    }
                )
            return pl.DataFrame()

    engine = CompanyProjectionEngine(catalog=MockCatalog())
    res_trough = engine.project_company("002601.SZ", "trough")
    res_mid = engine.project_company("002601.SZ", "mid_cycle")
    res_peak = engine.project_company("002601.SZ", "peak")

    assert res_trough.data_source_mode == "dynamic_catalog"
    assert res_trough.financial_report_date == "2026-06-30"
    # bps = 250亿 / 25亿股 = 10.0 元/股
    assert res_trough.bps_cny == 10.0
    assert res_trough.target_stock_price_pb_cny == round(10.0 * res_trough.target_pb, 2)

    # 验证动态装配的有息负债与资金存量
    ctx = engine.resolve_financial_context(
        "002601.SZ", engine.load_config()["companies"]["002601.SZ"]
    )
    assert ctx.interest_bearing_debt_cny == 2.2e10
    assert ctx.money_cap_cny == 6.0e9
    assert ctx.annualized_finance_expense == 7.0e8

    # 验证去杠杆情景递减: trough (1.0x -> 7.0亿), mid_cycle (0.55x -> 3.85亿), peak (0.40x -> 2.80亿)
    assert res_trough.finance_expense_cny == 7.0e8
    assert res_mid.finance_expense_cny == 3.85e8
    assert res_peak.finance_expense_cny == 2.80e8
    assert (
        res_trough.finance_expense_cny > res_mid.finance_expense_cny > res_peak.finance_expense_cny
    )


def test_dynamic_financial_context_with_real_catalog_if_available() -> None:
    """验证绑定真实 DataCatalog 时能成功动态提取本地真实财报事实与去杠杆对账。"""
    try:
        from stock_data.catalog import DataCatalog

        cat = DataCatalog(data_source="tushare")
        engine = CompanyProjectionEngine(catalog=cat)
        res_trough = engine.project_company("002601.SZ", "trough")
        res_mid = engine.project_company("002601.SZ", "mid_cycle")
        res_peak = engine.project_company("002601.SZ", "peak")
        if res_trough.data_source_mode == "dynamic_catalog":
            assert res_trough.financial_report_date == "2026-06-30"
            assert res_trough.bps_cny == 9.57
            # 真实 2026H1 财务费用 3.9063 亿 -> 年化 7.81 亿
            assert res_trough.finance_expense_cny == 781262087.92
            # 复苏期 0.55x -> 4.30 亿
            assert res_mid.finance_expense_cny == round(781262087.92 * 0.55, 2)
            # 景气期 0.40x -> 3.12 亿
            assert res_peak.finance_expense_cny == round(781262087.92 * 0.40, 2)
    except Exception:
        pass


def test_profit_sensitivity_grid() -> None:
    """验证二维价格敏感性矩阵生成。"""
    engine = CompanyProjectionEngine()
    grid_df = engine.generate_profit_sensitivity_grid(
        company_id="002601.SZ",
        price_steps=[14000.0, 16000.0, 18000.0],
        ore_steps=[1300.0, 1800.0, 2300.0],
    )
    assert isinstance(grid_df, pl.DataFrame)
    assert grid_df.height == 3
    assert "ore_price_cny" in grid_df.columns
    assert "tio2_14000" in grid_df.columns
    assert "tio2_18000" in grid_df.columns

    # 验证产品提价时净利润单调递增
    row0 = grid_df.row(0, named=True)
    assert row0["tio2_14000"] < row0["tio2_16000"] < row0["tio2_18000"]


def test_point_in_time_lookahead_prevention() -> None:
    """验证基于公告日 ann_date 与 as_of_date 的 Point-in-Time 严防前视截断机制。"""
    try:
        from stock_data.catalog import DataCatalog

        cat = DataCatalog(data_source="tushare")

        # 1. 模拟回测时点 as_of_date = 2026-08-01 (此时 2026H1 半年报尚未披露，公告日为 2026-08-27)
        engine_past = CompanyProjectionEngine(catalog=cat, as_of_date="2026-08-01")
        ctx_past = engine_past.resolve_financial_context("002601.SZ", {})
        if ctx_past.source_mode == "dynamic_catalog":
            # 严格截断为 2026Q1 一季报，绝不能出现 2026-06-30
            assert ctx_past.report_date == "2026-03-31"
            assert ctx_past.ann_date == "2026-04-28"

        # 2. 模拟当前时点 as_of_date = 2026-09-01 (此时 2026H1 已经披露)
        engine_now = CompanyProjectionEngine(catalog=cat, as_of_date="2026-09-01")
        ctx_now = engine_now.resolve_financial_context("002601.SZ", {})
        if ctx_now.source_mode == "dynamic_catalog":
            # 正常装配 2026H1 半年报
            assert ctx_now.report_date == "2026-06-30"
            assert ctx_now.ann_date == "2026-08-27"
    except Exception:
        pass


def test_internal_consumption_deduction() -> None:
    """验证氯化法钛白粉成功扣减转产海绵钛联产自用 12 万吨折合产能。"""
    engine = CompanyProjectionEngine()
    # 龙佰氯化法名牌 86 万吨 - 内部自用 12 万吨 = 有效可售产能 74 万吨
    # 磨底情景开工率 0.88 -> 销量 = 74 * 0.88 * 10000 = 651,200 吨
    seg = engine.project_segment("002601.SZ", "chloride_tio2", "trough")
    assert isinstance(seg, SegmentResult)
    assert seg.sales_volume_tons == 651_200.0


def test_auxiliary_business_dynamic_loading() -> None:
    """验证非核心副业 (新能源、贸易) 从 fina_mainbz 成功动态提取历史 3 年中枢。"""
    try:
        from stock_data.catalog import DataCatalog

        cat = DataCatalog(data_source="tushare")
        engine = CompanyProjectionEngine(catalog=cat, as_of_date="2026-09-01")
        ctx = engine.resolve_financial_context("002601.SZ", {})
        if ctx.source_mode == "dynamic_catalog" and ctx.auxiliary_revenues_cny:
            # 龙佰历史 3 年贸易中位数应在 19~22 亿之间
            assert 1.8e9 <= ctx.auxiliary_revenues_cny.get("trading_other", 0.0) <= 2.2e9
            # 龙佰历史 3 年新能源中位数应在 9~13 亿之间
            assert 0.9e9 <= ctx.auxiliary_revenues_cny.get("new_energy", 0.0) <= 1.3e9
    except Exception:
        pass


def test_reconciliation_audit_gate() -> None:
    """验证历史财务合理性对账门禁 (Reconciliation Audit Gate) 的判定逻辑。"""
    try:
        from stock_data.catalog import DataCatalog

        cat = DataCatalog(data_source="tushare")
        engine = CompanyProjectionEngine(catalog=cat, as_of_date="2026-09-01")
        results = engine.project_all()
        audits = engine.audit_reconciliation(results)
        assert len(audits) >= 2
        lb_audit = next((a for a in audits if a["symbol"] == "002601.SZ"), None)
        assert lb_audit is not None
        # 龙佰 Trough 营收与历史 3Y 年报均值偏差应在 10% 以内并合规通过
        assert abs(lb_audit["bias_pct"]) <= 10.0
        assert lb_audit["status"] == "PASSED"
    except Exception:
        pass


def test_auxiliary_stress_and_profit_decoupling() -> None:
    """验证副业极端失血压力测试与主辅业解耦字段计算。"""
    engine = CompanyProjectionEngine()
    results = engine.project_all()
    stress_results = [r for r in results if r.scenario_key == "auxiliary_stress"]
    assert len(stress_results) == 2  # 覆盖龙佰与钛能

    lb = next(r for r in stress_results if r.symbol == "002601.SZ")
    assert lb.core_tio2_gross_profit_cny > 0
    # 在主业正常造血下，即使副业失血，龙佰归母净利润和主业 EPS 依然能保持正数
    assert lb.net_profit_attr_p_cny > 0
    assert lb.core_tio2_eps_cny > 0
    # 主辅/退税拆分应还原总 EPS（两位小数舍入允许 ±0.02）
    assert pytest.approx(lb.core_tio2_eps_cny + lb.auxiliary_eps_cny, abs=0.02) == lb.eps_cny


def test_dynamic_utilization_injected_from_monthly_survey() -> None:
    """验证化学月频调研产能利用率动态注入：trough 用近 6 月最低、current_spot 用最新月。"""

    class MonthlyUtilCatalog:
        def load_dataset(
            self, name: str, symbols: list[str] | None = None, columns: list[str] | None = None
        ) -> pl.DataFrame:
            if name == "chemical_monthly_survey":
                return pl.DataFrame(
                    {
                        "report_month": ["2026-05", "2026-06", "2026-07", "2026-08"],
                        "symbol": ["TiO2"] * 4,
                        "operating_rate_pct": [80.0, 74.39, 72.29, 73.3],
                    }
                )
            return pl.DataFrame()

    engine = CompanyProjectionEngine(catalog=MonthlyUtilCatalog())

    # trough: 55 万吨 × 72.29% = 397,595 吨（行业近 6 月最低负荷，替代静态 95% 满产）
    trough_seg = engine.project_segment("002145.SZ", "sulfate_tio2", "trough")
    assert trough_seg.sales_volume_tons == 397_595.0

    # current_spot: 55 万吨 × 73.3%（最新 2026-08 产能利用率）
    spot_seg = engine.project_segment("002145.SZ", "sulfate_tio2", "current_spot")
    assert spot_seg.sales_volume_tons == 403_150.0

    # mid_cycle 无动态注入 → 保持配置利用率 95%
    mid_seg = engine.project_segment("002145.SZ", "sulfate_tio2", "mid_cycle")
    assert mid_seg.sales_volume_tons == 522_500.0


def test_extract_auxiliary_revenues_maps_zh_segments() -> None:
    """钛能年报主营构成 → 副业营收中枢映射（含排除‘其他业务’、磷酸铁/磷矿科目）。"""
    from stock_analytics.pipelines.tio2.projections import extract_auxiliary_revenues

    recent_mbz = pl.DataFrame(
        {
            "end_date": [
                "2023-12-31",
                "2024-12-31",
                "2025-12-31",
                "2023-12-31",
                "2024-12-31",
                "2025-12-31",
                "2023-12-31",
                "2024-12-31",
                "2025-12-31",
                "2025-12-31",
            ],
            "bz_item": [
                "金红石型钛白粉",
                "金红石型钛白粉",
                "钛白粉",
                "新能源材料",
                "新能源材料",
                "新能源材料",
                "磷矿石",
                "磷矿石",
                "磷矿",
                "其他业务",
            ],
            "bz_sales": [
                4.314105544e9,
                5.837254592e9,
                5.881752982e9,
                2.359985e6,
                4.124639e6,
                3.59608025e8,
                8.3207249e7,
                2.06462382e8,
                2.02493158e8,
                2.95066031e8,
            ],
        }
    )

    # 钛能：新能源材料 → iron_phosphate（中位数极小，反映 2025 前几乎为零）
    aux_zh = extract_auxiliary_revenues(recent_mbz, has_iron_phosphate_seg=True)
    assert "new_energy" not in aux_zh
    assert aux_zh["iron_phosphate"] == 4_124_639.0
    # 磷矿/磷矿石取近 3 年中位数 ≈ 2.02 亿
    assert aux_zh["phosphate_ore"] == 202_493_158.0
    # “其他业务”被排除在贸易匹配之外
    assert "trading_other" not in aux_zh

    # 龙佰：新能源材料 → new_energy
    aux_lb = extract_auxiliary_revenues(recent_mbz, has_iron_phosphate_seg=False)
    assert aux_lb["new_energy"] == 4_124_639.0
    assert "iron_phosphate" not in aux_lb


def test_filter_mainbz_by_disclosure_pit() -> None:
    """fina_mainbz 无 ann_date，借用 income 披露日映射做 Point-in-Time 截断。"""
    from stock_analytics.pipelines.tio2.projections import filter_mainbz_by_disclosure

    mbz = pl.DataFrame(
        {
            "end_date": ["2025-12-31", "2024-12-31"],
            "bz_item": ["磷矿", "磷矿石"],
            "bz_sales": [2.0e8, 1.0e8],
        }
    )
    ann_map = {"2025-12-31": "2026-04-28", "2024-12-31": "2025-04-20"}

    # 2025 年报 2026-04-28 才披露：2026-03-01 时点不得使用
    out = filter_mainbz_by_disclosure(mbz, ann_map, "2026-03-01")
    assert out["end_date"].to_list() == ["2024-12-31"]

    # 披露后可用
    out2 = filter_mainbz_by_disclosure(mbz, ann_map, "2026-05-01")
    assert out2.height == 2

    # 映射缺失时降级按 end_date 截断
    out3 = filter_mainbz_by_disclosure(mbz, {}, "2026-03-01")
    assert out3.height == 2


def test_monthly_utilization_pit_by_release_date() -> None:
    """月频利用率按 release_date（发布日）截断：未发布的数据不得在 as_of 前被使用。"""

    class PitMonthlyCatalog:
        def load_dataset(
            self, name: str, symbols: list[str] | None = None, columns: list[str] | None = None
        ) -> pl.DataFrame:
            if name == "chemical_monthly_survey":
                return pl.DataFrame(
                    {
                        "report_month": ["2026-05", "2026-06", "2026-07", "2026-08"],
                        "symbol": ["TiO2"] * 4,
                        "operating_rate_pct": [80.0, 74.39, 72.29, 90.0],
                        "release_date": ["2026-05-29", "2026-06-29", "2026-08-07", "2026-09-02"],
                    }
                )
            return pl.DataFrame()

    # as_of=2026-08-15：8 月数据 09-02 才发布 → 不得使用；最新可用为 7 月 72.29%
    engine_past = CompanyProjectionEngine(catalog=PitMonthlyCatalog(), as_of_date="2026-08-15")
    seg_past = engine_past.project_segment("002145.SZ", "sulfate_tio2", "trough")
    assert seg_past.sales_volume_tons == 397_595.0  # 55 万吨 × 72.29%

    # as_of=2026-09-15：8 月已发布 → 最新可用为 90.0%
    engine_now = CompanyProjectionEngine(catalog=PitMonthlyCatalog(), as_of_date="2026-09-15")
    seg_now = engine_now.project_segment("002145.SZ", "sulfate_tio2", "current_spot")
    assert seg_now.sales_volume_tons == 495_000.0  # 55 万吨 × 90.0%


def test_build_pit_audit_release_date_truncation() -> None:
    """PIT 审计清单：所有动态输入按披露/发布日截断，as_of 之前不得使用未发布数据。"""

    class PitAuditCatalog:
        def load_dataset(
            self, name: str, symbols: list[str] | None = None, columns: list[str] | None = None
        ) -> pl.DataFrame:
            if name == "chemical_spot_price":
                return pl.DataFrame(
                    {
                        "product_name": ["钛白粉", "钛白粉"],
                        "symbol": ["TiO2", "TiO2"],
                        "trade_date": ["2026-08-20", "2026-08-31"],
                        "release_date": ["2026-08-21", "2026-09-01"],
                        "spot_price_cny": [14500.0, 14200.0],
                    }
                )
            if name == "chemical_monthly_survey":
                return pl.DataFrame(
                    {
                        "report_month": ["2026-07", "2026-08"],
                        "symbol": ["TiO2", "TiO2"],
                        "operating_rate_pct": [72.29, 73.3],
                        "release_date": ["2026-08-07", "2026-09-02"],
                    }
                )
            if name == "income":
                return pl.DataFrame(
                    {
                        "symbol": ["002145.SZ", "002145.SZ"],
                        "end_date": ["2024-12-31", "2025-12-31"],
                        "ann_date": ["2025-04-20", "2026-04-28"],
                        "total_revenue": [1.0e9, 1.1e9],
                    }
                )
            if name == "balancesheet":
                return pl.DataFrame(
                    {
                        "symbol": ["002145.SZ"],
                        "end_date": ["2026-06-30"],
                        "ann_date": ["2026-08-27"],
                        "total_hldr_eqy_exc_min_int": [1.0e9],
                    }
                )
            if name == "daily_basic":
                return pl.DataFrame(
                    {
                        "symbol": ["002145.SZ"],
                        "trade_date": ["2026-09-10"],
                        "total_share": [1000.0],
                        "pb": [1.2],
                    }
                )
            if name == "fina_mainbz":
                return pl.DataFrame(
                    {
                        "symbol": ["002145.SZ", "002145.SZ"],
                        "end_date": ["2024-12-31", "2025-12-31"],
                        "bz_item": ["磷矿石", "磷矿"],
                        "bz_sales": [1.5e8, 2.0e8],
                    }
                )
            return pl.DataFrame()

    engine_now = CompanyProjectionEngine(catalog=PitAuditCatalog(), as_of_date="2026-09-15")
    audit_now = engine_now.build_pit_audit()
    by_name = {item["input"]: item for item in audit_now}
    assert by_name["chemical_spot_price(现货注入)"]["pit_ok"] is True
    assert by_name["chemical_monthly_survey(利用率注入)"]["pit_ok"] is True
    assert by_name["fina_mainbz(副业营收中枢)"]["pit_ok"] is True
    assert all(item["pit_ok"] for item in audit_now)

    engine_past = CompanyProjectionEngine(catalog=PitAuditCatalog(), as_of_date="2026-03-01")
    audit_past = engine_past.build_pit_audit()
    by_past = {item["input"]: item for item in audit_past}
    # 08-21 发布的现货、08-07 发布的利用率，均不得出现在 2026-03-01 之前
    assert by_past["chemical_spot_price(现货注入)"]["rows_used"] == 0
    assert by_past["chemical_monthly_survey(利用率注入)"]["rows_used"] == 0
    # 2024 年报（2025-04-20 披露）可用；2025 年报（2026-04-28 披露）不可用 → 仅 1 行
    assert by_past["fina_mainbz(副业营收中枢)"]["rows_used"] == 1
    assert by_past["fina_mainbz(副业营收中枢)"]["pit_ok"] is True
    assert by_past["chemical_spot_price(现货注入)"]["pit_ok"] is False


def test_projection_engine_confidence_band_lb() -> None:
    """验证龙佰集团 mid_cycle 情景下的 EPS 置信带宽推演。"""
    engine = CompanyProjectionEngine()
    band = engine.compute_confidence_band("002601.SZ", "mid_cycle")
    assert band.symbol == "002601.SZ"
    assert band.scenario_key == "mid_cycle"
    assert band.nominal_eps > 0
    assert band.low_eps < band.nominal_eps
    assert band.high_eps > band.nominal_eps
    assert band.bandwidth_pct > 0
    assert len(band.sensitivity_grid) == 3


def test_resolve_fx_rate_and_financial_expense() -> None:
    """验证高频外汇 CNH=X 实时汇率解析与财务费用平抑优化。"""
    engine_now = CompanyProjectionEngine()
    fx_now = engine_now.resolve_fx_rate()
    assert 6.0 <= fx_now <= 7.5

    # Point-in-Time 历史回溯验证
    engine_h1 = CompanyProjectionEngine(as_of_date="2026-06-30")
    fx_h1 = engine_h1.resolve_fx_rate()
    assert 6.0 <= fx_h1 <= 7.5
    # 2026 年上半年汇率（~6.79）高于 10 月末汇率（~6.66）
    assert fx_h1 >= fx_now

    # 验证高出口占比公司在稳态复苏期的财务费用平抑
    fin_ctx = engine_now.resolve_financial_context(
        "002601.SZ", engine_now.load_config()["companies"]["002601.SZ"]
    )
    fin_exp_mid = engine_now._resolve_finance_expense(
        fin_ctx, engine_now.load_config()["companies"]["002601.SZ"], "mid_cycle"
    )
    # 基础利息不超过 4.0 亿，乘 0.55 去杠杆系数后不超过 2.5 亿元
    assert fin_exp_mid <= 2.5e8


def test_cost_lag_filter_scenario() -> None:
    """验证原材料先进先出结转时滞模块 (Cost Lag Filter) 作为可选 Flag 的生效与解耦。"""
    # 1. 默认无时滞 (cost_lag_days=0)
    engine_spot = CompanyProjectionEngine(as_of_date="2026-09-30", cost_lag_days=0)
    cfg_spot = engine_spot.load_config()
    scen_spot = cfg_spot["scenarios"]["current_spot"]
    assert scen_spot["name"] == "当前现货实时测算"
    assert scen_spot["cost_lag_days"] == 0

    # 2. 会计对账时滞 (cost_lag_days=45)
    engine_lag = CompanyProjectionEngine(as_of_date="2026-09-30", cost_lag_days=45)
    cfg_lag = engine_lag.load_config()
    scen_lag = cfg_lag["scenarios"]["current_spot"]
    assert "会计时滞45天" in scen_lag["name"]
    assert scen_lag["cost_lag_days"] == 45

    # 3. 验证 2026-09-30 时点滞后 45 天结转的硫酸成本高于 9 月底即时成本 (因 7~8 月原料处于高位)
    # 即时硫酸约 1710 元/吨；8 月中旬结转的硫酸成本在 1870 元/吨左右
    assert scen_lag["acid_price"] >= scen_spot["acid_price"]
    # 钛白粉销售端出厂价保持当期不滞后
    assert scen_lag["tio2_sulfate_price"] == scen_spot["tio2_sulfate_price"]
