"""动态股票池筛选器 (UniverseFilter)。

结合 TuShare 数据源实现 ST 过滤、上市年限过滤及流动性过滤，
并生成用于理杏仁等引擎回填的优质股票池配置。
"""

from typing import Any

import os
from datetime import datetime, timedelta
import pandas as pd
import yaml

from stock.data.fetcher.tushare import TuShareDataFetcher
from stock.utils.logger import logger


class UniverseFilter:
    """生产级股票池筛选引擎。"""

    def __init__(
        self,
        fetcher: TuShareDataFetcher | None = None,
        use_local: bool = True,
    ) -> None:
        """初始化 UniverseFilter。

        Args:
            fetcher: TuShareDataFetcher 实例。
            use_local: 是否优先使用本地 DuckDB/Parquet 离线归档数据 (默认 True)。
        """
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

            from stock.exceptions import DataFetchError

            raise DataFetchError(
                "本地缺失 stock_basic 股票基础库离线归档数据！"
                "为保证数据绝对一致，已彻底禁止在线请求降级。请先运行 `make backfill ENDPOINT=stock_basic` 补全本地基础库。"
            )

        logger.info("测试/非本地模式：请求接口或 Mock 获取 stock_basic 数据...")
        return self.fetcher.client.query("stock_basic", list_status="L")

    def load_filter_rules(self, rule_file: str = "config/universe/filter_rules.yaml") -> dict[str, Any]:
        """从配置文件动态解析粗筛规则。"""
        if os.path.exists(rule_file):
            try:
                with open(rule_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                    if data and isinstance(data, dict) and "filter_rules" in data and isinstance(data["filter_rules"], dict):
                        logger.info(f"成功载入筛选规则配置文件: {rule_file}")
                        return data["filter_rules"]
            except Exception as e:
                logger.warning(f"读取规则配置文件 [{rule_file}] 失败: {e}，将使用默认规则。")
        return {}

    def _fetch_latest_daily_basic(self) -> tuple[str, pd.DataFrame]:
        """从本地离线库检索最新行情、20日均成交额、流通市值及 PB 估值。"""
        if self.use_local:
            try:
                from stock.data.storage.duckdb_store import DuckDBMarketStore
                import polars as pl
                from datetime import date

                store = DuckDBMarketStore(data_source="tushare")
                df_bar_pl = store.query_dataset(dataset="stock_daily_bar")

                if not df_bar_pl.is_empty() and "trade_date" in df_bar_pl.columns and "amount" in df_bar_pl.columns:
                    unique_dates = df_bar_pl["trade_date"].unique().sort(descending=True)
                    top20_dates = unique_dates.head(20)
                    latest_date = top20_dates[0]

                    code_col = "ts_code" if "ts_code" in df_bar_pl.columns else "symbol"

                    # 筛选最近 20 个交易日计算 amount 均值
                    df_20d = df_bar_pl.filter(pl.col("trade_date").is_in(top20_dates))
                    df_agg = df_20d.group_by(code_col).agg([
                        pl.col("amount").mean().alias("amount_20d"),
                        pl.col("amount").filter(pl.col("trade_date") == latest_date).first().alias("amount")
                    ])

                    df_pd = df_agg.to_pandas()
                    if "ts_code" not in df_pd.columns and "symbol" in df_pd.columns:
                        df_pd["ts_code"] = df_pd["symbol"]

                    # 关联 daily_basic 提取 circ_mv 与 pb
                    try:
                        df_db_pl = store.query_dataset(dataset="daily_basic")
                        if not df_db_pl.is_empty() and "trade_date" in df_db_pl.columns:
                            max_db_d = df_db_pl["trade_date"].max()
                            df_db_latest = df_db_pl.filter(pl.col("trade_date") == max_db_d).to_pandas()
                            if "ts_code" not in df_db_latest.columns and "symbol" in df_db_latest.columns:
                                df_db_latest["ts_code"] = df_db_latest["symbol"]

                            cols_to_merge = [c for c in ["ts_code", "circ_mv", "total_mv", "pb"] if c in df_db_latest.columns]
                            if len(cols_to_merge) > 1:
                                df_pd = df_pd.merge(df_db_latest[cols_to_merge], on="ts_code", how="left")
                    except Exception as e:
                        logger.warning(f"关联 daily_basic 流通市值及 PB 失败: {e}")

                    d_str = latest_date.strftime("%Y%m%d") if isinstance(latest_date, date) else str(latest_date).replace("-", "")
                    logger.info(f"命中本地 DuckDB 最新交易日 [{d_str}] 行情与 20日均成交额数据 (共 {len(df_pd)} 条)。")
                    return d_str, df_pd
            except Exception as e:
                logger.error(f"读取本地成交额与指标归档失败: {e}")

            from stock.exceptions import DataFetchError

            raise DataFetchError(
                "本地缺失 stock_daily_bar 行情离线归档数据！"
                "为保证数据绝对一致，已彻底禁止在线请求降级。请先运行 `make backfill` 补全本地行情数据。"
            )

        # 非本地/测试 Mock 模式
        today_str = datetime.now().strftime("%Y%m%d")
        try:
            df_daily = self.fetcher.client.query("daily_basic", trade_date=today_str)
            if df_daily is not None and not df_daily.empty:
                return today_str, df_daily
        except Exception as e:
            logger.debug(f"Mock/在线请求 daily_basic 失败: {e}")
        return today_str, pd.DataFrame()

    def get_liquid_universe(
        self,
        min_age_days: int | None = None,
        min_daily_amount_thousand: float | None = None,
        exclude_st: bool | None = None,
        rule_file: str = "config/universe/filter_rules.yaml",
    ) -> list[str]:
        """根据多维风控与流动性规则，筛选核心股票池。"""
        logger.info("开始执行全市场股票池多维精细筛选...")

        rules = self.load_filter_rules(rule_file)
        if exclude_st is None:
            exclude_st = rules.get("exclude_st", True)
        if min_age_days is None:
            min_age_days = rules.get("min_age_days", 730)
        if min_daily_amount_thousand is None:
            min_daily_amount_thousand = rules.get("min_daily_amount_thousand", 30000.0)

        min_amount_20d_thousand = rules.get("min_amount_20d_thousand", 30000.0)
        min_float_mv_yi = rules.get("min_float_mv_yi", 15.0)
        min_pb = rules.get("min_pb", 0.4)
        max_pb = rules.get("max_pb", 8.0)
        exclude_bj = rules.get("exclude_bj", True)

        # 1. 获取 stock_basic
        df_basic = self._fetch_stock_basic()
        total_initial = len(df_basic)
        logger.info(f"== Layer 1 粗筛开始 (全市场初始股票总数: {total_initial}) ==")

        # 2. 剔除 ST / *ST / 退市股
        if exclude_st:
            df_basic = df_basic[~df_basic["name"].str.contains("ST|退", case=False, na=False)]
            logger.info(f"  └─ [1. 剔除 ST/退市标的] 剩余: {len(df_basic)} 只 (淘汰 {total_initial - len(df_basic)} 只)")

        cnt_after_st = len(df_basic)
        # 3. 剔除北交所股票
        if exclude_bj:
            df_basic = df_basic[~df_basic["ts_code"].str.endswith(".BJ", na=False)]
            logger.info(f"  └─ [2. 剔除北交所标的] 剩余: {len(df_basic)} 只 (淘汰 {cnt_after_st - len(df_basic)} 只)")

        cnt_after_bj = len(df_basic)
        # 4. 剔除上市不满 N 天的次新股 (默认满 2 年 / 730 天)
        cutoff_date = (datetime.now() - timedelta(days=min_age_days)).strftime("%Y%m%d")
        df_basic = df_basic[df_basic["list_date"] <= cutoff_date]
        logger.info(f"  └─ [3. 剔除上市未满 {min_age_days} 天次新股] 剩余: {len(df_basic)} 只 (淘汰 {cnt_after_bj - len(df_basic)} 只)")

        # 5. 获取行情与指标
        latest_trade_date, df_daily = self._fetch_latest_daily_basic()

        if not df_daily.empty:
            cond = pd.Series(True, index=df_daily.index)

            # 单日成交额
            if "amount" in df_daily.columns:
                cond = cond & (df_daily["amount"] >= min_daily_amount_thousand)

            # 20 日均成交额 (防一日游脉冲放量)
            if "amount_20d" in df_daily.columns:
                cond = cond & (df_daily["amount_20d"] >= min_amount_20d_thousand)

            # 流通市值下限 (本地 DuckDB 中 circ_mv 单位为元，15亿 = 1.5e9 元)
            if "circ_mv" in df_daily.columns and min_float_mv_yi:
                min_circ_mv_yuan = min_float_mv_yi * 1e8
                cond = cond & (df_daily["circ_mv"].isna() | (df_daily["circ_mv"] >= min_circ_mv_yuan))

            # PB 市净率过滤
            if "pb" in df_daily.columns:
                if min_pb is not None:
                    cond = cond & (df_daily["pb"].isna() | (df_daily["pb"] >= min_pb))
                if max_pb is not None:
                    cond = cond & (df_daily["pb"].isna() | (df_daily["pb"] <= max_pb))

            valid_symbols = set(df_daily[cond]["ts_code"])
            filtered_df = df_basic[df_basic["ts_code"].isin(valid_symbols)]
            logger.info(f"  └─ [4. 行情与流动性/市值多维校验] 最终合格剩余: {len(filtered_df)} 只")
        else:
            logger.warning("未能获取有效行情数据，仅按基础信息过滤。")
            filtered_df = df_basic

        lx_symbols = [code.split(".")[0] for code in filtered_df["ts_code"].tolist()]
        logger.info(f"== Layer 1 粗筛完成，共获得 {len(lx_symbols)} 只生产级候选标的 ==")
        return lx_symbols

    def get_universe_snapshot_df(
        self,
        rule_name: str = "liquid_core_universe",
        rule_file: str = "config/universe/filter_rules.yaml",
    ) -> pd.DataFrame:
        """抽取当前筛选出的精选股票池完整明细快照。"""
        rules = self.load_filter_rules(rule_file)
        exclude_st = rules.get("exclude_st", True)
        min_age_days = rules.get("min_age_days", 730)
        min_daily_amount_thousand = rules.get("min_daily_amount_thousand", 30000.0)
        min_amount_20d_thousand = rules.get("min_amount_20d_thousand", 30000.0)
        min_float_mv_yi = rules.get("min_float_mv_yi", 15.0)
        min_pb = rules.get("min_pb", 0.4)
        max_pb = rules.get("max_pb", 8.0)
        exclude_bj = rules.get("exclude_bj", True)

        df_basic = self._fetch_stock_basic()

        if exclude_st:
            df_basic = df_basic[~df_basic["name"].str.contains("ST|退", case=False, na=False)]

        if exclude_bj:
            df_basic = df_basic[~df_basic["ts_code"].str.endswith(".BJ", na=False)]

        cutoff_date = (datetime.now() - timedelta(days=min_age_days)).strftime("%Y%m%d")
        df_basic = df_basic[df_basic["list_date"] <= cutoff_date]

        latest_trade_date, df_daily = self._fetch_latest_daily_basic()

        if not df_daily.empty:
            cond = pd.Series(True, index=df_daily.index)

            if "amount" in df_daily.columns:
                cond = cond & (df_daily["amount"] >= min_daily_amount_thousand)

            if "amount_20d" in df_daily.columns:
                cond = cond & (df_daily["amount_20d"] >= min_amount_20d_thousand)

            if "circ_mv" in df_daily.columns and min_float_mv_yi:
                min_circ_mv_yuan = min_float_mv_yi * 1e8
                cond = cond & (df_daily["circ_mv"].isna() | (df_daily["circ_mv"] >= min_circ_mv_yuan))

            if "pb" in df_daily.columns:
                if min_pb is not None:
                    cond = cond & (df_daily["pb"].isna() | (df_daily["pb"] >= min_pb))
                if max_pb is not None:
                    cond = cond & (df_daily["pb"].isna() | (df_daily["pb"] <= max_pb))

            valid_symbols = set(df_daily[cond]["ts_code"])
            filtered_df = df_basic[df_basic["ts_code"].isin(valid_symbols)].copy()

            if "amount" in df_daily.columns:
                amount_map = dict(zip(df_daily["ts_code"], df_daily["amount"]))
                filtered_df["amount"] = filtered_df["ts_code"].map(amount_map)
            if "amount_20d" in df_daily.columns:
                amount20_map = dict(zip(df_daily["ts_code"], df_daily["amount_20d"]))
                filtered_df["amount_20d"] = filtered_df["ts_code"].map(amount20_map)
            if "circ_mv" in df_daily.columns:
                mv_map = dict(zip(df_daily["ts_code"], df_daily["circ_mv"]))
                filtered_df["circ_mv"] = filtered_df["ts_code"].map(mv_map)
            if "pb" in df_daily.columns:
                pb_map = dict(zip(df_daily["ts_code"], df_daily["pb"]))
                filtered_df["pb"] = filtered_df["ts_code"].map(pb_map)
        else:
            filtered_df = df_basic.copy()
            filtered_df["amount"] = 0.0

        as_of_d = datetime.strptime(latest_trade_date, "%Y%m%d").strftime("%Y-%m-%d")
        filtered_df["as_of_date"] = as_of_d
        filtered_df["symbol"] = [c.split(".")[0] for c in filtered_df["ts_code"]]
        filtered_df["rule_name"] = rule_name
        filtered_df["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cols = ["as_of_date", "symbol", "ts_code", "name", "list_date", "amount", "amount_20d", "circ_mv", "pb", "rule_name", "created_at"]
        return filtered_df[[c for c in cols if c in filtered_df.columns]]

    def save_universe_snapshot(self, rule_name: str = "liquid_core_universe") -> str:
        """将选股快照持久化落盘至 DuckDB / Parquet 归档层 (Snapshot Archive)。"""
        df_snapshot = self.get_universe_snapshot_df(rule_name=rule_name)
        if df_snapshot.empty:
            logger.warning("选股快照为空，跳过持久化归档。")
            return ""

        from stock.data.storage.duckdb_store import DuckDBMarketStore
        import polars as pl

        store = DuckDBMarketStore(data_source="tushare")
        pl_df = pl.from_pandas(df_snapshot)

        as_of_date_str = df_snapshot.iloc[0]["as_of_date"]
        target_dir = store.storage_dir / "universe_snapshots" / f"as_of_date={as_of_date_str}"
        os.makedirs(target_dir, exist_ok=True)
        file_path = target_dir / "snapshot.parquet"
        pl_df.write_parquet(file_path)
        logger.info(f"选股池历史快照 (Snapshot Archive) 已成功归档至: {file_path} (共 {len(pl_df)} 条记录)")
        return str(file_path)


if __name__ == "__main__":
    filter_engine = UniverseFilter()
    filter_engine.save_universe_snapshot()
