"""A 股全市场数据完整性与停牌对账审计模块。"""

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from stock_core.utils.logger import logger
from stock_data.audit.factor_audit import run_adj_factor_audit, run_sw_daily_audit
from stock_data.audit.moneyflow_audit import run_hk_hold_audit
from stock_data.audit.registry import get_audit_spec
from stock_data.audit.valuation_audit import run_daily_basic_audit, run_sw_industry_audit
from stock_data.fetcher.tushare.client import TuShareClient
from stock_data.settings import data_settings
from stock_data.storage.compat import StorageCompat
from stock_data.task_registry import resolve_task

_DATE_COLUMNS = ("trade_date", "date", "end_date", "suspend_date", "Date")
_SYMBOL_COLUMNS = ("ts_code", "symbol", "stockCode", "code", "ticker")
_KEY_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "ts_code", "stockCode", "code", "ticker"),
    "trade_date": ("trade_date", "date", "Date", "end_date", "ann_date"),
    "industry_code": ("industry_code", "industryCode"),
    "index_code": ("index_code", "indexCode"),
    "area_code": ("area_code", "areaCode"),
}


def _is_artifact_path(path: Path) -> bool:
    """跳过迁移备份和临时文件。"""
    return path.name.endswith((".bak.parquet", ".tmp.parquet"))


def _dataset_aliases(data_source: str, endpoint: str) -> set[str]:
    aliases = {endpoint}
    try:
        task = resolve_task(data_source, endpoint)
        aliases.update({task.task_name, task.dataset, task.api_name})
    except Exception as exc:
        logger.debug(f"解析审计数据集别名失败 [{data_source}/{endpoint}]: {exc}")
    return {alias for alias in aliases if alias}


def _collect_dataset_files(
    base_dir: Path,
    data_source: str,
    endpoint: str,
    target_date: date,
) -> list[Path]:
    """按数据源、数据集别名和目标月份定位物理 Parquet 文件。"""
    source_root = base_dir / data_source
    if not source_root.exists():
        return []

    aliases = _dataset_aliases(data_source, endpoint)
    target_year = f"year={target_date.year:04d}"
    target_month = f"month={target_date.month:02d}"
    files: list[Path] = []
    for path in source_root.rglob("*.parquet"):
        if _is_artifact_path(path):
            continue
        if not any(alias in path.parts or alias in path.stem for alias in aliases):
            continue
        has_time_partition = any(part.startswith("year=") for part in path.parts)
        if has_time_partition and (target_year not in path.parts or target_month not in path.parts):
            continue
        files.append(path)
    return sorted(files)


def _clean_date_expr(col_name: str, dtype: pl.DataType) -> pl.Expr:
    """标准化日期列为 YYYYMMDD 格式的 Polars 表达式。"""
    if dtype in (pl.Date, pl.Datetime):
        return pl.col(col_name).dt.strftime("%Y%m%d")
    return (
        pl.col(col_name)
        .cast(pl.Utf8, strict=False)
        .str.split(" ")
        .list.first()
        .str.split("T")
        .list.first()
        .str.replace_all("-", "")
        .str.replace_all("/", "")
    )


def _filter_target_date(frame: pl.DataFrame, target_date: date) -> pl.DataFrame:
    """将不同日期列格式统一后筛选目标日期。"""
    date_cols = [col for col in _DATE_COLUMNS if col in frame.columns]
    if not date_cols or frame.is_empty():
        return frame

    target_plain = target_date.strftime("%Y%m%d")
    exprs = [_clean_date_expr(col, frame[col].dtype) == target_plain for col in date_cols]
    return frame.filter(pl.any_horizontal(exprs))


def _read_target_frames(
    files: list[Path],
    target_date: date,
) -> tuple[pl.DataFrame, list[str]]:
    frames: list[pl.DataFrame] = []
    errors: list[str] = []
    for path in files:
        try:
            frame = _filter_target_date(pl.read_parquet(path), target_date)
            if not frame.is_empty():
                frames.append(frame)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    if not frames:
        return pl.DataFrame(), errors
    return pl.concat(frames, how="diagonal_relaxed"), errors


def _extract_identity_keys_frame(
    frame: pl.DataFrame,
    primary_keys: list[str] | None = None,
) -> pl.DataFrame:
    """抽取 symbol + trade_date 标准主键集合 DataFrame，兼容 RAW 源端列名。"""
    if frame.is_empty():
        names = [_canonical_key_name(key) for key in (primary_keys or ["symbol", "trade_date"])]
        return pl.DataFrame({name: pl.Series([], dtype=pl.Utf8) for name in names})
    if primary_keys:
        expressions: list[pl.Expr] = []
        for key in primary_keys:
            output_name = _canonical_key_name(key)
            candidates = _KEY_COLUMN_ALIASES.get(output_name, (key,))
            source = next((column for column in candidates if column in frame.columns), None)
            if source is None:
                return pl.DataFrame()
            if output_name == "trade_date":
                expression = _clean_date_expr(source, frame[source].dtype)
            else:
                expression = pl.col(source).cast(pl.Utf8, strict=False)
            expressions.append(expression.alias(output_name))
        return frame.select(expressions).drop_nulls().unique()

    sym_cols = [col for col in _SYMBOL_COLUMNS if col in frame.columns]
    date_cols = [col for col in _DATE_COLUMNS if col in frame.columns]
    if not sym_cols or not date_cols:
        return pl.DataFrame(
            {"symbol": pl.Series([], dtype=pl.Utf8), "trade_date": pl.Series([], dtype=pl.Utf8)}
        )

    return (
        frame.select(
            [
                pl.coalesce([pl.col(c).cast(pl.Utf8, strict=False) for c in sym_cols]).alias(
                    "symbol"
                ),
                pl.coalesce([_clean_date_expr(c, frame[c].dtype) for c in date_cols]).alias(
                    "trade_date"
                ),
            ]
        )
        .drop_nulls()
        .unique()
    )


def _canonical_key_name(key: str) -> str:
    """将源端注册主键映射为 RAW/Curated 共用的对账列名。"""
    return {
        "stockCode": "symbol",
        "ts_code": "symbol",
        "code": "symbol",
        "ticker": "symbol",
        "date": "trade_date",
        "Date": "trade_date",
        "industryCode": "industry_code",
        "indexCode": "index_code",
        "areaCode": "area_code",
    }.get(key, key)


def _registered_primary_keys(data_source: str, endpoint: str) -> list[str]:
    """读取任务对应源端注册表的主键，静态关系表也必须按完整复合键对账。"""
    try:
        task = resolve_task(data_source, endpoint)
        registry_name = {
            "tushare": "stock_data.fetcher.tushare.registry",
            "lixinger": "stock_data.fetcher.lixinger.registry",
            "yfinance": "stock_data.fetcher.yfinance.registry",
            "fred": "stock_data.fetcher.fred.registry",
        }[data_source]
        registry_attr = {
            "tushare": "TUSHARE_API_REGISTRY",
            "lixinger": "LIXINGER_API_REGISTRY",
            "yfinance": "YFINANCE_API_REGISTRY",
            "fred": "FRED_API_REGISTRY",
        }[data_source]
        module = __import__(registry_name, fromlist=[registry_attr])
        meta = getattr(module, registry_attr).get(task.api_name)
        return list(getattr(meta, "primary_keys", []) or [])
    except (KeyError, ImportError, ValueError, AttributeError):
        return []


def _clean_raw_bar_frame(
    endpoint: str, data_source: str, frame: pl.DataFrame
) -> tuple[pl.DataFrame, int]:
    """按实际 ETL 清洗规则生成可与 Curated 对账的 RAW 有效集合。"""
    task = None
    try:
        task = resolve_task(data_source, endpoint)
        is_bar = task.dataset in {"stock_daily_bar", "index_daily_bar"}
    except ValueError:
        is_bar = endpoint in {"stock_daily_bar", "index_daily_bar"}
    if not is_bar or not {"open", "high", "low", "close"}.issubset(frame.columns):
        return frame, 0

    from stock_data.cleaner.bar_cleaner import BarDataCleaner
    from stock_data.normalizer.unit_normalizer import UnitNormalizer

    working = frame
    if data_source == "tushare" and (task is None or task.dataset == "stock_daily_bar"):
        endpoint_name = task.task_name if task is not None else endpoint
        working, _ = UnitNormalizer(data_source, endpoint_name).normalize_units_with_quarantine(
            working
        )

    listing_dates = (
        BarDataCleaner.load_listing_dates(data_source)
        if data_source == "tushare" and (task is None or task.dataset == "stock_daily_bar")
        else {}
    )
    cleaner = BarDataCleaner(listing_dates=listing_dates)
    eligible, _ = cleaner._exclude_pre_listing(working)
    cleaned = cleaner.clean(eligible)
    return cleaned, len(frame) - len(cleaned)


def _clean_raw_frame(
    endpoint: str, data_source: str, frame: pl.DataFrame
) -> tuple[pl.DataFrame, int]:
    """按实际 ETL 清洗规则生成可与 Curated 对账的 RAW 有效集合。"""
    cleaned, filtered_count = _clean_raw_bar_frame(endpoint, data_source, frame)
    if data_source != "lixinger":
        return cleaned, filtered_count

    try:
        task = resolve_task(data_source, endpoint)
    except ValueError:
        task = None
    if task is None or task.dataset != "index_fundamental":
        return cleaned, filtered_count

    from stock_data.cleaner.generic_cleaner import (
        filter_lixinger_index_fundamental_placeholders,
    )

    cleaned, placeholder_count = filter_lixinger_index_fundamental_placeholders(cleaned)
    return cleaned, filtered_count + placeholder_count


def _run_raw_curated_reconciliation(
    target_date: date,
    data_source: str,
    endpoint: str = "stock_daily_bar",
) -> dict[str, Any]:
    """执行 RAW 与 Curated 的物理文件、行数和主键对账。"""
    audit_spec = get_audit_spec(endpoint, data_source)
    if audit_spec.raw_reconciliation_exempt:
        logger.warning(
            f"跳过 [{data_source}/{endpoint}] RAW vs Curated 物理对账: "
            f"{audit_spec.raw_reconciliation_reason}"
        )
        return {
            "raw_curated_status": "SKIPPED",
            "raw_curated_reason": audit_spec.raw_reconciliation_reason,
            "raw_curated_match": None,
            "raw_curated_exempt": True,
            "raw_files": 0,
            "curated_files": 0,
            "raw_count": 0,
            "raw_effective_count": 0,
            "raw_filtered_count": 0,
            "curated_count": 0,
            "raw_key_count": 0,
            "curated_key_count": 0,
            "missing_in_curated_count": 0,
            "extra_in_curated_count": 0,
            "missing_in_curated_sample": [],
            "extra_in_curated_sample": [],
            "raw_errors": [],
            "curated_errors": [],
        }

    raw_files = _collect_dataset_files(
        data_settings.raw_data_dir,
        data_source,
        endpoint,
        target_date,
    )
    curated_files = _collect_dataset_files(
        data_settings.curated_data_dir,
        data_source,
        endpoint,
        target_date,
    )
    raw_df, raw_errors = _read_target_frames(raw_files, target_date)
    curated_df, curated_errors = _read_target_frames(curated_files, target_date)
    raw_count = len(raw_df)
    raw_df, raw_filtered_count = _clean_raw_frame(endpoint, data_source, raw_df)

    primary_keys = _registered_primary_keys(data_source, endpoint)
    raw_keys_df = _extract_identity_keys_frame(raw_df, primary_keys=primary_keys)
    curated_keys_df = _extract_identity_keys_frame(curated_df, primary_keys=primary_keys)

    join_keys = [column for column in raw_keys_df.columns if column in curated_keys_df.columns]
    if (
        not join_keys
        or set(join_keys) != set(raw_keys_df.columns)
        or set(join_keys) != set(curated_keys_df.columns)
    ):
        return {
            "raw_curated_status": "FAILED",
            "raw_curated_reason": "RAW 与 Curated 无法按注册主键构造统一对账键",
            "raw_curated_match": False,
            "raw_curated_exempt": False,
            "raw_files": len(raw_files),
            "curated_files": len(curated_files),
            "raw_count": raw_count,
            "raw_effective_count": len(raw_df),
            "raw_filtered_count": raw_filtered_count,
            "curated_count": len(curated_df),
            "raw_key_count": len(raw_keys_df),
            "curated_key_count": len(curated_keys_df),
            "missing_in_curated_count": 0,
            "extra_in_curated_count": 0,
            "missing_in_curated_sample": [],
            "extra_in_curated_sample": [],
            "raw_errors": raw_errors,
            "curated_errors": curated_errors,
        }

    raw_key_count = len(raw_keys_df)
    curated_key_count = len(curated_keys_df)

    # 采用 Polars anti_join 在 Rust 内部完成高效差集比对
    missing_in_curated_df = raw_keys_df.join(curated_keys_df, on=join_keys, how="anti")
    extra_in_curated_df = curated_keys_df.join(raw_keys_df, on=join_keys, how="anti")

    missing_count = len(missing_in_curated_df)
    extra_count = len(extra_in_curated_df)

    def _sample(frame: pl.DataFrame) -> list[str]:
        return [
            "@".join(str(row[column]) for column in join_keys)
            for row in frame.head(20).iter_rows(named=True)
        ]

    missing_sample = _sample(missing_in_curated_df)
    extra_sample = _sample(extra_in_curated_df)

    reason = ""
    status = "PASSED"
    if not raw_files and not curated_files:
        status = "SKIPPED"
        reason = "未找到 RAW/Curated 物理文件"
    elif not raw_files:
        status = "FAILED"
        reason = "缺少 RAW 物理文件"
    elif not curated_files:
        status = "FAILED"
        reason = "缺少 Curated 物理文件"
    elif raw_errors or curated_errors:
        status = "FAILED"
        reason = "存在 Parquet 读取错误"
    elif missing_count > 0 or extra_count > 0:
        status = "FAILED"
        reason = "目标日期 RAW 与 Curated 主键集合不一致"
    elif curated_key_count != len(curated_df):
        status = "FAILED"
        reason = "Curated 黄金表内部存在重复主键"
    elif raw_filtered_count or len(raw_df) != len(curated_df):
        status = "PASSED"
        reason_parts: list[str] = []
        if raw_filtered_count:
            reason_parts.append(f"RAW 清洗过滤 {raw_filtered_count} 条无效记录")
        raw_duplicate_count = len(raw_df) - raw_key_count
        if raw_duplicate_count:
            reason_parts.append(
                f"RAW 存在 {raw_duplicate_count} 条批次重复记录，Curated 黄金表已权威去重"
            )
        reason = "；".join(reason_parts) or "Curated 黄金表已权威去重"

    return {
        "raw_curated_status": status,
        "raw_curated_reason": reason,
        "raw_curated_match": status == "PASSED" if status != "SKIPPED" else None,
        "raw_curated_exempt": False,
        "raw_files": len(raw_files),
        "curated_files": len(curated_files),
        "raw_count": raw_count,
        "raw_effective_count": len(raw_df),
        "raw_filtered_count": raw_filtered_count,
        "curated_count": len(curated_df),
        "raw_key_count": raw_key_count,
        "curated_key_count": curated_key_count,
        "missing_in_curated_count": missing_count,
        "extra_in_curated_count": extra_count,
        "missing_in_curated_sample": missing_sample,
        "extra_in_curated_sample": extra_sample,
        "raw_errors": raw_errors,
        "curated_errors": curated_errors,
    }


def run_audit(
    target_date: date,
    data_source: str = "tushare",
    quiet: bool = False,
    endpoint: str = "stock_daily_bar",
    basic_df: pl.DataFrame | None = None,
) -> dict[str, Any]:
    """对指定单日进行 A 股行情完整性审计对账。

    Args:
        target_date: 目标审计日期。
        data_source: 数据源标识 (默认 tushare)。
        quiet: 是否抑制 stdout 日报表控制台打印 (用于历史区间批量审计时静默模式)。
        endpoint: RAW/Curated 物理对账的数据集名称。
        basic_df: 外部传入的 stock_basic 缓存 DataFrame（用于批量审计时避免重复磁盘 I/O）。

    Returns:
        dict[str, Any]: 单日审计结果统计字典。
    """
    logger.info(f"开始对账审计，目标日期: {target_date} [数据源: {data_source}]")

    # 1. 检查 stock_basic 基础元数据是否存在
    if basic_df is None:
        try:
            basic_files = [
                p
                for p in (data_settings.curated_data_dir / data_source).rglob("*.parquet")
                if "stock_basic" in p.parts and not _is_artifact_path(p)
            ]
            basic_df = pl.read_parquet(basic_files) if basic_files else pl.DataFrame()
        except Exception as e:
            logger.error(f"加载 [{data_source}] stock_basic 失败: {e}")
            return {}

    # 2. 读取对应月份的 daily_bar 数据
    year_str, month_str = f"year={target_date.year:04d}", f"month={target_date.month:02d}"
    try:
        daily_files = [
            p
            for p in (data_settings.curated_data_dir / data_source).rglob("*.parquet")
            if "stock_daily_bar" in p.parts
            and year_str in p.parts
            and month_str in p.parts
            and not _is_artifact_path(p)
        ]
        daily_df = pl.read_parquet(daily_files) if daily_files else pl.DataFrame()
    except Exception:
        daily_df = pl.DataFrame()

    if daily_df.is_empty():
        logger.warning(f"本地日K行情库中未找到 {target_date} 的任何数据")
        actual_symbols: set[str] = set()
    else:
        # 确保 trade_date 转换为 date 类型进行比较
        daily_df = StorageCompat.safe_cast_date_col(daily_df, "trade_date")
        day_df = daily_df.filter(pl.col("trade_date") == target_date)
        actual_symbols = set(day_df["symbol"].unique().to_list())

    # 3. 筛选理论上在 target_date 已经上市且未退市的个股
    sym_col = "symbol" if "symbol" in basic_df.columns else "ts_code"
    if "delist_date" in basic_df.columns and basic_df["delist_date"].dtype != pl.Null:
        basic_df = basic_df.with_columns(
            [
                pl.col("list_date").str.to_date("%Y%m%d", strict=False).alias("list_date_d"),
                pl.col("delist_date").str.to_date("%Y%m%d", strict=False).alias("delist_date_d"),
            ]
        )
        expected_df = basic_df.filter(
            (
                (pl.col("list_date_d") >= date(1990, 12, 1))
                | (pl.col(sym_col).is_in(list(actual_symbols)))
            )
            & (pl.col("list_date_d") <= target_date)
            & (pl.col("delist_date_d").is_null() | (pl.col("delist_date_d") > target_date))
        )
    else:
        basic_df = basic_df.with_columns(
            pl.col("list_date").str.to_date("%Y%m%d", strict=False).alias("list_date_d")
        )
        expected_df = basic_df.filter(
            (
                (pl.col("list_date_d") >= date(1990, 12, 1))
                | (pl.col(sym_col).is_in(list(actual_symbols)))
            )
            & (pl.col("list_date_d") <= target_date)
        )
    expected_symbols = set(expected_df[sym_col].unique().to_list())

    theoretical_count = len(expected_symbols)
    actual_count = len(actual_symbols)

    # 4. 计算差异个股
    missing_symbols = list(expected_symbols - actual_symbols)
    missing_count = len(missing_symbols)

    logger.info(
        f"预期上市个股数: {theoretical_count}，实际行情个股数: {actual_count}，"
        f"缺失个股数: {missing_count}"
    )

    suspended_symbols: list[str] = []
    unexplained_symbols: list[str] = []

    # 5. 对于缺失的个股，优先通过本地落盘的 suspend_d 数据集校验停牌状态，离线优先
    if missing_count > 0:
        logger.info(f"正在对 {missing_count} 只缺失个股进行停牌状态对账...")
        suspend_set: set[str] = set()

        # 优先读取本地 suspend_d 数据
        try:
            year_str, month_str = f"year={target_date.year:04d}", f"month={target_date.month:02d}"
            sus_files = [
                p
                for p in (data_settings.curated_data_dir / data_source).rglob("*.parquet")
                if "suspend_d" in p.parts
                and year_str in p.parts
                and month_str in p.parts
                and not _is_artifact_path(p)
            ]
            local_sus_df = pl.read_parquet(sus_files) if sus_files else pl.DataFrame()
            date_col = next(
                (c for c in ["trade_date", "date", "suspend_date"] if c in local_sus_df.columns),
                None,
            )
            if date_col:
                if local_sus_df[date_col].dtype == pl.String:
                    local_sus_df = local_sus_df.with_columns(
                        pl.col(date_col)
                        .str.to_date("%Y-%m-%d", strict=False)
                        .alias("suspend_d_date")
                    )
                else:
                    local_sus_df = local_sus_df.with_columns(
                        pl.col(date_col).alias("suspend_d_date")
                    )
                sub_sus = local_sus_df.filter(pl.col("suspend_d_date") == target_date)
                sym_col_sus = next((c for c in ["symbol", "ts_code"] if c in sub_sus.columns), None)
                if sym_col_sus:
                    suspend_set = set(sub_sus[sym_col_sus].drop_nulls().unique().to_list())
        except Exception:
            suspend_set = set()

        # 本地未命中时，尝试降级请求远程 TuShare API
        if not suspend_set:
            try:
                client = TuShareClient()
                trade_date_str = target_date.strftime("%Y%m%d")
                suspend_df = client.query("suspend_d", trade_date=trade_date_str)
                if suspend_df is not None and len(suspend_df) > 0:
                    if hasattr(suspend_df, "get_column"):
                        suspend_set = set(suspend_df.get_column("ts_code").unique().to_list())
                    else:
                        suspend_set = set(suspend_df["ts_code"].unique().tolist())
            except Exception as e:
                logger.debug(f"调用 TuShare 停牌远程接口降级失败: {e}")

        for sym in missing_symbols:
            if sym in suspend_set:
                suspended_symbols.append(sym)
            else:
                unexplained_symbols.append(sym)

    # 6. 计算最终的数据完整率
    verified_suspended_count = len(suspended_symbols)
    true_missing_count = len(unexplained_symbols)

    integrity_rate = 0.0
    if theoretical_count > 0:
        integrity_rate = ((actual_count + verified_suspended_count) / theoretical_count) * 100.0

    physical_recon = _run_raw_curated_reconciliation(
        target_date=target_date,
        data_source=data_source,
        endpoint=endpoint,
    )
    raw_curated_status = physical_recon["raw_curated_status"]
    status = (
        "PASSED"
        if true_missing_count == 0 and raw_curated_status in {"PASSED", "SKIPPED"}
        else "FAILED"
    )

    if not quiet:
        print("\n" + "=" * 50)
        print(f"数据完整性对账审计报告 [{target_date}]")
        print("=" * 50)
        print(f"1. 理论已上市个股数 (Expected):  {theoretical_count}")
        print(f"2. 本地实际行情个股数 (Actual):  {actual_count}")
        print(f"3. 发现缺失股票总数 (Difference): {missing_count}")
        print(f"   - 证实停牌股票数 (Suspended): {verified_suspended_count}")
        print(f"   - 异常缺失股票数 (Unexplained): {true_missing_count}")
        print("-" * 50)
        print(f"4. 行情数据完整率 (Integrity Rate): {integrity_rate:.2f}%")
        print(
            "5. RAW vs Curated 物理对账: "
            f"{raw_curated_status}"
            f" (RAW {physical_recon['raw_count']} 行 / "
            f"Curated {physical_recon['curated_count']} 行)"
        )
        if physical_recon["raw_curated_reason"]:
            print(f"   - 诊断: {physical_recon['raw_curated_reason']}")
        print("=" * 50)

        if true_missing_count > 0:
            print(
                f"\n[警告] 以下 {true_missing_count} 只个股存在异常缺失，"
                "请检查网络拉取或尝试重新执行回填："
            )
            for sym in sorted(unexplained_symbols):
                name_val = expected_df.filter(pl.col(sym_col) == sym)["name"].to_list()
                name_str = name_val[0] if name_val else "未知"
                print(f" - {sym} ({name_str})")
            print("=" * 50)
        else:
            print("\n[优秀] 恭喜！当前交易日无任何异常缺失数据。")
            print("=" * 50)

    return {
        "date": target_date,
        "expected": theoretical_count,
        "actual": actual_count,
        "suspended": verified_suspended_count,
        "unexplained": true_missing_count,
        "integrity_rate": integrity_rate,
        "unexplained_symbols": unexplained_symbols,
        "status": status,
        **physical_recon,
    }


def get_trading_calendar(start_date: date, end_date: date) -> list[date]:
    """获取指定时间段内的开市交易日列表，缺少日历时返回空列表。"""
    try:
        from stock_data.update_scheduler import DataUpdateScheduler

        return list(DataUpdateScheduler.get_trading_days(start_date, end_date, "tushare"))
    except Exception as e:
        logger.warning(f"无法获取 TuShare 交易日历，拒绝按工作日推算: {e}")
        return []


def run_audit_range(
    start_date: date,
    end_date: date,
    data_source: str = "tushare",
    max_workers: int = 4,
    show_details: bool = False,
) -> dict[str, Any]:
    """对指定历史时间范围（多交易日）进行批量多线程完整性对账审计。

    Args:
        start_date: 开始日期。
        end_date: 结束日期。
        data_source: 数据源标识 (默认 tushare)。
        max_workers: 并发线程数 (默认 4)。
        show_details: 是否为每个交易日打印详细的每日报告 (默认 False)。

    Returns:
        dict[str, Any]: 历史区间汇总审计统计报告。
    """
    logger.info(
        f"开始历史时间段对账审计 (区间: {start_date} ~ {end_date}, "
        f"数据源: {data_source}, 线程数: {max_workers})..."
    )

    open_dates = get_trading_calendar(start_date, end_date)
    if not open_dates:
        logger.warning(f"在日期范围 [{start_date} ~ {end_date}] 内未查找到有效交易日")
        return {}

    logger.info(f"成功获取交易日历，共计 {len(open_dates)} 个有效交易日，开始并发审计...")

    # 预先加载一次 stock_basic，避免在每个子线程中重复磁盘 I/O
    cached_basic_df: pl.DataFrame | None = None
    try:
        source_dir = data_settings.curated_data_dir / data_source
        basic_files = [
            p
            for p in source_dir.rglob("*.parquet")
            if "stock_basic" in p.parts and not _is_artifact_path(p)
        ]
        if basic_files:
            cached_basic_df = pl.read_parquet(basic_files)
    except Exception as e:
        logger.debug(f"预加载 stock_basic 失败，子任务将独立尝试: {e}")

    daily_results: list[dict[str, Any]] = []

    if max_workers > 1 and len(open_dates) > 1:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_date = {
                executor.submit(
                    run_audit,
                    d,
                    data_source=data_source,
                    quiet=not show_details,
                    basic_df=cached_basic_df,
                ): d
                for d in open_dates
            }
            for fut in as_completed(future_to_date):
                try:
                    res = fut.result()
                    if res:
                        daily_results.append(res)
                except Exception as e:
                    d = future_to_date[fut]
                    logger.error(f"交易日 [{d}] 审计抛出异常: {e}")
    else:
        for d in open_dates:
            res = run_audit(
                d, data_source=data_source, quiet=not show_details, basic_df=cached_basic_df
            )
            if res:
                daily_results.append(res)

    if not daily_results:
        logger.warning("未能获取到任何有效的单日审计结果")
        return {}

    # 按交易日升序排序结果
    daily_results.sort(key=lambda x: x["date"])

    total_days = len(daily_results)
    avg_integrity_rate = (
        sum(r["integrity_rate"] for r in daily_results) / total_days if total_days > 0 else 0.0
    )

    problematic_days = [r for r in daily_results if r["unexplained"] > 0]
    perfect_days_count = total_days - len(problematic_days)

    # 汇总各股票异常缺失出现的频次
    symbol_missing_counts: dict[str, int] = {}
    for r in daily_results:
        for sym in r.get("unexplained_symbols", []):
            symbol_missing_counts[sym] = symbol_missing_counts.get(sym, 0) + 1

    top_missing_symbols = sorted(symbol_missing_counts.items(), key=lambda x: x[1], reverse=True)

    print("\n" + "=" * 65)
    print(
        "       历史时间段数据完整性对账审计汇总报告 "
        f"[{start_date} ~ {end_date}] (数据源: {data_source})       "
    )
    print("=" * 65)
    print(f"1. 审计交易日总数 (Trading Days):    {total_days} 天")
    print(f"2. 完美无缺失天数 (Perfect Days):    {perfect_days_count} 天")
    print(f"3. 存在异常缺失天数 (Problem Days):   {len(problematic_days)} 天")
    print(f"4. 区间平均数据完整率 (Avg Integrity Rate): {avg_integrity_rate:.2f}%")
    print("=" * 65)

    if top_missing_symbols:
        print("\n[警告] 区间内频次最高的异常缺失股票 Top 10:")
        for sym, freq in top_missing_symbols[:10]:
            ratio = (freq / total_days) * 100.0
            print(f" - {sym}: 缺失 {freq} 个交易日 ({ratio:.1f}%)")
        print("=" * 65)
    else:
        print("\n[优秀] 恭喜！在整个历史区间内，所有交易日均实现 100% 数据完备对算。")
        print("=" * 65)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "total_days": total_days,
        "perfect_days": perfect_days_count,
        "problematic_days": len(problematic_days),
        "avg_integrity_rate": avg_integrity_rate,
        "top_missing_symbols": top_missing_symbols,
        "daily_results": daily_results,
    }


def run_index_audit(
    target_date: date, data_source: str = "tushare", quiet: bool = False
) -> dict[str, Any]:
    """对指定单日进行指数观察池完整性审计对账。"""
    from stock_core.config.loader import load_watchlist_config

    wl = load_watchlist_config()
    source_wl = getattr(wl, data_source, None)
    all_configured_indices = (
        set(source_wl.indices) if (source_wl and hasattr(source_wl, "indices")) else set()
    )
    base_dates = getattr(source_wl, "base_dates", {}) if source_wl else {}

    target_date_str = target_date.strftime("%Y-%m-%d")
    expected_indices: set[str] = set()
    for sym in all_configured_indices:
        b_date = base_dates.get(sym) or base_dates.get(sym.split(".")[0])
        if b_date is None or str(b_date) <= target_date_str:
            expected_indices.add(sym)

    if not expected_indices:
        if not quiet:
            logger.warning(f"数据源 [{data_source}] 未配置指数观察池")
        return {}

    target_year = f"year={target_date.year:04d}"
    target_month = f"month={target_date.month:02d}"
    root_path = data_settings.curated_data_dir / data_source
    matched_files = (
        [
            p
            for p in root_path.rglob("*.parquet")
            if ("index_daily" in p.parts or "index_daily_bar" in p.parts)
            and "index_dailybasic" not in p.parts
            and target_year in p.parts
            and target_month in p.parts
            and not _is_artifact_path(p)
        ]
        if root_path.exists()
        else []
    )

    try:
        if matched_files:
            df = pl.read_parquet(matched_files)
            df = StorageCompat.safe_cast_date_col(df, "trade_date")
            sub_df = df.filter(pl.col("trade_date") == target_date)
            actual_indices = set(sub_df["symbol"].to_list())
        else:
            actual_indices = set()
    except Exception as exc:
        logger.debug(f"读取指数行情对账失败: {exc}")
        actual_indices = set()

    missing = expected_indices - actual_indices
    integrity_rate = (
        (len(actual_indices) / len(expected_indices) * 100.0) if expected_indices else 0.0
    )

    if not quiet:
        logger.info(
            f"指数审计结果 [{target_date}]: 预期 {len(expected_indices)} 个, "
            f"实际 {len(actual_indices)} 个, 缺失: {list(missing)}, 完整率: {integrity_rate:.2f}%"
        )

    return {
        "date": target_date,
        "expected_count": len(expected_indices),
        "actual_count": len(actual_indices),
        "missing_count": len(missing),
        "missing_indices": list(missing),
        "integrity_rate": integrity_rate,
    }


def run_index_audit_range(
    start_date: date,
    end_date: date,
    data_source: str = "tushare",
    max_workers: int = 4,
    show_details: bool = False,
) -> dict[str, Any]:
    """对指定时间段进行指数观察池完整性审计对账。"""
    logger.info(
        f"开始指数时间段对账审计 (区间: {start_date} ~ {end_date}, 数据源: {data_source})..."
    )

    trading_dates = get_trading_calendar(start_date, end_date)
    if not trading_dates:
        logger.error(f"获取 {start_date} ~ {end_date} 交易日历失败")
        return {}

    daily_results: list[dict[str, Any]] = []
    perfect_count = 0

    for d in trading_dates:
        res = run_index_audit(d, data_source=data_source, quiet=not show_details)
        if res:
            daily_results.append(res)
            if res["missing_count"] == 0 and res["integrity_rate"] >= 100.0:
                perfect_count += 1

    total_days = len(daily_results)
    avg_rate = (
        sum(r["integrity_rate"] for r in daily_results) / total_days if total_days > 0 else 0.0
    )

    print("\n" + "=" * 65)
    print(
        "       指数时间段完整性对账审计汇总报告 "
        f"[{start_date} ~ {end_date}] (数据源: {data_source})       "
    )
    print("=" * 65)
    print(f"1. 审计交易日总数 (Trading Days):    {total_days} 天")
    print(f"2. 完美无缺失天数 (Perfect Days):    {perfect_count} 天")
    print(f"3. 存在缺失天数 (Problem Days):     {total_days - perfect_count} 天")
    print(f"4. 区间平均数据完整率 (Avg Integrity Rate): {avg_rate:.2f}%")
    print("=" * 65 + "\n")

    return {
        "total_days": total_days,
        "perfect_days": perfect_count,
        "avg_integrity_rate": avg_rate,
        "daily_results": daily_results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="数据完整性对账与审计工具")
    parser.add_argument(
        "-s",
        "--source",
        "--data-source",
        dest="data_source",
        type=str,
        default="tushare",
        help="数据源标识名称 (如 tushare / yfinance / lixinger，默认: tushare)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="stock",
        choices=[
            "stock",
            "index",
            "daily_basic",
            "adj_factor",
            "hk_hold",
            "sw_industry",
            "sw_daily",
        ],
        help=(
            "对账模式 (stock: K线审计, index: 指数审计, daily_basic: 估值对账, "
            "adj_factor: 复权因子对账, hk_hold: 北向持仓, sw_industry: "
            "申万行业图谱与估值, sw_daily: 申万行业日行情)"
        ),
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="对账目标单日 (格式: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="历史区间对账开始日期 (格式: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="历史区间对账结束日期 (格式: YYYY-MM-DD)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="历史区间批量对账时的并发线程数 (默认: 4)",
    )
    parser.add_argument(
        "--show-details",
        action="store_true",
        help="历史区间批量对账时是否显示每日明细",
    )
    args = parser.parse_args()

    data_source = args.data_source or "tushare"

    if args.start and args.end:
        try:
            start_d = datetime.strptime(args.start, "%Y-%m-%d").date()
            end_d = datetime.strptime(args.end, "%Y-%m-%d").date()
        except ValueError:
            logger.error("开始日期或结束日期格式不正确，必须为 YYYY-MM-DD")
            sys.exit(1)
        if args.mode == "index":
            run_index_audit_range(
                start_d,
                end_d,
                data_source=data_source,
                max_workers=args.max_workers,
                show_details=args.show_details,
            )
        else:
            run_audit_range(
                start_d,
                end_d,
                data_source=data_source,
                max_workers=args.max_workers,
                show_details=args.show_details,
            )
    else:
        target_date: date
        if args.date:
            try:
                target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
            except ValueError:
                logger.error("日期格式不正确，必须为 YYYY-MM-DD")
                sys.exit(1)
        else:
            target_date = date.today() - timedelta(days=1)

        if args.mode == "index":
            run_index_audit(target_date, data_source=data_source)
        elif args.mode == "daily_basic":
            run_daily_basic_audit(target_date, data_source=data_source)
        elif args.mode == "adj_factor":
            run_adj_factor_audit(target_date, data_source=data_source)
        elif args.mode == "hk_hold":
            run_hk_hold_audit(target_date, data_source=data_source)
        elif args.mode == "sw_industry":
            run_sw_industry_audit(
                target_date,
                data_source=args.data_source if args.data_source != "tushare" else "lixinger",
            )
        elif args.mode == "sw_daily":
            run_sw_daily_audit(target_date, data_source=data_source)
        else:
            run_audit(target_date, data_source=data_source)


if __name__ == "__main__":
    main()
