"""RAW 缓存读写共享字段规则。"""

from datetime import date
from typing import Any

import polars as pl

from stock_core.contracts import DatasetKey

RAW_DATE_COLUMNS = (
    "trade_date",
    "report_date",
    "date",
    "end_date",
    "as_of_date",
    "asOfDate",
    "month",
    "quarter",
)
RAW_RANGE_DATE_COLUMNS = ("trade_date", "report_date", "date", "end_date", "as_of_date", "asOfDate")
RAW_SYMBOL_COLUMNS = (
    "symbol",
    "ts_code",
    "stockCode",
    "code",
    "index_id",
    "industry_id",
    "index_code",
)
RAW_ENTITY_COLUMNS = (
    "ts_code",
    "symbol",
    "stockCode",
    "code",
    "index_id",
    "industry_id",
    "index_code",
)
RAW_DATE_CANDIDATE_COLUMNS = (
    "trade_date",
    "report_date",
    "date",
    "end_date",
    "as_of_date",
    "asOfDate",
    "ann_date",
    "month",
    "quarter",
    "suspend_date",
)
RAW_PRIMARY_KEY_FALLBACK_COLUMNS = (
    "symbol",
    "stockCode",
    "ts_code",
    "code",
    "index_id",
    "industry_id",
    "index_code",
    "con_code",
    "exchange_id",
    "market_type",
    "report_type",
    "trade_date",
    "report_date",
    "date",
    "end_date",
    "as_of_date",
    "asOfDate",
    "ann_date",
    "month",
    "quarter",
)
RAW_ARTIFACT_SUFFIXES = (".bak.parquet", ".tmp.parquet")


def first_existing_column(frame: pl.DataFrame, candidates: tuple[str, ...]) -> str | None:
    """按候选顺序返回 DataFrame 中存在的第一列。"""
    return next((column for column in candidates if column in frame.columns), None)


def normalize_raw_date_series(series: pl.Series | pl.Expr) -> Any:
    """将源端日期文本归一为纯数字字符串，用于分区和范围判断。"""
    return (
        series.cast(pl.Utf8, strict=False).str.replace(r"\.0+$", "").str.replace_all(r"[^\d]", "")
    )


def month_key_for(key: DatasetKey, month_start: date) -> DatasetKey:
    """按月份生成与原始请求等价的 RAW 分区 key。"""
    return DatasetKey(
        provider=key.provider,
        dataset=key.dataset,
        endpoint=key.endpoint,
        start_date=month_start,
        end_date=date(month_start.year, month_start.month, 28),
        instrument=key.instrument,
        adjustment=key.adjustment,
        schema_version=key.schema_version,
    )


def resolve_raw_primary_keys(key: DatasetKey, df: pl.DataFrame) -> list[str]:
    """根据数据源元数据与列别名安全解析 RAW 去重主键。"""
    from typing import Any

    from stock_core.utils.logger import logger
    from stock_data.core.task_registry import resolve_task

    meta: Any = None
    try:
        if key.provider == "tushare":
            from stock_data.fetcher.tushare.registry import TUSHARE_API_REGISTRY

            meta = TUSHARE_API_REGISTRY.get(resolve_task(key.provider, key.endpoint).api_name)
        elif key.provider == "lixinger":
            from stock_data.fetcher.lixinger.registry import LIXINGER_API_REGISTRY

            meta = LIXINGER_API_REGISTRY.get(resolve_task(key.provider, key.endpoint).api_name)
        elif key.provider == "alphavantage":
            from stock_data.fetcher.alphavantage.registry import ALPHAVANTAGE_API_REGISTRY

            meta = ALPHAVANTAGE_API_REGISTRY.get(resolve_task(key.provider, key.endpoint).api_name)
        elif key.provider == "yfinance":
            from stock_data.fetcher.yfinance.registry import YFINANCE_API_REGISTRY

            meta = YFINANCE_API_REGISTRY.get(resolve_task(key.provider, key.endpoint).api_name)
    except Exception as e:
        logger.debug(f"解析 RAW 主键失败 [{key.provider}/{key.endpoint}]: {e}")

    meta_pks = getattr(meta, "primary_keys", None)
    if meta and meta_pks:
        mapped_keys: list[str] = []
        for k in meta_pks:
            if k in RAW_ENTITY_COLUMNS:
                found = next((c for c in [k, *RAW_ENTITY_COLUMNS] if c in df.columns), None)
                if found and found not in mapped_keys:
                    mapped_keys.append(found)
            elif k in RAW_DATE_CANDIDATE_COLUMNS:
                found = next((c for c in [k, *RAW_DATE_CANDIDATE_COLUMNS] if c in df.columns), None)
                if found and found not in mapped_keys:
                    mapped_keys.append(found)
            elif k in df.columns:
                if k not in mapped_keys:
                    mapped_keys.append(k)

        # 防御：如果元数据包含实体键（如 ts_code/symbol 等），但当前映射结果没有实体键，且 df 中包含实体列时，补全实体列
        has_meta_entity = any(k in RAW_ENTITY_COLUMNS for k in meta_pks)
        has_mapped_entity = any(k in RAW_ENTITY_COLUMNS for k in mapped_keys)
        if has_meta_entity and not has_mapped_entity:
            entity_in_df = next((c for c in RAW_ENTITY_COLUMNS if c in df.columns), None)
            if entity_in_df:
                mapped_keys.insert(0, entity_in_df)

        if mapped_keys:
            return mapped_keys

    return [c for c in RAW_PRIMARY_KEY_FALLBACK_COLUMNS if c in df.columns]


def deduplicate_raw_merged_frame(
    merged: pl.DataFrame, key: DatasetKey | None = None
) -> pl.DataFrame:
    """对异构合并后的 RAW DataFrame 执行聚合防折叠唯一性去重。"""
    entity_present = [c for c in RAW_ENTITY_COLUMNS if c in merged.columns]
    date_present = [c for c in RAW_DATE_CANDIDATE_COLUMNS if c in merged.columns]
    temp_cols: list[str] = []

    registered_keys = resolve_raw_primary_keys(key, merged) if key is not None else []
    dedup_subset: list[str] = []
    if registered_keys:
        for registered_key in registered_keys:
            if registered_key in date_present:
                if "_dedup_date" not in dedup_subset:
                    raw_date_exprs = [normalize_raw_date_series(pl.col(c)) for c in date_present]
                    merged = merged.with_columns(pl.coalesce(raw_date_exprs).alias("_dedup_date"))
                    dedup_subset.append("_dedup_date")
                    temp_cols.append("_dedup_date")
            elif registered_key in RAW_ENTITY_COLUMNS:
                if len(entity_present) > 1:
                    if "_dedup_entity" not in dedup_subset:
                        merged = merged.with_columns(
                            pl.coalesce([pl.col(c) for c in entity_present]).alias("_dedup_entity")
                        )
                        dedup_subset.append("_dedup_entity")
                        temp_cols.append("_dedup_entity")
                elif registered_key in merged.columns:
                    dedup_subset.append(registered_key)
            elif registered_key in merged.columns:
                dedup_subset.append(registered_key)

    if not registered_keys and entity_present:
        if len(entity_present) > 1:
            merged = merged.with_columns(
                pl.coalesce([pl.col(c) for c in entity_present]).alias("_dedup_entity")
            )
            dedup_subset.append("_dedup_entity")
            temp_cols.append("_dedup_entity")
        else:
            dedup_subset.append(entity_present[0])

    if not registered_keys and date_present:
        raw_date_exprs = [normalize_raw_date_series(pl.col(c)) for c in date_present]
        merged = merged.with_columns(pl.coalesce(raw_date_exprs).alias("_dedup_date"))
        dedup_subset.append("_dedup_date")
        temp_cols.append("_dedup_date")

    if not registered_keys:
        for k in (
            "exchange_id",
            "market_type",
            "report_type",
            "con_code",
            "in_date",
            "out_date",
            "src",
            "adj_factor",
        ):
            if k in merged.columns and k not in dedup_subset:
                dedup_subset.append(k)

    if dedup_subset:
        merged = merged.unique(subset=dedup_subset, keep="last")

    if temp_cols:
        merged = merged.drop(temp_cols)

    return merged
