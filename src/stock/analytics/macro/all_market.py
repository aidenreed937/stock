"""全 A 股整体资产水位分析器 (以中证全指 000985 等权 PB 为核心标尺)。

核心量化原理:
    1. 中证全指 (000985) 覆盖全 A 股 93%+ 的总市值与绝大多数股票，是衡量全市场最权威的基准；
    2. 全 A 整体 PE (等权 113 倍) 易受微利/亏损小票的分母塌陷扭曲，不宜作宏观择时标尺；
    3. 全 A 等权 PB (市净率) 锚定企业净资产重置成本，抗亏损噪音强，是衡量资产水位的黄金标尺。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Final

import polars as pl

from stock.analytics.models import AllMarketValuationResult, ValuationZone
from stock.data.catalog import DataCatalog

# 指数符号标准化映射 (支持理杏仁 6 位代码与 TuShare/交易所标准后缀)
_INDEX_SYMBOL_MAP: Final[dict[str, str]] = {
    "000985": "000985",
    "000985.SH": "000985",
    "000985.CSI": "000985",
    "000001": "000001",
    "000001.SH": "000001",
    "000300": "000300",
    "000300.SH": "000300",
}


def _evaluate_pb_zone(pb_pctl: float) -> tuple[ValuationZone, str]:
    """根据全 A 等权 PB 的 10 年历史分位数判定资产水位区间。"""
    if pb_pctl >= 85.0:
        return ValuationZone.EXTREME_HIGH, "全 A 资产水位处于近 10 年极高水位区 (估值偏贵)"
    if pb_pctl >= 70.0:
        return ValuationZone.HIGH, "全 A 资产水位处于近 10 年中高分位 (具备一定溢价)"
    if pb_pctl >= 30.0:
        return ValuationZone.FAIR, "全 A 资产水位处于近 10 年常态合理中枢"
    if pb_pctl >= 15.0:
        return ValuationZone.LOW, "全 A 资产水位处于近 10 年偏低分位 (具备较好安全边际)"
    return ValuationZone.EXTREME_LOW, "全 A 资产水位处于近 10 年极度低估洼地 (大级别资产折价)"


def _resolve_index_name(std_symbol: str) -> str:
    """获取标准指数中文名称。"""
    if std_symbol == "000985":
        return "中证全指"
    if std_symbol == "000001":
        return "上证指数"
    return std_symbol


class AllMarketValuationAnalyzer:
    """全 A 股市场资产水位分析器。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分析器。"""
        self.catalog = catalog or DataCatalog(data_source="lixinger")

    def calculate_latest(
        self,
        symbol: str = "000985",
        target_date: date | None = None,
        fundamental_df: pl.DataFrame | None = None,
    ) -> AllMarketValuationResult | None:
        """计算指定交易日全 A 指数 (默认中证全指 000985) 的等权 PB、PE 及 10 年分位数。"""
        std_symbol = _INDEX_SYMBOL_MAP.get(symbol.strip(), symbol.split(".")[0])
        idx_name = _resolve_index_name(std_symbol)

        raw_df = (
            self.catalog.load_dataset("index_fundamental")
            if fundamental_df is None
            else fundamental_df
        )
        if raw_df.is_empty():
            return None

        filtered = raw_df.filter(pl.col("symbol") == std_symbol)
        if target_date is not None:
            filtered = filtered.filter(pl.col("trade_date") <= target_date)

        if filtered.is_empty() or "pb.ew" not in filtered.columns:
            return None

        sorted_df = filtered.sort("trade_date")
        latest_row = sorted_df[-1]
        eval_date = latest_row["trade_date"][0]
        curr_pb = float(latest_row["pb.ew"][0])
        curr_pe = float(latest_row["pe_ttm.ew"][0]) if "pe_ttm.ew" in latest_row.columns else 0.0

        start_10y = eval_date - timedelta(days=3652)
        window_10y = sorted_df.filter(pl.col("trade_date") >= start_10y)

        total_days = len(window_10y)
        if total_days == 0:
            return None

        pb_pctl = (window_10y.filter(pl.col("pb.ew") <= curr_pb).height / total_days) * 100.0
        pe_pctl = (
            (window_10y.filter(pl.col("pe_ttm.ew") <= curr_pe).height / total_days) * 100.0
            if "pe_ttm.ew" in window_10y.columns and curr_pe > 0
            else 50.0
        )

        zone, zone_desc = _evaluate_pb_zone(pb_pctl)

        return AllMarketValuationResult(
            trade_date=eval_date,
            symbol=std_symbol,
            index_name=idx_name,
            pb_ew=round(curr_pb, 3),
            pb_percentile_10y=round(pb_pctl, 1),
            pe_ttm_ew=round(curr_pe, 2),
            pe_percentile_10y=round(pe_pctl, 1),
            zone=zone,
            zone_desc=zone_desc,
        )
