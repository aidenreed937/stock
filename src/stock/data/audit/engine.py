"""通用数据审计与事实对账引擎 (Universal Anti-Join Audit Engine)。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

import polars as pl

from stock.config.settings import settings
from stock.data.audit.benchmarks.base import get_trading_calendar
from stock.data.audit.domains import AuditReportResult
from stock.data.audit.registry import get_audit_spec, resolve_benchmark_provider
from stock.data.catalog import DataCatalog
from stock.utils.logger import logger


def extract_identity_keys(frame: pl.DataFrame) -> pl.DataFrame:
    """从任意 DataFrame 中提取标准 (symbol, trade_date) 格式的主键。"""
    if frame.is_empty():
        return pl.DataFrame(
            {"symbol": pl.Series([], dtype=pl.Utf8), "trade_date": pl.Series([], dtype=pl.Utf8)}
        )

    sym_cols = [c for c in ["symbol", "ts_code", "index_code", "industry_code"] if c in frame.columns]
    date_cols = [c for c in ["trade_date", "date", "period", "end_date"] if c in frame.columns]

    if not sym_cols or not date_cols:
        return pl.DataFrame(
            {"symbol": pl.Series([], dtype=pl.Utf8), "trade_date": pl.Series([], dtype=pl.Utf8)}
        )

    def _clean_date_expr(col_name: str, col_dtype: pl.DataType) -> pl.Expr:
        if col_dtype in (pl.Date, pl.Datetime):
            return pl.col(col_name).dt.strftime("%Y%m%d")
        return pl.col(col_name).cast(pl.Utf8, strict=False).str.replace_all("-", "")

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


def print_audit_summary_report(results: list[AuditReportResult]) -> None:
    """打印标准化的历史时间段汇总审计报告。"""
    if not results:
        print("未产生任何审计结果。")
        return

    total_days = len(results)
    perfect_days = sum(1 for r in results if r.missing_count == 0)
    problem_days = total_days - perfect_days
    avg_integrity = sum(r.integrity_rate for r in results) / total_days
    start_d = results[0].start_date
    end_d = results[-1].end_date
    dataset = results[0].dataset
    source = results[0].data_source

    print("\n" + "=" * 65)
    print(f"       【{dataset}】历史数据完整性对账审计汇总报告 [{start_d} ~ {end_d}] ({source})")
    print("=" * 65)
    print(f"1. 审计交易日总数 (Trading Days):    {total_days:>4} 天")
    print(f"2. 完美无缺失天数 (Perfect Days):    {perfect_days:>4} 天")
    print(f"3. 存在异常缺失天数 (Problem Days):   {problem_days:>4} 天")
    print(f"4. 区间平均数据完整率 (Avg Integrity Rate): {avg_integrity:>6.2f}%")
    print("=" * 65)

    missing_pool: dict[str, int] = {}
    for r in results:
        for s in r.missing_samples:
            sym = s.split("@")[0]
            missing_pool[sym] = missing_pool.get(sym, 0) + 1

    if missing_pool:
        print("\n[警告] 区间内频次最高的异常缺失标的 Top 10:")
        sorted_missing = sorted(missing_pool.items(), key=lambda x: x[1], reverse=True)[:10]
        for sym, cnt in sorted_missing:
            pct = (cnt / total_days) * 100.0
            print(f" - {sym}: 缺失 {cnt} 个交易日 ({pct:.1f}%)")
        print("=" * 65 + "\n")


class UniversalAuditEngine:
    """通用数据审计与事实对账引擎。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        self.catalog = catalog or DataCatalog()

    def _get_catalog(self, data_source: str) -> DataCatalog:
        if self.catalog.data_source == data_source:
            return self.catalog
        return DataCatalog(data_source=data_source, storage_dir=self.catalog.storage_dir)

    def audit_single_day(
        self,
        dataset: str,
        target_date: date,
        data_source: str = "tushare",
    ) -> AuditReportResult:
        """对单个交易日执行事实基准差集对账。"""
        spec = get_audit_spec(dataset, data_source)
        cat = self._get_catalog(data_source)
        provider = resolve_benchmark_provider(spec, catalog=cat)

        expected_df = provider.get_expected_keys(target_date, target_date)
        suspended_df = provider.get_suspended_keys(target_date, target_date)

        actual_df = cat.load_dataset(dataset, start_date=target_date, end_date=target_date)
        actual_keys = extract_identity_keys(actual_df)

        expected_count, actual_count = len(expected_df), len(actual_keys)
        if expected_count > 0:
            diff_df = expected_df.join(actual_keys, on=["symbol", "trade_date"], how="anti")
            true_missing_df = diff_df.join(suspended_df, on=["symbol", "trade_date"], how="anti")
            extra_df = actual_keys.join(expected_df, on=["symbol", "trade_date"], how="anti")
        else:
            diff_df = true_missing_df = extra_df = pl.DataFrame()

        missing_count = len(true_missing_df)
        suspended_count = len(diff_df) - missing_count
        extra_count = len(extra_df)

        if expected_count > 0:
            covered_expected = max(0, expected_count - missing_count)
            integrity_rate = min(100.0, (covered_expected / expected_count) * 100.0)
        else:
            integrity_rate = 100.0 if actual_count > 0 else 0.0

        status = "PASSED" if integrity_rate >= (spec.min_expected_ratio * 100.0) else "FAILED"
        missing_samples = [
            f"{r['symbol']}@{r['trade_date']}"
            for r in true_missing_df.head(10).iter_rows(named=True)
        ]
        extra_samples = [
            f"{r['symbol']}@{r['trade_date']}"
            for r in extra_df.head(10).iter_rows(named=True)
        ]
        raw_count, curated_count, raw_curated_status = self._check_raw_curated(
            dataset, data_source, target_date
        )

        return AuditReportResult(
            dataset=dataset,
            data_source=data_source,
            domain=spec.domain,
            frequency=spec.frequency,
            start_date=target_date,
            end_date=target_date,
            expected_count=expected_count,
            actual_count=actual_count,
            suspended_count=suspended_count,
            missing_count=missing_count,
            integrity_rate=integrity_rate,
            status=status,
            missing_samples=missing_samples,
            extra_samples=extra_samples,
            raw_curated_status=raw_curated_status,
            raw_count=raw_count,
            curated_count=curated_count,
        )

    def _check_raw_curated(
        self, dataset: str, data_source: str, target_date: date
    ) -> tuple[int, int, str]:
        from stock.data.storage.compat import StorageCompat

        raw_base = settings.raw_data_dir / data_source
        curated_base = settings.curated_data_dir / data_source
        if not raw_base.exists() and not curated_base.exists():
            return 0, 0, "SKIPPED"

        year_str = f"year={target_date.year:04d}"
        month_str = f"month={target_date.month:02d}"

        raw_files = [
            p
            for p in raw_base.rglob("*.parquet")
            if dataset in p.parts
            and year_str in p.parts
            and month_str in p.parts
            and not StorageCompat.is_artifact_path(p)
        ]
        if not raw_files:
            raw_files = [
                p
                for p in raw_base.rglob("*.parquet")
                if dataset in p.parts and not StorageCompat.is_artifact_path(p)
            ]

        curated_files = [
            p
            for p in curated_base.rglob("*.parquet")
            if dataset in p.parts
            and year_str in p.parts
            and month_str in p.parts
            and not StorageCompat.is_artifact_path(p)
        ]
        if not curated_files:
            curated_files = [
                p
                for p in curated_base.rglob("*.parquet")
                if dataset in p.parts and not StorageCompat.is_artifact_path(p)
            ]

        if not raw_files and not curated_files:
            return 0, 0, "SKIPPED"
        if not raw_files or not curated_files:
            return 0, 0, "FAILED"

        try:
            target_date_str = target_date.strftime("%Y%m%d")
            raw_df = pl.read_parquet(raw_files)
            raw_keys = extract_identity_keys(raw_df).filter(
                pl.col("trade_date") == target_date_str
            )

            curated_df = pl.read_parquet(curated_files)
            curated_keys = extract_identity_keys(curated_df).filter(
                pl.col("trade_date") == target_date_str
            )

            r_cnt, c_cnt = len(raw_keys), len(curated_keys)
            if r_cnt == 0 and c_cnt == 0:
                return 0, 0, "SKIPPED"

            # 跨层主键差集对账
            missing_in_curated = raw_keys.join(
                curated_keys, on=["symbol", "trade_date"], how="anti"
            )
            extra_in_curated = curated_keys.join(
                raw_keys, on=["symbol", "trade_date"], how="anti"
            )

            if len(missing_in_curated) == 0 and len(extra_in_curated) == 0:
                return r_cnt, c_cnt, "PASSED"
            return r_cnt, c_cnt, "FAILED"
        except Exception as exc:
            logger.debug(f"RAW/Curated 对账读取异常: {exc}")
            return 0, 0, "FAILED"

    def audit_range(
        self,
        dataset: str,
        start_date: date,
        end_date: date,
        data_source: str = "tushare",
        max_workers: int = 4,
    ) -> list[AuditReportResult]:
        """多线程并发执行历史时间段每日对账。"""
        trading_dates = get_trading_calendar(start_date=start_date, end_date=end_date)
        if not trading_dates:
            logger.warning(f"指定区间 {start_date} ~ {end_date} 无有效交易日")
            return []

        results: list[AuditReportResult] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_date = {
                executor.submit(self.audit_single_day, dataset, d, data_source): d
                for d in trading_dates
            }
            for future in as_completed(future_to_date):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as exc:
                    d = future_to_date[future]
                    logger.error(f"日期 {d} 审计执行异常: {exc}")

        results.sort(key=lambda r: r.start_date)
        return results
