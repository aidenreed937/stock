"""UN Comtrade 海关重点品类进出口贸易黄金事实表 Schema 与转换器。"""

from collections.abc import Sequence

import polars as pl

from stock_data.fetcher.industry.models import CustomsTradeRecord

CUSTOMS_TRADE_SCHEMA = {
    "category_key": pl.Utf8,
    "category_name": pl.Utf8,
    "product_key": pl.Utf8,
    "product_name": pl.Utf8,
    "hs_code": pl.Utf8,
    "hs_name": pl.Utf8,
    "report_month": pl.Utf8,
    "trade_date": pl.Date,
    "trade_direction": pl.Utf8,
    "export_value_usd": pl.Float64,
    "export_volume": pl.Float64,
    "quantity_unit": pl.Utf8,
    "export_asp_usd": pl.Float64,
    "target_l1_code": pl.Utf8,
    "target_l1_name": pl.Utf8,
    "target_l2_codes": pl.Utf8,
    "target_l2_names": pl.Utf8,
    "export_value_3mma": pl.Float64,
    "yoy_growth_3mma": pl.Float64,
    "mom_growth_3mma": pl.Float64,
    "source": pl.Utf8,
    "source_url": pl.Utf8,
    "release_date": pl.Date,
    "data_status": pl.Utf8,
    "collected_at": pl.Utf8,
}


def empty_customs_trade() -> pl.DataFrame:
    """返回标准空的 CustomsTradeRecord DataFrame。"""
    return pl.DataFrame(schema=CUSTOMS_TRADE_SCHEMA)


def records_to_customs_trade_frame(records: Sequence[CustomsTradeRecord]) -> pl.DataFrame:
    """将 CustomsTradeRecord 列表转换为 Polars 黄金事实表长表。

    派生指标:
    1. export_asp_usd: 出口均价 = export_value_usd / export_volume
    2. export_value_3mma: 按 (product_key, hs_code, trade_direction) 分组计算 3 个月移动平均出口金额
    3. yoy_growth_3mma: 3MMA 出口金额同比增速 (lag 12 个月)
    4. mom_growth_3mma: 3MMA 出口金额月环比增速 (lag 1 个月)
    """
    if not records:
        return empty_customs_trade()

    data_dicts = [
        {
            "category_key": r.category_key,
            "category_name": r.category_name,
            "product_key": r.product_key,
            "product_name": r.product_name,
            "hs_code": r.hs_code,
            "hs_name": r.hs_name,
            "report_month": r.report_month,
            "trade_date": r.trade_date,
            "trade_direction": r.trade_direction,
            "export_value_usd": r.export_value_usd,
            "export_volume": r.export_volume,
            "quantity_unit": r.quantity_unit,
            "export_asp_usd": r.export_asp_usd,
            "target_l1_code": r.target_l1_code,
            "target_l1_name": r.target_l1_name,
            "target_l2_codes": r.target_l2_codes,
            "target_l2_names": r.target_l2_names,
            "export_value_3mma": r.export_value_3mma,
            "yoy_growth_3mma": r.yoy_growth_3mma,
            "mom_growth_3mma": r.mom_growth_3mma,
            "source": r.source,
            "source_url": r.source_url,
            "release_date": r.release_date,
            "data_status": r.data_status,
            "collected_at": r.collected_at,
        }
        for r in records
    ]

    df = pl.DataFrame(data_dicts, schema=CUSTOMS_TRADE_SCHEMA)
    df = df.sort(["product_key", "hs_code", "trade_direction", "trade_date"])

    # 1. 计算/补全 export_asp_usd
    df = df.with_columns(
        pl.when(
            pl.col("export_asp_usd").is_null()
            & pl.col("export_volume").is_not_null()
            & (pl.col("export_volume") > 0)
        )
        .then(pl.col("export_value_usd") / pl.col("export_volume"))
        .otherwise(pl.col("export_asp_usd"))
        .alias("export_asp_usd")
    )

    # 2. 按品类与税号分组计算 3MMA 与同比/环比
    group_cols = ["product_key", "hs_code", "trade_direction"]
    df = df.with_columns(
        pl.col("export_value_usd")
        .rolling_mean(window_size=3, min_samples=1)
        .over(group_cols)
        .alias("export_value_3mma")
    )

    df = df.with_columns(
        pl.when(pl.col("export_value_3mma").shift(12).over(group_cols) > 0)
        .then(
            (pl.col("export_value_3mma") - pl.col("export_value_3mma").shift(12).over(group_cols))
            / pl.col("export_value_3mma").shift(12).over(group_cols)
        )
        .otherwise(None)
        .alias("yoy_growth_3mma"),
        pl.when(pl.col("export_value_3mma").shift(1).over(group_cols) > 0)
        .then(
            (pl.col("export_value_3mma") - pl.col("export_value_3mma").shift(1).over(group_cols))
            / pl.col("export_value_3mma").shift(1).over(group_cols)
        )
        .otherwise(None)
        .alias("mom_growth_3mma"),
    )

    return df
