"""产业趋势跟踪盘尾实时信号推演与 ETF 报单指令生成引擎（申万二级方向池）。

面向周期尺度全球产业趋势（AI 算力 / 新能源 / 电网 / 创新药 等）的实盘巡检：
1. 加载二级方向池基本面面板（industry_l2_panel_daily：动量/估值/量价齐升/方向分）；
2. 执行二级方向池策略（动量 Top3 + 估值防守，可选量价齐升门/方向防守门）；
3. 目标二级行业映射为场内 ETF（theme_etf_direction 主题 → 方向池 6 行业精确映射）；
4. 输出报单卡片（含方向层状态：全球共振候选池的方向分）。

数据源：
- 面板：`data/curated/mart/industry_l2_panel_daily.parquet`（阶段 1/3 产物）；
- 方向分：`data/curated/mart/global_resonance_l2_map.parquet`（理杏仁码）；
- 参考现价：从 fund_daily 最新收盘读取（非 mock）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl

from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_strategy.industry.live import IndustryLiveOrderInstruction
from stock_strategy.industry.report import load_all_industry_strategy_specs
from stock_strategy.pool import create_strategy

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_TREND_CONFIG = Path("config/strategy/industry_trend_tracking.yaml")
_L2_PANEL_MART = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_THEME_ETF_DIRECTION_MART = Path("data/curated/mart/theme_etf_direction.parquet")
_WATCHLIST_CONFIG = Path("config/universe/watchlist.yaml")
# L2 财务黄金表 2020Q1 起，巡检窗口对齐实证起点
_L2_AVAILABLE_FROM = date(2020, 5, 1)
# 全球共振方向池 6 个申万二级行业（理杏仁码）
_L2_DIRECTION_POOL = ("270100", "730200", "710100", "630500", "630700", "280500")


@dataclass(frozen=True)
class TrendLiveInspectionResult:
    """产业趋势跟踪盘尾巡检结果容器。"""

    strategy_key: str
    strategy_class: str
    as_of_time: datetime
    has_rebalance: bool
    latest_date: str
    candidate_direction: dict[str, float]  # 候选池行业 → 方向分
    etf_direction: dict[str, tuple[str, float]]  # ETF 池：etf_symbol → (theme, direction_score)
    instructions: list[IndustryLiveOrderInstruction]
    markdown_card: str


def load_l2_etf_map() -> dict[str, dict[str, str]]:
    """构建二级行业 → 场内 ETF 映射（方向池 6 行业）。

    以 theme_etf_direction.parquet 的最新 ETF→主题归属为准（该表由
    scripts/industry_direction_map.py 从 watchlist 的 sw_level2 标签生成），
    再用方向池行业名反查主题对应 ETF。
    """
    import yaml

    # 方向池行业名（theme_etf_direction 的 theme 口径）
    pool_names = {
        "270100": "半导体",
        "730200": "通信设备",
        "710100": "计算机设备",
        "630500": "光伏设备",
        "630700": "电池",
        "280500": "汽车",
    }
    # 读取 theme_etf_direction 最新归属：theme → etf_symbol（同一主题多 ETF 取最后写入者）
    if _THEME_ETF_DIRECTION_MART.exists():
        try:
            edf = pl.read_parquet(_THEME_ETF_DIRECTION_MART)
            theme_etf: dict[str, str] = {}
            for r in (
                edf.sort("trade_date")
                .group_by("theme")
                .agg(pl.col("etf_symbol").last().alias("etf"))
                .to_dicts()
            ):
                theme_etf[str(r["theme"])] = str(r["etf"])
        except Exception as exc:
            logger.warning(f"读取 theme_etf_direction 失败，回退 watchlist: {exc}")
            theme_etf = {}
    else:
        theme_etf = {}

    # 回退：watchlist 中 sw_level2 标签 → ETF（取第一个）
    if not theme_etf and _WATCHLIST_CONFIG.exists():
        try:
            cfg = yaml.safe_load(_WATCHLIST_CONFIG.read_text(encoding="utf-8"))
            for f in cfg["universe"]["a_shares"]["funds"]:
                if isinstance(f, dict) and f.get("sw_level2"):
                    theme_etf.setdefault(str(f["sw_level2"]), str(f["code"]))
        except Exception as exc:
            logger.warning(f"读取 watchlist 失败: {exc}")

    result: dict[str, dict[str, str]] = {}
    for code, name in pool_names.items():
        etf = theme_etf.get(name)
        if etf:
            result[code] = {"symbol": etf, "name": f"{name}ETF"}
    return result


def inspect_live_industry_trend_signal(
    *,
    strategy_key: str = "industry_l2_direction",
    config_path: Path | str = _TREND_CONFIG,
    etf_map_config: Path | str = "config/strategy/industry_rotation.yaml",
    factor_root: Path | str = "data/analytics/industry_trend",
    total_capital: float = 100_000.0,
    data_source: str = "tushare",
) -> TrendLiveInspectionResult:
    """执行产业趋势跟踪盘尾信号推演与 ETF 报单指令生成（申万二级方向池）。"""
    cfg_p = Path(config_path)
    specs = load_all_industry_strategy_specs(cfg_p)
    if strategy_key not in specs:
        raise ValueError(f"未找到产业趋势策略配置: {strategy_key}，可选: {list(specs.keys())}")

    spec = specs[strategy_key]
    cls_name = str(spec["strategy_class"])
    etf_map = load_l2_etf_map()

    # 1. 加载二级方向池基本面面板
    if not _L2_PANEL_MART.exists():
        raise RuntimeError(f"缺少二级行业基本面面板: {_L2_PANEL_MART}")
    panel = (
        pl.read_parquet(_L2_PANEL_MART)
        .filter(
            (pl.col("trade_date") >= _L2_AVAILABLE_FROM)
            & (pl.col("industry_code").is_in(_L2_DIRECTION_POOL))
        )
        .sort(["trade_date", "industry_code"])
    )
    if panel.is_empty():
        raise RuntimeError("二级行业基本面面板为空，无法推演信号")
    latest_date = panel["trade_date"].max()

    # 2. 实例化策略并推演
    kwargs = {
        k: v
        for k, v in spec.items()
        if k not in ("strategy_class", "friction", "description", "name")
    }
    strat = create_strategy(cls_name, **kwargs)
    strat.on_init()
    signals = strat.on_bar(panel)
    has_rebalance = len(signals) > 0

    # 3. 候选池方向层状态（每个全球共振行业最近可用方向分；中性 50 为数据缺口）
    latest_rows = panel.filter(pl.col("trade_date") == latest_date)
    ind_names: dict[str, str] = {}
    for r in latest_rows.select(["industry_code", "industry_name"]).to_dicts():
        ind_names[str(r["industry_code"])] = str(r.get("industry_name", r["industry_code"]))

    candidate_direction: dict[str, float] = {}
    for code in panel["industry_code"].unique().to_list():
        sub = (
            panel.filter(pl.col("industry_code") == code)
            .filter((pl.col("direction_score") - 50.0).abs() > 1e-6)
            .sort("trade_date")
        )
        if not sub.is_empty():
            candidate_direction[code] = round(float(sub["direction_score"][-1]), 1)

    # 3b. ETF 池方向状态（执行层参考：观察池方向层主题 ETF 的方向分）
    etf_direction: dict[str, tuple[str, float]] = {}
    if _THEME_ETF_DIRECTION_MART.exists():
        try:
            edf = pl.read_parquet(_THEME_ETF_DIRECTION_MART)
            for etf in edf["etf_symbol"].unique().to_list():
                sub = (
                    edf.filter(pl.col("etf_symbol") == etf)
                    .sort("trade_date")
                    .filter(pl.col("direction_score").is_not_null())
                )
                if not sub.is_empty():
                    last = sub.tail(1).row(0, named=True)
                    etf_direction[etf] = (
                        str(last["theme"]),
                        round(float(last["direction_score"]), 1),
                    )
        except Exception as exc:
            logger.warning(f"读取 ETF 池方向分失败: {exc}")

    # 4. 参考现价：ETF 最新收盘
    catalog = DataCatalog(data_source=data_source)
    etf_codes = sorted({v["symbol"] for v in etf_map.values() if isinstance(v, dict)})
    latest_prices: dict[str, float] = {}
    try:
        fund = catalog.load_dataset("fund_daily", symbols=etf_codes)
        if not fund.is_empty():
            for row in (
                fund.group_by("symbol").agg(pl.col("trade_date").max().alias("d")).to_dicts()
            ):
                sym = str(row["symbol"])
                price_rows = fund.filter(
                    (pl.col("symbol") == sym) & (pl.col("trade_date") == row["d"])
                )
                if not price_rows.is_empty():
                    latest_prices[sym] = float(price_rows["close"][0])
    except Exception as exc:
        logger.warning(f"读取 ETF 最新价格失败，使用占位价: {exc}")

    # 5. 生成报单指令
    instructions: list[IndustryLiveOrderInstruction] = []
    for sig in signals:
        code = sig.symbol
        ind_name = ind_names.get(code, code)
        etf_info = etf_map.get(code)
        t_weight = float(sig.target_weight or 0.0)
        t_amount = total_capital * t_weight

        if etf_info is not None:
            etf_code = etf_info["symbol"]
            etf_name = etf_info["name"]
            ref_price = latest_prices.get(etf_code, 1.0)
            lots = int(t_amount / (ref_price * 100)) if ref_price > 0 and t_amount > 0 else 0
        else:
            # 无对应场内 ETF：不生成可执行报单
            etf_code = "—"
            etf_name = "无对应场内ETF"
            ref_price = None
            lots = None

        instructions.append(
            IndustryLiveOrderInstruction(
                industry_code=code,
                industry_name=ind_name,
                etf_symbol=etf_code,
                etf_name=etf_name,
                direction="BUY" if t_weight > 0 else "CLOSE",
                target_weight=round(t_weight, 4),
                current_weight=0.0,
                delta_weight=round(t_weight, 4),
                latest_price=ref_price,
                target_amount=round(t_amount, 2),
                recommended_lots=lots,
                reason=sig.reason,
            )
        )

    now_time = datetime.now(_SHANGHAI_TZ)
    card_md = _render_trend_markdown_card(
        strategy_key=strategy_key,
        strategy_class=cls_name,
        as_of_time=now_time,
        latest_date=str(latest_date),
        has_rebalance=has_rebalance,
        candidate_direction=candidate_direction,
        etf_direction=etf_direction,
        instructions=instructions,
        total_capital=total_capital,
    )

    return TrendLiveInspectionResult(
        strategy_key=strategy_key,
        strategy_class=cls_name,
        as_of_time=now_time,
        has_rebalance=has_rebalance,
        latest_date=str(latest_date),
        candidate_direction=candidate_direction,
        etf_direction=etf_direction,
        instructions=instructions,
        markdown_card=card_md,
    )


def _render_trend_markdown_card(
    strategy_key: str,
    strategy_class: str,
    as_of_time: datetime,
    latest_date: str,
    has_rebalance: bool,
    candidate_direction: dict[str, float],
    etf_direction: dict[str, tuple[str, float]],
    instructions: list[IndustryLiveOrderInstruction],
    total_capital: float,
) -> str:
    """生成产业趋势跟踪盘尾实盘调仓指令卡片。"""
    time_str = as_of_time.strftime("%Y-%m-%d %H:%M:%S")
    status = "🚨 【触发调仓】" if has_rebalance else "🟢 【维持现状】"

    # 候选池方向层状态
    dir_rows = [
        f"| `{code}` | **{d:.1f}** |"
        for code, d in sorted(candidate_direction.items(), key=lambda x: -x[1])
    ]
    dir_table = (
        "| 全球共振候选行业 | 方向分 (0-100) |\n| :--- | :---: |\n" + "\n".join(dir_rows)
        if dir_rows
        else "候选池方向层数据缺失。"
    )

    # ETF 池方向状态（执行层参考）
    etf_rows = [
        f"| **{etf}** | {theme} | **{score:.1f}** |"
        for etf, (theme, score) in sorted(etf_direction.items(), key=lambda x: -x[1][1])
    ]
    etf_table = (
        "| ETF | 二级行业归属 | 方向分 (0-100) |\n| :--- | :--- | :---: |\n" + "\n".join(etf_rows)
        if etf_rows
        else "ETF 池方向分数据缺失。"
    )

    inst_rows = []
    for inst in instructions:
        lots_str = "—" if inst.recommended_lots is None else f"**{inst.recommended_lots} 手**"
        inst_rows.append(
            f"| `{inst.industry_code}` ({inst.industry_name}) | **{inst.etf_symbol}** ({inst.etf_name}) | **{inst.direction}** | {inst.target_weight * 100:.1f}% | ¥{inst.target_amount:,.0f} | {lots_str} | {inst.reason} |"
        )
    inst_table = (
        "| 申万二级行业 | 对应场内 ETF | 调仓方向 | 目标权重 | 目标金额 | 建议下单手数 | 调仓理由 |\n"
        "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |\n" + "\n".join(inst_rows)
        if inst_rows
        else "今日无调仓指令，保持当前产业配置。"
    )

    return f"""# 产业趋势跟踪 盘尾实盘巡检卡片（申万二级方向池）

> **巡检时间**: `{time_str}` | **因子基准日**: `{latest_date}` | **总资金规模**: `¥{total_capital:,.2f}`
> **策略标识**: `{strategy_key}` (`{strategy_class}`) | **调仓状态**: **{status}**

---

## 🌍 方向层状态（全球共振候选池）

{dir_table}

---

## 📊 ETF 池方向状态（执行层参考）

{etf_table}

---

## 🎯 今日目标配置与 ETF 报单指令

{inst_table}

---

💡 **执行提示**：产业趋势跟踪为季度尺度，调仓指令在季度确认日盘尾通过对应场内 ETF 申报；
注意规避 ETF 盘中大幅折溢价 (>0.3%)。方向层防守：全球方向高位 × 非量价齐升行业已被策略过滤。
"""


__all__ = [
    "TrendLiveInspectionResult",
    "inspect_live_industry_trend_signal",
    "load_l2_etf_map",
]
