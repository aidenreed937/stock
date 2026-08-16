"""Curated 黄金表数值分布与数量级阶跃异动审计模块。

已知限制:
- 阶跃检测基于全市场按日聚合的均值，局部标的/单一交易所的单位错位会被大多数未受损行稀释而漏检。
- 分布审计只对"相对突变"敏感（负值、数量级阶跃），无法发现从入库首日即整体错量的持续错误，
  因其缺少外部基准参考。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock.config.settings import settings
from stock.data.catalog import DataCatalog
from stock.data.storage.compat import StorageCompat
from stock.utils.logger import logger

DEFAULT_DATASET_NUMERIC_COLS: dict[str, list[str]] = {
    "sw_daily": ["amount", "volume", "total_mv", "float_mv", "close"],
    "daily_basic": ["total_mv", "circ_mv", "turnover_rate", "pe", "pe_ttm", "pb"],
    "stock_daily_bar": ["amount", "volume", "open", "high", "low", "close"],
    "daily": ["amount", "vol", "close"],
    "margin": ["rzrqye", "rzye", "rqye"],
    "index_fundamental": [
        "pe_ttm.ew",
        "pe_ttm.mcw",
        "pb.ew",
        "pb.mcw",
        "ps_ttm.ew",
        "ps_ttm.mcw",
        "dyr.ew",
        "dyr.mcw",
    ],
    "fund_daily": ["amount", "volume", "close"],
    "moneyflow": ["buy_sm_amount", "sell_sm_amount", "net_mf_amount"],
}

NON_NEGATIVE_COLUMNS: set[str] = {
    "amount",
    "volume",
    "vol",
    "total_mv",
    "circ_mv",
    "float_mv",
    "turnover_rate",
    "open",
    "high",
    "low",
    "close",
    "rzrqye",
    "rzye",
    "rqye",
    "buy_sm_amount",
    "sell_sm_amount",
}


@dataclass
class DistributionAnomaly:
    """单个分布或跳跃异动事件。"""

    trade_date: date
    column: str
    anomaly_type: str
    severity: str
    current_val: float
    previous_val: float | None = None
    ratio: float | None = None
    detail: str = ""


@dataclass
class ColumnDistributionSummary:
    """单个数值列的历史全景分布统计。"""

    column: str
    total_records: int
    non_null_records: int
    null_records: int
    mean: float
    std: float
    cv: float
    median: float
    mad: float
    min: float
    max: float
    p1: float
    p99: float
    negative_count: int
    step_jumps_count: int


@dataclass
class DistributionAuditReport:
    """数据集全景分布审计报告。"""

    dataset_name: str
    data_source: str
    total_rows: int
    total_dates: int
    date_range: tuple[date | None, date | None]
    columns_summary: dict[str, ColumnDistributionSummary] = field(default_factory=dict)
    anomalies: list[DistributionAnomaly] = field(default_factory=list)
    passed: bool = True


def _to_float(v: Any) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _audit_col_distribution(
    df: pl.DataFrame,
    col: str,
    max_step_ratio: float,
    min_step_ratio: float,
) -> tuple[ColumnDistributionSummary, list[DistributionAnomaly]]:
    """计算单列分布统计并探测跳跃异动与负值异常。"""
    col_series = df[col].drop_nulls().cast(pl.Float64, strict=False)
    mean_val = _to_float(col_series.mean())
    std_val = _to_float(col_series.std())
    cv_val = (std_val / mean_val) if abs(mean_val) > 1e-9 else 0.0
    median_val = _to_float(col_series.median())
    abs_dev = (col_series - median_val).abs()
    mad_val = _to_float(abs_dev.median())

    anomalies: list[DistributionAnomaly] = []
    neg_count = 0
    if col in NON_NEGATIVE_COLUMNS:
        # 在 strict=False 转换后的数值列上判负，避免原始 dtype 非数值时比较报错
        neg_df = df.filter(pl.col(col).cast(pl.Float64, strict=False) < 0.0)
        neg_count = len(neg_df)
        for r in neg_df.head(3).iter_rows(named=True):
            d = r["trade_date"]
            t_d = d if isinstance(d, date) else date.fromisoformat(str(d))
            anomalies.append(
                DistributionAnomaly(
                    trade_date=t_d,
                    column=col,
                    anomaly_type="NEGATIVE_VALUE",
                    severity="ERROR",
                    current_val=float(r[col]),
                    detail=f"非物理负值: 标的 {r.get('symbol', 'N/A')} 字段 [{col}] 值为 {r[col]}",
                )
            )

    step_jump_count = 0
    if "trade_date" in df.columns:
        daily_agg = (
            df.group_by("trade_date")
            .agg(pl.col(col).mean().alias("mean_val"))
            .drop_nulls(subset=["mean_val"])
            .sort("trade_date")
        )
        if len(daily_agg) > 1:
            # 阶跃判定使用 |cur|/|prev| 的量级倍数而非带符号比值，避免可正可负列（如净额）
            # 在 0 附近翻号时产生无意义的负比率误报；并通过近零保护门槛避免前值≈0 时比率
            # 爆炸成 inf 造成的误报。eps 以全时段均值量级的比例确定，与字段单位无关。
            scale = _to_float(daily_agg["mean_val"].abs().max()) or 1.0
            eps = scale * 1e-9
            jumps = (
                daily_agg.with_columns(
                    pl.col("mean_val").shift(1).alias("prev_mean"),
                    pl.col("mean_val").shift(1).abs().alias("prev_abs"),
                )
                .filter(pl.col("prev_mean").is_not_null())
                .with_columns((pl.col("mean_val").abs() / pl.col("prev_abs")).alias("fold"))
                .filter(pl.col("prev_abs") >= eps)
                .filter((pl.col("fold") > max_step_ratio) | (pl.col("fold") < min_step_ratio))
            )
            step_jump_count = len(jumps)
            for r in jumps.iter_rows(named=True):
                d = r["trade_date"]
                t_d = d if isinstance(d, date) else date.fromisoformat(str(d))
                anomalies.append(
                    DistributionAnomaly(
                        trade_date=t_d,
                        column=col,
                        anomaly_type="STEP_JUMP",
                        severity="ERROR",
                        current_val=float(r["mean_val"]),
                        previous_val=float(r["prev_mean"])
                        if r["prev_mean"] is not None
                        else None,
                        ratio=round(float(r["fold"]), 4),
                        detail=f"数量级阶跃异动: 日均值 {r['prev_mean']:.2e} -> {r['mean_val']:.2e} "
                        f"(跳跃比率: {r['fold']:.2f}x)",
                    )
                )

    summary = ColumnDistributionSummary(
        column=col,
        total_records=len(df),
        non_null_records=len(col_series),
        null_records=df[col].null_count(),
        mean=round(mean_val, 4),
        std=round(std_val, 4),
        cv=round(cv_val, 4),
        median=round(median_val, 4),
        mad=round(mad_val, 4),
        min=round(_to_float(col_series.min()), 4),
        max=round(_to_float(col_series.max()), 4),
        p1=round(_to_float(col_series.quantile(0.01)), 4),
        p99=round(_to_float(col_series.quantile(0.99)), 4),
        negative_count=neg_count,
        step_jumps_count=step_jump_count,
    )
    return summary, anomalies


class CuratedDistributionAuditor:
    """Curated 黄金表数值分布与阶跃审计器。"""

    def __init__(
        self,
        catalog: DataCatalog | None = None,
        base_dir: str | Path | None = None,
        max_step_ratio: float = 10.0,
        min_step_ratio: float = 0.1,
    ) -> None:
        self.catalog = catalog
        self.base_dir = Path(base_dir) if base_dir else settings.curated_data_dir
        self.max_step_ratio = max_step_ratio
        self.min_step_ratio = min_step_ratio

    def audit_dataset(
        self,
        dataset_name: str,
        data_source: str = "tushare",
        value_cols: list[str] | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DistributionAuditReport:
        """审计指定 Curated 数据集的历史数值分布与相邻日阶跃。"""
        logger.info(
            f"开始 Curated 数值分布审计: 数据集 [{dataset_name}], 数据源 [{data_source}]"
        )
        target_dir = self.base_dir / data_source
        files = [
            p
            for p in target_dir.rglob("*.parquet")
            if dataset_name in p.parts and not StorageCompat.is_artifact_path(p)
        ]
        frames = []
        for p in files:
            try:
                frame = pl.read_parquet(p)
                if not frame.is_empty():
                    frames.append(StorageCompat.safe_normalize_frame(frame))
            except Exception as exc:
                logger.debug(f"跳过异常文件 [{p}]: {exc}")

        if not frames:
            logger.warning(f"未找到数据集 [{dataset_name}] 的有效数据")
            return DistributionAuditReport(
                dataset_name=dataset_name,
                data_source=data_source,
                total_rows=0,
                total_dates=0,
                date_range=(None, None),
                passed=False,
            )

        df = pl.concat(frames, how="diagonal_relaxed")
        df = StorageCompat.safe_cast_date_col(df, "trade_date")
        if start_date is not None:
            df = df.filter(pl.col("trade_date") >= start_date)
        if end_date is not None:
            df = df.filter(pl.col("trade_date") <= end_date)

        if df.is_empty():
            logger.warning(
                f"数据集 [{dataset_name}] 在目标时间区间内无有效数据，按 fail-closed 视为未通过"
            )
            return DistributionAuditReport(
                dataset_name=dataset_name,
                data_source=data_source,
                total_rows=0,
                total_dates=0,
                date_range=(None, None),
                passed=False,
            )

        target_cols = value_cols or DEFAULT_DATASET_NUMERIC_COLS.get(
            dataset_name,
            [
                col
                for col, dtype in df.schema.items()
                if dtype in (pl.Float64, pl.Float32, pl.Int64, pl.Int32)
                and col not in ("trade_date", "year", "month")
            ],
        )
        target_cols = [c for c in target_cols if c in df.columns]
        dates = df["trade_date"].drop_nulls()
        min_date, max_date = dates.min(), dates.max()

        report = DistributionAuditReport(
            dataset_name=dataset_name,
            data_source=data_source,
            total_rows=len(df),
            total_dates=dates.n_unique(),
            date_range=(
                min_date if isinstance(min_date, date) else None,
                max_date if isinstance(max_date, date) else None,
            ),
        )

        for col in target_cols:
            if df[col].drop_nulls().is_empty():
                continue
            summary, col_anomalies = _audit_col_distribution(
                df, col, self.max_step_ratio, self.min_step_ratio
            )
            report.columns_summary[col] = summary
            report.anomalies.extend(col_anomalies)

        report.passed = len(report.anomalies) == 0
        return report

    def format_report(self, report: DistributionAuditReport) -> str:
        """生成格式化的终端报告。"""
        lines = [
            f"=== Curated 数据集数值分布与阶跃审计报告: [{report.dataset_name}] ===",
            f"数据源: {report.data_source} | 总行数: {report.total_rows:,} | 交易日数: {report.total_dates:,}",
            f"时间区间: {report.date_range[0]} ~ {report.date_range[1]}",
            f"总体审计状态: {'🟢 PASSED (分布正常)' if report.passed else '🔴 FAILED (存在异常)'}",
            "",
            "【各字段数值分布全景统计】",
            "字段名               均值          中位数         标准差        CV(变异系数)   MAD(中位偏差)   P1~P99 区间              负值数  阶跃突变数",
            "-" * 125,
        ]
        for col, s in report.columns_summary.items():
            lines.append(
                f"{col:<18} {s.mean:<13.2e} {s.median:<13.2e} {s.std:<13.2e} "
                f"{s.cv:<12.2f} {s.mad:<14.2e} [{s.p1:.1e}, {s.p99:.1e}] "
                f"{s.negative_count:<7} {s.step_jumps_count:<8}"
            )
        if report.anomalies:
            lines.append("\n【检测到的异常异动列表 (Top 10)】")
            for a in report.anomalies[:10]:
                lines.append(
                    f"- [{a.severity}] {a.trade_date} | 字段 [{a.column}] | 类型 [{a.anomaly_type}]: {a.detail}"
                )
        return "\n".join(lines)


def run_distribution_audit(
    dataset_name: str | None = None,
    data_source: str = "tushare",
    quiet: bool = False,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    """CLI / CI 审计入口函数。"""
    auditor = CuratedDistributionAuditor()
    datasets = (
        [dataset_name]
        if dataset_name
        else ["sw_daily", "daily_basic", "stock_daily_bar", "margin", "index_fundamental"]
    )
    all_passed = True
    results: dict[str, Any] = {}
    for ds in datasets:
        ds_source = "lixinger" if ds == "index_fundamental" else data_source
        rep = auditor.audit_dataset(
            ds,
            data_source=ds_source,
            start_date=start_date,
            end_date=end_date,
        )
        if not rep.passed:
            all_passed = False
        results[ds] = {
            "passed": rep.passed,
            "total_rows": rep.total_rows,
            "total_dates": rep.total_dates,
            "anomalies_count": len(rep.anomalies),
            "anomalies": [
                {"date": str(a.trade_date), "col": a.column, "type": a.anomaly_type}
                for a in rep.anomalies
            ],
        }
        if not quiet:
            print(auditor.format_report(rep))
            print()
    return {"status": "PASSED" if all_passed else "FAILED", "datasets": results}
