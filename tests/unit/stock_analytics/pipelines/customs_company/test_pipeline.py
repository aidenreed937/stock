from pathlib import Path

import polars as pl

from stock_analytics.pipelines.customs_company import run_customs_company_pipeline
from stock_analytics.pipelines.customs_company.config import (
    CustomsCompanyConfig,
    load_customs_company_config,
)
from stock_analytics.pipelines.customs_company.exposure_panel import (
    build_exposure_panel,
    build_segment_key_map,
    load_catalog_hs_codes,
    save_exposure_panel,
)
from stock_analytics.pipelines.customs_company.signal import (
    build_company_signal,
    export_leg_state,
    fin_leg_state,
    fund_leg_state,
    load_fina_latest,
    load_margin_change,
    load_moneyflow_strength,
    rate,
    save_company_signal,
)


def _month_strs(n: int, start: str = "2016-01") -> list[str]:
    """生成连续合法月份（2016-01 起 n 个月），显式拼接避免 polars duration 差异。"""
    y0, m0 = int(start[:4]), int(start[5:7])
    out: list[str] = []
    for i in range(n):
        total = y0 * 12 + (m0 - 1) + i
        out.append(f"{total // 12}-{(total % 12) + 1:02d}")
    return out


def _trades_frame() -> pl.DataFrame:
    """最小海关黄金事实表：1 产品 1 hs8 码 30 个月（保证 3MMA yoy 有 12 期基数）。"""
    rows = []
    for month_i, m in enumerate(_month_strs(30)):
        rows.append(
            {
                "report_month": m,
                "trade_direction": "export",
                "hs_level": "8",
                "hs_code": "84138200",
                "hs_parent_code": "841382",
                "source": "UN_Comtrade",
                "export_value_usd": 1000.0 + month_i * 100,
                "export_volume": float(10 + month_i),
                "quantity_unit": "units",
                "quantity_unit_norm": "units",
                "unit_known": True,
                "product_key": "transformer",
                "product_name": "变压器",
                "hs_name": "电力变压器",
                "target_l1_code": "801900.SI",
                "target_l1_name": "电气",
                "target_l2_codes": "801738.SI",
                "target_l2_names": "电网设备",
                "target_l3_codes": "850331.SI",
                "target_l3_names": "电网设备Ⅲ",
            }
        )
    return pl.DataFrame(rows)


def _write_assets(tmp_path: Path) -> tuple[Path, Path, Path]:
    """写 exposure map / catalog / segments 三个配置 CSV（loader 必填列齐全）。"""
    map_p = tmp_path / "company_exposure_map.csv"
    pl.DataFrame(
        {
            "product_key": ["transformer"],
            "product_name": ["变压器"],
            "stock_code": ["600089.SH"],
            "company_name": ["特变电工"],
            "exposure": [0.8],
            "sw_l2": ["电网设备"],
            "evidence": ["fina_mainbz 2026-06-30"],
            "status": ["verified"],
            "taxline_segment": ["ultra"],
        }
    ).write_csv(map_p)

    cat_p = tmp_path / "hs_codes_catalog.csv"
    pl.DataFrame(
        {
            "product_key": ["transformer", "transformer"],
            "hs_code": ["84138200", "841382"],
            "hs_level": ["8", "6"],
            "hs_parent_code": ["841382", "841382"],
            "quantity_unit": ["units", "units"],
        }
    ).write_csv(cat_p)

    seg_p = tmp_path / "taxline_segments.csv"
    pl.DataFrame(
        {
            "product_key": ["transformer"],
            "segment_key": ["ultra"],
            "segment_name": ["超高压段"],
            "hs_codes": ["84138200"],
            "description": ["测试段"],
        }
    ).write_csv(seg_p)
    return map_p, cat_p, seg_p


def _write_market_data(tmp_path: Path) -> tuple[Path, Path, Path]:
    """写资金/两融/财报三个目录（各一个 parquet 文件，symbol 与公司快照一致）。"""
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


def _write_customs_trade(tmp_path: Path) -> Path:
    p = tmp_path / "curated" / "industry" / "customs_trade.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    _trades_frame().write_parquet(p)
    return p


def test_load_config_defaults() -> None:
    config = load_customs_company_config("config/analytics/customs_company.yaml")
    assert isinstance(config, CustomsCompanyConfig)
    assert config.artifact_root == "data/analytics/industry"
    assert config.fund_window == 20
    assert config.margin_chg_th == 2.0

    missing = load_customs_company_config("/nonexistent/customs_company.yaml")
    assert missing.fund_window == 20


def test_load_catalog_hs_codes_and_segment_keys(tmp_path: Path) -> None:
    _, cat_p, seg_p = _write_assets(tmp_path)
    trade = _trades_frame()
    catalog_hs = load_catalog_hs_codes(cat_p, trade)
    assert "84138200" in catalog_hs["transformer"]
    from stock_data.fetcher.industry.customs.parsers.company_exposure import load_taxline_segments

    seg_map = load_taxline_segments(seg_p)
    keys = build_segment_key_map(seg_map, catalog_hs)
    assert "transformer::ultra" in keys
    assert "transformer::product" in keys


def test_build_exposure_panel(tmp_path: Path) -> None:
    trade = _trades_frame()
    map_p, cat_p, seg_p = _write_assets(tmp_path)
    panel, latest, stats = build_exposure_panel(
        trade,
        exposure_map_path=map_p,
        hs_catalog_path=cat_p,
        segments_path=seg_p,
    )
    assert "key" in panel.columns and "value_yoy_3mma" in panel.columns
    assert panel["key"].n_unique() >= 2  # segment + product 两个键
    assert latest["company_name"].to_list() == ["特变电工"]
    assert stats["companies"] == 1
    pq, csv = save_exposure_panel(panel, latest, tmp_path)
    assert pq.name == "customs_company_exposure.parquet"
    assert csv.name == "customs_company_exposure_latest.csv"
    assert pq.exists() and csv.exists()


def test_leg_state_functions() -> None:
    # 腿1 出口前瞻
    assert export_leg_state(0.4, "量价齐升", None, None)[0] == "强正"
    assert export_leg_state(0.1, "量驱动", None, None)[0] == "正"
    assert export_leg_state(-0.05, "双弱", None, None)[0] == "弱"
    assert export_leg_state(-0.3, "双弱", None, None)[0] == "负"
    assert export_leg_state(None, None, None, None)[0] == "未知"
    # 腿2 资金
    assert fund_leg_state(2.0, None)[0] == "正"
    assert fund_leg_state(-1.0, -3.0)[0] == "负"
    assert fund_leg_state(None, None)[0] == "未知"
    assert fund_leg_state(0.1, 0.5)[0] == "平"
    # 腿3 财报
    assert fin_leg_state(15.0, 20.0)[0] == "真扩张"
    assert fin_leg_state(15.0, -3.0)[0] == "增收不增利"
    assert fin_leg_state(None, 20.0)[0] == "未知"


def test_rate_combinations() -> None:
    assert rate("强正", "正", "真扩张", None, None) == ("A强机会", "")
    assert rate("正", "正", "未兑现", None, None) == ("B确认中", "")
    assert rate("正", "平", "真扩张", None, None) == ("C兑现中", "")
    assert rate("正", "未知", "未知", None, None) == ("D前瞻观察", "")
    # 顶背离：出口见顶 + 资金负 + 财报真扩张
    assert rate("正", "负", "真扩张", "见顶拐点", None) == ("回避", "顶背离⚠")
    assert rate("弱", "未知", "未知", None, None) == ("观望", "")


def test_market_loaders(tmp_path: Path) -> None:
    mf_dir, mg_dir, fi_dir = _write_market_data(tmp_path)
    fund = load_moneyflow_strength(mf_dir, ["600089.SH"], fund_window=20)
    assert fund["symbol"].to_list() == ["600089.SH"]
    # net=20*1=20, turn=20*400=8000 → 0.25%
    assert abs(fund["fund_strength_20d"].to_list()[0] - 0.25) < 1e-6
    margin = load_margin_change(mg_dir, ["600089.SH"], fund_window=20)
    assert abs(margin["margin_chg_20d"].to_list()[0] - 19.0) < 1e-6  # (119-100)/100*100
    fina = load_fina_latest(fi_dir, ["600089.SH"])
    assert fina["or_yoy"].to_list() == [15.0]


def test_build_company_signal(tmp_path: Path) -> None:
    _ = _write_assets(tmp_path)
    trade = _trades_frame()
    map_p, cat_p, seg_p = _write_assets(tmp_path)
    _, latest, _ = build_exposure_panel(
        trade, exposure_map_path=map_p, hs_catalog_path=cat_p, segments_path=seg_p
    )
    mf_dir, mg_dir, fi_dir = _write_market_data(tmp_path)
    signal = build_company_signal(
        latest,
        moneyflow_path=mf_dir,
        margin_path=mg_dir,
        fina_path=fi_dir,
    )
    assert {
        "f1_state",
        "f2_state",
        "f3_state",
        "rating",
        "risk_flag",
    }.issubset(signal.columns)
    assert signal.height == 1
    row = signal.row(0, named=True)
    assert row["f1_state"] == "强正"
    assert row["f3_state"] == "真扩张"
    assert row["rating"] == "A强机会"
    pq, csv = save_company_signal(signal, tmp_path)
    assert pq.name == "customs_company_signal.parquet"
    assert csv.name == "customs_company_signal_latest.csv"


def test_run_pipeline_writes_manifest(tmp_path: Path) -> None:
    config_path = tmp_path / "customs_company.yaml"
    map_p, cat_p, seg_p = _write_assets(tmp_path)
    mf_dir, mg_dir, fi_dir = _write_market_data(tmp_path)
    config_path.write_text(
        f"""
artifact_root: "{tmp_path}"
customs_trade_path: "{_write_customs_trade(tmp_path)}"
exposure_map_path: "{map_p}"
hs_catalog_path: "{cat_p}"
segments_path: "{seg_p}"
moneyflow_path: "{mf_dir}"
margin_path: "{mg_dir}"
fina_path: "{fi_dir}"
""".lstrip(),
        encoding="utf-8",
    )
    outputs = run_customs_company_pipeline(config_path=config_path)
    assert "exposure_panel" in outputs and outputs["exposure_panel"].exists()
    assert "exposure_latest" in outputs
    assert "signal_panel" in outputs and outputs["signal_panel"].exists()
    manifest_path = tmp_path / "customs_company_manifest.json"
    assert manifest_path.exists()
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact_type"] == "customs_company"
    assert manifest["stats"]["companies"] == 1
    assert manifest["watermarks"]["exposure_panel"]["min"] == "2016-01"


def test_run_pipeline_skip_signal(tmp_path: Path) -> None:
    config_path = tmp_path / "c.yaml"
    map_p, cat_p, seg_p = _write_assets(tmp_path)
    config_path.write_text(
        f"""
artifact_root: "{tmp_path}"
customs_trade_path: "{_write_customs_trade(tmp_path)}"
exposure_map_path: "{map_p}"
hs_catalog_path: "{cat_p}"
segments_path: "{seg_p}"
""".lstrip(),
        encoding="utf-8",
    )
    outputs = run_customs_company_pipeline(config_path=config_path, build_signal=False)
    assert "exposure_panel" in outputs
    assert "signal_panel" not in outputs
    assert not (tmp_path / "customs_company_signal.parquet").exists()


def test_run_pipeline_empty_trade_raises(tmp_path: Path) -> None:
    p = tmp_path / "curated" / "industry" / "customs_trade.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "report_month": [],
            "trade_direction": [],
            "hs_level": [],
            "hs_code": [],
            "source": [],
            "export_value_usd": [],
        }
    ).write_parquet(p)
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f'customs_trade_path: "{p}"\n', encoding="utf-8")
    try:
        run_customs_company_pipeline(config_path=cfg)
        raise AssertionError("空表应报错")
    except ValueError:
        pass
