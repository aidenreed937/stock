from pathlib import Path

import polars as pl

from stock_analytics.pipelines.customs_prosperity import (
    build_forward_watch,
    build_product_panel,
    run_customs_prosperity_pipeline,
)
from stock_analytics.pipelines.customs_prosperity.amount_panel import (
    build_amount_panel,
    complete_months,
    derive_amount_metrics,
    save_amount_panel,
)
from stock_analytics.pipelines.customs_prosperity.config import (
    CustomsProsperityConfig,
    load_customs_prosperity_config,
)
from stock_analytics.pipelines.customs_prosperity.product_panel import save_product_panel
from stock_analytics.pipelines.customs_prosperity.volume_price import (
    build_volume_price_panel,
    save_volume_price_panel,
)

_HS_CODES = {
    "84138200",  # transformer 相关 hs8
    "85340000",  # pcb
    "27101913",  # 成品油新码（GACC-only）
    "27101911",  # 成品油旧码（UN）
}


def _trades_frame() -> pl.DataFrame:
    """构造最小海关黄金事实表：2 产品 × 2 源 × 14 个月（2016-01 ~ 2017-02）。"""
    rows = []
    for month_i, m in enumerate([f"2016-{i:02d}" for i in range(1, 13)] + ["2017-01", "2017-02"]):
        # transformer::units（UN 与 GACC 各一半月份，模拟跨源）
        v = 1000 + month_i * 100
        rows.append(
            {
                "report_month": m,
                "trade_direction": "export",
                "hs_level": "8",
                "hs_code": "84138200",
                "hs_parent_code": "8413",
                "source": "UN_Comtrade" if month_i % 2 == 0 else "GACC",
                "export_value_usd": v,
                "export_volume": float(10 + month_i),
                "quantity_unit": "units",
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
        # pcb::units（仅 UN，另一产品）
        rows.append(
            {
                "report_month": m,
                "trade_direction": "export",
                "hs_level": "8",
                "hs_code": "85340000",
                "hs_parent_code": "8534",
                "source": "UN_Comtrade",
                "export_value_usd": 500 + month_i * 50,
                "export_volume": float(5 + month_i),
                "quantity_unit": "units",
                "product_key": "pcb",
                "product_name": "印制电路板",
                "hs_name": "印制电路",
                "target_l1_code": "801900.SI",
                "target_l1_name": "电子",
                "target_l2_codes": "801153.SI",
                "target_l2_names": "元件",
                "target_l3_codes": "850241.SI",
                "target_l3_names": "元件Ⅲ",
            }
        )
    return pl.DataFrame(rows)


def _hs_catalog(tmp_path: Path) -> Path:
    """构造最小 good_h8_codes.csv（6/8 位行，拆段用）。"""
    p = tmp_path / "good_h8_codes.csv"
    pl.DataFrame(
        {
            "product_key": ["transformer", "pcb"],
            "hs_code": ["84138200", "85340000"],
            "hs_level": ["8", "8"],
            "hs_parent_code": ["8413", "8534"],
            "quantity_unit": ["units", "units"],
        }
    ).write_csv(p)
    return p


def _fake_dim(derived_dir: Path) -> None:
    """写最小维度黄金表用于桥接校验（仅 2 条 L2/L3 行）。"""
    derived_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(
        {
            "classification": ["sw2021" for _ in range(4)],
            "level": ["L2", "L2", "L3", "L3"],
            "industry_code": ["270100", "270300", "852331", "852241"],
            "index_code": ["801738.SI", "801153.SI", "850331.SI", "850241.SI"],
            "industry_name": ["电网设备", "元件", "电网设备Ⅲ", "元件Ⅲ"],
            "parent_code": [None, None, "270100", "270300"],
            "src": ["manual"] * 4,
            "tushare_present": [1] * 4,
            "lixinger_present": [1] * 4,
            "mapping_status": ["mapped"] * 4,
        }
    ).write_parquet(derived_dir / "sw_2021_industry_dimension_golden.parquet")


def _write_customs_trade(tmp_path: Path) -> Path:
    p = tmp_path / "curated" / "industry" / "customs_trade.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    _trades_frame().write_parquet(p)
    return p


def test_load_config_defaults() -> None:
    """默认配置加载（YAML 存在时读取一致性表；缺失时回退默认值）。"""
    config = load_customs_prosperity_config("config/analytics/customs_prosperity.yaml")
    assert isinstance(config, CustomsProsperityConfig)
    assert config.artifact_root == "data/analytics/industry"
    assert "801033.SI;801034.SI" in config.skip_l2
    assert "hydrogen_electrolyzer" in config.skip_vp
    assert config.research_sources == ("GACC",)
    assert "801738.SI" in config.consistency_table
    assert config.consistency_table["801738.SI"] == (1.0, "A")

    # 缺失路径回退默认值
    config_missing = load_customs_prosperity_config("/nonexistent/customs_prosperity.yaml")
    assert config_missing.consistency_table == {}


def test_derive_amount_metrics_and_complete_months() -> None:
    """3MMA yoy 口径：跨源拼接序列上统一重算，缺月置 null 不填 0。"""
    monthly = pl.DataFrame(
        {
            "hs_code": ["84138200"] * 14,
            "report_month": [f"2016-{i:02d}" for i in range(1, 13)] + ["2017-01", "2017-02"],
            "export_value_usd": [1000.0 + i * 100 for i in range(14)],
        }
    )
    all_months = [f"2016-{i:02d}" for i in range(1, 13)] + ["2017-01", "2017-02", "2017-03"]
    completed = complete_months(monthly, "hs_code", all_months)
    # 2017-03 为缺月 → 三个指标为 null
    missing = completed.filter(pl.col("report_month") == "2017-03")
    assert missing["export_value_usd"].to_list() == [None]

    derived = derive_amount_metrics(completed, "hs_code")
    # 3MMA 首月 = 自身值（min_samples=1，忽略 null）
    first = derived.filter(pl.col("report_month") == "2016-01")
    assert first["export_value_3mma"].to_list() == [1000.0]
    # 缺月 export_value_usd 为 null（补全对位依据），3MMA 沿用窗口内值不崩溃
    missing_derived = derived.filter(pl.col("report_month") == "2017-03")
    assert missing_derived["export_value_usd"].to_list() == [None]
    # 连续 14 月序列：2017-01 3MMA(2000+2100+2200)/3=2100 vs 2016-12 3MMA=2000 → mom=0.05
    jan17 = derived.filter(pl.col("report_month") == "2017-01")
    assert jan17["mom_growth_3mma"].to_list() == [0.05]


def test_build_amount_panel(tmp_path: Path) -> None:
    """金额面板：hs8/l3/l2 三层合并；GACC-only 码保留；组合码不在 hs8/L3 层剔除。"""
    trade = _trades_frame()
    panel = build_amount_panel(trade, sources=("UN_Comtrade", "GACC"))
    assert {"granularity", "code", "name", "report_month", "yoy_growth_3mma"}.issubset(
        panel.columns
    )
    # 三层粒度齐全
    assert set(panel["granularity"].unique().to_list()) == {"hs8", "l3", "l2"}
    # hs8 层含 2 产品 14 月序列
    hs8 = panel.filter(pl.col("granularity") == "hs8")
    assert hs8["code"].n_unique() == 2
    assert hs8.height == 2 * 14
    # l2 层：无组合码
    l2 = panel.filter(pl.col("granularity") == "l2")
    assert l2["code"].str.contains(";").any() is False
    # 输出路径契约
    out = save_amount_panel(panel, tmp_path)
    assert out.name == "customs_export_prosperity_panel.parquet"
    assert out.exists()


def test_build_amount_panel_gacc_only_default() -> None:
    """默认研究口径只消费 GACC：UN-only 产品不进入面板，序列起点随 GACC 段。"""
    trade = _trades_frame()
    panel = build_amount_panel(trade)  # 默认 sources=("GACC",)
    hs8 = panel.filter(pl.col("granularity") == "hs8")
    # pcb 只有 UN 行 → 被过滤；transformer 仅保留 GACC 月份（7 个有值月 + 补全 6 个缺月）
    assert hs8["code"].n_unique() == 1
    assert hs8.height == 13  # 2016-01 ~ 2017-01（GACC 段 13 个月）
    assert set(hs8["code"].unique().to_list()) == {"84138200"}
    l2 = panel.filter(pl.col("granularity") == "l2")
    assert set(l2["code"].unique().to_list()) == {"801738.SI"}


def test_build_volume_price_panel(tmp_path: Path) -> None:
    """量价分解：数量仅可加总产品聚合；伪影产品量价置空；组合码跳过。"""
    trade = _trades_frame().with_columns(
        pl.col("export_volume").cast(pl.Float64),
        pl.col("quantity_unit").cast(pl.String),
    )
    vp = build_volume_price_panel(
        trade,
        skip_vp=frozenset({"hydrogen_electrolyzer"}),
        sources=("UN_Comtrade", "GACC"),
    )
    assert {
        "粒度",
        "code",
        "report_month",
        "value_yoy_3mma",
        "volume_yoy_3mma",
        "驱动类型",
    }.issubset(vp.columns)
    assert set(vp["粒度"].unique().to_list()) == {"L2", "L3"}
    # 无组合码行
    assert vp["code"].str.contains(";").any() is False
    out = save_volume_price_panel(vp, tmp_path)
    assert out.name == "customs_l2_volume_price_monthly.parquet"


def test_build_product_panel(tmp_path: Path) -> None:
    """商品级拐点：段级面板 + 桥接校验关闭时仍含拐点/二阶导列。"""
    trade = _trades_frame()
    cat = _hs_catalog(tmp_path)
    panel = build_product_panel(
        trade,
        catalog_path=cat,
        storage_dir=tmp_path,
        validate_bridge_flag=False,
        sources=("UN_Comtrade", "GACC"),
    )
    assert {
        "seg_key",
        "product_key",
        "unit_segment",
        "report_month",
        "value_yoy_3mma",
        "volume_yoy_3mma",
        "price_yoy_3mma",
        "驱动类型",
        "拐点",
        "二阶导",
    }.issubset(panel.columns)
    # 单单位产品整品不拆段：unit_segment == units
    assert set(panel["unit_segment"].unique().to_list()) == {"units"}
    out = save_product_panel(panel, tmp_path)
    assert out.name == "customs_product_volume_price.parquet"


def test_build_forward_watch_skips_bridge_broken(tmp_path: Path) -> None:
    """观察表：缺维度黄金表时以 bridge 缺失结束（不产生空文件）。"""
    _write_customs_trade(tmp_path)
    # 未写维度表 → load_dim 失败，但不静默产出
    try:
        build_forward_watch(
            tmp_path,
            storage_dir=tmp_path,
            consistency_table={"801738.SI": (1.0, "A")},
        )
        raise AssertionError("缺维度表应抛出异常")
    except Exception:
        pass


def test_run_pipeline_writes_manifest(tmp_path: Path) -> None:
    """管线编排：金额/量价/商品产物 + Manifest 落盘（观察表缺维度表由错误路径测试覆盖）。"""
    config_path = tmp_path / "customs_prosperity.yaml"
    config_path.write_text(
        f"""
artifact_root: "{tmp_path}"
customs_trade_path: "{_write_customs_trade(tmp_path)}"
research_sources:
  - "UN_Comtrade"
  - "GACC"
hs_catalog_path: "{_hs_catalog(tmp_path)}"
consistency_table:
  "801738.SI": [1.00, "A"]
""".lstrip(),
        encoding="utf-8",
    )
    outputs = run_customs_prosperity_pipeline(
        config_path=config_path,
        storage_dir=tmp_path,
        build_forward=False,
        product_bridge_check=False,
    )
    assert "amount" in outputs and outputs["amount"].exists()
    assert "volume_price" in outputs and outputs["volume_price"].exists()
    assert "product" in outputs and outputs["product"].exists()
    # Manifest 含水位
    manifest_path = tmp_path / "customs_prosperity_manifest.json"
    assert manifest_path.exists()
    import json

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact_type"] == "customs_prosperity"
    assert manifest["watermarks"]["amount"]["min"] == "2016-01"
    assert manifest["watermarks"]["amount"]["max"] == "2017-02"


def test_pipeline_build_product_flag_false(tmp_path: Path) -> None:
    """skip-product：不构建商品级拐点面板（仅金额/量价）。"""
    config_path = tmp_path / "c.yaml"
    config_path.write_text(
        f"""
artifact_root: "{tmp_path}"
customs_trade_path: "{_write_customs_trade(tmp_path)}"
hs_catalog_path: "{_hs_catalog(tmp_path)}"
""".lstrip(),
        encoding="utf-8",
    )
    outputs = run_customs_prosperity_pipeline(
        config_path=config_path,
        storage_dir=tmp_path,
        build_product=False,
        build_forward=False,
    )
    assert "amount" in outputs and "volume_price" in outputs
    assert "product" not in outputs
    assert not (tmp_path / "customs_product_volume_price.parquet").exists()
    assert not (tmp_path / "customs_forward_watch_l2.parquet").exists()


def test_pipeline_empty_trade_raises(tmp_path: Path) -> None:
    """空黄金事实表 → 显式报错而非静默产出。"""
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
        run_customs_prosperity_pipeline(config_path=cfg, storage_dir=tmp_path)
        raise AssertionError("空表应报错")
    except ValueError:
        pass
