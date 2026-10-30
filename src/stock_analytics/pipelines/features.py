"""Analytics Feature 与 Domain Mart 构建业务入口。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from stock_analytics.features import FeatureStore, MarketDailyBuilder
from stock_analytics.marts import DomainMartBuilder
from stock_analytics.marts.build_steps import build_corporate_actions, build_unlock_pressure
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog

#: ``features build`` 支持的目标宽表或领域 Mart
TARGET_CHOICES: tuple[str, ...] = (
    "market_daily",
    "industry_daily",
    "industry_panel_daily",
    "derived_facts",
    "global_macro_daily",
    "dragon_tiger_daily",
    "etf_flow_daily",
    "industry_l2_daily",
    "corporate_actions_daily",
    "unlock_pressure_daily",
    "northbound_industry_daily",
    "capital_game_daily",
    "smart_money_daily",
    "settlement_iv_proxy_daily",
    "domain_marts",
    "all",
)


def build_features(
    *,
    target: str,
    start_date: date,
    end_date: date | None = None,
    overwrite: bool = False,
    storage_dir: Path | None = None,
    refresh_marts: bool = False,
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
    elif target in (
        "industry_daily",
        "industry_panel_daily",
        "derived_facts",
        "global_macro_daily",
        "dragon_tiger_daily",
        "etf_flow_daily",
        "industry_l2_daily",
        "corporate_actions_daily",
        "unlock_pressure_daily",
        "northbound_industry_daily",
        "capital_game_daily",
        "smart_money_daily",
        "settlement_iv_proxy_daily",
    ):
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
        elif target == "derived_facts":
            result = domain_builder.build_market_temperature_derived_facts(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info(
                "领域 Mart [market_temperature_derived_facts] 构建完成: {} 行",
                result.height,
            )
        elif target == "global_macro_daily":
            result = domain_builder.build_global_macro(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [global_macro_daily] 构建完成: {} 行", result.height)
        elif target == "dragon_tiger_daily":
            result = domain_builder.build_dragon_tiger(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [dragon_tiger_daily] 构建完成: {} 行", result.height)
        elif target == "etf_flow_daily":
            result = domain_builder.build_etf_flow(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [etf_flow_daily] 构建完成: {} 行", result.height)
        elif target == "corporate_actions_daily":
            result = build_corporate_actions(
                catalog,
                store,
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
                include_block_trade_discount=True,
                refresh_start=refresh_marts,
            )
            output_count = sum(frame.height for frame in result.values())
            logger.info("领域 Mart [corporate_actions_daily] 构建完成: {} 行", output_count)
        elif target == "unlock_pressure_daily":
            result = build_unlock_pressure(
                catalog,
                store,
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
                refresh_start=refresh_marts,
            )
            logger.info("领域 Mart [unlock_pressure_daily] 构建完成: {} 行", result.height)
        elif target == "northbound_industry_daily":
            result = domain_builder.build_northbound_industry(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [northbound_industry_daily] 构建完成: {} 行", result.height)
        elif target == "capital_game_daily":
            result = domain_builder.build_capital_game(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [capital_game_daily] 构建完成: {} 行", result.height)
        elif target == "smart_money_daily":
            result = domain_builder.build_smart_money(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [smart_money_daily] 构建完成: {} 行", result.height)
        elif target == "settlement_iv_proxy_daily":
            result = domain_builder.build_settlement_iv_proxy(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [settlement_iv_proxy_daily] 构建完成: {} 行", result.height)
        else:
            result = domain_builder.build_industry_l2(
                start_date=start_date,
                end_date=end_date,
                overwrite=overwrite,
            )
            logger.info("领域 Mart [industry_l2_daily] 构建完成: {} 行", result.height)


__all__ = ["TARGET_CHOICES", "build_features"]
