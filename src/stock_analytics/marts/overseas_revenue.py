"""公司海外营收布局 Mart：海外营收 / 占比 / 毛利率，point-in-time 无前视。

目的：持续跟踪 A 股公司的海外布局，用核心指标 + 对照组看发展前景：
  - overseas_revenue        海外营收（亿元，累计口径）
  - overseas_ratio          占总营收比例（= 海外营收 / 营业总收入）
  - overseas_revenue_yoy    海外营收同比（累计同比）
  - total_revenue_yoy       总营收同比（对照组，区分"出海加速"与"水涨船高"）
  - overseas_ratio_chg      占比同比变化（pp，直接看"海外占比是否在提升"）
  - overseas_gross_margin   海外毛利率（= 海外主营利润 bz_profit / 海外营收）
  - gross_margin            公司整体毛利率（fina_indicator，百分数 ÷100 转小数）
  - netprofit_margin        公司整体净利率（fina_indicator，百分数 ÷100 转小数）

海外净利率不可得：分地区数据只披露主营利润（bz_profit），无费用分摊，算不出
净利润，故 Mart 只给海外毛利率 + 公司整体净利率（作参考），不列海外净利率。

数据源与口径：
  - 总营收：income 表 ``total_revenue``（营业总收入累计值），全 A 股覆盖。
  - 海外营收：fina_mainbz ``type=D``（地域构成）海外地域 ``bz_sales`` 合计（累计）。
    海外识别用关键词 + 披露质量门（地域披露颗粒度参差，不能把"没披露"当"没海外"）。
  - 无前视：income 有 ``ann_date``（公告日），fina_mainbz 通过 (symbol, end_date)
    关联取 ann_date；观察月只能用 ann_date <= 当月的财报，绝不使用未来财报。
  - 同比：累计同比 = 本期累计 / 去年同期同报告期累计 - 1（report_type 均合并报表口径）。

披露质量门（disclosure 列）：
  - ok:            有海外项 + 国内项，海外营收可信
  - domestic_only: 只披露国内地域、无海外项（可能真内销，也可能未拆海外，低置信）
  - overseas_only: 只披露海外项（分母可能不全，低置信）
  - undisclosed:   只有兜底项（地区/合计/其他），无法判断
  - no_data:       该期无 type=D 地域披露（海外营收置空）

单位：金额列均为亿元（raw 元 / 1e8）；比例、同比与毛利率均为小数（0.3 = 30%）。

产品与 H8 的动态映射由 ``customs_company_h8`` 链路单独构建；本 Mart 只保存公司级海外营收事实。
"""

from __future__ import annotations

import glob
from pathlib import Path

import polars as pl

MART_NAME = "overseas_revenue"
OVERSEAS_REVENUE_MART_NAME = MART_NAME
PANEL_FILE = "overseas_revenue.parquet"
LATEST_FILE = "overseas_revenue_latest.csv"

DEFAULT_INCOME_DIR = Path("data/curated/tushare/market=CN/income")
DEFAULT_MAINBZ_DIR = Path("data/curated/tushare/market=CN/fina_mainbz")
DEFAULT_INDICATOR_DIR = Path("data/curated/tushare/market=CN/fina_indicator")

# 海外/出口地域项关键词（type=D bz_item，按字面命中；"台湾/香港/澳门"视为境外；
# "国家和地区"用于覆盖"其他国家和地区"这类境外披露表述）
OVERSEAS_KEYS = (
    "国外",
    "境外",
    "海外",
    "港澳台",
    "出口",
    "外销",
    "欧洲",
    "北美",
    "美洲",
    "南美",
    "非洲",
    "亚洲",
    "大洋",
    "中东",
    "亚太",
    "国际",
    "台湾",
    "香港",
    "澳门",
    "国家和地区",
)
# 含"外/境/出口"字样但实为国内跨区域，海外判定前先排除；
# "包括/含/除/不含港澳台"用于把"中国(包括/除港澳台地区)"这类"中国大陆±港澳台"合并披露判为国内
DOMESTIC_PSEUDO = (
    "省外",
    "疆外",
    "省内",
    "中国大陆",
    "大陆",
    "境内",
    "国内",
    "新疆以外",
    "包括港澳台",
    "含港澳台",
    "除港澳台",
    "不含港澳台",
)
# type=D 地域兜底项（无地域信息，剔除；精确匹配，避免误伤"其他国外/其他境外"）
REGION_GENERIC_ITEMS = {
    "地区",
    "合计",
    "分部",
    "抵销",
    "主营业务",
    "抵消",
    "其他",
    "其他(地区)",
    "其他地区",
    "其他业务",
    "其他业务(地区)",
    "其他收入",
    "内部抵销",
    "分部抵消",
    "全部地区",
}


def classify_item(item: str) -> str:
    """type=D 地域项分类：overseas / domestic / generic。"""
    if item in REGION_GENERIC_ITEMS or "其他业务" in item:
        return "generic"
    if any(k in item for k in DOMESTIC_PSEUDO):
        return "domestic"
    if any(k in item for k in OVERSEAS_KEYS):
        return "overseas"
    return "domestic"


def _load_income(income_dir: Path) -> pl.DataFrame:
    """Income 表 → 每 (symbol, end_date) 的营业总收入（亿元）与公告日。"""
    frames = []
    for f in sorted(glob.glob(str(income_dir / "**/*.parquet"), recursive=True)):
        try:
            frames.append(
                pl.read_parquet(f).select(
                    ["symbol", "end_date", "ann_date", "total_revenue", "revenue"]
                )
            )
        except Exception:
            continue
    inc = pl.concat(frames).unique()
    return inc.with_columns(
        pl.col("total_revenue").fill_null(0.0) / 1e8,
        pl.col("revenue").fill_null(0.0) / 1e8,
    )


def _load_indicator(indicator_dir: Path) -> pl.DataFrame:
    """fina_indicator → 每 (symbol, end_date) 整体毛利率/净利率（百分数 ÷100 转小数）。"""
    frames = []
    for f in sorted(glob.glob(str(indicator_dir / "**/*.parquet"), recursive=True)):
        try:
            frames.append(
                pl.read_parquet(f).select(
                    ["symbol", "end_date", "grossprofit_margin", "netprofit_margin"]
                )
            )
        except Exception:
            continue
    fi = pl.concat(frames).unique()
    return fi.with_columns(
        (pl.col("grossprofit_margin") / 100.0).alias("gross_margin"),
        (pl.col("netprofit_margin") / 100.0).alias("netprofit_margin"),
    ).select(["symbol", "end_date", "gross_margin", "netprofit_margin"])


def _load_region(region_dir: Path) -> pl.DataFrame:
    """fina_mainbz type=D → 每 (symbol, end_date) 海外/国内营收（亿元）+ 披露质量。"""
    frames = []
    for f in sorted(glob.glob(str(region_dir / "**/*.parquet"), recursive=True)):
        try:
            frames.append(
                pl.read_parquet(f).select(
                    ["symbol", "end_date", "bz_code", "bz_item", "bz_sales", "bz_profit"]
                )
            )
        except Exception:
            continue
    d = pl.concat(frames).unique().filter(pl.col("bz_code") == "D")
    d = d.with_columns(
        pl.col("bz_sales").fill_null(0.0) / 1e8,
        # 利润缺失保持 null（不 fill 0），聚合后全 null 时海外毛利率为 null 而非误报 0
        (pl.col("bz_profit") / 1e8).alias("bz_profit"),
        pl.col("bz_item").map_elements(classify_item, return_dtype=pl.String).alias("cat"),
    )
    # 同值去重（"境外"与"国外"、"中国大陆"与"境内"等重复披露，复刻 calibrate type=P 口径）
    d = d.unique(subset=["symbol", "end_date", "bz_sales"], keep="first")
    d = d.with_columns(
        (pl.col("cat") == "overseas").cast(pl.Float64).alias("is_ov"),
        (pl.col("cat") == "domestic").cast(pl.Float64).alias("is_dom"),
    )
    agg = d.group_by(["symbol", "end_date"]).agg(
        (pl.col("bz_sales") * pl.col("is_ov")).sum().alias("overseas_revenue"),
        (pl.col("bz_sales") * pl.col("is_dom")).sum().alias("domestic_revenue"),
        (pl.col("bz_profit") * pl.col("is_ov")).sum().alias("overseas_profit"),
    )
    total = pl.col("overseas_revenue") + pl.col("domestic_revenue")
    return agg.with_columns(
        pl.when(total == 0)
        .then(pl.lit("undisclosed"))
        .when((pl.col("overseas_revenue") > 0) & (pl.col("domestic_revenue") > 0))
        .then(pl.lit("ok"))
        .when(pl.col("overseas_revenue") == 0)
        .then(pl.lit("domestic_only"))
        .otherwise(pl.lit("overseas_only"))
        .alias("disclosure")
    ).drop("domestic_revenue")


def build_overseas_revenue_mart(
    *,
    income_dir: Path | str | None = None,
    mainbz_dir: Path | str | None = None,
    indicator_dir: Path | str | None = None,
    data_root: Path | str = "data",
) -> pl.DataFrame:
    """构建海外营收布局 Mart（symbol × end_date 全 A 股，point-in-time 无前视）。

    Args:
        income_dir: income 表目录（缺省按 data_root 推导）。
        mainbz_dir: fina_mainbz 目录（缺省按 data_root 推导）。
        indicator_dir: fina_indicator 目录（缺省按 data_root 推导）。
        data_root: 数据根目录（默认 data）。

    Returns:
        按 symbol、end_date 排序的 Mart DataFrame。
    """
    root = Path(data_root)
    income = (
        Path(income_dir) if income_dir else root / "curated" / "tushare" / "market=CN" / "income"
    )
    mainbz = (
        Path(mainbz_dir)
        if mainbz_dir
        else root / "curated" / "tushare" / "market=CN" / "fina_mainbz"
    )
    indicator = (
        Path(indicator_dir)
        if indicator_dir
        else root / "curated" / "tushare" / "market=CN" / "fina_indicator"
    )
    inc = _load_income(income)
    region = _load_region(mainbz)
    ind = _load_indicator(indicator)

    base = (
        inc.join(region, on=["symbol", "end_date"], how="left")
        .join(ind, on=["symbol", "end_date"], how="left")
        .with_columns(pl.col("disclosure").fill_null("no_data"))
    )
    base = base.with_columns(
        (pl.col("overseas_revenue") / pl.col("total_revenue")).alias("overseas_ratio"),
        pl.when((pl.col("overseas_revenue") > 0) & pl.col("overseas_profit").is_not_null())
        .then(pl.col("overseas_profit") / pl.col("overseas_revenue"))
        .otherwise(None)
        .alias("overseas_gross_margin"),
    )

    # 去年同期（同报告期累计）self-join，算同比与占比同比变化
    base = base.with_columns(pl.col("end_date").dt.offset_by("-1y").alias("prev_end_date"))
    prev = base.select(
        ["symbol", "end_date", "overseas_revenue", "total_revenue", "overseas_ratio"]
    ).rename(
        {
            "overseas_revenue": "overseas_revenue_prev",
            "total_revenue": "total_revenue_prev",
            "overseas_ratio": "overseas_ratio_prev",
        }
    )
    joined = base.join(
        prev,
        left_on=["symbol", "prev_end_date"],
        right_on=["symbol", "end_date"],
        how="left",
    ).with_columns(
        pl.when(pl.col("overseas_revenue_prev") > 0)
        .then(pl.col("overseas_revenue") / pl.col("overseas_revenue_prev") - 1)
        .otherwise(None)
        .alias("overseas_revenue_yoy"),
        pl.when(pl.col("total_revenue_prev") > 0)
        .then(pl.col("total_revenue") / pl.col("total_revenue_prev") - 1)
        .otherwise(None)
        .alias("total_revenue_yoy"),
        (pl.col("overseas_ratio") - pl.col("overseas_ratio_prev")).alias("overseas_ratio_chg"),
    )

    mart = joined.select(
        [
            "symbol",
            "end_date",
            "ann_date",
            "total_revenue",
            "overseas_revenue",
            "overseas_ratio",
            "overseas_revenue_yoy",
            "total_revenue_yoy",
            "overseas_ratio_chg",
            "overseas_gross_margin",
            "gross_margin",
            "netprofit_margin",
            "disclosure",
        ]
    )
    return mart.sort(["symbol", "end_date"])


def save_overseas_revenue_mart(mart: pl.DataFrame, output_dir: Path | str) -> tuple[Path, Path]:
    """落盘全序列 parquet + 最新报告期快照 CSV。"""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    pq = root / PANEL_FILE
    csv_path = root / LATEST_FILE
    mart.write_parquet(pq)

    latest_end = mart["end_date"].max()
    snap = mart.filter(pl.col("end_date") == latest_end).sort(
        ["overseas_revenue"], descending=True, nulls_last=True
    )
    snap.write_csv(csv_path, include_header=True)
    return pq, csv_path


__all__ = [
    "LATEST_FILE",
    "MART_NAME",
    "OVERSEAS_REVENUE_MART_NAME",
    "PANEL_FILE",
    "build_overseas_revenue_mart",
    "classify_item",
    "save_overseas_revenue_mart",
]
