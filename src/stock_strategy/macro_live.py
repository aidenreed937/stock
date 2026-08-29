"""宏观风控实时盘尾信号推演与报单指令生成引擎。

用于交易日 14:50 (盘尾预警) 或盘后：
1. 抓取基准与标的实时现价（支持腾讯行情与历史收盘回退）；
2. 构造今日盘中虚拟 Bar，执行状态机推演；
3. 输出包含调仓方向、目标仓位、参考现价、预估下单手数与折溢价提示的标准指令卡片。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_data.fetcher.realtime.tencent import TencentRealtimeFetcher
from stock_strategy.macro_assembly import assemble_macro_panel, load_price_panel
from stock_strategy.macro_report import load_all_strategy_specs
from stock_strategy.pool import create_strategy

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class LiveOrderInstruction:
    """单标的具体交易报单指令。"""

    symbol: str
    name: str
    direction: str  # 'BUY' | 'SELL' | 'CLOSE' | 'HOLD'
    target_weight: float
    current_weight: float
    delta_weight: float
    latest_price: float | None
    target_amount: float | None
    recommended_lots: int | None  # 1手=100份整手
    reason: str


@dataclass(frozen=True)
class LiveSignalInspectionResult:
    """盘尾实时巡检结果容器。"""

    strategy_key: str
    strategy_class: str
    as_of_time: datetime
    has_rebalance: bool
    benchmark_symbol: str
    benchmark_price: float
    benchmark_ma20: float
    panic_index: float
    overheat_index: float
    instructions: list[LiveOrderInstruction]
    markdown_card: str


def inspect_live_signal(
    *,
    strategy_key: str,
    config_path: Path | str = "config/strategy/macro_risk.yaml",
    risk_root: Path | str = "data/analytics/macro_risk",
    total_capital: float = 100_000.0,
    data_source: str = "tushare",
    mock_quotes: dict[str, float] | None = None,
) -> LiveSignalInspectionResult:
    """执行盘中/盘尾实时信号推演与报单指令生成。"""
    config_path = Path(config_path)
    risk_root = Path(risk_root)
    catalog = DataCatalog(data_source=data_source)

    specs = load_all_strategy_specs(config_path)
    if strategy_key not in specs:
        raise ValueError(f"未找到策略配置: {strategy_key}，可选: {list(specs.keys())}")

    spec = specs[strategy_key]
    symbols = tuple(spec["symbols"])
    initial_weights = dict(spec.get("initial_weights", {}))
    benchmark_symbol = str(spec["benchmark_symbol"])
    ma_window = int(spec.get("ma_window", 20))

    # 1. 提取历史宏观因子面板
    panel = assemble_macro_panel(
        catalog=catalog,
        benchmark_symbol=benchmark_symbol,
        risk_root=risk_root,
    )
    if panel.is_empty():
        raise RuntimeError("本地宏观风险面板为空，无法推演信号")

    panel = panel.sort("trade_date")
    latest_hist = panel.tail(1).to_dicts()[0]
    last_hist_date = latest_hist["trade_date"]

    # 2. 获取实时行情 (Tencent Realtime 或 mock 回退)
    all_needed_syms = list({benchmark_symbol, *symbols})
    realtime_prices: dict[str, float] = {}
    realtime_names: dict[str, str] = {}

    if mock_quotes:
        realtime_prices.update(mock_quotes)
    else:
        try:
            fetcher = TencentRealtimeFetcher()
            quotes = fetcher.fetch_quotes(all_needed_syms)
            for q in quotes:
                if q.price is not None and q.price > 0:
                    realtime_prices[q.symbol] = q.price
                    realtime_names[q.symbol] = q.name
        except Exception as exc:
            logger.warning("获取实时行情失败，将回退使用最近历史收盘价: %s", exc)

    # 标的历史价格面板（用于计算最新现价回退）
    price_panel = load_price_panel(catalog=catalog, symbols=symbols)
    if not price_panel.is_empty():
        for sym in symbols:
            if sym not in realtime_prices:
                sub = price_panel.filter(pl.col("symbol") == sym).sort("trade_date")
                if not sub.is_empty():
                    realtime_prices[sym] = float(str(sub.tail(1)["close"][0]))

    # 基准现价
    bench_price = realtime_prices.get(benchmark_symbol, float(str(latest_hist["close"])))

    # 3. 构造今日虚拟 Bar
    today = date.today()
    if today > last_hist_date:
        today_dict = dict(latest_hist)
        today_dict["trade_date"] = today
        today_dict["close"] = bench_price
        eval_panel = pl.concat([panel, pl.DataFrame([today_dict])], how="vertical_relaxed")
    else:
        eval_panel = panel

    eval_panel = eval_panel.sort("trade_date")

    # 计算 20 日均线
    ma20_val = eval_panel["close"].tail(ma_window).mean()
    benchmark_ma20 = float(str(ma20_val)) if ma20_val is not None else bench_price

    # 4. 实例化策略并生成今日信号
    strategy_kwargs: dict[str, Any] = {
        "symbols": symbols,
        "initial_weights": initial_weights,
        "benchmark_symbol": benchmark_symbol,
    }
    for k, v in spec.items():
        if k not in {
            "strategy_class",
            "symbols",
            "initial_weights",
            "benchmark_symbol",
            "friction",
        }:
            strategy_kwargs[k] = v

    strategy = create_strategy(str(spec["strategy_class"]), **strategy_kwargs)
    strategy.on_init()

    # 推进历史以获得当前真实持仓
    for i in range(len(eval_panel) - 1):
        window = eval_panel.slice(0, i + 1)
        strategy.on_bar(window)

    current_weights = (
        strategy.weights.copy() if hasattr(strategy, "weights") else initial_weights.copy()
    )

    # 评估今日最新 Bar 信号
    signals = strategy.on_bar(eval_panel)
    new_target_weights = current_weights.copy()
    reason_map: dict[str, str] = {}
    for sig in signals:
        new_target_weights[sig.symbol] = float(sig.target_weight or 0.0)
        reason_map[sig.symbol] = sig.reason or ""

    # 5. 组装操作指令
    friction = dict(spec.get("friction", {}))
    deadband = float(friction.get("rebalance_deadband", 0.0))

    total_turnover = sum(
        abs(new_target_weights.get(s, 0.0) - current_weights.get(s, 0.0))
        for s in set(symbols) | set(current_weights.keys())
    )
    has_rebalance = total_turnover >= deadband and total_turnover > 0.0

    instructions: list[LiveOrderInstruction] = []
    for sym in symbols:
        c_w = float(current_weights.get(sym, 0.0))
        t_w = float(new_target_weights.get(sym, 0.0)) if has_rebalance else c_w
        delta_w = t_w - c_w
        price = realtime_prices.get(sym)
        name = realtime_names.get(sym, sym)

        if t_w == 0.0 and c_w > 0.0:
            direction = "CLOSE"
        elif delta_w > 0.001:
            direction = "BUY"
        elif delta_w < -0.001:
            direction = "SELL"
        else:
            direction = "HOLD"

        target_amount = total_capital * t_w
        rec_lots = None
        if price and price > 0:
            rec_lots = int((target_amount / price) // 100)

        instructions.append(
            LiveOrderInstruction(
                symbol=sym,
                name=name,
                direction=direction,
                target_weight=t_w,
                current_weight=c_w,
                delta_weight=delta_w,
                latest_price=price,
                target_amount=target_amount,
                recommended_lots=rec_lots,
                reason=reason_map.get(sym, "维持当前持仓"),
            )
        )

    # 6. 生成 Markdown 卡片
    now_str = datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    panic_val = float(latest_hist.get("panic_index", 0.0))
    overheat_val = float(latest_hist.get("overheat_index", 0.0))

    card_md = f"**巡检时间**：`{now_str}`  \n"
    card_md += f"**策略类型**：`{strategy_key}` ({spec['strategy_class']})  \n"
    card_md += f"**基准点位**：{benchmark_symbol} 现价 **`{bench_price:.2f}`** / MA{ma_window} **`{benchmark_ma20:.2f}`**  \n"
    card_md += (
        f"**宏观指数**：Panic **`{panic_val:.1f}`** / Overheat **`{overheat_val:.1f}`**  \n\n"
    )

    if has_rebalance:
        card_md += "### 🚨 【触发调仓信号】\n\n"
        card_md += "| 标的代码 | 标的名称 | 操作方向 | 当前仓位 | 目标仓位 | 参考现价 | 建议下单手数 | 触发原因 |\n"
        card_md += "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |\n"
        for inst in instructions:
            dir_tag = f"**`{inst.direction}`**"
            p_str = f"¥{inst.latest_price:.3f}" if inst.latest_price else "—"
            lots_str = (
                f"{inst.recommended_lots} 手 ({inst.recommended_lots * 100}份)"
                if inst.recommended_lots is not None
                else "—"
            )
            card_md += f"| {inst.symbol} | {inst.name} | {dir_tag} | {inst.current_weight:.0%} | **{inst.target_weight:.0%}** | {p_str} | {lots_str} | {inst.reason} |\n"
    else:
        card_md += "### ✅ 【持仓状态正常 · 无需调仓】\n\n"
        card_md += "| 标的代码 | 标的名称 | 当前持仓权重 | 参考现价 | 持仓市值 (预估) |\n"
        card_md += "| :--- | :--- | :---: | :---: | :---: |\n"
        for inst in instructions:
            p_str = f"¥{inst.latest_price:.3f}" if inst.latest_price else "—"
            amt_str = f"¥{inst.target_amount:,.2f}" if inst.target_amount is not None else "—"
            card_md += f"| {inst.symbol} | {inst.name} | {inst.current_weight:.0%} | {p_str} | {amt_str} |\n"

    return LiveSignalInspectionResult(
        strategy_key=strategy_key,
        strategy_class=str(spec["strategy_class"]),
        as_of_time=datetime.now(_SHANGHAI_TZ),
        has_rebalance=has_rebalance,
        benchmark_symbol=benchmark_symbol,
        benchmark_price=bench_price,
        benchmark_ma20=benchmark_ma20,
        panic_index=panic_val,
        overheat_index=overheat_val,
        instructions=instructions,
        markdown_card=card_md,
    )


__all__ = [
    "LiveOrderInstruction",
    "LiveSignalInspectionResult",
    "inspect_live_signal",
]
