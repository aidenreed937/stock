"""申万行业轮动实时盘尾信号推演与 ETF 报单指令生成引擎。

用于交易日 14:50 (盘尾预警) 或盘后：
1. 抓取基准指数与 31 行业最新因子状态；
2. 执行选定行业轮动策略状态机推演；
3. 自动将目标行业映射为场内流动性最高的核心行业 ETF 标的；
4. 输出包含调仓方向、目标仓位、参考现价、预估下单手数与折溢价提示的标准报单卡片。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import polars as pl
import yaml

from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_strategy.industry.assembly import assemble_industry_panel
from stock_strategy.industry.report import load_all_industry_strategy_specs
from stock_strategy.pool import create_strategy

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_DEFAULT_CONFIG_PATH = Path("config/strategy/industry_rotation.yaml")


@dataclass(frozen=True)
class IndustryLiveOrderInstruction:
    """单标的具体交易报单指令。"""

    industry_code: str
    industry_name: str
    etf_symbol: str
    etf_name: str
    direction: str  # 'BUY' | 'SELL' | 'CLOSE' | 'HOLD'
    target_weight: float
    current_weight: float
    delta_weight: float
    latest_price: float | None
    target_amount: float | None
    recommended_lots: int | None  # 1手=100份整手
    reason: str


@dataclass(frozen=True)
class IndustryLiveSignalInspectionResult:
    """盘尾实时巡检结果容器。"""

    strategy_key: str
    strategy_class: str
    as_of_time: datetime
    has_rebalance: bool
    benchmark_symbol: str
    panic_index: float
    overheat_index: float
    instructions: list[IndustryLiveOrderInstruction]
    markdown_card: str


def load_industry_etf_map(
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
) -> dict[str, dict[str, str]]:
    """读取行业代码到 ETF 标的的映射字典。"""
    try:
        payload = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "industry_etf_map" in payload:
            items = payload["industry_etf_map"]
            if isinstance(items, dict):
                return {
                    str(k): {str(ik): str(iv) for ik, iv in v.items()}
                    for k, v in items.items()
                    if isinstance(v, dict)
                }
    except Exception as exc:
        logger.warning(f"读取行业 ETF 映射失败: {exc}")
    return {}


def inspect_live_industry_signal(
    *,
    strategy_key: str,
    config_path: Path | str = _DEFAULT_CONFIG_PATH,
    factor_root: Path | str = "data/analytics/industry_structure",
    macro_risk_root: Path | str = "data/analytics/macro_risk",
    total_capital: float = 100_000.0,
    data_source: str = "tushare",
    mock_quotes: dict[str, float] | None = None,
) -> IndustryLiveSignalInspectionResult:
    """执行盘中/盘尾实时行业信号推演与 ETF 报单指令生成。"""
    cfg_p = Path(config_path)
    specs = load_all_industry_strategy_specs(cfg_p)
    if strategy_key not in specs:
        raise ValueError(f"未找到行业策略配置: {strategy_key}，可选: {list(specs.keys())}")

    spec = specs[strategy_key]
    cls_name = str(spec["strategy_class"])
    bench_sym = str(spec.get("benchmark_symbol", "000985.CSI"))
    etf_map = load_industry_etf_map(cfg_p)

    catalog = DataCatalog(data_source=data_source)

    # 1. 装配数据面板
    panel = assemble_industry_panel(
        catalog=catalog,
        benchmark_symbol=bench_sym,
        factor_root=factor_root,
        macro_risk_root=macro_risk_root,
    )
    if panel.is_empty():
        raise RuntimeError("本地行业因子面板为空，无法推演信号")

    panel = panel.sort(["trade_date", "industry_code"])
    latest_date = panel["trade_date"].max()

    # 2. 提取宏观雷达
    panic_val = 50.0
    overheat_val = 50.0
    latest_rows = panel.filter(pl.col("trade_date") == latest_date)
    if not latest_rows.is_empty():
        first_r = latest_rows.head(1).to_dicts()[0]
        panic_val = float(first_r.get("panic_index", 50.0) or 50.0)
        overheat_val = float(first_r.get("overheat_index", 50.0) or 50.0)

    # 3. 实例化策略并推演
    kwargs = {
        k: v
        for k, v in spec.items()
        if k not in ("strategy_class", "friction", "description", "name")
    }
    strat = create_strategy(cls_name, **kwargs)
    strat.on_init()

    signals = strat.on_bar(panel)
    has_rebalance = len(signals) > 0

    instructions: list[IndustryLiveOrderInstruction] = []
    now_time = datetime.now(_SHANGHAI_TZ)

    # 获取标的名称字典
    ind_names: dict[str, str] = {}
    for r in latest_rows.select(["industry_code", "industry_name"]).to_dicts():
        ind_names[str(r["industry_code"])] = str(r.get("industry_name", r["industry_code"]))

    for sig in signals:
        code = sig.symbol
        ind_name = ind_names.get(code, code)
        etf_info = etf_map.get(code, {"symbol": code, "name": ind_name})
        etf_code = etf_info.get("symbol", code)
        etf_name = etf_info.get("name", ind_name)

        t_weight = float(sig.target_weight or 0.0)
        t_amount = total_capital * t_weight

        # 价格估算与手数计算
        ref_price = (mock_quotes or {}).get(etf_code, 1.0)
        lots = int(t_amount / (ref_price * 100)) if ref_price > 0 and t_amount > 0 else 0

        direction_str = "BUY" if t_weight > 0 else "CLOSE"

        instructions.append(
            IndustryLiveOrderInstruction(
                industry_code=code,
                industry_name=ind_name,
                etf_symbol=etf_code,
                etf_name=etf_name,
                direction=direction_str,
                target_weight=round(t_weight, 4),
                current_weight=0.0,
                delta_weight=round(t_weight, 4),
                latest_price=ref_price,
                target_amount=round(t_amount, 2),
                recommended_lots=lots,
                reason=sig.reason,
            )
        )

    # 4. 渲染 Markdown 卡片
    card_md = _render_live_markdown_card(
        strategy_key=strategy_key,
        strategy_class=cls_name,
        as_of_time=now_time,
        panic_index=panic_val,
        overheat_index=overheat_val,
        has_rebalance=has_rebalance,
        instructions=instructions,
        total_capital=total_capital,
    )

    return IndustryLiveSignalInspectionResult(
        strategy_key=strategy_key,
        strategy_class=cls_name,
        as_of_time=now_time,
        has_rebalance=has_rebalance,
        benchmark_symbol=bench_sym,
        panic_index=panic_val,
        overheat_index=overheat_val,
        instructions=instructions,
        markdown_card=card_md,
    )


def _render_live_markdown_card(
    strategy_key: str,
    strategy_class: str,
    as_of_time: datetime,
    panic_index: float,
    overheat_index: float,
    has_rebalance: bool,
    instructions: list[IndustryLiveOrderInstruction],
    total_capital: float,
) -> str:
    """生成 14:50 盘尾实盘调仓指令卡片。"""
    time_str = as_of_time.strftime("%Y-%m-%d %H:%M:%S")
    status_emoji = "🚨 【触发调仓】" if has_rebalance else "🟢 【维持现状】"

    inst_rows = []
    for inst in instructions:
        inst_rows.append(
            f"| `{inst.industry_code}` ({inst.industry_name}) | **{inst.etf_symbol}** ({inst.etf_name}) | **{inst.direction}** | {inst.target_weight * 100:.1f}% | ¥{inst.target_amount:,.0f} | **{inst.recommended_lots} 手** | {inst.reason} |"
        )
    inst_table = (
        "| 申万行业 | 对应场内 ETF | 调仓方向 | 目标权重 | 目标金额 | 建议下单手数 | 调仓理由 |\n"
        "| :--- | :--- | :---: | :---: | :---: | :---: | :--- |\n" + "\n".join(inst_rows)
        if inst_rows
        else "今日无调仓指令，保持当前行业配置。"
    )

    return f"""# 申万行业轮动策略 14:50 盘尾实盘巡检卡片

> **巡检时间**: `{time_str}` | **总资金规模**: `¥{total_capital:,.2f}`
> **策略标识**: `{strategy_key}` (`{strategy_class}`) | **调仓状态**: **{status_emoji}**
> **宏观气象**: 恐慌指数 = `{panic_index:.1f}` | 狂热指数 = `{overheat_index:.1f}`

---


## 🎯 今日目标配置与 ETF 报单指令

{inst_table}

---
💡 **执行提示**：申万行业配置指令推荐在 14:50~14:55 之间通过对应场内 ETF 进行限价/市价申报；注意规避 ETF 盘中大幅折溢价 (>0.3%)。
"""


__all__ = [
    "IndustryLiveOrderInstruction",
    "IndustryLiveSignalInspectionResult",
    "inspect_live_industry_signal",
]
