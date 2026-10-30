"""公司×月份×产品出口暴露面板（动态 H8 链路）。

输入 ``customs_company_h8_exposure.parquet``（公司×月份×H8，暴露金额
= H8 全国出口金额 × 公司主营产品暴露度），聚合到公司×产品×月份：

- ``export_value_usd``：该月该产品下公司暴露金额之和（出口景气代理）；
- ``export_volume``：量代理（全国量 × 加权暴露度），仅当产品内 H8 已知
  单位唯一时加总（否则置空，驱动不判，与 exposure_panel 同口径）；
- 3MMA 金额/量/价(ASP) yoy、驱动类型、拐点、二阶导——复用
  ``pipelines.customs_company.derive._derive`` 派生口径。

面板最新月快照与 ``customs_company_exposure_latest.csv`` 同构
（``bind_segment=""``，segment_name="H8动态"），可直接被
``signal.build_company_signal`` 消费合成三层信号。
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from stock_analytics.pipelines.customs_company.derive import _derive

PANEL_FILE = "customs_company_h8_product_panel.parquet"
PANEL_LATEST_FILE = "customs_company_h8_product_panel_latest.csv"

_NEEDED_COLUMNS = (
    "symbol",
    "company_name",
    "stock_industry",
    "product_key",
    "report_month",
    "hs_code",
    "product_exposure",
    "export_value_usd",
    "export_volume",
    "company_h8_export_value_usd",
    "company_h8_overseas_rev_est",
    "mapping_report_period",
    "segment_key",
    "segment_name",
)


def _check_columns(frame: pl.DataFrame, columns: tuple[str, ...]) -> None:
    missing = sorted(set(columns) - set(frame.columns))
    if missing:
        raise ValueError(f"公司-H8 暴露 Mart 缺少字段: {missing}")


def _build_unit_map(customs_trade: pl.DataFrame) -> dict[str, str | None]:
    """hs_code → 已知单位（黄金表；未知/缺失记 None，用于产品内单位唯一性判定）。"""
    if "quantity_unit_norm" not in customs_trade.columns:
        return {}
    rows = (
        customs_trade.select(["hs_code", "quantity_unit_norm", "unit_known"])
        .filter(pl.col("unit_known"))
        .select(["hs_code", "quantity_unit_norm"])
        .unique()
    )
    return {r["hs_code"]: r["quantity_unit_norm"] for r in rows.iter_rows(named=True)}


def _all_month_strs(months: list[str]) -> list[str]:
    """从离散月份构造完整月序（2016-01 起 n 个月，显式拼接避免 duration 差异）。"""
    first, last = months[0], months[-1]
    y0, m0 = int(first[:4]), int(first[5:7])
    y1, m1 = int(last[:4]), int(last[5:7])
    total0 = y0 * 12 + (m0 - 1)
    total1 = y1 * 12 + (m1 - 1)
    return [f"{(t // 12)}-{(t % 12) + 1:02d}" for t in range(total0, total1 + 1)]


def build_company_h8_product_panel(
    exposure_mart: pl.DataFrame,
    customs_trade: pl.DataFrame,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, object]]:
    """从公司-H8 月度暴露 Mart 聚合公司×产品×月份面板 + 最新月快照。

    Args:
        exposure_mart: ``customs_company_h8_exposure.parquet``（公司×月份×H8）。
        customs_trade: 海关黄金事实表（用于产品内 H8 单位唯一性判定）。

    Returns:
        (panel 全序列, latest 最新月快照, 统计)。
    """
    _check_columns(exposure_mart, _NEEDED_COLUMNS)
    if exposure_mart.is_empty():
        raise ValueError("公司-H8 暴露 Mart 为空")

    exp = exposure_mart.select(list(_NEEDED_COLUMNS))
    unit_map = _build_unit_map(customs_trade)

    # 产品内 H8 已知单位唯一性：唯一才允许加总量（否则量置空，驱动不判）
    hs_units = (
        exp.select(["product_key", "hs_code"])
        .unique()
        .with_columns(
            pl.col("hs_code")
            .map_elements(lambda code: unit_map.get(str(code)), return_dtype=pl.String)
            .alias("unit")
        )
    )
    product_unit_ok = (
        hs_units.group_by("product_key")
        .agg(pl.col("unit").drop_nulls().unique().len().alias("n_units"))
        .with_columns((pl.col("n_units") == 1).alias("volume_aggregable"))
        .select(["product_key", "volume_aggregable"])
    )

    # 公司×产品×月份聚合：金额全量；加权暴露度（Σ暴露金额/Σ全国金额）；
    # 量仅产品内单位唯一时加总（Σ 量×暴露度）
    monthly = (
        exp.group_by(
            [
                "symbol",
                "company_name",
                "stock_industry",
                "product_key",
                "report_month",
                "segment_key",
            ]
        )
        .agg(
            pl.col("company_h8_export_value_usd").sum().alias("export_value_usd"),
            (pl.col("export_volume") * pl.col("product_exposure")).sum().alias("_vol_sum"),
            (pl.col("company_h8_export_value_usd").sum() / pl.col("export_value_usd").sum()).alias(
                "product_exposure"
            ),
            pl.col("company_h8_overseas_rev_est").sum().alias("overseas_rev_est"),
            pl.col("mapping_report_period").max().alias("mapping_report_period"),
            pl.col("segment_name").first().alias("segment_name"),
        )
        .join(product_unit_ok, on="product_key", how="left")
        .with_columns(
            pl.when(pl.col("volume_aggregable"))
            .then(pl.col("_vol_sum"))
            .otherwise(None)
            .alias("export_volume")
        )
        .drop(["_vol_sum", "volume_aggregable"])
    )

    # 补全月序（公司×产品键 × 全局月序），重算 3MMA yoy/驱动/拐点/二阶导
    key = "symbol::product_key::segment_key"
    monthly = monthly.with_columns(
        (pl.col("symbol") + "::" + pl.col("product_key") + "::" + pl.col("segment_key")).alias(key)
    )
    months = exp["report_month"].unique().sort().to_list()
    panel = (
        _derive(monthly, key, _all_month_strs(months))
        .sort([key, "report_month"])
        .filter(pl.col("export_value_usd").is_not_null())
        .drop(key)
    )

    # H8 覆盖数预聚合（避免逐行扫全表）
    hs_count = exp.group_by(["symbol", "product_key", "segment_key"]).agg(
        pl.col("hs_code").n_unique().alias("n_hs_codes")
    )

    # 最新月快照：每 (symbol, product_key, segment_key) 一行
    panel_keys = panel.select(["symbol", "product_key", "segment_key"]).unique()
    last_rows = []
    for row in panel_keys.iter_rows(named=True):
        sub = panel.filter(
            (pl.col("symbol") == row["symbol"])
            & (pl.col("product_key") == row["product_key"])
            & (pl.col("segment_key") == row["segment_key"])
        ).sort("report_month")
        last_rows.append(sub.tail(1).row(0, named=True))
    latest = (
        pl.DataFrame(last_rows)
        .join(hs_count, on=["symbol", "product_key", "segment_key"], how="left")
        .rename({"symbol": "stock_code"})
        .with_columns(
            pl.col("segment_key").alias("bind_segment"),
            pl.when(pl.col("segment_name") == "")
            .then(pl.lit("产品级"))
            .otherwise(pl.col("segment_name"))
            .alias("segment_name"),
        )
        .select(
            [
                "company_name",
                "stock_code",
                "product_key",
                "product_exposure",
                "bind_segment",
                "segment_name",
                "n_hs_codes",
                "report_month",
                "overseas_rev_est",
                "value_yoy_3mma",
                "volume_yoy_3mma",
                "price_yoy_3mma",
                "驱动类型",
                "拐点",
                "二阶导",
            ]
        )
        .rename({"product_exposure": "exposure"})
        .sort(["product_key", "company_name"])
    )
    stats = {
        "panel_rows": panel.height,
        "panel_pairs": panel_keys.height,
        "company_rows": latest.height,
        "companies": latest["company_name"].n_unique(),
        "products": latest["product_key"].n_unique(),
        "months": panel["report_month"].n_unique(),
        "latest_month": str(panel["report_month"].max()),
    }
    return panel, latest, stats


def save_company_h8_product_panel(
    panel: pl.DataFrame, latest: pl.DataFrame, output_dir: Path | str
) -> tuple[Path, Path]:
    """落盘公司×产品面板（全序列 parquet + 最新月 CSV）。"""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    pq = root / PANEL_FILE
    csv = root / PANEL_LATEST_FILE
    panel.write_parquet(pq)
    latest.write_csv(csv, include_header=True)
    return pq, csv


__all__ = [
    "PANEL_FILE",
    "PANEL_LATEST_FILE",
    "build_company_h8_product_panel",
    "save_company_h8_product_panel",
]
