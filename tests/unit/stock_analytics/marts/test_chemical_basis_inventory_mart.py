"""大宗化工品期现基差时钟与交割仓单异动量化 Mart (chemical_basis_inventory_mart) 单元测试。

覆盖：
1. FUTURES_LOT_SPECS 合约规格与标准手吨数换算验证；
2. 期现结构判定 (Backwardation / Contango / Flat) 与右侧门禁通过规则；
3. 仓单万吨物理量折算、分位数、注销加速度与微观共振状态机；
4. 端到端 Mart 构建、落盘完整性与 Schema 契约验证；
5. 横向截面 Mart (chemical_cross_section_mart) 挂接消费微观特征联动验证。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.marts.chemical_basis_inventory_mart import (
    FUTURES_LOT_SPECS,
    ChemicalBasisInventoryMart,
)
from stock_analytics.marts.chemical_cross_section_mart import ChemicalCrossSectionMart


def test_futures_lot_specs_integrity() -> None:
    """验证大宗期货品种规格、手吨数与交易所配置完整性。"""
    core_symbols = ["SA", "TA", "EG", "MA", "V", "UR", "FG", "SH", "EB", "PP", "L"]
    for sym in core_symbols:
        assert sym in FUTURES_LOT_SPECS, f"缺少期货品种规格: {sym}"
        spec = FUTURES_LOT_SPECS[sym]
        assert spec["lot_size_tons"] > 0, f"{sym} 每手吨数必须大于 0"
        assert spec["exchange"] in ("CZCE", "DCE", "SHFE"), f"{sym} 交易所非法: {spec['exchange']}"

    # 验证关键品种标准手吨数
    assert FUTURES_LOT_SPECS["SA"]["lot_size_tons"] == 20.0
    assert FUTURES_LOT_SPECS["TA"]["lot_size_tons"] == 5.0
    assert FUTURES_LOT_SPECS["V"]["lot_size_tons"] == 5.0
    assert FUTURES_LOT_SPECS["EG"]["lot_size_tons"] == 10.0
    assert FUTURES_LOT_SPECS["MA"]["lot_size_tons"] == 10.0
    assert FUTURES_LOT_SPECS["SH"]["lot_size_tons"] == 30.0


def test_microstructure_calculation_logic() -> None:
    """验证手吨折算、期现结构与微观共振状态机判定逻辑。"""
    mart = ChemicalBasisInventoryMart()

    # 构造仿真时序测试数据 (25 交易日)
    n = 25
    dates = [date(2026, 1, 1 + i) for i in range(n)]

    # 模拟 PVC: 现货贴水 (Contango) + 天量仓单
    pvc_basis_df = pl.DataFrame(
        {
            "trade_date": dates,
            "spot_price_cny": [4800.0] * n,
            "dom_contract_price": [4900.0] * n,
            "basis_cny": [-100.0] * n,
            "basis_rate_pct": [-2.08] * n,
        }
    )
    pvc_inv_df = pl.DataFrame(
        {
            "trade_date": dates,
            "inventory": [60000.0 + i * 100 for i in range(n)],  # 约 6 万手
        }
    )

    res_pvc = mart._align_and_compute_symbol_timeseries(
        sub_basis=pvc_basis_df,
        sub_inv=pvc_inv_df,
        sub_sv=pl.DataFrame(),
        comm_code="V",
        f_sym="V",
        p_name="聚氯乙烯",
        lot_size=5.0,
    )

    assert not res_pvc.is_empty()
    latest_pvc = res_pvc.row(-1, named=True)
    # 62400 手 * 5 吨 / 10000 = 31.2 万吨
    assert pytest.approx(latest_pvc["warehouse_receipts_w_tons"], 0.1) == 31.2
    assert latest_pvc["basis_term_structure"] == "CONTANGO"
    assert latest_pvc["right_side_basis_gate_pass"] is False
    assert latest_pvc["receipts_overhang_status"] == "MASSIVE_OVERHANG"
    assert latest_pvc["composite_micro_regime"] == "BEARISH_CONTANGO_OVERHANG"

    # 模拟纯碱: 现货升水 (Backwardation) + 仓单加速注销
    sa_basis_df = pl.DataFrame(
        {
            "trade_date": dates,
            "spot_price_cny": [1200.0] * n,
            "dom_contract_price": [1100.0] * n,
            "basis_cny": [100.0] * n,
            "basis_rate_pct": [8.33] * n,
        }
    )
    # 仓单近 5 日加速下降
    inv_series = [5000.0] * 20 + [4000.0, 3000.0, 2000.0, 1000.0, 500.0]
    sa_inv_df = pl.DataFrame(
        {
            "trade_date": dates,
            "inventory": inv_series,
        }
    )

    res_sa = mart._align_and_compute_symbol_timeseries(
        sub_basis=sa_basis_df,
        sub_inv=sa_inv_df,
        sub_sv=pl.DataFrame(),
        comm_code="SA",
        f_sym="SA",
        p_name="纯碱",
        lot_size=20.0,
    )

    assert not res_sa.is_empty()
    latest_sa = res_sa.row(-1, named=True)
    assert latest_sa["basis_term_structure"] == "BACKWARDATION"
    assert latest_sa["right_side_basis_gate_pass"] is True
    assert latest_sa["receipts_acceleration_status"] == "ACCELERATED_DRAIN"
    assert latest_sa["composite_micro_regime"] == "STRONG_BULLISH_REVERSAL"


def test_build_mart_real_curated_data() -> None:
    """端到端测试真实 Curated 事实表构建并验证 Schema 契约。"""
    mart = ChemicalBasisInventoryMart()
    df = mart.build_mart()

    assert not df.is_empty(), "构建生成的 Mart 不能为空"
    expected_cols = [
        "trade_date",
        "spot_price_cny",
        "futures_close_cny",
        "basis_cny",
        "basis_rate_pct",
        "warehouse_receipts_contracts",
        "warehouse_receipts_w_tons",
        "basis_rate_pctl_1y",
        "receipts_pctl_1y",
        "basis_term_structure",
        "basis_convergence_signal",
        "receipts_acceleration_status",
        "composite_micro_regime",
        "right_side_basis_gate_pass",
    ]
    for col in expected_cols:
        assert col in df.columns, f"Mart 缺失必要字段: {col}"

    # 验证落盘 Parquet
    parquet_path = Path("data/curated/mart/chemical_basis_inventory_mart.parquet")
    assert parquet_path.exists()
    assert parquet_path.stat().st_size > 1000


def test_cross_section_mart_consumes_microstructure() -> None:
    """验证横向截面 Mart 能够正确吸收期现基差与仓单异动特征。"""
    cs_engine = ChemicalCrossSectionMart(as_of_date=date(2026, 9, 20))
    df = cs_engine.build_cross_section_frame()

    assert not df.is_empty()
    assert "basis_term_structure" in df.columns
    assert "warehouse_receipts_w_tons" in df.columns
    assert "composite_micro_regime" in df.columns
    assert "right_side_basis_gate_pass" in df.columns

    # 检查纯碱与 PVC 的微观指标是否填充
    row_sa = df.filter(pl.col("commodity_code") == "SA").row(0, named=True)
    assert row_sa["basis_term_structure"] == "BACKWARDATION"
    assert row_sa["right_side_basis_gate_pass"] is True

    row_v = df.filter(pl.col("commodity_code") == "V").row(0, named=True)
    assert row_v["basis_term_structure"] == "CONTANGO"
    assert row_v["right_side_basis_gate_pass"] is False
    assert "天量仓单压顶" in row_v["key_rationale"] or "贴水" in row_v["key_rationale"]
