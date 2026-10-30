from datetime import date
from pathlib import Path

import polars as pl
import pytest

from stock_analytics.pipelines.customs_company_h8 import (
    build_company_h8_product_panel,
    run_customs_company_h8_pipeline,
    save_company_h8_product_panel,
)


def _month_strs(n: int, start: str = "2020-04") -> list[str]:
    """生成连续合法月份（显式拼接避免 polars duration 差异）。"""
    y0, m0 = int(start[:4]), int(start[5:7])
    out: list[str] = []
    for i in range(n):
        total = y0 * 12 + (m0 - 1) + i
        out.append(f"{total // 12}-{(total % 12) + 1:02d}")
    return out


def _exposure_mart() -> pl.DataFrame:
    """最小公司-H8 暴露 Mart：1 公司 × 1 产品 × 2 个 H8 × 30 个月。"""
    months = _month_strs(30)
    rows = []
    for i, m in enumerate(months):
        rows.append(
            {
                "symbol": "600089.SH",
                "company_name": "特变电工",
                "stock_industry": "电网设备",
                "product_key": "transformer",
                "report_month": m,
                "hs_code": "84138200",
                "product_exposure": 0.6,
                "export_value_usd": 1000.0 + i * 100,
                "export_volume": 10.0 + i,
                "company_h8_export_value_usd": (1000.0 + i * 100) * 0.6,
                "company_h8_overseas_rev_est": 100.0,
                "mapping_report_period": date(2025, 12, 31),
                "segment_key": "",
                "segment_name": "",
            }
        )
        rows.append(
            {
                "symbol": "600089.SH",
                "company_name": "特变电工",
                "stock_industry": "电网设备",
                "product_key": "transformer",
                "report_month": m,
                "hs_code": "85042100",
                "product_exposure": 0.6,
                "export_value_usd": 500.0 + i * 50,
                "export_volume": 5.0 + i * 0.5,
                "company_h8_export_value_usd": (500.0 + i * 50) * 0.6,
                "company_h8_overseas_rev_est": 60.0,
                "mapping_report_period": date(2025, 12, 31),
                "segment_key": "",
                "segment_name": "",
            }
        )
    return pl.DataFrame(rows)


def _customs_trade() -> pl.DataFrame:
    """黄金表：两个 H8 同一单位（units），保证产品内单位唯一可加总量。"""
    return pl.DataFrame(
        {
            "hs_code": ["84138200", "85042100"],
            "quantity_unit_norm": ["units", "units"],
            "unit_known": [True, True],
        }
    )


def _customs_trade_mixed_units() -> pl.DataFrame:
    """黄金表：两个 H8 单位不一致 → 产品内量不可加总（驱动不判）。"""
    return pl.DataFrame(
        {
            "hs_code": ["84138200", "85042100"],
            "quantity_unit_norm": ["units", "kg"],
            "unit_known": [True, True],
        }
    )


def test_build_panel_derives_3mma_yoy_series() -> None:
    panel, latest, stats = build_company_h8_product_panel(_exposure_mart(), _customs_trade())
    assert "value_yoy_3mma" in panel.columns
    assert "volume_yoy_3mma" in panel.columns
    assert "price_yoy_3mma" in panel.columns
    assert "驱动类型" in panel.columns
    # 单调递增金额 → yoy 为正，量价齐升
    nonzero = panel.filter(pl.col("value_yoy_3mma").is_not_null())
    assert nonzero.height > 0
    latest_row = latest.row(0, named=True)
    assert latest_row["stock_code"] == "600089.SH"
    assert latest_row["product_key"] == "transformer"
    assert latest_row["bind_segment"] == ""
    assert latest_row["segment_name"] == "产品级"
    assert stats["panel_pairs"] == 1
    # 暴露金额 = 两个 H8 全国金额之和 × 0.6
    last_month = panel["report_month"].max()
    last = panel.filter(pl.col("report_month") == last_month)
    assert last["export_value_usd"].item() == pytest.approx(
        (1000.0 + 29 * 100 + 500.0 + 29 * 50) * 0.6
    )


def test_build_panel_volume_null_when_product_units_mixed() -> None:
    panel, _, _ = build_company_h8_product_panel(_exposure_mart(), _customs_trade_mixed_units())
    # 单位不一致 → export_volume 全空 → 量 yoy/驱动不判
    assert panel["export_volume"].null_count() == panel.height
    assert panel["volume_yoy_3mma"].null_count() == panel.height
    drv = panel["驱动类型"].drop_nulls()
    assert drv.is_empty() or (drv.to_list() and all(v in ("价驱动", "双弱") for v in drv.to_list()))


def test_save_company_h8_product_panel(tmp_path: Path) -> None:
    panel, latest, _ = build_company_h8_product_panel(_exposure_mart(), _customs_trade())
    pq, csv = save_company_h8_product_panel(panel, latest, tmp_path)
    assert pq.exists() and csv.exists()
    assert pl.read_parquet(pq).height == panel.height
    assert pl.read_csv(csv).height == latest.height


def _write_market_data(tmp_path: Path) -> tuple[Path, Path, Path]:
    """写资金/两融/财报三个目录（各一个 parquet，symbol 与面板快照一致）。"""
    mf_dir = tmp_path / "moneyflow"
    mf_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["600089.SH"] * 20,
            "trade_date": [f"2026-0{1 + i // 10}-{1 + i % 10:02d}" for i in range(20)],
            "net_mf_amount": [1.0] * 20,
            "buy_elg_amount": [100.0] * 20,
            "buy_lg_amount": [100.0] * 20,
            "buy_md_amount": [100.0] * 20,
            "buy_sm_amount": [100.0] * 20,
        }
    ).write_parquet(mf_dir / "part.parquet")

    mg_dir = tmp_path / "margin"
    mg_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["600089.SH"] * 20,
            "trade_date": [f"2026-0{1 + i // 10}-{1 + i % 10:02d}" for i in range(20)],
            "rzye": [100.0 + i for i in range(20)],
        }
    ).write_parquet(mg_dir / "part.parquet")

    fi_dir = tmp_path / "fina"
    fi_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "symbol": ["600089.SH"],
            "end_date": ["2026-06-30"],
            "or_yoy": [15.0],
            "netprofit_yoy": [20.0],
        }
    ).write_parquet(fi_dir / "part.parquet")
    return mf_dir, mg_dir, fi_dir


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """写暴露 Mart + 黄金表 parquet（管线输入）。"""
    mart = tmp_path / "exposure.parquet"
    _exposure_mart().write_parquet(mart)
    trade = tmp_path / "trade.parquet"
    _customs_trade().write_parquet(trade)
    return mart, trade


def test_run_h8_pipeline_produces_panel_and_signal(tmp_path: Path) -> None:
    mart, trade = _write_inputs(tmp_path)
    mf_dir, mg_dir, fi_dir = _write_market_data(tmp_path)
    root = tmp_path / "analytics"

    outputs = run_customs_company_h8_pipeline(
        exposure_mart_path=mart,
        customs_trade_path=trade,
        artifact_root=root,
        build_signal=True,
        moneyflow_path=mf_dir,
        margin_path=mg_dir,
        fina_path=fi_dir,
    )
    # 面板产物
    assert outputs["h8_product_panel"].exists()
    assert outputs["h8_product_latest"].exists()
    # 信号产物（出口强正 + 资金正 + 财报双正 → A强机会）
    signal = pl.read_parquet(outputs["h8_signal_panel"])
    assert "f1_state" in signal.columns
    assert "f2_state" in signal.columns
    assert "f3_state" in signal.columns
    assert "rating" in signal.columns
    row = signal.row(0, named=True)
    assert row["f1_state"] == "强正"
    assert row["f2_state"] == "正"
    assert row["f3_state"] == "真扩张"
    assert row["rating"] == "A强机会"
    assert row["risk_flag"] == ""
    # Manifest
    manifest = (root / "customs_company_h8_manifest.json").read_text(encoding="utf-8")
    assert '"stats"' in manifest
