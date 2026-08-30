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
# 全球共振方向池 13 个申万二级行业（理杏仁码）
_L2_DIRECTION_POOL = (
    "270100",  # 半导体
    "730200",  # 通信设备
    "710100",  # 计算机设备
    "630500",  # 光伏设备
    "630700",  # 电池
    "630800",  # 电网设备
    "280500",  # 乘用车(汽车)
    "240300",  # 工业金属
    "240400",  # 贵金属
    "370100",  # 化学制药
    "370300",  # 生物制品
    "640600",  # 工程机械
    "421100",  # 航运港口
)

# 申万二级行业标准 1:1 ETF 映射基准与代理属性定义: (symbol, name, match_type, note)
_CANONICAL_L2_ETF_MAP: dict[str, tuple[str, str, str, str]] = {
    "270100": ("512480.SH", "半导体ETF", "pure_l2", "申万二级半导体纯正对标"),
    "730200": ("515880.SH", "通信ETF", "pure_l2", "申万二级通信设备纯正对标"),
    "630500": ("515790.SH", "光伏ETF", "pure_l2", "申万二级光伏设备纯正对标"),
    "630700": ("159755.SZ", "电池ETF", "pure_l2", "申万二级电池纯正对标"),
    "630800": ("159326.SZ", "电网设备ETF", "pure_l2", "申万二级电网设备纯正对标"),
    "240400": (
        "159562.SZ",
        "黄金股ETF",
        "pure_l2",
        "申万二级贵金属股票纯正对标 (亦可选用 518880.SH 黄金ETF)",
    ),
    "370300": ("512290.SH", "生物医药ETF", "pure_l2", "申万二级生物制品/疫苗纯正对标"),
    "370100": ("159992.SZ", "创新药ETF", "pure_l2", "申万二级化学制药/创新药出海对标"),
    "240300": (
        "512400.SH",
        "有色金属ETF",
        "proxy_l1",
        "申万一级有色金属全指代理 (含工业金属与稀土)",
    ),
    "710100": (
        "512720.SH",
        "计算机ETF",
        "proxy_l1",
        "申万一级计算机全指代理 (混合硬件整机与软件IT服务)",
    ),
    "280500": (
        "516110.SH",
        "汽车ETF",
        "proxy_l1",
        "申万一级汽车全指代理 (混合整车制造与汽车零部件)",
    ),
    "640600": (
        "560280.SH",
        "工程机械主题ETF",
        "pure_l2",
        "申万二级工程机械纯正对标 (三一/徐工/中联/恒立)",
    ),
    "421100": (
        "159666.SZ",
        "交通运输ETF",
        "proxy_l1",
        "申万一级交通运输全指代理 (含铁路航空物流，非纯航运港口)",
    ),
}


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
    """构建二级行业 → 场内 ETF 映射（方向池 13 行业）。

    以 _CANONICAL_L2_ETF_MAP 为权威基准：
    - 对具备纯正场内 ETF 的二级行业（半导体、通信设备、光伏设备、电池、电网设备、贵金属、生物制品、化学制药）
      实现精确 1:1 对标；
    - 对尚无纯二级 ETF 的行业（工业金属、计算机设备、乘用车、工程机械、航运港口）
      采用对应所属申万一级行业全指 ETF 进行代理，并显式标注代理属性及跟踪偏差说明。
    """
    return {
        code: {"symbol": sym, "name": name, "match_type": m_type, "note": note}
        for code, (sym, name, m_type, note) in _CANONICAL_L2_ETF_MAP.items()
    }


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
    # 宏观恐慌指数（组合防守门 panic_scale 消费；缺失回退中性 50）
    rf_path = Path("data/analytics/macro_risk/latest/risk_factors.parquet")
    if rf_path.exists():
        panel = panel.join(
            pl.read_parquet(rf_path).select(["trade_date", "panic_index"]),
            on="trade_date",
            how="left",
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
            match_type = etf_info.get("match_type", "pure_l2")
            match_badge = "🎯 纯二级对标" if match_type == "pure_l2" else "⚠️ L1泛行业代理"
            etf_name = f"{etf_info['name']} [{match_badge}]"
            ref_price = latest_prices.get(etf_code, 1.0)
            lots = int(t_amount / (ref_price * 100)) if ref_price > 0 and t_amount > 0 else 0
            reason_str = f"{sig.reason} | {etf_info.get('note', '')}"
        else:
            etf_code = "—"
            etf_name = "无对应场内ETF"
            ref_price = None
            lots = None
            reason_str = sig.reason

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
                reason=reason_str,
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
        "| 申万二级行业 | 对应场内 ETF | 调仓方向 | 目标权重 | 目标金额 | 建议下单手数 | 调仓理由与跟踪说明 |\n"
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

💡 **执行与标的对标提示**：
1. **🎯 纯二级对标**：标的 ETF 与所选二级行业成份高度吻合（如半导体、通信设备、光伏设备、电池、电网设备、生物医药、创新药、黄金股等）；
2. **⚠️ L1泛行业代理**：A股暂无纯正二级 ETF，采用所属申万一级行业全指 ETF 替代执行（如交通运输替代航运港口、机械设备替代工程机械、汽车替代乘用车、计算机替代计算机设备），实际持仓存在成分稀释与跟踪偏差；
3. **申报规范**：产业趋势跟踪为季度尺度，调仓指令在季度确认日盘尾通过对应场内 ETF 申报；注意规避 ETF 盘中大幅折溢价 (>0.3%)。
"""


__all__ = [
    "TrendLiveInspectionResult",
    "inspect_live_industry_trend_signal",
    "load_l2_etf_map",
]
