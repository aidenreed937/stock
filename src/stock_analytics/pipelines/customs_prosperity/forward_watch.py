"""申万 L2/L3 × 海关出口 前瞻观察表（METHODOLOGY_FINAL 定稿口径）。

合并来源（全部本地黄金表/产物）：
  - 金额面板: customs_export_prosperity_panel.parquet（同一 artifact_root 下产物）
  - 量价面板: customs_l2_volume_price_monthly.parquet（同一 artifact_root 下产物）
  - 财报:     sw_2021_l2_fs_* / sw_2021_l3_fs_*（营收/净利 TTM yoy，后视验证列）
  - 维度表:   sw_2021_industry_dimension_golden（index_code ↔ industry_code 桥接唯一源）

输出：
  - L2 观察表: customs_forward_watch_l2.parquet
  - L3 观察表: customs_forward_watch_l3.parquet

列：industry_code / industry_name / idx_code / 金额yoy / 量yoy / 价yoy / 驱动类型 /
    分位36m / 财报营收yoy / 财报净利yoy / 一致率分级（仅 L2）/ n_hs8
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from stock_analytics.pipelines.customs_prosperity.config import (
    FORWARD_WATCH_L2_FILE,
    FORWARD_WATCH_L3_FILE,
)
from stock_data.catalog import DataCatalog
from stock_data.catalog.sw_industry_golden import load_sw_2021_industry_dimension
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_DIR = Path("data/analytics/industry")
DEFAULT_FINANCIAL_START = date(2020, 1, 1)


def load_dim(
    storage_dir: Path | str = "data",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """读取 L2/L3 维度黄金表（index_code ↔ industry_code ↔ parent_code）。"""
    runtime = DataRuntimeContext.from_root(storage_dir)
    cat = DataCatalog(data_source="derived", runtime=runtime)
    l2 = load_sw_2021_industry_dimension(
        cat, level="L2", columns=("industry_code", "industry_name", "index_code")
    ).rename({"index_code": "idx_code", "industry_code": "industry_code"})
    l3 = load_sw_2021_industry_dimension(
        cat, level="L3", columns=("industry_code", "industry_name", "index_code", "parent_code")
    ).rename({"index_code": "idx_code"})
    return l2, l3


def load_financial(
    data_source: str,
    dataset: str,
    *,
    storage_dir: Path | str = "data",
    end_date: date | None = None,
    start_date: date = DEFAULT_FINANCIAL_START,
) -> pl.DataFrame:
    """财报 TTM yoy：官方优先、派生兜底（data-catalog §1.3 口径）。

    end_date 动态取当前日期（P5-1 修复：原硬编码 2026-12-31 会在之后年份
    漏掉最新财报期，导致观察表财报列过期）。
    """
    runtime = DataRuntimeContext.from_root(storage_dir)
    cat = DataCatalog(data_source=data_source, runtime=runtime)
    fs = cat.load_dataset(dataset, start_date=start_date, end_date=end_date or date.today())
    toi = pl.col("q").struct.field("ps").struct.field("toi")
    np_ = pl.col("q").struct.field("ps").struct.field("np")
    fs2 = fs.with_columns(
        pl.coalesce([toi.struct.field("ttm_y2y"), toi.struct.field("ttm_y2y_derived")]).alias(
            "revenue_y2y"
        ),
        pl.coalesce([np_.struct.field("ttm_y2y"), np_.struct.field("ttm_y2y_derived")]).alias(
            "profit_y2y"
        ),
    ).select(["symbol", "reportDate", "revenue_y2y", "profit_y2y"])
    latest = (
        fs2.sort("reportDate")
        .group_by("symbol")
        .agg(pl.col("reportDate").max().alias("reportDate"))
    )
    return fs2.join(latest, on=["symbol", "reportDate"], how="inner").rename(
        {"symbol": "industry_code"}
    )


def _emp_pct_36m(grp: pl.DataFrame) -> pl.DataFrame:
    """Framework §1 口径：当前 yoy 在近 36 个频点内 ≤ 当前值的比例 × 100。"""
    ys = grp.sort("report_month")
    vals = ys["yoy_growth_3mma"].to_list()
    out = []
    for i in range(len(vals)):
        lo = max(0, i - 35)
        win = [v for v in vals[lo : i + 1] if v is not None]
        cur = vals[i]
        out.append(
            None
            if (cur is None or len(win) < 12)
            else round(sum(1 for v in win if v <= cur) / len(win) * 100, 1)
        )
    return ys.with_columns(pl.Series("yoy_pct_36m", out))


def build_level(
    level: str,
    artifact_root: Path | str,
    *,
    consistency_table: dict[str, tuple[float, str]] | None = None,
    l2_financial_datasets: tuple[str, ...] | None = None,
    l3_financial_dataset: str | None = None,
    storage_dir: Path | str = "data",
) -> pl.DataFrame:
    """构建单层观察表（L2/L3）并落盘到 artifact_root。

    Args:
        level: "L2" 或 "L3"。
        artifact_root: 产物目录（金额面板/量价面板所在，也是输出目录）。
        consistency_table: L2 一致率分级表（idx_code -> (一致率, 分级)）。
        l2_financial_datasets: L2 财报数据集（官方四张表）。
        l3_financial_dataset: L3 财报数据集。
        storage_dir: 数据根目录。

    Returns:
        观察表面板（L2 含 grade/consistency 列；L3 不含）。
    """
    dim_l2, dim_l3 = load_dim(storage_dir=storage_dir)
    dim = dim_l2 if level == "L2" else dim_l3
    root = Path(artifact_root)

    # 1. 金额面板（含全历史 → 36 月分位）
    c = pl.read_parquet(root / "customs_export_prosperity_panel.parquet")
    l2_all = c.filter(pl.col("granularity") == level.lower()).rename({"code": "idx_code"})
    m_all = l2_all.join(dim, on="idx_code", how="left").filter(
        pl.col("industry_code").is_not_null()
    )
    if level == "L2":
        m_all = m_all.filter(pl.col("idx_code").str.contains(";").not_())  # 组合码跳过
    m_all = pl.concat([_emp_pct_36m(g) for _, g in m_all.group_by("industry_code")])
    cur = m_all.filter(pl.col("report_month") == m_all["report_month"].max())

    # 2. 量价分解
    vp = pl.read_parquet(root / "customs_l2_volume_price_monthly.parquet")
    vp_lv = vp.filter(
        (pl.col("粒度") == level) & (pl.col("report_month") == cur["report_month"].max())
    )
    cur = cur.join(
        vp_lv.select(["code", "volume_yoy_3mma", "price_yoy_3mma", "驱动类型"]).rename(
            {"code": "idx_code"}
        ),
        on="idx_code",
        how="left",
    )

    # 3. 财报（后视验证列）
    if level == "L2":
        datasets = l2_financial_datasets or (
            "sw_2021_l2_fs_non_financial",
            "sw_2021_l2_fs_bank",
            "sw_2021_l2_fs_security",
            "sw_2021_l2_fs_insurance",
        )
        fin = pl.concat(
            [load_financial("lixinger", ds, storage_dir=storage_dir) for ds in datasets]
        )
    else:
        ds = l3_financial_dataset or "sw_2021_l3_fs_non_financial"
        fin = load_financial("lixinger", ds, storage_dir=storage_dir)
    cur = cur.join(fin, on="industry_code", how="left")

    # 4. 一致率分级（仅 L2）
    if level == "L2" and consistency_table:
        cons = pl.DataFrame(
            [
                {"idx_code": k, "consistency": v[0], "grade": v[1]}
                for k, v in consistency_table.items()
            ]
        )
        cur = cur.join(cons, on="idx_code", how="left")

    out_cols = [
        "industry_code",
        "industry_name",
        "idx_code",
        "report_month",
        "yoy_growth_3mma",
        "volume_yoy_3mma",
        "price_yoy_3mma",
        "驱动类型",
        "yoy_pct_36m",
        "revenue_y2y",
        "profit_y2y",
        "n_hs8",
    ]
    if level == "L2":
        out_cols += ["grade", "consistency"]
    out = cur.select(out_cols).sort("yoy_growth_3mma", descending=True)
    return out


def build_forward_watch(
    artifact_root: Path | str,
    *,
    levels: tuple[str, ...] = ("L2", "L3"),
    consistency_table: dict[str, tuple[float, str]] | None = None,
    l2_financial_datasets: tuple[str, ...] | None = None,
    l3_financial_dataset: str | None = None,
    storage_dir: Path | str = "data",
) -> dict[str, Path]:
    """构建 L2/L3 前瞻观察表并落盘。

    Returns:
        level -> 输出 parquet 路径（L2/L3）。
    """
    root = Path(artifact_root)
    root.mkdir(parents=True, exist_ok=True)
    outputs: dict[str, Path] = {}
    for lv in levels:
        df = build_level(
            lv,
            root,
            consistency_table=consistency_table,
            l2_financial_datasets=l2_financial_datasets,
            l3_financial_dataset=l3_financial_dataset,
            storage_dir=storage_dir,
        )
        fname = FORWARD_WATCH_L2_FILE if lv == "L2" else FORWARD_WATCH_L3_FILE
        dst = root / fname
        df.write_parquet(dst)
        outputs[lv] = dst
        logger.info("[%s] 观察表 %s 行 → %s", lv, df.height, dst)
    return outputs


__all__ = [
    "DEFAULT_OUTPUT_DIR",
    "build_forward_watch",
    "build_level",
    "load_dim",
    "load_financial",
]
