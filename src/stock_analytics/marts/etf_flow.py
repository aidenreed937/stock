r"""ETF 份额变动与风格资金流日频领域 Mart。

用 ``etf_share_size``（份额）与 ``fund_daily``（收盘价）预计算观察池
（``config/universe/watchlist.yaml`` 的 funds，单一信任源）每日资金净流入：

.. math::

    flow_t = (\\text{total\\_share}_t - \\text{total\\_share}_{t-1}) \\times \\text{close}_t

口径说明：
- ``total_share`` 源单位为万份，构建时转换为份（乘以 1e4），输出金额统一为元；
- 份额缺测日不产出流水（不推断流入为零之外的事实）；
- 宽基/行业主题按基金名称关键词分类，属近似口径；货币、债券与国债类 ETF 不计入
  股票型宽基/行业风格资金流，但计入 ``total_etf_net_inflow``（若其份额变动可观测）。
"""

from __future__ import annotations

from typing import Any

import polars as pl

ETF_FLOW_MART_NAME = "etf_flow_daily"

TEN_THOUSAND = 10_000.0

#: 宽基/风格指数关键词（与行业主题互斥时优先命中宽基）
BROAD_KEYWORDS = (
    "沪深300",
    "中证500",
    "中证1000",
    "中证2000",
    "中证800",
    "科创50",
    "科创板50",
    "科创100",
    "上证50",
    "创业板",
    "深证100",
    "A500",
    "A50",
    "双创",
    "红利",
    "央企",
    "国企",
    "自由现金流",
    "价值",
    "成长",
)

#: 行业/主题关键词（命中即视为行业风格 ETF）
SECTOR_KEYWORDS = (
    "芯片",
    "半导体",
    "科技",
    "计算机",
    "软件",
    "人工智能",
    "云计算",
    "通信",
    "5G",
    "电子",
    "消费电子",
    "互联网",
    "传媒",
    "游戏",
    "医药",
    "医疗",
    "创新药",
    "生物",
    "疫苗",
    "中药",
    "消费",
    "食品",
    "白酒",
    "酒",
    "饮料",
    "家电",
    "汽车",
    "新能源",
    "光伏",
    "电池",
    "储能",
    "风电",
    "电力",
    "公用事业",
    "煤炭",
    "石油",
    "油气",
    "有色",
    "金属",
    "稀土",
    "钢铁",
    "化工",
    "建材",
    "房地产",
    "建筑",
    "交运",
    "物流",
    "农业",
    "养殖",
    "畜牧",
    "军工",
    "国防",
    "航天",
    "机械",
    "机器人",
    "智能制造",
    "环保",
    "碳中和",
    "金融",
    "银行",
    "证券",
    "券商",
    "保险",
    "非银",
    "地产",
    "旅游",
    "酒店",
    "零售",
    "纺织",
    "服饰",
    "轻工",
    "教育",
    "影视",
)

#: 货币/债券/国债（不计入股票风格资金流）
MONEY_BOND_KEYWORDS = (
    "货币",
    "国债",
    "国开",
    "政金债",
    "信用债",
    "中短债",
    "短融",
    "地方债",
    "城投债",
    "可转债",
    "年金",
)

ETF_FLOW_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "total_etf_net_inflow": pl.Float64,
    "broad_etf_net_inflow": pl.Float64,
    "sector_etf_net_inflow": pl.Float64,
    "etf_300_inflow": pl.Float64,
    "etf_500_inflow": pl.Float64,
    "etf_1000_inflow": pl.Float64,
    "etf_kcb50_inflow": pl.Float64,
    "top_inflow_sector_name": pl.Utf8,
}


def empty_etf_flow() -> pl.DataFrame:
    """返回稳定 schema 的空 ETF 资金流 Mart。"""
    return pl.DataFrame(schema=ETF_FLOW_SCHEMA)


def _contains_any(text: str | None, keywords: tuple[str, ...]) -> bool:
    if not text:
        return False
    return any(kw in text for kw in keywords)


def classify_etf(name: str | None) -> str:
    """粗分类：``broad`` / ``sector`` / ``other``（货币债券归 other）。"""
    if _contains_any(name, MONEY_BOND_KEYWORDS):
        return "other"
    if _contains_any(name, BROAD_KEYWORDS):
        return "broad"
    if _contains_any(name, SECTOR_KEYWORDS):
        return "sector"
    return "other"


def _index_bucket(name: str | None) -> str | None:
    """返回命中的核心宽基桶（300/500/1000/kcb50），未命中返回 None。"""
    if not name:
        return None
    if any(kw in name for kw in ("科创50", "科创板50")):
        return "kcb50"
    if "沪深300" in name or "300" in name:
        return "300"
    if "中证500" in name or "500" in name:
        return "500"
    if "中证1000" in name or "1000" in name:
        return "1000"
    return None


def _sector_tag(name: str | None) -> str | None:
    """返回命中的行业主题词（用于逐日统计最大流入行业），未命中返回 None。"""
    if not name:
        return None
    for keyword in SECTOR_KEYWORDS:
        if keyword in name:
            return keyword
    return None


def build_etf_flow_frame(
    etf_share_size: pl.DataFrame,
    fund_daily: pl.DataFrame,
    etf_universe: list[str] | None = None,
) -> pl.DataFrame:
    """从份额与行情构建观察池 ETF 日频资金流聚合。

    ``etf_share_size`` 提供份额（源单位为万份），``fund_daily`` 提供收盘价；
    未指定 ``etf_universe`` 时使用两源交集（覆盖完整、可算流水的标的），
    建议由调用方传入观察池（如 ``watchlist.yaml`` 的 funds）。
    """
    required = {"trade_date", "symbol", "total_share", "close"}
    if fund_daily.is_empty() or "close" not in fund_daily.columns:
        return empty_etf_flow()
    if etf_share_size.is_empty() or not required.issubset(etf_share_size.columns):
        return empty_etf_flow()

    # 1) 份额侧：每股按日排序，计算 Δ份额（万份）
    shares = (
        etf_share_size.select(
            "trade_date",
            "symbol",
            "etf_name",
            pl.col("total_share").cast(pl.Float64, strict=False).alias("_share_wan"),
        )
        .filter(pl.col("_share_wan").is_not_null())
        .sort(["symbol", "trade_date"])
        .with_columns(
            pl.col("_share_wan")
            .shift(1)
            .over("symbol", order_by="trade_date")
            .alias("_prev_share_wan")
        )
        .filter(pl.col("_prev_share_wan").is_not_null())
        .with_columns((pl.col("_share_wan") - pl.col("_prev_share_wan")).alias("_delta_wan"))
    )
    if shares.is_empty():
        return empty_etf_flow()

    # 2) 价格侧：fund_daily 收盘价（按 symbol+date 去重）
    prices = (
        fund_daily.select(
            "trade_date",
            "symbol",
            pl.col("close").cast(pl.Float64, strict=False).alias("_close"),
        )
        .filter(pl.col("_close").is_not_null())
        .unique(subset=["symbol", "trade_date"], keep="last")
    )

    # 3) 合并：日频资金流 = Δ份额(份) × 收盘价(元)
    merged = (
        shares.join(prices, on=["symbol", "trade_date"], how="left")
        .with_columns((pl.col("_delta_wan") * TEN_THOUSAND * pl.col("_close")).alias("_flow"))
        .filter(pl.col("_close").is_not_null() & pl.col("_flow").is_not_null())
    )
    if merged.is_empty():
        return empty_etf_flow()

    # 4) 采用两源交集（或调用方指定观察池），资产名不可用则跳过
    universe = etf_universe or sorted(merged.select("symbol").unique().to_series().to_list())
    merged = merged.filter(pl.col("symbol").is_in(universe))
    if merged.is_empty():
        return empty_etf_flow()

    tagged = merged.with_columns(
        pl.col("etf_name").fill_null("").alias("_name"),
    ).with_columns(
        pl.col("_name").map_elements(classify_etf, return_dtype=pl.Utf8).alias("_bucket"),
        pl.col("_name").map_elements(_index_bucket, return_dtype=pl.Utf8).alias("_index_bucket"),
        pl.col("_name").map_elements(_sector_tag, return_dtype=pl.Utf8).alias("_sector"),
    )

    daily = (
        tagged.group_by("trade_date")
        .agg(
            pl.col("_flow").sum().alias("total_etf_net_inflow"),
            pl.col("_flow").filter(pl.col("_bucket") == "broad").sum().alias("_broad_flow"),
            pl.col("_flow").filter(pl.col("_bucket") == "sector").sum().alias("_sector_flow"),
        )
        .sort("trade_date")
        .with_columns(
            pl.col("_broad_flow").alias("broad_etf_net_inflow"),
            pl.col("_sector_flow").alias("sector_etf_net_inflow"),
        )
        .drop("_broad_flow", "_sector_flow")
    )

    index_sums = (
        tagged.filter(pl.col("_index_bucket").is_not_null())
        .group_by(["trade_date", "_index_bucket"])
        .agg(pl.col("_flow").sum().alias("_flow_sum"))
        .pivot(
            values="_flow_sum",
            index="trade_date",
            on="_index_bucket",
            aggregate_function="sum",
        )
    )
    sector_daily = (
        tagged.filter(pl.col("_sector").is_not_null())
        .group_by(["trade_date", "_sector"])
        .agg(pl.col("_flow").sum().alias("_sector_flow"))
        .sort(["trade_date", "_sector_flow"], descending=[False, True])
        .unique(subset=["trade_date"], keep="first")
        .select(
            "trade_date",
            pl.col("_sector").alias("top_inflow_sector_name"),
        )
    )

    result = daily
    for column, target in (
        ("300", "etf_300_inflow"),
        ("500", "etf_500_inflow"),
        ("1000", "etf_1000_inflow"),
        ("kcb50", "etf_kcb50_inflow"),
    ):
        if column in index_sums.columns:
            result = result.join(
                index_sums.select("trade_date", pl.col(column).alias(target)),
                on="trade_date",
                how="left",
            )
        else:
            result = result.with_columns(pl.lit(None, dtype=pl.Float64).alias(target))
    if not sector_daily.is_empty():
        result = result.join(sector_daily, on="trade_date", how="left")
    else:
        result = result.with_columns(pl.lit(None, dtype=pl.Utf8).alias("top_inflow_sector_name"))

    return result.select(list(ETF_FLOW_SCHEMA)).sort("trade_date")


__all__ = ["ETF_FLOW_MART_NAME", "build_etf_flow_frame", "empty_etf_flow"]
