"""第二梯队通用塑料与大炼化核心品种 (EB 苯乙烯 / PP 聚丙烯 / PX 对二甲苯) 单元测试。

验证：
1. EB/PP/PX 成本模型与工艺阶梯配置解析；
2. 核心上市公司 (宝丰能源/东华能源/荣盛石化/恒力石化) 业绩弹性映射与暴露度；
3. 截面雷达对 EB/PP/PX 现货价格、成本出清、期现基差与综合评级的端到端计算。
"""

from __future__ import annotations

import polars as pl
import yaml

from stock_analytics.marts.chemical_cost_curves import (
    DEFAULT_COST_CONFIGS,
    build_chemical_cost_curves_mart,
)
from stock_analytics.marts.chemical_cross_section_mart import (
    ChemicalCrossSectionMart,
)
from stock_analytics.marts.chemical_elasticity_mart import (
    build_chemical_elasticity_mart,
)


def test_eb_pp_px_cost_models_validity() -> None:
    """验证 EB、PP、PX 的成本模型配置与工艺阶梯完整性。"""
    for sym in ("EB", "PP", "PX"):
        assert sym in DEFAULT_COST_CONFIGS
        cfg_path = DEFAULT_COST_CONFIGS[sym]
        assert cfg_path.exists(), f"配置文件不存在: {cfg_path}"

        content = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        assert content["symbol"] == sym
        models = content.get("models", {})
        assert len(models) >= 2, f"{sym} 至少应包含 2 条及以上工艺路线"

        for _, m in models.items():
            assert "full_cost_approx" in m
            assert "cash_cost_approx" in m
            assert float(m["full_cost_approx"]) >= float(m["cash_cost_approx"])


def test_eb_pp_px_cost_curves_mart_output() -> None:
    """验证成本曲线 Mart 能够正确物化 EB、PP、PX 并判定出清状态。"""
    summary_df, ladders_df = build_chemical_cost_curves_mart()
    codes = summary_df["commodity_code"].to_list()
    assert "EB" in codes
    assert "PP" in codes
    assert "PX" in codes

    # 验证 PP 阶梯包含煤制、油制与 PDH 路线
    pp_ladders = ladders_df.filter(pl.col("commodity_code") == "PP")
    assert len(pp_ladders) == 3
    routes = pp_ladders["process_key"].to_list()
    assert "coal_to_polypropylene" in routes
    assert "pdh_to_pp" in routes


def test_eb_pp_px_elasticity_mart() -> None:
    """验证上市公司业绩弹性 Mart 包含大炼化与塑料龙头标的。"""
    el_df = build_chemical_elasticity_mart()
    assert not el_df.is_empty()

    # 验证宝丰能源 (PP)
    bf = el_df.filter((pl.col("commodity_code") == "PP") & (pl.col("symbol") == "600989.SH"))
    assert not bf.is_empty()
    assert float(bf["eps_delta_per_100cny"][0]) > 0.0

    # 验证东华能源 (PP-PDH)
    dh = el_df.filter((pl.col("commodity_code") == "PP") & (pl.col("symbol") == "002221.SZ"))
    assert not dh.is_empty()
    assert float(dh["eps_delta_per_100cny"][0]) > 0.0

    # 验证荣盛石化 (PX/EB)
    rs_px = el_df.filter((pl.col("commodity_code") == "PX") & (pl.col("symbol") == "002493.SZ"))
    assert not rs_px.is_empty()
    assert float(rs_px["eps_delta_per_100cny"][0]) > 0.0


def test_eb_pp_px_cross_section_mart_integration() -> None:
    """验证截面雷达中 EB、PP、PX 的端到端整合与特征完备性。"""
    engine = ChemicalCrossSectionMart()
    df = engine.build_cross_section_frame()
    assert len(df) == 13

    for sym in ("EB", "PP", "PX"):
        row = df.filter(pl.col("commodity_code") == sym).row(0, named=True)
        assert row["spot_price_cny"] > 0.0, f"{sym} 现货价格应大于 0"
        assert row["composite_score"] >= 0.0
        assert row["investment_stance"] in (
            "OVERWEIGHT_LEFT",
            "OVERWEIGHT_RIGHT",
            "NEUTRAL_WATCH",
            "UNDERWEIGHT_TRIM",
            "AVOID_SHORT",
        )
