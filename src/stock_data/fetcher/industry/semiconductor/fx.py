"""韩元与美元双轨汇率折算引擎 (IAS 21 / ASC 830 会计准则).

原则：
1. 资产负债表存货 (时点存量): 采用季度期末即期汇率 (Spot Rate).
2. 利润表营业成本 (期间发生额): 采用季度全交易日平均汇率 (Quarterly Average Rate).
3. 官方数据源: 美联储 FRED 官方日频 DEXKOUS (韩元兑美元正午即期电汇汇率).
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)


def quarter_to_date_range(report_quarter: str) -> tuple[date, date]:
    """将报告季度 (如 '2024Q1') 转换为起止自然日."""
    normalized = report_quarter.strip().upper()
    year = int(normalized[:4])
    quarter = int(normalized[-1])
    if quarter == 1:
        return date(year, 1, 1), date(year, 3, 31)
    if quarter == 2:
        return date(year, 4, 1), date(year, 6, 30)
    if quarter == 3:
        return date(year, 7, 1), date(year, 9, 30)
    if quarter == 4:
        return date(year, 10, 1), date(year, 12, 31)
    raise ValueError(f"无效的报告季度格式: {report_quarter}")


def get_krw_usd_rates(
    report_quarter: str,
    runtime: Any = None,
) -> tuple[float, float]:
    """获取指定报告季度的韩元兑美元 (KRW/USD) 即期期末汇率与季度日均汇率.

    严格遵守 Ground Truth First 原则：
    1. 期末即期汇率 (Spot Rate): trade_date <= q_end 的最新有效交易日 close
    2. 季度平均汇率 (Quarterly Average Rate): q_start <= trade_date <= q_end 的所有交易日 close 均值
    3. 唯一信源: 本地美联储 FRED 黄金表 (DataCatalog 消费 macro_indicators / DEXKOUS)
    严禁任何静态字典回退或硬编码常数兜底。若本地缺失对应时序，直接抛出 ValueError。

    Returns:
        (spot_rate_end, avg_rate_quarter)
    """
    normalized_q = report_quarter.strip().upper()
    q_start, q_end = quarter_to_date_range(normalized_q)

    # 从本地 FRED 黄金表加载官方 DEXKOUS 时序
    try:
        from stock_data.catalog import DataCatalog
        from stock_data.core.settings import data_settings

        active_runtime = runtime or data_settings.runtime_context
        cat = DataCatalog(data_source="fred", runtime=active_runtime)
        df_fred = cat.load_dataset("macro_indicators", symbols=["DEXKOUS"])
    except Exception as exc:
        raise ValueError(f"加载本地 FRED macro_indicators 黄金表失败: {exc}") from exc

    if df_fred.is_empty():
        raise ValueError(
            f"本地 FRED 黄金表中未找到 DEXKOUS 汇率数据集 (季度: {normalized_q})。"
            "请先执行 FRED 历史回填/增量同步 (make backfill SOURCE=fred ENDPOINT=macro_indicators SYMBOL=DEXKOUS)，"
            "严禁使用静态基准回退。"
        )

    df_kous = df_fred.filter(pl.col("symbol") == "DEXKOUS")
    if df_kous.is_empty():
        raise ValueError(
            f"本地 FRED 黄金表中未找到 symbol='DEXKOUS' 的记录 (季度: {normalized_q})。"
        )

    # 期末即期汇率: trade_date <= q_end 的最新有效交易日
    spot_df = (
        df_kous.filter(pl.col("trade_date") <= q_end)
        .sort("trade_date")
        .drop_nulls(subset=["close"])
    )
    # 季度均价: q_start <= trade_date <= q_end
    quarter_df = df_kous.filter(
        (pl.col("trade_date") >= q_start) & (pl.col("trade_date") <= q_end)
    ).drop_nulls(subset=["close"])

    if spot_df.is_empty():
        raise ValueError(
            f"本地 FRED DEXKOUS 缺失 <= {q_end} 的期末即期汇率记录 (季度: {normalized_q})。"
        )
    if quarter_df.is_empty():
        raise ValueError(
            f"本地 FRED DEXKOUS 缺失 {q_start} ~ {q_end} 区间的季度交易日汇率记录 (季度: {normalized_q})。"
        )

    raw_spot = spot_df["close"][-1]
    raw_avg = quarter_df["close"].mean()

    if raw_spot is None or raw_avg is None:
        raise ValueError(
            f"本地 FRED DEXKOUS 计算汇率值为空: spot={raw_spot!r}, avg={raw_avg!r} (季度: {normalized_q})。"
        )

    spot_num = float(str(raw_spot))
    avg_num = float(str(raw_avg))
    if spot_num <= 0 or avg_num <= 0:
        raise ValueError(
            f"本地 FRED DEXKOUS 汇率非正数值异常: spot={spot_num}, avg={avg_num} (季度: {normalized_q})。"
        )

    return round(spot_num, 4), round(avg_num, 4)


def convert_krw_to_usd_million(
    inventory_krw: float,
    cost_of_revenue_krw: float,
    report_quarter: str,
    unit: str = "trillion_krw",
    runtime: Any = None,
) -> tuple[float, float]:
    """严格按 IAS 21 / ASC 830 双轨折算韩元数据为百万美元.

    - 存货 (Balance Sheet): 按季度末即期汇率折算
    - 营业成本 (Income Statement): 按季度平均汇率折算

    Returns:
        (inventory_usd_million, cost_of_revenue_usd_million)
    """
    spot_rate, avg_rate = get_krw_usd_rates(report_quarter, runtime=runtime)
    if spot_rate <= 0 or avg_rate <= 0:
        raise ValueError(f"汇率异常: spot={spot_rate}, avg={avg_rate}")

    normalized_unit = unit.strip().lower()
    if normalized_unit in ("trillion_krw", "trillion"):
        scale = 1_000_000.0
    elif normalized_unit in ("billion_krw", "billion"):
        scale = 1_000.0
    elif normalized_unit in ("krw", "won"):
        scale = 0.000001
    else:
        raise ValueError(f"未知的韩元单位: {unit}")

    inv_usd_million = round((inventory_krw * scale) / spot_rate, 2)
    cogs_usd_million = round((cost_of_revenue_krw * scale) / avg_rate, 2)
    return inv_usd_million, cogs_usd_million


def derive_fx_normalized_amounts(
    df: pl.DataFrame,
    runtime: Any = None,
) -> tuple[pl.Series, pl.Series]:
    """根据各行的 unit 与 report_quarter 计算标准化为 million_usd 的存货与营业成本."""
    quarters = df["report_quarter"].to_list()
    units = df["unit"].to_list() if "unit" in df.columns else ["million_usd"] * len(df)
    inv_raws = df["inventory_usd_raw"].to_list()
    cogs_raws = df["cost_of_revenue_usd_raw"].to_list()

    inv_usd_list: list[float] = []
    cogs_usd_list: list[float] = []

    for q, u, inv_str, cogs_str in zip(quarters, units, inv_raws, cogs_raws, strict=False):
        inv_val = float(str(inv_str).replace(",", "").replace("$", ""))
        cogs_val = float(str(cogs_str).replace(",", "").replace("$", ""))
        u_clean = str(u or "").strip().lower()

        if "krw" in u_clean or "won" in u_clean:
            inv_m, cogs_m = convert_krw_to_usd_million(
                inv_val, cogs_val, str(q), unit=u_clean, runtime=runtime
            )
        elif u_clean == "usd":
            inv_m = round(inv_val / 1_000_000.0, 2)
            cogs_m = round(cogs_val / 1_000_000.0, 2)
        else:  # million_usd 或默认
            inv_m = round(inv_val, 2)
            cogs_m = round(cogs_val, 2)
        inv_usd_list.append(inv_m)
        cogs_usd_list.append(cogs_m)

    return (
        pl.Series("inventory_usd_million", inv_usd_list, dtype=pl.Float64),
        pl.Series("cost_of_revenue_usd_million", cogs_usd_list, dtype=pl.Float64),
    )
