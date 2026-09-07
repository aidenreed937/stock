"""UN Comtrade 海关重点品类进出口贸易黄金事实表 Schema 与转换器。"""

from collections.abc import Sequence

import polars as pl

from stock_data.fetcher.industry.customs.models import CustomsTradeRecord
from stock_data.fetcher.industry.customs.schemas import CUSTOMS_TRADE_SCHEMA
from stock_data.fetcher.industry.customs.transforms.volume_price import (
    flag_volume_aggregable,
    normalize_quantity_unit,
)


def empty_customs_trade() -> pl.DataFrame:
    """返回标准空的 CustomsTradeRecord DataFrame。"""
    return pl.DataFrame(schema=CUSTOMS_TRADE_SCHEMA)


def records_to_customs_trade_frame(records: Sequence[CustomsTradeRecord]) -> pl.DataFrame:
    """将 CustomsTradeRecord 列表转换为 Polars 黄金事实表长表。

    派生指标:
    1. export_asp_usd: 出口均价 = export_value_usd / export_volume（税号粒度）
    2. export_value_3mma: 按 (product_key, trade_direction) 聚合月度出口金额
       （同一品类多税号先求和，跨 HS 版本演进保持序列连续）后计算 3 个月移动平均
    3. yoy_growth_3mma: 3MMA 出口金额同比增速 (lag 12 个月)
    4. mom_growth_3mma: 3MMA 出口金额月环比增速 (lag 1 个月)

    单位标注（2026-09 量价分离核查落地）:
    5. quantity_unit_norm / unit_known: 计量单位同义归一（千克→kg、台/个/辆→units），
       未知单位保留原值并标记
    6. volume_aggregable: 产品级数量可加总标注——产品在其全部行中单位归一去重后
       唯一且已知才为 True；真混用（如半导体设备 units vs kg）或含未知单位的产品
       数量跨 HS 加总无意义，下游聚合 `export_volume` 前必须先过滤该列。
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
            "hs_level": r.hs_level,
            "hs_parent_code": r.hs_parent_code,
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
            "target_l3_codes": r.target_l3_codes,
            "target_l3_names": r.target_l3_names,
            "export_value_3mma": r.export_value_3mma,
            "yoy_growth_3mma": r.yoy_growth_3mma,
            "mom_growth_3mma": r.mom_growth_3mma,
            "source": r.source,
            "source_url": r.source_url,
            "release_date": r.release_date,
            "data_status": r.data_status,
            "collected_at": r.collected_at,
            "trade_value_currency": r.trade_value_currency,
            "raw_content_sha256": r.raw_content_sha256,
            "raw_snapshot_path": r.raw_snapshot_path,
        }
        for r in records
    ]

    df = pl.DataFrame(data_dicts, schema=CUSTOMS_TRADE_SCHEMA)
    df = df.sort(["product_key", "hs_code", "trade_direction", "trade_date"])

    # 1. 计算/补全 export_asp_usd（税号粒度）
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

    # 2. 品类级月度聚合：同一 product 多税号先求和（跨 HS 版本演进连续），再算 3MMA/YoY/MoM
    agg_cols = ["product_key", "trade_date", "trade_direction", "trade_value_currency"]
    prod = (
        df.group_by(agg_cols)
        .agg(pl.col("export_value_usd").sum().alias("export_value_usd"))
        .sort(agg_cols)
        .with_columns(
            pl.col("export_value_usd")
            .rolling_mean(window_size=3, min_samples=1)
            .over(["product_key", "trade_direction", "trade_value_currency"])
            .alias("export_value_3mma")
        )
    )
    prod = prod.with_columns(
        pl.when(
            pl.col("export_value_3mma")
            .shift(12)
            .over(["product_key", "trade_direction", "trade_value_currency"])
            > 0
        )
        .then(
            (
                pl.col("export_value_3mma")
                - pl.col("export_value_3mma")
                .shift(12)
                .over(["product_key", "trade_direction", "trade_value_currency"])
            )
            / pl.col("export_value_3mma")
            .shift(12)
            .over(["product_key", "trade_direction", "trade_value_currency"])
        )
        .otherwise(None)
        .alias("yoy_growth_3mma"),
        pl.when(
            pl.col("export_value_3mma")
            .shift(1)
            .over(["product_key", "trade_direction", "trade_value_currency"])
            > 0
        )
        .then(
            (
                pl.col("export_value_3mma")
                - pl.col("export_value_3mma")
                .shift(1)
                .over(["product_key", "trade_direction", "trade_value_currency"])
            )
            / pl.col("export_value_3mma")
            .shift(1)
            .over(["product_key", "trade_direction", "trade_value_currency"])
        )
        .otherwise(None)
        .alias("mom_growth_3mma"),
    )

    # 3. 品类级派生指标回填到税号长表（先移除旧派生列，避免 join 同名列冲突）
    df = df.drop(["export_value_3mma", "yoy_growth_3mma", "mom_growth_3mma"]).join(
        prod.select(
            [
                "product_key",
                "trade_date",
                "trade_direction",
                "trade_value_currency",
                "export_value_3mma",
                "yoy_growth_3mma",
                "mom_growth_3mma",
            ]
        ),
        on=["product_key", "trade_date", "trade_direction", "trade_value_currency"],
        how="left",
    )

    # 4. 单位归一 + 产品级数量可加总标注（量价分离核查落地）
    df = normalize_quantity_unit(df)
    df = flag_volume_aggregable(df).with_columns(pl.col("volume_aggregable").fill_null(False))

    return df


__all__ = ["CUSTOMS_TRADE_SCHEMA", "empty_customs_trade", "records_to_customs_trade_frame"]
