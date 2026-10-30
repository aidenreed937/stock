"""化工产业链理论利润与加工费计算器测试。"""

from datetime import date
from pathlib import Path

import polars as pl

from stock_data.fetcher.industry.chemicals.collectors.spreads import ChemicalSpreadCalculator
from stock_data.fetcher.industry.chemicals.transforms.spreads import build_spread_curated_frame


def test_spread_calculator_methods(tmp_path: Path) -> None:
    calc = ChemicalSpreadCalculator(raw_dir="data/raw/industry")

    # 测试纯碱联产双吨计算
    soda_margin = calc.calculate_soda_ash_double_ton_margin(
        soda_price=1500.0,
        nh4cl_price=450.0,
        salt_price=230.0,
        nh3_price=2400.0,
        coal_price=650.0,
        fixed_cost=450.0,
    )
    assert isinstance(soda_margin, float)

    # 测试 PTA 加工费
    pta_spread = calc.calculate_pta_processing_spread(pta_price=5850.0, px_price=7950.0)
    assert pta_spread == 5850.0 - 0.655 * 7950.0

    # 测试钛白粉硫酸法理论毛利
    # tio2_price=14000, ilmenite=2200, acid=350 -> raw_cost = 2.0*2200 + 3.5*350 = 5625
    # fixed_cost = 3800 -> margin = 14000 - 5625 - 3800 = 4575.0
    tio2_margin = calc.calculate_tio2_sulfate_margin(
        tio2_price=14000.0,
        ilmenite_price=2200.0,
        acid_price=350.0,
    )
    assert tio2_margin == 4575.0

    # 测试硫酸法现金保本成本线: 5625 + 2600 = 8225.0
    tio2_cash_cost = calc.calculate_tio2_sulfate_cash_cost(
        ilmenite_price=2200.0,
        acid_price=350.0,
    )
    assert tio2_cash_cost == 8225.0

    # 测试氯化法基准完全成本参考
    chloride_cost = calc.calculate_tio2_chloride_cash_cost()
    assert chloride_cost == 12500.0

    # 测试氯化法理论毛利: tio2=16000, slag=5000, petcoke=2000, chlorine=1200
    # raw = 1.2*5000 + 0.2*2000 + 0.1*1200 = 6520; fixed = 6000 -> margin = 3480
    chloride_margin = calc.calculate_tio2_chloride_margin(
        tio2_price=16000.0,
        slag_price=5000.0,
        petcoke_price=2000.0,
        chlorine_price=1200.0,
    )
    assert chloride_margin == 3480.0

    # 测试氯化法现金保本成本线: 6520 + 4200 = 10720.0
    chloride_cash = calc.calculate_tio2_chloride_cash_breakeven(
        slag_price=5000.0,
        petcoke_price=2000.0,
        chlorine_price=1200.0,
    )
    assert chloride_cash == 10720.0

    # 测试钛白粉利润区间判定 (high_profit > 2000, profitable > 500, near_breakeven > -500, deep_loss <= -500)
    assert calc.get_margin_regime(2500.0, product="tio2") == "high_profit"
    assert calc.get_margin_regime(1200.0, product="tio2") == "profitable"
    assert calc.get_margin_regime(-100.0, product="tio2") == "near_breakeven"
    assert calc.get_margin_regime(-800.0, product="tio2") == "deep_loss"
    assert calc.get_margin_regime(2500.0, product="TiO2") == "high_profit"

    # 无真实 RAW 价差表时只能返回空 schema，不得内置历史样本。
    df = ChemicalSpreadCalculator(raw_dir=tmp_path / "missing_raw").build_historical_spreads()
    assert isinstance(df, pl.DataFrame)
    assert "spread_margin_cny" in df.columns
    assert "margin_regime" in df.columns
    assert df.is_empty()


def test_build_historical_spreads_from_raw(tmp_path: Path) -> None:
    raw_file = tmp_path / "chemicals" / "chemical_spreads.csv"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text(
        "trade_date,product_name,symbol,process_type,product_price_cny,byproduct_price_cny,"
        "raw_material_cost_cny,spread_margin_cny,cash_breakeven_cost_cny,margin_regime,"
        "source,release_date,collected_at,data_status\n"
        "2026-08-27,纯碱,SA,联碱法双吨,1350,420,1380,-60,0,near_breakeven,"
        "Longzhong_Oilchem,2026-08-27,2026-09-01T00:00:00Z,actual\n",
        encoding="utf-8",
    )

    df = ChemicalSpreadCalculator(raw_dir=tmp_path).build_historical_spreads()

    assert df.height == 1
    assert df["trade_date"][0] == date(2026, 8, 27)


def test_spread_result_reports_invalid_rows_and_filters_curated(tmp_path: Path) -> None:
    raw_file = tmp_path / "chemicals" / "chemical_spreads.csv"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text(
        "trade_date,product_name,symbol,process_type,product_price_cny,byproduct_price_cny,"
        "raw_material_cost_cny,spread_margin_cny,cash_breakeven_cost_cny,margin_regime,"
        "source,release_date,collected_at,data_status\n"
        "2026-08-27,纯碱,SA,联碱法双吨,1350,420,1380,-60,0,near_breakeven,"
        "Longzhong_Oilchem,2026-08-27,2026-09-01T00:00:00Z,actual\n"
        "2026-08-28,纯碱,SA,联碱法双吨,bad,420,1380,-60,0,near_breakeven,"
        "Longzhong_Oilchem,2026-08-28,2026-09-01T00:00:00Z,actual\n",
        encoding="utf-8",
    )

    result = ChemicalSpreadCalculator(raw_dir=tmp_path).load_raw_spreads_result()

    assert result.status == "PARTIAL"
    assert result.frame.height == 2
    assert result.errors
    assert build_spread_curated_frame(result.frame).height == 1


def test_load_real_raw_spreads() -> None:
    calc = ChemicalSpreadCalculator(raw_dir="data/raw/industry")
    df = calc.load_raw_spreads()
    assert not df.is_empty()
    curated = calc.build_historical_spreads()
    assert curated.height >= 12
    assert {"纯碱", "烧碱", "PTA", "钛白粉"}.issubset(
        set(curated["product_name"].unique().to_list())
    ), "核心化工品种价差必须存在于 Curated 价差表"
    assert "spread_margin_cny" in curated.columns
    assert "margin_regime" in curated.columns


def test_calculate_tio2_company_margins() -> None:
    calc = ChemicalSpreadCalculator(raw_dir="data/raw/industry")

    # 1. 测试具备自备矿一体化的硫酸法毛利计算
    # tio2=14000, ilmenite=2200, acid=350, captive=0.65, mine_cost=900, acid_coeff=3.0, fixed=3800, credit=150
    # blended_ore = 0.65*900 + 0.35*2200 = 1355.0
    # raw_cost = 2.0*1355 + 3.0*350 = 3760.0
    # margin = 14000 - 3760 - 3800 + 150 = 6590.0
    sulfate_lb = calc.calculate_tio2_integrated_sulfate_margin(
        tio2_price=14000.0,
        ilmenite_market_price=2200.0,
        acid_price=350.0,
        captive_ratio=0.65,
        captive_cash_cost=900.0,
        acid_coeff=3.0,
        fixed_cost=3800.0,
        byproduct_credit=150.0,
    )
    assert sulfate_lb == 6590.0

    # 2. 测试龙佰集团 (002601.SZ) 综合理论毛利计算 (硫酸法 43% + 氯化法 57%)
    # 动态氯化法毛利 = 14000 + 1800 - 12500 = 3300.0
    # 综合毛利 = 0.43 * 6590.0 + 0.57 * 3300.0 = 2833.7 + 1881.0 = 4714.7
    lb_res = calc.calculate_tio2_company_margins(
        symbol="002601.SZ",
        tio2_price=14000.0,
        ilmenite_price=2200.0,
        acid_price=350.0,
    )
    assert lb_res["symbol"] == "002601.SZ"
    assert lb_res["company_name"] == "龙佰集团"
    assert lb_res["sulfate_margin_cny"] == 6590.0
    assert lb_res["chloride_margin_cny"] == 3300.0
    assert lb_res["unit_gross_margin_cny"] == 4714.7
    assert lb_res["gross_margin_ratio"] == round(4714.7 / 14000.0, 4)
    assert lb_res["ore_captive_ratio"] == 0.65
    assert lb_res["sulfate_alpha_cny"] == 2015.0

    # 3. 测试钛能化学 (002145.SZ) 纯外购硫酸法毛利计算
    # raw_cost = 2.0*2200 + 3.0*350 = 5450.0
    # margin = 14000 - 5450 - 3800 + 100 = 4850.0
    zh_res = calc.calculate_tio2_company_margins(
        symbol="002145.SZ",
        tio2_price=14000.0,
        ilmenite_price=2200.0,
        acid_price=350.0,
    )
    assert zh_res["symbol"] == "002145.SZ"
    assert zh_res["company_name"] == "钛能化学"
    assert zh_res["unit_gross_margin_cny"] == 4850.0
    assert zh_res["ore_captive_ratio"] == 0.0

    # 4. 验证在相同硫酸法工艺下，龙佰集团相比钛能化学的矿石一体化 Alpha 利差
    # 龙佰硫酸法 6590 - 钛能硫酸法 4850 = 1740 元/吨
    diff = lb_res["sulfate_margin_cny"] - zh_res["unit_gross_margin_cny"]
    assert diff == 1740.0
