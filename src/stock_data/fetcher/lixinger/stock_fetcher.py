"""理杏仁 (Lixinger) 股票领域专用数据抓取组件。"""

from datetime import date, datetime, timedelta
from typing import Any

import polars as pl

from stock_core.config.loader import load_data_config
from stock_core.exceptions import DataFetchError
from stock_core.models.market import DailyBar
from stock_core.utils.logger import logger
from stock_data.core.task_registry import resolve_task
from stock_data.fetcher.lixinger import query_helpers
from stock_data.fetcher.lixinger.bar_converter import fetch_daily_bars as _fetch_daily_bars
from stock_data.fetcher.lixinger.client import LixingerClient
from stock_data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY, EndpointMeta
from stock_data.fetcher.lixinger.risk_fetcher import fetch_risk_endpoint

_INDUSTRY_TABLE_CACHE: Any = None


def _resolve_endpoint_meta(endpoint: str) -> tuple[str, EndpointMeta]:
    """将公开 task 或完整路径统一解析为真实 API 路由与元数据。"""
    try:
        api_name = resolve_task("lixinger", endpoint).api_name
    except ValueError:
        api_name = endpoint

    meta = LIXINGER_API_REGISTRY.get(api_name)
    if meta is None and api_name != endpoint:
        meta = LIXINGER_API_REGISTRY.get(endpoint)
    return api_name, meta or EndpointMeta(api_name=api_name, description=api_name)


def _lixinger_month(value: Any) -> str | None:
    """将理杏仁 UTC 时间戳映射为业务月份 YYYYMM。"""
    if value is None:
        return None
    text = str(value)
    if len(text) >= 7 and text[4] == "-" and text[6] == "-":
        return f"{text[:4]}{text[5:7]}"
    digits = "".join(char for char in text if char.isdigit())
    return digits[:6] if len(digits) >= 6 else None


def _scaled_value(value: Any, divisor: float = 1.0) -> float | None:
    if value is None:
        return None
    try:
        return float(value) / divisor
    except (TypeError, ValueError):
        return None


def _flatten_lixinger_macro_frame(pandas_df: Any, dataset: str) -> pl.DataFrame:
    """展开理杏仁宏观接口嵌套指标，并统一到现有月频黄金表口径。"""
    if pandas_df.empty:
        return pl.DataFrame()

    rows: list[dict[str, Any]] = []
    for record in pandas_df.to_dict(orient="records"):
        month = _lixinger_month(record.get("date"))
        if month is None:
            continue
        metrics = record.get("m") or {}
        row: dict[str, Any] = {"symbol": dataset, "month": month}
        if dataset == "cn_m":
            for metric in ("m0", "m1", "m2"):
                values = metrics.get(metric) or {}
                row[metric] = _scaled_value(values.get("t"), divisor=100_000_000.0)
                yoy = _scaled_value(values.get("t_y2y"))
                row[f"{metric}_yoy"] = yoy * 100.0 if yoy is not None else None
                row[f"{metric}_mom"] = None
        else:
            values = metrics.get("sf") or {}
            row["stk_endval"] = _scaled_value(values.get("t"), divisor=100_000_000.0)
            yoy = _scaled_value(values.get("t_y2y"))
            row["stk_endval_yoy"] = yoy * 100.0 if yoy is not None else None
        rows.append(row)

    if not rows:
        return pl.DataFrame()

    frame = pl.DataFrame(rows).sort("month")
    if dataset == "cn_m":
        frame = frame.with_columns(
            [
                pl.when(pl.col(metric).shift(1) > 0)
                .then((pl.col(metric) / pl.col(metric).shift(1) - 1.0) * 100.0)
                .otherwise(None)
                .alias(f"{metric}_mom")
                for metric in ("m0", "m1", "m2")
            ]
        )
    return frame


def _resolve_sw_2021_industry_codes(
    client: LixingerClient,
    endpoint: str = "",
    level: str = "one",
) -> list[str]:
    """动态从理杏仁获取申万 2021 版行业代码列表，根据接口类型自动匹配对应分类（无硬编码）。"""
    global _INDUSTRY_TABLE_CACHE
    try:
        if _INDUSTRY_TABLE_CACHE is None or _INDUSTRY_TABLE_CACHE.empty:
            _INDUSTRY_TABLE_CACHE = client.query("cn/industry", source="sw_2021")

        df_ind = _INDUSTRY_TABLE_CACHE
        if df_ind.empty or "level" not in df_ind.columns or "stockCode" not in df_ind.columns:
            raise DataFetchError("理杏仁申万 2021 行业目录为空或缺少 level/stockCode 字段")

        def select_codes(mask: Any) -> list[str]:
            codes = sorted(df_ind[mask]["stockCode"].dropna().astype(str).unique().tolist())
            if not codes:
                raise DataFetchError(f"理杏仁申万 2021 行业目录未找到匹配分类 [{endpoint}/{level}]")
            return codes

        if "/bank" in endpoint:
            mask = df_ind["name"].str.contains("银行", na=False) & (
                df_ind["level"].isin(["one", "two"])
            )
            return select_codes(mask)

        if "/security" in endpoint:
            mask = df_ind["name"].str.contains("证券", na=False) & (
                df_ind["level"].isin(["one", "two"])
            )
            return select_codes(mask)

        if "/insurance" in endpoint:
            mask = df_ind["name"].str.contains("保险", na=False) & (
                df_ind["level"].isin(["one", "two"])
            )
            return select_codes(mask)

        if "/non_financial" in endpoint:
            mask = ~df_ind["name"].str.contains("银行|非银", na=False) & (df_ind["level"] == level)
            return select_codes(mask)

        mask = df_ind["level"] == level
        return select_codes(mask)

    except DataFetchError:
        raise
    except Exception as e:
        raise DataFetchError(f"动态获取申万行业分类失败: {e}") from e


def _get_lixinger_universe() -> list[str]:
    """获取理杏仁回填的目标 A 股股票池列表（不含后缀）。"""
    try:
        from stock_data.storage.duckdb_store import DuckDBMarketStore

        store = DuckDBMarketStore(data_source="tushare")
        df_snapshots = store.query_universe_snapshots()
        if not df_snapshots.is_empty() and "symbol" in df_snapshots.columns:
            latest_as_of = df_snapshots["as_of_date"].max()
            df_latest_snap = df_snapshots.filter(df_snapshots["as_of_date"] == latest_as_of)
            symbols = df_latest_snap["symbol"].unique().to_list()
            return sorted(list({s.split(".")[0] for s in symbols if s}))
    except Exception as e:
        logger.warning(f"从 DuckDB 获取股票池快照失败，尝试降级: {e}")

    try:
        from stock_data.storage.duckdb_store import DuckDBMarketStore

        store = DuckDBMarketStore(data_source="tushare")
        df_basic = store.query_dataset(dataset="stock_basic")
        if not df_basic.is_empty():
            code_col = "ts_code" if "ts_code" in df_basic.columns else "symbol"
            symbols = df_basic[code_col].unique().to_list()
            return sorted(list({s.split(".")[0] for s in symbols if s}))
    except Exception as e:
        logger.error(f"从 DuckDB 降级获取 stock_basic 股票池也失败: {e}")

    return []


def _fetch_batch_index_fundamentals(
    client: LixingerClient, meta: EndpointMeta, query_kwargs: dict[str, Any]
) -> pl.DataFrame:
    """按理杏仁指数接口约束批量查询观察池代码并拼接。"""
    data_conf = load_data_config()
    lx_indices = data_conf.watchlists.lixinger.indices
    supported = (
        getattr(data_conf, "source_endpoint_supports", {})
        .get("lixinger", {})
        .get("index_fundamental", [])
    )
    if supported:
        supported_set = set(supported)
        lx_indices = [code for code in lx_indices if code in supported_set]
    batch_kwargs = dict(query_kwargs)
    if batch_kwargs.get("startDate") == batch_kwargs.get("endDate"):
        batch_kwargs["date"] = batch_kwargs.pop("startDate")
        batch_kwargs.pop("endDate", None)
    try:
        result = client.query_batch(meta.api_name, lx_indices, **batch_kwargs)
    except DataFetchError:
        raise
    except Exception as err:
        raise DataFetchError(f"理杏仁指数批量查询失败: {err}") from err
    return pl.from_pandas(result) if not result.empty else pl.DataFrame()


def _fetch_batch_sw_industries(
    client: LixingerClient,
    meta: EndpointMeta,
    endpoint: str,
    query_kwargs: dict[str, Any],
    level: str | None = None,
) -> pl.DataFrame:
    """按 API 约束抓取申万行业数据；同日请求按最多 100 个代码批量合并。"""
    target_level = level or ("two" if "l2" in endpoint.lower() else "one")
    codes = _resolve_sw_2021_industry_codes(client, endpoint=endpoint, level=target_level)
    same_day = query_kwargs.get("startDate") == query_kwargs.get("endDate")
    if same_day and query_kwargs.get("startDate"):
        batch_kwargs = dict(query_kwargs)
        batch_kwargs["date"] = batch_kwargs.pop("startDate")
        batch_kwargs.pop("endDate", None)
        code_groups = [codes[i : i + 100] for i in range(0, len(codes), 100)]
    else:
        batch_kwargs = query_kwargs
        code_groups = [[code] for code in codes]

    dfs: list[pl.DataFrame] = []
    for code_group in code_groups:
        sub_kwargs = dict(batch_kwargs)
        sub_kwargs["stockCodes"] = code_group
        try:
            sub_df = client.query(meta.api_name, **sub_kwargs)
            if not sub_df.empty:
                dfs.append(pl.from_pandas(sub_df))
        except DataFetchError:
            raise
        except Exception as err:
            raise DataFetchError(f"理杏仁行业代码批次 [{code_group}] 查询失败: {err}") from err
    if not dfs:
        return pl.DataFrame()
    return pl.concat(dfs, how="diagonal_relaxed")


class LixingerStockFetcher:
    """理杏仁股票领域专用数据抓取器。"""

    _prefetch_cache: dict[str, pl.DataFrame] = {}

    def __init__(self, client: LixingerClient | None = None) -> None:
        self.client = client or LixingerClient()

    def fetch_daily_bars_df(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
        endpoint: str = "cn/company/fundamental/non_financial",
        **kwargs: Any,
    ) -> pl.DataFrame:
        """抓取指定股票或全市场在给定日期范围内的行情/估值数据。"""
        task_endpoint = str(kwargs.pop("endpoint_name", "") or "")
        requested_endpoint = task_endpoint or endpoint
        endpoint, meta = _resolve_endpoint_meta(endpoint)
        if (
            (end_date - start_date).days > 3200
            and endpoint != "cn/industry/constituents/sw_2021"
            and meta.frequency != "static"
        ):
            chunks: list[pl.DataFrame] = []
            curr_start = start_date
            while curr_start <= end_date:
                curr_end = min(curr_start + timedelta(days=3200), end_date)
                chunk_df = self.fetch_daily_bars_df(
                    symbol=symbol,
                    start_date=curr_start,
                    end_date=curr_end,
                    endpoint=requested_endpoint,
                    **kwargs,
                )
                if not chunk_df.is_empty():
                    chunks.append(chunk_df)
                curr_start = curr_end + timedelta(days=1)
            if not chunks:
                return pl.DataFrame()
            return pl.concat(chunks, how="diagonal_relaxed").unique()

        risk_frame = fetch_risk_endpoint(
            self.client, endpoint, meta, symbol, start_date, end_date, kwargs
        )
        if risk_frame is not None:
            return risk_frame

        start_str, end_str = query_helpers.query_date_strings(endpoint, start_date, end_date)
        raw_code = symbol.split(".")[0] if symbol else ""

        query_kwargs: dict[str, Any] = {}
        query_kwargs.update(meta.default_params)
        if meta.default_metrics:
            query_kwargs["metricsList"] = meta.default_metrics
        query_kwargs.update(kwargs)

        if "constituents" in endpoint:
            query_kwargs["date"] = start_str
            query_kwargs.pop("stockCodes", None)
            query_kwargs.pop("stockCode", None)
        else:
            query_kwargs["startDate"] = start_str
            query_kwargs["endDate"] = end_str

            is_generic = (
                not raw_code
                or raw_code == endpoint
                or raw_code == meta.api_name
                or _resolve_endpoint_meta(raw_code)[0] == endpoint
                or raw_code.startswith("sw_2021")
                or "fundamental" in raw_code
                or "candlestick" in raw_code
            )

            if not is_generic:
                if meta.code_param_name == "stockCode":
                    query_kwargs["stockCode"] = raw_code
                else:
                    query_kwargs["stockCodes"] = [raw_code]
            elif not query_kwargs.get("stockCodes") and not query_kwargs.get("stockCode"):
                if endpoint == "cn/index/fundamental":
                    return _fetch_batch_index_fundamentals(self.client, meta, query_kwargs)
                if "industry" in endpoint or "sw_2021" in endpoint:
                    industry_level = "two" if "l2" in requested_endpoint.lower() else None
                    return _fetch_batch_sw_industries(
                        self.client, meta, endpoint, query_kwargs, level=industry_level
                    )

        pandas_df = query_helpers.query_frame(
            self.client,
            meta.api_name,
            endpoint,
            query_kwargs,
            stock_code=raw_code,
        )
        if pandas_df.empty:
            return pl.DataFrame()

        if endpoint in {"macro/money-supply", "macro/social-financing"}:
            dataset = "cn_m" if endpoint == "macro/money-supply" else "sf_month"
            return _flatten_lixinger_macro_frame(pandas_df, dataset)

        # 指数 K 线响应不带 stockCode，使用本次请求的指数代码补齐主键。
        if endpoint == "cn/index/candlestick" and raw_code:
            pandas_df = pandas_df.copy()
            if "stockCode" not in pandas_df.columns:
                pandas_df.insert(0, "stockCode", raw_code)
            else:
                pandas_df["stockCode"] = pandas_df["stockCode"].fillna(raw_code)

        if "constituents" in endpoint and "constituents" in pandas_df.columns:
            rows: list[dict[str, Any]] = []
            for record in pandas_df.to_dict(orient="records"):
                industry_code = record.get("stockCode")
                constituents = record.get("constituents") or []
                if isinstance(constituents, dict):
                    constituents = [constituents]
                for constituent in constituents:
                    if isinstance(constituent, dict):
                        rows.append({"industryCode": industry_code, **constituent})
            return pl.DataFrame(rows) if rows else pl.DataFrame()

        return pl.from_pandas(pandas_df)

    def fetch_daily_bars(self, symbol: str, start_date: date, end_date: date) -> list[DailyBar]:
        """抓取数据并转换为 DailyBar 模型列表。"""
        return _fetch_daily_bars(self, symbol, start_date, end_date)

    def fetch_trade_cal(self, start_date: date, end_date: date) -> list[date]:
        """获取指定日期范围内的有效交易日列表。"""
        try:
            from stock_data.pipeline.scheduler import DataUpdateScheduler

            local_calendar = DataUpdateScheduler.get_trading_days(
                start_date, end_date, data_source="tushare"
            )
            if local_calendar:
                return list(local_calendar)
        except Exception as e:
            logger.debug(f"读取本地 TuShare trade_cal 失败，继续查询理杏仁日历: {e}")

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        try:
            data_cfg = load_data_config()
            pandas_df = self.client.query(
                "cn/index/candlestick",
                stockCode=data_cfg.default_benchmark_index_code,
                type="normal",
                startDate=start_str,
                endDate=end_str,
            )
        except Exception as e:
            logger.warning(f"理杏仁指数 K 线日历获取失败 ({e})，尝试使用 TuShare 交易日历...")
            try:
                from stock_data.fetcher.tushare.facade import TuShareDataFetcher

                dates = TuShareDataFetcher().fetch_trade_cal(start_date, end_date)
                if dates:
                    return dates
            except Exception as fallback_error:
                logger.debug(f"TuShare 交易日历获取失败: {fallback_error}")
            raise DataFetchError(
                f"缺少 {start_date} ~ {end_date} 的可信交易日历，拒绝按工作日推算"
            ) from e

        if pandas_df.empty or "date" not in pandas_df.columns:
            try:
                from stock_data.fetcher.tushare.facade import TuShareDataFetcher

                dates = TuShareDataFetcher().fetch_trade_cal(start_date, end_date)
                if dates:
                    return dates
            except Exception as fallback_error:
                logger.debug(f"TuShare 交易日历获取失败: {fallback_error}")
            raise DataFetchError(
                f"理杏仁未返回有效交易日历: {start_date} ~ {end_date}，拒绝按工作日推算"
            )

        parsed_dates: list[date] = []
        for d_val in pandas_df["date"].to_list():
            if isinstance(d_val, str):
                parsed_dates.append(datetime.strptime(d_val[:10], "%Y-%m-%d").date())
            elif isinstance(d_val, date):
                parsed_dates.append(d_val)

        return sorted(parsed_dates)
