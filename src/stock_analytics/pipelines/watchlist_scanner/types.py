"""自选池批量量化雷达领域模型与报表渲染器。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class WatchlistItemSummary:
    """单个自选标的诊断精简快照。"""

    symbol: str
    name: str
    industry: str
    close: float
    pct_chg: float | None = None
    pe_ttm: float | None = None
    pe_percentile_5y: float | None = None
    pb: float | None = None
    dv_ttm: float | None = None
    dividend_spread_10y: float | None = None
    roe: float | None = None
    trend_description: str = "震荡整理"
    value_trap_warning: bool = False
    screen_status: str = "passed"
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class WatchlistScanResult:
    """自选池全量扫描聚合结果。"""

    as_of_date: str
    total_scanned: int
    items: list[WatchlistItemSummary]
    golden_pit_candidates: list[WatchlistItemSummary] = field(default_factory=list)
    high_dividend_candidates: list[WatchlistItemSummary] = field(default_factory=list)
    value_trap_candidates: list[WatchlistItemSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """序列化为紧凑字典。"""
        return asdict(self)

    def to_markdown(self) -> str:
        """渲染为结构化 Markdown 全景雷达表。"""
        lines = [
            f"# 核心观察池量化全景雷达 (基准日: {self.as_of_date})",
            "",
            f"- **共扫描标的**: {self.total_scanned} 只",
            f"- **极低估值黄金坑 (PE 5Y分位 ≤ 15%)**: {len(self.golden_pit_candidates)} 只",
            f"- **高股息利差安全垫 (利差 ≥ +2.0%)**: {len(self.high_dividend_candidates)} 只",
            f"- **价值陷阱预警 (负增长+低分位)**: {len(self.value_trap_candidates)} 只",
            "",
            "## 核心观察池全景量化明细表",
            "",
            "| 标的代码 | 标的名称 | 所属行业 | 最新价格 (涨跌) | PE (5Y分位) | PB | 股息率 (超额利差) | ROE | 均线状态 | 风险/特色标签 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for item in self.items:
            pct_str = f"{item.pct_chg:+.2f}%" if item.pct_chg is not None else "--"
            pe_str = (
                f"{item.pe_ttm:.1f} ({item.pe_percentile_5y:.1f}%)"
                if item.pe_ttm is not None and item.pe_percentile_5y is not None
                else f"{item.pe_ttm:.1f}"
                if item.pe_ttm is not None
                else "--"
            )
            pb_str = f"{item.pb:.2f}" if item.pb is not None else "--"
            dv_str = (
                f"{item.dv_ttm:.2f}% ({item.dividend_spread_10y:+.2f}%)"
                if item.dv_ttm is not None and item.dividend_spread_10y is not None
                else f"{item.dv_ttm:.2f}%"
                if item.dv_ttm is not None
                else "--"
            )
            roe_str = f"{item.roe:.1f}%" if item.roe is not None else "--"
            tag_str = "、".join(item.tags) if item.tags else "常规"

            lines.append(
                f"| {item.symbol} | {item.name} | {item.industry} | {item.close:.2f} ({pct_str}) | {pe_str} | {pb_str} | {dv_str} | {roe_str} | {item.trend_description.split(' ')[0]} | {tag_str} |"
            )

        lines.append("")
        return "\n".join(lines)
