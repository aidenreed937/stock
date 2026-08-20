"""从 Curated 黄金表构建衍生品与公司行为领域 Mart。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from stock_analytics.features.store import FeatureStore
from stock_analytics.marts.build_steps import (
    _load_risk_free_rates,
    build_convertible_bond,
    build_corporate_actions,
    build_settlement_iv_proxy,
)
from stock_analytics.marts.convertible_bond import CB_MART_NAME
from stock_analytics.marts.industry_structure import (
    build_industry_daily_mart,
    build_industry_panel_daily_mart,
)
from stock_analytics.marts.market_temperature import (
    build_market_temperature_derived_facts_mart,
)
from stock_analytics.marts.option_volatility import (
    DEFAULT_UNDERLYINGS,
    SETTLEMENT_IV_PROXY_MART_NAME,
)
from stock_analytics.pipelines.market_temperature.cache import DatasetFrameCache
from stock_data.catalog import DataCatalog
from stock_reporting.interpretation.industry_structure.config import (
    DEFAULT_CONFIG_PATH as DEFAULT_INDUSTRY_CONFIG_PATH,
)
from stock_reporting.interpretation.industry_structure.config import (
    load_industry_structure_config,
)
from stock_reporting.interpretation.market_temperature.config import (
    DEFAULT_CONFIG_PATH as DEFAULT_MARKET_TEMPERATURE_CONFIG_PATH,
)
from stock_reporting.interpretation.market_temperature.config import (
    load_market_temperature_config,
)

if TYPE_CHECKING:
    from stock_data.core.runtime import DataRuntimeContext


class DomainMartBuilder:
    """领域 Mart 构建器，统一管理 Curated 输入与 Mart 输出。"""

    def __init__(
        self,
        catalog: DataCatalog,
        store: FeatureStore,
        *,
        runtime: DataRuntimeContext | None = None,
    ) -> None:
        self.catalog = catalog
        self.store = store
        self.runtime = runtime

    def build_convertible_bond(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        overwrite: bool = False,
    ) -> pl.DataFrame:
        """构建并保存可转债日频聚合 Mart。"""
        return build_convertible_bond(
            self.catalog,
            self.store,
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
        )

    def build_corporate_actions(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        overwrite: bool = False,
        include_block_trade_discount: bool = True,
    ) -> dict[str, pl.DataFrame]:
        """构建并保存产业资本、回购和大宗交易三个 Mart。"""
        return build_corporate_actions(
            self.catalog,
            self.store,
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
            include_block_trade_discount=include_block_trade_discount,
        )

    def build_settlement_iv_proxy(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        overwrite: bool = False,
        underlying_symbols: tuple[str, ...] = DEFAULT_UNDERLYINGS,
    ) -> pl.DataFrame:
        """构建并保存结算价隐含波动率代理 Mart。"""
        return build_settlement_iv_proxy(
            self.catalog,
            self.store,
            runtime=self.runtime,
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
            underlying_symbols=underlying_symbols,
            risk_free_rates=self._load_risk_free_rates(
                start_date=start_date,
                end_date=end_date,
            ),
        )

    def build_industry_daily(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        overwrite: bool = False,
        config_path: Path | str = DEFAULT_INDUSTRY_CONFIG_PATH,
        dataset_cache: DatasetFrameCache | None = None,
    ) -> pl.DataFrame:
        """构建并保存申万行业日频事实 Mart。"""
        config = load_industry_structure_config(config_path)
        cache = dataset_cache or DatasetFrameCache(end_date=end_date)
        return build_industry_daily_mart(
            self.catalog,
            self.store,
            config,
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
            dataset_cache=cache,
        )

    def build_industry_panel_daily(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        overwrite: bool = False,
        config_path: Path | str = DEFAULT_INDUSTRY_CONFIG_PATH,
        dataset_cache: DatasetFrameCache | None = None,
    ) -> pl.DataFrame:
        """构建并保存逐基准日申万行业结构面板 Mart。"""
        config = load_industry_structure_config(config_path)
        cache = dataset_cache or DatasetFrameCache(end_date=end_date)
        return build_industry_panel_daily_mart(
            self.catalog,
            self.store,
            config,
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
            dataset_cache=cache,
        )

    def build_market_temperature_derived_facts(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        overwrite: bool = False,
        config_path: Path | str = DEFAULT_MARKET_TEMPERATURE_CONFIG_PATH,
        dataset_cache: DatasetFrameCache | None = None,
    ) -> pl.DataFrame:
        """构建并保存市场温度计派生事实 Mart。"""
        config = load_market_temperature_config(config_path)
        return build_market_temperature_derived_facts_mart(
            self.catalog,
            self.store,
            config,
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
            dataset_cache=dataset_cache,
        )

    def _load_risk_free_rates(
        self,
        *,
        start_date: date | None,
        end_date: date | None,
    ) -> pl.DataFrame:
        """加载期权波动率代理所需的风险利率。"""
        return _load_risk_free_rates(
            self.catalog,
            runtime=self.runtime,
            start_date=start_date,
            end_date=end_date,
        )

    def build_all(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        overwrite: bool = False,
    ) -> dict[str, pl.DataFrame | dict[str, pl.DataFrame]]:
        """按阶段构建全部可用领域 Mart；输入缺失时返回空结果，不伪造数据。"""
        dataset_cache = DatasetFrameCache(end_date=end_date)
        results: dict[str, pl.DataFrame | dict[str, pl.DataFrame]] = {
            CB_MART_NAME: self.build_convertible_bond(
                start_date=start_date, end_date=end_date, overwrite=overwrite
            ),
            "corporate_actions": self.build_corporate_actions(
                start_date=start_date, end_date=end_date, overwrite=overwrite
            ),
            SETTLEMENT_IV_PROXY_MART_NAME: self.build_settlement_iv_proxy(
                start_date=start_date, end_date=end_date, overwrite=overwrite
            ),
        }
        results["industry_daily"] = self.build_industry_daily(
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
            dataset_cache=dataset_cache,
        )
        results["industry_panel_daily"] = self.build_industry_panel_daily(
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
            dataset_cache=dataset_cache,
        )
        results["market_temperature_derived_facts"] = self.build_market_temperature_derived_facts(
            start_date=start_date,
            end_date=end_date,
            overwrite=overwrite,
            dataset_cache=dataset_cache,
        )
        return results


__all__ = ["DomainMartBuilder"]
