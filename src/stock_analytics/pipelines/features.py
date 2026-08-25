"""Analytics Feature 与 Domain Mart 构建业务入口。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_analytics.features import FeatureStore, MarketDailyBuilder
from stock_analytics.marts import DomainMartBuilder
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog


def build_features(
    *,
    target: str,
    start_date: date,
    end_date: date | None = None,
    overwrite: bool = False,
    storage_dir: Path | None = None,
) -> None:
    """构建指定的 Analytics Feature 或 Domain Mart。"""
    catalog = DataCatalog(data_source="tushare", storage_dir=storage_dir)
    store = FeatureStore(mart_dir=storage_dir / "mart" if storage_dir else None)

    if target in ("market_daily", "all"):
        market_builder = MarketDailyBuilder(catalog=catalog, store=store, storage_dir=storage_dir)
        frame = market_builder.build(
            start_date=start_date,
            end_date=end_date,
            save=True,
            overwrite=overwrite,
        )
        if frame.is_empty():
            raise RuntimeError("构建 market_daily 失败: 产出数据为空")
        date_min = str(frame["trade_date"].min())
        date_max = str(frame["trade_date"].max())
        logger.info(
            "成功构建并物化 market_daily: {} 行 (时间跨度: {} ~ {})",
            len(frame),
            date_min,
            date_max,
        )

    if target in ("domain_marts", "all"):
        domain_builder = DomainMartBuilder(catalog=catalog, store=store)
        results = domain_builder.build_all(
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
        )
        output_count = 0
        for name, result in results.items():
            count = (
                sum(frame.height for frame in result.values())
                if isinstance(result, dict)
                else result.height
            )
            output_count += count
            logger.info("领域 Mart [{}] 构建完成: {} 行", name, count)
        logger.info("领域 Mart 全部构建完成: {} 行", output_count)
    elif target in ("industry_daily", "industry_panel_daily", "derived_facts"):
        domain_builder = DomainMartBuilder(catalog=catalog, store=store)
        if target == "industry_daily":
            result = domain_builder.build_industry_daily(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [industry_daily] 构建完成: {} 行", result.height)
        elif target == "industry_panel_daily":
            result = domain_builder.build_industry_panel_daily(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [industry_panel_daily] 构建完成: {} 行", result.height)
        else:
            result = domain_builder.build_market_temperature_derived_facts(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info(
                "领域 Mart [market_temperature_derived_facts] 构建完成: {} 行",
                result.height,
            )


__all__ = ["build_features"]
