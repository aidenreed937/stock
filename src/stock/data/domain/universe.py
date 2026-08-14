"""动态股票池筛选器 (UniverseFilter)。

结合 TuShare 数据源实现 ST 过滤、上市年限过滤及流动性过滤，
并生成用于理杏仁等引擎回填的优质股票池配置。
"""

from datetime import date, datetime
import os
from pathlib import Path
from typing import Any
import pandas as pd
import polars as pl
import yaml

from stock.data.domain.rules import (
    BasicExclusionRule,
    CompositeRuleChain,
    LiquidityRule,
    ValuationRule,
)
from stock.data.fetcher.tushare import TuShareDataFetcher
from stock.exceptions import DataFetchError
from stock.utils.logger import logger


class UniverseFilter:
    """生产级股票池筛选引擎 (Facade / Orchestrator)。"""

    def __init__(
        self,
        fetcher: TuShareDataFetcher | None = None,
        use_local: bool = True,
    ) -> None:
        self.fetcher = fetcher or TuShareDataFetcher()
        self.use_local = use_local

    def _fetch_stock_basic(self) -> pd.DataFrame:
        """获取 stock_basic 股票全集 (严格读取本地或按配置模式拉取)。"""
        if self.use_local:
            try:
                from stock.data.storage.duckdb_store import DuckDBMarketStore

                store = DuckDBMarketStore(data_source="tushare")
                df_pl = store.query_dataset(dataset="stock_basic")
                if not df_pl.is_empty():
                    logger.info("命中本地 DuckDB [stock_basic] 股票基础库归档。")
                    df = df_pl.to_pandas()
                    if "ts_code" in df.columns and "list_date" in df.columns:
                        return df
            except Exception as e:
                logger.error(f"读取本地 stock_basic 归档失败: {e}")

            raise DataFetchError(
                "本地缺失 stock_basic 股票基础库离线归档数据！"
                "为保证数据绝对一致，已彻底禁止在线请求降级。请先运行 `make backfill ENDPOINT=stock_basic` 补全本地基础库。"
            )

        logger.info("测试/非本地模式：请求接口或 Mock 获取 stock_basic 数据...")
        return self.fetcher.client.query("stock_basic", list_status="L")

    def load_filter_rules(
        self, rule_file: str = "config/universe/filter_rules.yaml"
    ) -> dict[str, Any]:
        """从配置文件动态解析粗筛规则。"""
        if os.path.exists(rule_file):
            try:
                with open(rule_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if (
                        data
                        and isinstance(data, dict)
                        and "filter_rules" in data
                        and isinstance(data["filter_rules"], dict)
                    ):
                        logger.info(f"成功载入筛选规则配置文件: {rule_file}")
                        return data["filter_rules"]
            except Exception as e:
                logger.warning(f"读取规则配置文件 [{rule_file}] 失败: {e}，将使用默认规则。")
        return {}

    def _filter_basic_stocks(
        self,
        df_basic: pd.DataFrame,
        *,
        exclude_st: bool,
        exclude_bj: bool,
        min_age_days: int,
    ) -> pd.DataFrame:
        """应用股票池共用的基础排除规则 (委托 BasicExclusionRule)。"""
        rule = BasicExclusionRule(
            exclude_st=exclude_st, exclude_bj=exclude_bj, min_age_days=min_age_days
        )
        return rule.apply(df_basic)

    def _fetch_latest_daily_basic(self) -> tuple[str, pd.DataFrame]:
        """从本地离线库检索最新行情、20日均成交额、流通市值及 PB 估值。"""
        if self.use_local:
            try:
                from stock.data.storage.duckdb_store import DuckDBMarketStore

                store = DuckDBMarketStore(data_source="tushare")
                df_bar_pl = store.query_dataset(dataset="stock_daily_bar")

                if (
                    not df_bar_pl.is_empty()
                    and "trade_date" in df_bar_pl.columns
                    and "amount" in df_bar_pl.columns
                ):
                    unique_dates = df_bar_pl["trade_date"].unique().sort(descending=True)
                    top20_dates = unique_dates.head(20)
                    latest_date = top20_dates[0]
                    code_col = "ts_code" if "ts_code" in df_bar_pl.columns else "symbol"

                    df_20d = df_bar_pl.filter(pl.col("trade_date").is_in(top20_dates.to_list()))
                    df_agg = df_20d.group_by(code_col).agg(
                        [
                            pl.col("amount").mean().alias("amount_20d"),
                            pl.col("amount")
                            .filter(pl.col("trade_date") == latest_date)
                            .first()
                            .alias("amount"),
                        ]
                    )

                    df_pd = df_agg.to_pandas()
                    if "ts_code" not in df_pd.columns and "symbol" in df_pd.columns:
                        df_pd["ts_code"] = df_pd["symbol"]

                    try:
                        df_db_pl = store.query_dataset(dataset="daily_basic")
                        if not df_db_pl.is_empty() and "trade_date" in df_db_pl.columns:
                            max_db_d = df_db_pl["trade_date"].max()
                            df_db_latest = df_db_pl.filter(
                                pl.col("trade_date") == max_db_d
                            ).to_pandas()
                            if (
                                "ts_code" not in df_db_latest.columns
                                and "symbol" in df_db_latest.columns
                            ):
                                df_db_latest["ts_code"] = df_db_latest["symbol"]

                            cols = [
                                c
                                for c in ["ts_code", "circ_mv", "total_mv", "pb"]
                                if c in df_db_latest.columns
                            ]
                            if len(cols) > 1:
                                df_pd = df_pd.merge(
                                    df_db_latest[cols], on="ts_code", how="left"
                                )
                    except Exception as e:
                        logger.warning(f"关联 daily_basic 流通市值及 PB 失败: {e}")

                    d_str = (
                        latest_date.strftime("%Y%m%d")
                        if isinstance(latest_date, date)
                        else str(latest_date).replace("-", "")
                    )
                    logger.info(
                        f"命中本地 DuckDB 最新交易日 [{d_str}] 行情与 20日均成交额数据 (共 {len(df_pd)} 条)。"
                    )
                    return d_str, df_pd
            except Exception as e:
                logger.error(f"读取本地成交额与指标归档失败: {e}")

            raise DataFetchError(
                "本地缺失 stock_daily_bar 行情离线归档数据！"
                "为保证数据绝对一致，已彻底禁止在线请求降级。请先运行 `make backfill` 补全本地行情数据。"
            )

        today_str = datetime.now().strftime("%Y%m%d")
        try:
            df_daily = self.fetcher.client.query("daily_basic", trade_date=today_str)
            if df_daily is not None and not df_daily.empty:
                return today_str, df_daily
        except Exception as e:
            logger.debug(f"Mock/在线请求 daily_basic 失败: {e}")
        return today_str, pd.DataFrame()

    def _build_rule_chain(self, rules: dict[str, Any]) -> CompositeRuleChain:
        """依据配置规则字典装配复合规则链。"""
        chain = CompositeRuleChain()
        chain.add_rule(
            BasicExclusionRule(
                exclude_st=rules.get("exclude_st", True),
                exclude_bj=rules.get("exclude_bj", True),
                min_age_days=rules.get("min_age_days", 730),
            )
        )
        chain.add_rule(
            LiquidityRule(
                min_daily_amount_thousand=rules.get("min_daily_amount_thousand", 30000.0),
                min_amount_20d_thousand=rules.get("min_amount_20d_thousand", 30000.0),
            )
        )
        chain.add_rule(
            ValuationRule(
                min_float_mv_yi=rules.get("min_float_mv_yi", 15.0),
                min_pb=rules.get("min_pb", 0.4),
                max_pb=rules.get("max_pb", 8.0),
            )
        )
        return chain

    def get_liquid_universe(
        self,
        min_age_days: int | None = None,
        min_daily_amount_thousand: float | None = None,
        exclude_st: bool | None = None,
        rule_file: str = "config/universe/filter_rules.yaml",
    ) -> list[str]:
        """根据多维风控与流动性规则，筛选核心股票池。"""
        df_snapshot = self.get_universe_snapshot_df(
            rule_file=rule_file,
            override_rules={
                k: v
                for k, v in {
                    "min_age_days": min_age_days,
                    "min_daily_amount_thousand": min_daily_amount_thousand,
                    "exclude_st": exclude_st,
                }.items()
                if v is not None
            },
        )
        symbols = df_snapshot["symbol"].tolist() if not df_snapshot.empty else []
        logger.info(f"== Layer 1 粗筛完成，共获得 {len(symbols)} 只生产级候选标的 ==")
        return symbols

    def get_universe_snapshot_df(
        self,
        rule_name: str = "liquid_core_universe",
        rule_file: str = "config/universe/filter_rules.yaml",
        override_rules: dict[str, Any] | None = None,
    ) -> pd.DataFrame:
        """抽取当前筛选出的精选股票池完整明细快照。"""
        rules = self.load_filter_rules(rule_file)
        if override_rules:
            rules.update(override_rules)

        df_basic = self._fetch_stock_basic()
        latest_trade_date, df_daily = self._fetch_latest_daily_basic()

        # 关联基础数据与指标数据
        merged = df_basic.copy()
        if not df_daily.empty:
            for col in ("amount", "amount_20d", "circ_mv", "pb"):
                if col in df_daily.columns:
                    val_map = dict(zip(df_daily["ts_code"], df_daily[col]))
                    merged[col] = merged["ts_code"].map(val_map)

        chain = self._build_rule_chain(rules)
        filtered_df = chain.apply(merged).copy()

        if "amount" not in filtered_df.columns:
            filtered_df["amount"] = 0.0

        try:
            as_of_d = datetime.strptime(latest_trade_date, "%Y%m%d").strftime("%Y-%m-%d")
        except Exception:
            as_of_d = datetime.now().strftime("%Y-%m-%d")

        filtered_df["as_of_date"] = as_of_d
        filtered_df["symbol"] = [c.split(".")[0] for c in filtered_df["ts_code"]]
        filtered_df["rule_name"] = rule_name
        filtered_df["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cols = [
            "as_of_date",
            "symbol",
            "ts_code",
            "name",
            "list_date",
            "amount",
            "amount_20d",
            "circ_mv",
            "pb",
            "rule_name",
            "created_at",
        ]
        return filtered_df[[c for c in cols if c in filtered_df.columns]]

    def save_universe_snapshot(self, rule_name: str = "liquid_core_universe") -> str:
        """将选股快照持久化落盘至 DuckDB / Parquet 归档层 (Snapshot Archive)。"""
        df_snapshot = self.get_universe_snapshot_df(rule_name=rule_name)
        if df_snapshot.empty:
            logger.warning("选股快照为空，跳过持久化归档。")
            return ""

        from stock.data.storage.duckdb_store import DuckDBMarketStore

        store = DuckDBMarketStore(data_source="tushare")
        pl_df = pl.from_pandas(df_snapshot)

        as_of_date_str = str(df_snapshot.iloc[0]["as_of_date"])
        target_dir = store.storage_dir / "universe_snapshots" / f"as_of_date={as_of_date_str}"
        os.makedirs(target_dir, exist_ok=True)
        file_path = target_dir / "snapshot.parquet"
        pl_df.write_parquet(file_path)
        logger.info(
            f"选股池历史快照 (Snapshot Archive) 已成功归档至: {file_path} (共 {len(pl_df)} 条记录)"
        )
        return str(file_path)


if __name__ == "__main__":
    filter_engine = UniverseFilter()
    filter_engine.save_universe_snapshot()
