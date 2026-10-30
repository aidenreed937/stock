"""光伏景气前瞻仪表盘：前瞻评分与信号面板。

评分机制透明：每个读数 = (数值, 方向, 状态标签, 阈值/参考, 说明)。
- 价格分（周度最新，权重最高）：环节毛利空间方向 + 组件价格同比；
- 库存分（月度）：多晶硅库存去化/累库；
- 量分（月度）：国内装机环比/3MMA；
- 需求分（月度）：供需剪刀差同比 + 国内消化比。
综合前瞻状态是对四类读数的机制化摘要，不是已验证因子（对齐项目特征分层约定）。
"""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any

import polars as pl

from stock_analytics.pipelines.pv_outlook.config import PvOutlookConfig
from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

logger = logging.getLogger(__name__)


def _load_tail(runtime: DataRuntimeContext, dataset: str, n: int = 4) -> pl.DataFrame:
    """加载数据集并按报告期升序取尾部 n 行（用于环比/同比）。"""
    try:
        catalog = DataCatalog(data_source="industry", runtime=runtime)
        df = catalog.load_dataset(dataset)
        if df.is_empty():
            return pl.DataFrame()
        period_col = "report_month" if "report_month" in df.columns else "trade_date"
        return df.sort(period_col).tail(n)
    except Exception as exc:  # noqa: BLE001 - 数据缺口如实呈现
        logger.warning("评分数据源 %s 加载失败: %s", dataset, exc)
        return pl.DataFrame()


def _pct_change(latest: float | None, prev: float | None) -> float | None:
    if latest is None or prev is None or prev == 0:
        return None
    return (latest / prev - 1.0) * 100.0


def _direction(value: float | None, positive_is_up: bool = True) -> str:
    if value is None:
        return "NA"
    if abs(value) < 1e-9:
        return "持平"
    up = value > 0 if positive_is_up else value < 0
    return "改善" if up else "走弱"


def _price_readings(price_chain: pl.DataFrame, config: PvOutlookConfig) -> list[dict[str, Any]]:
    if price_chain.is_empty():
        return [
            {
                "维度": "价格链",
                "读数": "NA",
                "方向": "NA",
                "状态": "数据缺失",
                "说明": "本地周度价格链缺失",
            }
        ]
    lookback = config.scoring.spread_lookback_weeks
    latest = price_chain.tail(1)
    base = (
        price_chain.tail(lookback + 1).head(1)
        if len(price_chain) > lookback
        else price_chain.head(1)
    )
    readings: list[dict[str, Any]] = []

    def _row(col: str, label: str, note: str) -> None:
        cur = latest[col].to_list()[0]
        ref = base[col].to_list()[0]
        diff = (cur - ref) if cur is not None and ref is not None else None
        readings.append(
            {
                "环节": "价格链",
                "维度": label,
                "读数": f"{cur:.3f}" if isinstance(cur, float) else str(cur),
                "方向": _direction(diff),
                "状态": "改善" if (diff or 0) > 0 else ("走弱" if (diff or 0) < 0 else "持平"),
                "说明": note,
            }
        )

    _row("spread_module_cny_watt", "组件毛利空间(元/W)", f"较{lookback}周前方向")
    _row("spread_cell_cny_watt", "电池片毛利空间(元/W)", "电池片环节价差")
    _row("spread_wafer_cny_watt", "硅片毛利空间(元/W)", "简化口径，仅趋势参考")

    yoy = latest["module_price_yoy"].to_list()[0] if "module_price_yoy" in latest.columns else None
    if yoy is None or (isinstance(yoy, float) and math.isnan(yoy)):
        yoy = None
    yoy_flag = config.scoring.module_price_yoy_positive
    yoy_ok = yoy is not None and yoy > 0 and yoy_flag
    readings.append(
        {
            "环节": "价格链",
            "维度": "组件价格同比",
            "读数": f"{yoy * 100:.1f}%" if yoy is not None else "NA",
            "方向": "改善"
            if (yoy is not None and yoy > 0)
            else ("走弱" if yoy is not None else "NA"),
            "状态": "价格修复确认" if yoy_ok else "未确认",
            "说明": "同比转正=价格底确认信号",
        }
    )
    return readings


def _monthly_readings(runtime: DataRuntimeContext, config: PvOutlookConfig) -> list[dict[str, Any]]:
    readings: list[dict[str, Any]] = []

    cap = _load_tail(runtime, "solar_capacity")
    if cap.is_empty():
        readings.append(
            {
                "环节": "需求",
                "维度": "国内装机",
                "读数": "NA",
                "方向": "NA",
                "状态": "数据缺失",
                "说明": "能源局装机表缺失",
            }
        )
    else:
        val_col = next(
            (
                c
                for c in (
                    "monthly_new_capacity_gw",
                    "add_installed_gw",
                    "new_installed_gw",
                    "install_gw",
                    "output_current",
                )
                if c in cap.columns
            ),
            None,
        )
        if val_col is None:
            readings.append(
                {
                    "环节": "需求",
                    "维度": "国内装机",
                    "读数": "NA",
                    "方向": "NA",
                    "状态": "口径未知",
                    "说明": f"装机表无已知数值列: {cap.columns}",
                }
            )
        else:
            vals = cap[val_col].to_list()
            latest, prev = vals[-1], (vals[-2] if len(vals) >= 2 else None)
            mom = _pct_change(latest, prev)
            period = cap["report_month"].to_list()[-1]
            readings.append(
                {
                    "环节": "需求",
                    "维度": "国内月度装机",
                    "读数": f"{latest:g} GW ({period})",
                    "方向": _direction(mom),
                    "状态": "需求拐点信号" if (mom or 0) > 0 else "需求仍走弱",
                    "说明": "环比回升=首个需求右侧信号",
                }
            )

    inv = _load_tail(runtime, "polysilicon_inventory_monthly")
    if inv.is_empty():
        readings.append(
            {
                "环节": "库存",
                "维度": "多晶硅库存",
                "读数": "NA",
                "方向": "NA",
                "状态": "数据缺失",
                "说明": "库存表缺失",
            }
        )
    else:
        vals = inv["inventory_w_tons"].to_list()
        latest, prev = vals[-1], (vals[-2] if len(vals) >= 2 else None)
        delta = (latest - prev) if (latest is not None and prev is not None) else None
        threshold = config.scoring.inventory_rebuild_threshold_w_tons
        period = inv["report_month"].to_list()[-1]
        if delta is None:
            state = "数据不足"
        elif delta > threshold:
            state = "累库（超阈值）"
        elif delta < -threshold:
            state = "去库"
        else:
            state = "库存平稳"
        readings.append(
            {
                "环节": "库存",
                "维度": "多晶硅库存(万吨)",
                "读数": f"{latest:g} ({period})",
                "方向": "累库" if (delta or 0) > 0 else ("去库" if (delta or 0) < 0 else "持平"),
                "状态": state,
                "说明": f"单月环比阈值 {threshold:g} 万吨",
            }
        )

    sd = _load_tail(runtime, "solar_supply_demand")
    if sd.is_empty():
        readings.append(
            {
                "环节": "供需",
                "维度": "供需剪刀差",
                "读数": "NA",
                "方向": "NA",
                "状态": "数据缺失",
                "说明": "剪刀差表缺失",
            }
        )
    else:
        if "scissors_spread_yoy" in sd.columns:
            # 该列为小数比例（如 0.179 表示 +17.9%），展示时转为 pct
            latest = sd["scissors_spread_yoy"].to_list()[-1]
            prev = sd["scissors_spread_yoy"].to_list()[-2] if len(sd) >= 2 else None
            period = sd["report_month"].to_list()[-1]
            delta = (latest - prev) if (latest is not None and prev is not None) else None
            if delta is None:
                spread_dir = "NA"
            elif delta < 0:
                spread_dir = "过剩收窄"
            elif delta > 0:
                spread_dir = "过剩走阔"
            else:
                spread_dir = "持平"
            readings.append(
                {
                    "环节": "供需",
                    "维度": "剪刀差同比(pct)",
                    "读数": f"{latest * 100:+.0f}pct ({period})" if latest is not None else "NA",
                    "方向": spread_dir,
                    "状态": "仍过剩" if (latest or 0) > 0 else "需求修复",
                    "说明": ">0=供给增速仍快于需求（过剩）；较前月收窄为改善",
                }
            )
        if "domestic_absorption_ratio" in sd.columns:
            latest = sd["domestic_absorption_ratio"].to_list()[-1]
            readings.append(
                {
                    "环节": "供需",
                    "维度": "国内消化比(%)",
                    "读数": f"{latest * 100:.1f}%" if latest is not None else "NA",
                    "方向": _direction(latest, positive_is_up=True),
                    "状态": "改善" if (latest or 0) > 0 else "走弱",
                    "说明": "国内装机消化供给的比例",
                }
            )
    return readings


def build_outlook_snapshot(
    runtime: DataRuntimeContext,
    config: PvOutlookConfig,
    price_chain: pl.DataFrame,
    as_of: date,
) -> pl.DataFrame:
    """构建前瞻读数面板（price/volume/inventory/demand + 综合状态）。"""
    readings: list[dict[str, Any]] = []
    readings.extend(_price_readings(price_chain, config))
    readings.extend(_monthly_readings(runtime, config))

    # 综合前瞻状态：机制化摘要，依据价格链最新方向 + 库存/装机状态
    states = [r["状态"] for r in readings]
    positive_flags = sum(1 for s in states if s in ("改善", "价格修复确认", "去库", "需求拐点信号"))
    negative_flags = sum(
        1 for s in states if s in ("走弱", "累库（超阈值）", "需求仍走弱", "仍过剩")
    )
    if positive_flags >= 2 and negative_flags <= 1:
        stage = "边际改善（左侧后段）"
    elif positive_flags >= 2:
        stage = "边际改善与需求走弱并存"
    elif negative_flags >= 3:
        stage = "景气仍下行（底部待确认）"
    else:
        stage = "政策底已现、市场底待验证"
    readings.append(
        {
            "环节": "综合",
            "维度": "前瞻状态",
            "读数": f"{positive_flags}正/{negative_flags}负",
            "方向": "改善"
            if positive_flags > negative_flags
            else ("走弱" if negative_flags > positive_flags else "拉锯"),
            "状态": stage,
            "说明": "价格/库存/需求读数加总（机制化摘要，非验证因子）",
        }
    )
    df = pl.DataFrame(readings)
    return df.with_columns(pl.lit(as_of, dtype=pl.Date).alias("as_of_date"))
