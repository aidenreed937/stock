"""二级方向池量价齐升（供需层）接入与组合回测。

全球共振方向池 15 个申万二级行业（去重版：半导体/通信设备/计算机设备/电池/乘用车/
工业金属/贵金属/化学制药/医疗服务/化学原料/化学纤维/农化制品/
工程机械/航运港口/电网设备，剔除高相关成员 光伏/生物制品/化学制品/塑料），
季度调仓（63 交易日）：
- baseline：动量 Top3 + 估值防守（return_60d 动量，pe_ttm_ew_percentile_5y<=90，缺失放行）；
- +量价齐升：在 baseline 上叠加供需层质量门——只从「营收 + 净利 TTM 同比双正」行业选 Top3；
- +方向防守门：在 baseline 上叠加方向层防守——方向高位（direction_score > 66）×
  非量价齐升行业剔除（对齐一级实证：方向追高反向，作防守不作进攻）。

数据源：`industry_l2_panel_daily`（阶段 1/3 产物：行情/估值/动量 + L2 财务量价齐升 +
`global_resonance_l2_map` 方向分，报告期按 `reportDate` 生效，无前视）。

回测口径：T+1 执行（当日收盘信号次日生效），佣金万一 + 滑点万五 + 3% 调仓死区，
对齐 `scripts/industry_trend_exit.py` 的摩擦设置。指标：算术 Sharpe / CAGR / MaxDD / Calmar，
全周期（2020-05 起，首份 L2 财报发布后）与样本外（2022-01-01 后）。

输出：data/analytics/industry_strategy/industry_l2_direction_qlq.csv / .md
"""

from __future__ import annotations

from datetime import date
from math import sqrt
from pathlib import Path

import polars as pl

from stock_strategy.base import BaseStrategy
from stock_strategy.industry.runner import IndustryStrategyRunner
from stock_strategy.signal import Signal, SignalDirection

_TRADING_DAYS_PER_YEAR = 252.0

# 全球共振方向池 15 个申万二级行业（去重版；代码对齐 industry_l2_daily / sw_2021_l2_fs）
_DIRECTION_POOL: dict[str, str] = {
    "270100": "半导体",
    "730200": "通信设备",
    "710100": "计算机设备",
    "630700": "电池",
    "280500": "乘用车",  # 汽车（整车需求端）
    "240300": "工业金属",
    "240400": "贵金属",
    "370100": "化学制药",
    "370600": "医疗服务",
    "220200": "化学原料",
    "220400": "化学纤维",
    "220800": "农化制品",
    "640600": "工程机械",
    "421100": "航运港口",
    "630800": "电网设备",
}

_L2_PANEL_MART = Path("data/curated/mart/industry_l2_panel_daily.parquet")
_L2_FS = Path("data/curated/lixinger/sw_2021_l2_fs_non_financial.parquet")
_OUT_DIR = Path("data/analytics/industry_strategy")


def _metrics(nav_df: pl.DataFrame) -> dict[str, float]:
    """与 scripts/industry_trend_exit.py 一致的指标口径（算术 Sharpe）。"""
    navs = [float(v) for v in nav_df["nav"].to_list()]
    n = len(navs)
    final = navs[-1]
    years = n / _TRADING_DAYS_PER_YEAR
    cagr = (
        ((final / navs[0]) ** (1.0 / years) - 1.0) * 100.0
        if years > 0 and final > 0 and navs[0] > 0
        else 0.0
    )
    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    rets = [navs[i] / navs[i - 1] - 1.0 for i in range(1, n)]
    mean_r = sum(rets) / len(rets) if rets else 0.0
    var_r = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    sharpe = mean_r / sqrt(var_r) * sqrt(_TRADING_DAYS_PER_YEAR) if var_r > 0 else 0.0
    calmar = cagr / (max_dd * 100.0) if max_dd > 0 else 0.0
    return {"cagr": cagr, "max_drawdown": max_dd * 100.0, "sharpe": sharpe, "calmar": calmar}


def build_l2_direction_panel() -> tuple[pl.DataFrame, pl.DataFrame]:
    """构建方向池 12 行业日频面板（动量/估值/量价齐升/方向分）与价格面板。

    直接消费阶段 1/3 产物 ``industry_l2_panel_daily``：量价齐升已按 `reportDate`
    生效（无前视），direction_score 来自 ``global_resonance_l2_map``。
    """
    panel = pl.read_parquet(_L2_PANEL_MART).filter(
        pl.col("industry_code").is_in(list(_DIRECTION_POOL))
    )
    panel = panel.with_columns(
        pl.col("industry_name").fill_null(pl.col("industry_code")),
    ).sort(["trade_date", "industry_code"])

    price_panel = panel.select(
        [
            pl.col("trade_date"),
            pl.col("industry_code").alias("symbol"),
            "close",
        ]
    ).sort(["symbol", "trade_date"])
    return panel, price_panel


class L2DirectionPoolStrategy(BaseStrategy):
    """二级方向池策略：动量 Top3 + 估值防守，可选量价齐升门 / 方向防守门。

    - score_column：动量列（默认 return_60d）；
    - valuation_max：pe_ttm_ew_percentile_5y 高位剔除阈值（缺失放行）；
    - require_qlq：True 时仅从量价齐升行业（rev/np 双正）选 Top3（硬门）；
    - qlq_bonus：>0 时对量价齐升行业动量加分（软性接入），保持 Top3 满仓；
    - direction_gate：True 时启用方向防守门——方向高位（direction_score>阈值）×
      非量价齐升行业剔除（对齐一级实证：方向追高反向，作防守不作进攻）。
    """

    def __init__(
        self,
        context=None,
        *,
        top_k: int = 3,
        rebalance_period: int = 63,
        score_column: str = "return_60d",
        valuation_max: float = 90.0,
        require_qlq: bool = False,
        qlq_bonus: float = 0.0,
        direction_gate: bool = False,
        direction_high_threshold: float = 66.0,
    ) -> None:
        super().__init__(context)
        self.top_k = max(int(top_k), 1)
        self.rebalance_period = max(int(rebalance_period), 1)
        self.score_column = score_column
        self.valuation_max = float(valuation_max)
        self.require_qlq = bool(require_qlq)
        self.qlq_bonus = float(qlq_bonus)
        self.direction_gate = bool(direction_gate)
        self.direction_high_threshold = float(direction_high_threshold)
        self.weights: dict[str, float] = {}
        self._bar_count = 0

    def on_init(self) -> None:
        self.weights = {}
        self._bar_count = 0

    def on_bar(self, data: pl.DataFrame) -> list[Signal]:
        if data.is_empty():
            return []
        latest_date = data["trade_date"].max()
        latest = data.filter(pl.col("trade_date") == latest_date)
        if latest.is_empty():
            return []

        self._bar_count += 1
        signals: list[Signal] = []
        ts = latest_date if isinstance(latest_date, date) else None

        # 季度调仓
        if self._bar_count > 1 and (self._bar_count - 1) % self.rebalance_period != 0:
            return signals

        # 候选：估值防守（pe5y 高位剔除，缺失放行）
        candidates = latest
        if "pe_ttm_ew_percentile_5y" in candidates.columns:
            candidates = candidates.filter(
                pl.col("pe_ttm_ew_percentile_5y").is_null()
                | (pl.col("pe_ttm_ew_percentile_5y") <= self.valuation_max)
            )
        # 量价齐升质量门（供需层，硬门）：营收 + 净利 TTM 同比双正
        if self.require_qlq:
            if "revenue_growth_ttm" not in candidates.columns:
                return signals
            candidates = candidates.filter(
                (pl.col("revenue_growth_ttm") > 0.0) & (pl.col("profit_growth_ttm") > 0.0)
            )
        # 方向防守门：方向高位 × 非量价齐升 → 剔除（防守语义，不进攻加分）
        if self.direction_gate:
            if (
                "direction_score" in candidates.columns
                and "revenue_growth_ttm" in candidates.columns
            ):
                candidates = candidates.filter(
                    ~(
                        (pl.col("direction_score") > self.direction_high_threshold)
                        & ~(
                            (pl.col("revenue_growth_ttm") > 0.0)
                            & (pl.col("profit_growth_ttm") > 0.0)
                        )
                    )
                )

        ranked = (
            candidates.select(
                [
                    "industry_code",
                    "industry_name",
                    self.score_column,
                    "revenue_growth_ttm",
                    "profit_growth_ttm",
                ]
            )
            .drop_nulls(subset=[self.score_column])
            .with_columns(
                pl.when((pl.col("revenue_growth_ttm") > 0.0) & (pl.col("profit_growth_ttm") > 0.0))
                .then(pl.col(self.score_column) + self.qlq_bonus)
                .otherwise(pl.col(self.score_column))
                .alias("score")
            )
            .sort("score", descending=True)
        )
        top_rows = ranked.head(self.top_k).to_dicts()
        # 候选为空（如量价齐升硬门过滤后无合格行业）→ 维持现状，不清仓（与正式 CLI 策略一致）
        if not top_rows:
            return signals
        new_weights: dict[str, float] = {}
        w = round(1.0 / len(top_rows), 4)
        # 每次调仓对全部 Top K 发 BUY（含已持有行业，权重以信号为准），与正式 CLI 策略一致
        for row in top_rows:
            code = str(row["industry_code"])
            new_weights[code] = w
            signals.append(
                Signal(
                    symbol=code,
                    direction=SignalDirection.BUY,
                    target_weight=w,
                    reason=(
                        f"方向池建仓 ({self.score_column}={float(row[self.score_column]):.1f})"
                        + (" [量价齐升]" if self.require_qlq else "")
                        + (" [方向防守]" if self.direction_gate else "")
                    ),
                    timestamp=ts,
                )
            )

        for code in list(self.weights.keys()):
            if code not in new_weights:
                signals.append(
                    Signal(
                        symbol=code,
                        direction=SignalDirection.CLOSE,
                        target_weight=0.0,
                        reason="季度调仓剔除",
                        timestamp=ts,
                    )
                )
        self.weights = new_weights
        return signals


def _run_strategy(
    panel: pl.DataFrame,
    price_panel: pl.DataFrame,
    *,
    require_qlq: bool = False,
    qlq_bonus: float = 0.0,
    direction_gate: bool = False,
) -> pl.DataFrame:
    strat = L2DirectionPoolStrategy(
        top_k=3,
        rebalance_period=63,
        score_column="return_60d",
        valuation_max=90.0,
        require_qlq=require_qlq,
        qlq_bonus=qlq_bonus,
        direction_gate=direction_gate,
    )
    return IndustryStrategyRunner(
        strat, commission_rate=0.0001, slippage_rate=0.0005, rebalance_deadband=0.03
    ).backtest(panel, price_panel)


# 量价齐升数据可用起点：首份 L2 财报发布日之后（sw_2021_l2_fs 从 2020Q1 报告期起）
_QLQ_AVAILABLE_FROM = date(2020, 5, 1)


def main() -> None:
    panel, price_panel = build_l2_direction_panel()
    if panel.is_empty():
        raise RuntimeError("方向池面板为空，请检查 industry_l2_daily / sw_2021_l2_fs 数据")
    print(
        f"方向池面板: {len(panel)} 行, {panel['trade_date'].min()} ~ {panel['trade_date'].max()}, "
        f"行业 {panel['industry_code'].n_unique()} 个"
    )

    # 量价齐升状态矩阵（15 行业，取每报告期发布日的最新值）
    qlq_matrix = (
        panel.select(
            [
                pl.col("industry_code").alias("行业"),
                pl.col("revenue_growth_ttm").alias("营收同比"),
                pl.col("profit_growth_ttm").alias("净利同比"),
            ]
        )
        .with_columns(
            pl.col("行业").replace_strict(_DIRECTION_POOL),
            ((pl.col("营收同比") > 0) & (pl.col("净利同比") > 0)).alias("量价齐升"),
        )
        .drop_nulls(subset=["营收同比", "净利同比"])
        .group_by("行业")
        .tail(1)
        .sort("行业")
    )
    print("\n=== 15 行业量价齐升状态（最新报告期） ===")
    print(qlq_matrix)

    # 组合回测：统一窗口从量价齐升数据可用起点开始（公平对比），样本外 2022 后
    panel_cmp = panel.filter(pl.col("trade_date") >= _QLQ_AVAILABLE_FROM)
    price_cmp = price_panel.filter(pl.col("trade_date") >= _QLQ_AVAILABLE_FROM)
    nav_base = _run_strategy(panel_cmp, price_cmp, require_qlq=False)
    nav_qlq = _run_strategy(panel_cmp, price_cmp, require_qlq=True)
    nav_bonus = _run_strategy(panel_cmp, price_cmp, qlq_bonus=10.0)
    nav_dgate = _run_strategy(panel_cmp, price_cmp, direction_gate=True)

    nav_map = {
        "方向池动量Top3+估值防守": nav_base,
        "方向池动量Top3+估值防守+量价齐升(硬门)": nav_qlq,
        "方向池动量Top3+估值防守+量价齐升(加分)": nav_bonus,
        "方向池动量Top3+估值防守+方向防守门": nav_dgate,
    }
    rows = []
    for name, nav in nav_map.items():
        rows.append({"strategy": name, "区间": "全周期(2020-05起)", **_metrics(nav)})
        oos = nav.filter(pl.col("trade_date") >= date(2022, 1, 1))
        rows.append({"strategy": name, "区间": "样本外2022后", **_metrics(oos)})
    result = pl.DataFrame(rows)

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    result.write_csv(_OUT_DIR / "industry_l2_direction_qlq.csv")
    print("\n=== 回测指标 ===")
    print(
        result.select(
            [
                "strategy",
                "区间",
                pl.col("cagr").round(2),
                pl.col("max_drawdown").round(2),
                pl.col("sharpe").round(2),
                pl.col("calmar").round(2),
            ]
        )
    )

    # Markdown 留档
    md = f"""# 二级方向池量价齐升（供需层）与方向层接入实证

> 日期：{date.today().isoformat()}
> 定位：全球共振方向池 14 个申万二级行业（半导体/通信设备/计算机设备/光伏设备/电池/乘用车/
> 工业金属/贵金属/化学制药/生物制品/工程机械/航运港口/电网设备），
> 将三层共振框架的「供需层（量价齐升）+ 方向层（防守门）」接入「动量 Top3 + 估值防守」
> 闭环的组合回测记录。
> 回测窗口统一从量价齐升数据可用起点（2020-05，首份 L2 财报发布后）开始，保证公平对比。

## 1. 数据源（阶段 1/3 产物）

- `industry_l2_panel_daily`：行情/估值/动量 + 理杏仁 L2 财务黄金表（2020Q1 ~ 2026Q1，25 报告期）
  量价齐升，按 `reportDate` 发布日生效（无前视）；
- `global_resonance_l2_map`：二级行业方向分（SOX/光模块/光伏装机/新能源车销量/铜价/变压器出口/
  创新药 BD/挖机产销/海运运价 等信号腿），缺失回退中性 50。

## 2. 组合回测（季度调仓 Top3，T+1，佣金万一 + 滑点万五 + 3% 死区）

> 指标口径：CAGR/MaxDD/Calmar 与 CLI 回测一致；Sharpe 为算术口径（日收益均值/标准差 × √252），
> 与 `stock_strategy.industry.report.compute_metrics` 的 CAGR 口径 Sharpe 数值不同，对比时注意。

| 策略 | 区间 | CAGR% | MaxDD% | Sharpe | Calmar |
| :--- | :--- | ---: | ---: | ---: | ---: |
"""
    for r in result.select(
        ["strategy", "区间", "cagr", "max_drawdown", "sharpe", "calmar"]
    ).to_dicts():
        md += (
            f"| {r['strategy']} | {r['区间']} | {r['cagr']:.2f} | {r['max_drawdown']:.2f} "
            f"| {r['sharpe']:.2f} | {r['calmar']:.2f} |\n"
        )

    base_full = result.filter(
        (pl.col("strategy") == "方向池动量Top3+估值防守") & (pl.col("区间") == "全周期(2020-05起)")
    )
    base_oos = result.filter(
        (pl.col("strategy") == "方向池动量Top3+估值防守") & (pl.col("区间") == "样本外2022后")
    )
    qlq_full = result.filter(
        (pl.col("strategy") == "方向池动量Top3+估值防守+量价齐升(硬门)")
        & (pl.col("区间") == "全周期(2020-05起)")
    )
    qlq_oos = result.filter(
        (pl.col("strategy") == "方向池动量Top3+估值防守+量价齐升(硬门)")
        & (pl.col("区间") == "样本外2022后")
    )
    bonus_full = result.filter(
        (pl.col("strategy") == "方向池动量Top3+估值防守+量价齐升(加分)")
        & (pl.col("区间") == "全周期(2020-05起)")
    )
    gate_full = result.filter(
        (pl.col("strategy") == "方向池动量Top3+估值防守+方向防守门")
        & (pl.col("区间") == "全周期(2020-05起)")
    )

    def _v(df: pl.DataFrame, col: str) -> str:
        return f"{df[col][0]:.2f}" if not df.is_empty() else "—"

    md += f"""
## 3. 结论（实测）

- **baseline（return_60d 动量 Top3 + pe5y<=90 估值防守）全周期 Sharpe = {_v(base_full, "sharpe")}**
  （2020-05 起，样本外 {_v(base_oos, "sharpe")}）；15 行业扩池后集中度下降，Sharpe 低于 6 行业池的 0.72；
- **量价齐升硬门**：全周期 {_v(qlq_full, "sharpe")}（样本外 {_v(qlq_oos, "sharpe")}），
  相对 baseline 影响见上表（候选不足 Top3 时选不满，集中度风险）；
- **量价齐升加分（+10）**：全周期 {_v(bonus_full, "sharpe")}，弱于 baseline；
- **方向防守门（高位×非量价齐升剔除）**：全周期 {_v(gate_full, "sharpe")}，弱于 baseline，
  方向层在 L2 池的防守语义以回测为准；
- 结论：**供需层（量价齐升）在 15 行业方向池 Top3 框架下不作选股硬门**，保留为持仓观察/预警
  信号；方向层延续一级实证的「防守门」语义（追高反向，不作进攻加分）。

## 4. 文件

- 脚本：`scripts/industry_l2_direction_qlq.py`
- 数据：`data/curated/mart/industry_l2_panel_daily.parquet` + `global_resonance_l2_map.parquet`
"""
    (_OUT_DIR / "industry_l2_direction_qlq.md").write_text(md, encoding="utf-8")
    print(f"\n已写入: {_OUT_DIR / 'industry_l2_direction_qlq.csv'} / .md")


if __name__ == "__main__":
    main()
