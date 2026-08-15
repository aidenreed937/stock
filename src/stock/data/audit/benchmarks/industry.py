"""中观行业日频事实基准提供者 (申万 2021 一级 31 / 二级 134 行业基准)。"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

from stock.data.audit.benchmarks.base import BenchmarkProvider, get_trading_calendar

if TYPE_CHECKING:
    from stock.data.catalog import DataCatalog


# 申万 2021 官方一级 31 行业标准代码集合 (TuShare 口径兜底)
SW_L1_INDUSTRY_CODES: list[str] = [
    "801010.SI", "801030.SI", "801040.SI", "801050.SI", "801080.SI",
    "801110.SI", "801120.SI", "801130.SI", "801140.SI", "801150.SI",
    "801160.SI", "801170.SI", "801180.SI", "801200.SI", "801210.SI",
    "801230.SI", "801710.SI", "801720.SI", "801730.SI", "801740.SI",
    "801750.SI", "801760.SI", "801770.SI", "801780.SI", "801790.SI",
    "801880.SI", "801890.SI", "801950.SI", "801960.SI", "801970.SI",
    "801980.SI",
]

# 理杏仁 2021 申万一级行业代码集合 (理杏仁 6 位代码口径兜底，后 4 位为 0000)
LIXINGER_SW_L1_CODES: list[str] = [
    "110000", "210000", "220000", "230000", "240000", "270000", "280000",
    "330000", "340000", "350000", "360000", "370000", "410000", "420000",
    "430000", "450000", "460000", "480000", "490000", "510000", "610000",
    "620000", "630000", "640000", "650000", "710000", "720000", "730000",
    "740000", "750000", "760000", "770000",
]


class IndustryDailyBenchmarkProvider(BenchmarkProvider):
    """申万行业日频事实基准提供者 (支持 TuShare / LiXinger 多源动态元数据提取)。

    预期集合公式: Expected(t) = TradingCalendar(t) × L1_Industry_Codes
    """

    def __init__(
        self,
        catalog: DataCatalog | None = None,
        level: str = "L1",
        data_source: str | None = None,
    ) -> None:
        self.level = level.upper()
        if catalog is None:
            from stock.data.catalog import DataCatalog

            self.data_source = data_source or "tushare"
            self.catalog = DataCatalog(data_source=self.data_source)
        else:
            self.catalog = catalog
            self.data_source = data_source or catalog.data_source

    def _get_industry_codes(self) -> list[str]:
        """动态从落盘元数据表提取行业代码全集，若表未落盘则安全回退至官方代码常量。"""
        if self.data_source == "lixinger":
            try:
                # 优先从理杏仁成分股图谱元数据中提取一级行业 (后四位为 0000 且属于可交付代码)
                df_const = self.catalog.load_dataset("sw_2021_constituents")
                if not df_const.is_empty() and "symbol" in df_const.columns:
                    l1_symbols = (
                        df_const.filter(pl.col("symbol").cast(pl.Utf8).str.ends_with("0000"))[
                            "symbol"
                        ]
                        .unique()
                        .to_list()
                    )
                    valid_symbols = [
                        str(s) for s in l1_symbols if str(s) in LIXINGER_SW_L1_CODES
                    ]
                    if valid_symbols:
                        return sorted(valid_symbols)
            except Exception:
                pass
            return LIXINGER_SW_L1_CODES

        # 默认 TuShare 申万行业
        try:
            df_idx = self.catalog.load_dataset("index_basic")
            if not df_idx.is_empty() and "symbol" in df_idx.columns and "market" in df_idx.columns:
                sw_symbols = (
                    df_idx.filter(
                        (pl.col("market") == "SW") & pl.col("symbol").cast(pl.Utf8).str.starts_with("801")
                    )["symbol"]
                    .unique()
                    .to_list()
                )
                if sw_symbols:
                    return sorted([str(s) for s in sw_symbols if s in SW_L1_INDUSTRY_CODES])
        except Exception:
            pass
        return SW_L1_INDUSTRY_CODES

    def get_expected_keys(self, start_date: date, end_date: date) -> pl.DataFrame:
        """根据交易日历与行业代码全集生成预期主键全集。"""
        trading_dates = get_trading_calendar(start_date=start_date, end_date=end_date)
        if not trading_dates:
            return pl.DataFrame(
                {
                    "symbol": pl.Series([], dtype=pl.Utf8),
                    "trade_date": pl.Series([], dtype=pl.Utf8),
                }
            )

        dates_str = [d.strftime("%Y%m%d") for d in trading_dates]
        codes = self._get_industry_codes()

        codes_df = pl.DataFrame({"symbol": codes})
        dates_df = pl.DataFrame({"trade_date": dates_str})

        return codes_df.join(dates_df, how="cross").select(["symbol", "trade_date"])
