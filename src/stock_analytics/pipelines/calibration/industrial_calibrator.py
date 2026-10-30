"""年报工业单耗动态倒轧求解器与敏感性置信带宽模型 (IndustrialCostCalibrator)。

解决传统投研中“静态工艺单耗与动态工业现实脱节”的核心断层：
1. 年报成本倒轧：基于财务报告披露的实际主营营业成本 (fina_mainbz.bz_cost) 与当期原料均价，
   求解隐含自给率 (implied_captive_ratio) 与隐含动力制造费用 (implied_fixed_cost)；
2. 工业漂移检测：识别单耗系统性偏差，发出工艺异动预警 (DRIFT_UPWARD / DRIFT_DOWNWARD)；
3. 置信带宽生成：输出在矿自给率与动力成本波动下的二维 EPS 置信区间 [low_eps, high_eps]，
   替代单一死板的点估计。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    """单个公司工业单耗年报倒轧校准结果。"""

    symbol: str
    company_name: str
    report_date: str
    reported_sales_cny: float
    reported_cost_cny: float
    implied_volume_tons: float
    implied_unit_cost_cny: float
    nominal_unit_cost_cny: float
    cost_bias_pct: float
    implied_captive_ratio: float | None
    implied_fixed_cost_cny: float | None
    drift_status: str  # "HEALTHY" / "DRIFT_UPWARD" / "DRIFT_DOWNWARD"
    details: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "report_date": self.report_date,
            "reported_sales_cny": self.reported_sales_cny,
            "reported_cost_cny": self.reported_cost_cny,
            "implied_volume_tons": self.implied_volume_tons,
            "implied_unit_cost_cny": self.implied_unit_cost_cny,
            "nominal_unit_cost_cny": self.nominal_unit_cost_cny,
            "cost_bias_pct": self.cost_bias_pct,
            "implied_captive_ratio": self.implied_captive_ratio,
            "implied_fixed_cost_cny": self.implied_fixed_cost_cny,
            "drift_status": self.drift_status,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class ConfidenceBandResult:
    """EPS 敏感性置信带宽测算结果。"""

    symbol: str
    company_name: str
    scenario_key: str
    nominal_eps: float
    low_eps: float  # 保守下界 (自给率-10%, 制费+10%)
    high_eps: float  # 乐观上界 (自给率+10%, 制费-10%)
    bandwidth_pct: float  # (high - low) / nominal * 100
    sensitivity_grid: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "company_name": self.company_name,
            "scenario_key": self.scenario_key,
            "nominal_eps": self.nominal_eps,
            "low_eps": self.low_eps,
            "high_eps": self.high_eps,
            "bandwidth_pct": self.bandwidth_pct,
            "sensitivity_grid": self.sensitivity_grid,
        }


class IndustrialCostCalibrator:
    """年报工业单耗倒轧求解器与置信带宽生成引擎。"""

    def __init__(self, drift_threshold_pct: float = 8.0) -> None:
        """初始化校准器。

        Args:
            drift_threshold_pct: 判定成本发生系统性漂移的偏差阈值百分比 (默认 8%)。
        """
        self.drift_threshold_pct = drift_threshold_pct

    def calibrate_sulfate_tio2(
        self,
        symbol: str,
        company_name: str,
        reported_sales_cny: float,
        reported_cost_cny: float,
        ore_market_price: float,
        acid_market_price: float,
        nominal_ore_consumption: float = 2.3,
        nominal_acid_consumption: float = 3.0,
        nominal_ore_captive_ratio: float = 0.65,
        nominal_ore_captive_cost: float = 900.0,
        nominal_fixed_cost: float = 6600.0,
        spot_tio2_price: float = 15500.0,
        reported_volume_tons: float | None = None,
        report_date: str = "2025-12-31",
    ) -> CalibrationResult:
        """执行硫酸法钛白粉年报成本倒轧求解。

        方程体系：
        c_actual = reported_cost_cny / volume_tons
        c_nominal = ore_cost_nominal + acid_cost + fixed_cost_nominal
        其中：
        ore_cost_nominal = alpha * captive_cost + (1 - alpha) * ore_consumption * ore_market_price
        """
        if reported_sales_cny <= 0 or reported_cost_cny <= 0:
            raise ValueError("营业收入与营业成本必须大于 0")

        # 确定实际产销量
        volume = reported_volume_tons
        if volume is None or volume <= 0:
            # 由主营营业收入 / 当期基准现货价推算商品销售量
            volume = reported_sales_cny / max(spot_tio2_price, 1000.0)

        c_actual = round(reported_cost_cny / volume, 2)

        # 标称理论成本计算
        ore_cost_nominal = (
            nominal_ore_captive_ratio * nominal_ore_captive_cost
            + (1.0 - nominal_ore_captive_ratio) * nominal_ore_consumption * ore_market_price
        )
        acid_cost_nominal = nominal_acid_consumption * acid_market_price
        c_nominal = round(ore_cost_nominal + acid_cost_nominal + nominal_fixed_cost, 2)

        cost_bias_pct = round((c_actual - c_nominal) / c_nominal * 100.0, 2)

        # 1. 求解隐含自给率 implied_alpha (假设固定制费和酸耗按名义值执行)
        implied_ore_budget = c_actual - (acid_cost_nominal + nominal_fixed_cost)
        market_ore_full_cost = nominal_ore_consumption * ore_market_price

        implied_captive_ratio: float | None = None
        if abs(market_ore_full_cost - nominal_ore_captive_cost) > 1e-4:
            raw_alpha = (market_ore_full_cost - implied_ore_budget) / (
                market_ore_full_cost - nominal_ore_captive_cost
            )
            # 物理区间截断与有效性判定
            implied_captive_ratio = round(max(0.0, min(1.0, raw_alpha)), 4)

        # 2. 求解隐含动力制造费用 implied_fixed (假设自给率按名义值执行)
        implied_fixed_cost = round(c_actual - (ore_cost_nominal + acid_cost_nominal), 2)

        # 判定漂移状态
        if abs(cost_bias_pct) <= self.drift_threshold_pct:
            drift_status = "HEALTHY"
            details = (
                f"财报实际单吨成本 {c_actual:.0f}元 与模型标称 {c_nominal:.0f}元 吻合度高 "
                f"(偏差 {cost_bias_pct:+.1f}%)，处于 ±{self.drift_threshold_pct}% 健康工业区间。"
            )
        elif cost_bias_pct > self.drift_threshold_pct:
            drift_status = "DRIFT_UPWARD"
            details = (
                f"财报实际单吨成本 {c_actual:.0f}元 显著高于模型标称 {c_nominal:.0f}元 "
                f"(偏差 {cost_bias_pct:+.1f}%)。若自给率保持名义值，隐含制造与动力成本已漂移至 "
                f"{implied_fixed_cost:.0f}元/吨 (标称 {nominal_fixed_cost:.0f}元)；"
                f"若制费正常，隐含矿石自给率已稀释下移至 "
                f"{(implied_captive_ratio or 0.0) * 100:.1f}% (标称 {nominal_ore_captive_ratio * 100:.1f}%)。"
            )
        else:
            drift_status = "DRIFT_DOWNWARD"
            details = (
                f"财报实际单吨成本 {c_actual:.0f}元 显著优于模型标称 {c_nominal:.0f}元 "
                f"(偏差 {cost_bias_pct:+.1f}%)。公司展现出技改降耗或自产矿提效，"
                f"隐含矿石自给率达 {(implied_captive_ratio or 0.0) * 100:.1f}%。"
            )

        return CalibrationResult(
            symbol=symbol,
            company_name=company_name,
            report_date=report_date,
            reported_sales_cny=reported_sales_cny,
            reported_cost_cny=reported_cost_cny,
            implied_volume_tons=round(volume, 1),
            implied_unit_cost_cny=c_actual,
            nominal_unit_cost_cny=c_nominal,
            cost_bias_pct=cost_bias_pct,
            implied_captive_ratio=implied_captive_ratio,
            implied_fixed_cost_cny=implied_fixed_cost,
            drift_status=drift_status,
            details=details,
        )

    def compute_eps_confidence_band(
        self,
        symbol: str,
        company_name: str,
        scenario_key: str,
        nominal_eps: float,
        annual_capacity_w_tons: float,
        total_shares: float,
        ore_market_price: float,
        nominal_ore_consumption: float = 2.3,
        nominal_ore_captive_cost: float = 900.0,
        nominal_fixed_cost: float = 6600.0,
        tax_rate: float = 0.15,
        base_expense_ratio: float = 0.08,
        captive_ratio_delta: float = 0.10,
        fixed_cost_delta: float = 0.10,
        sales_utilization_rate: float = 0.85,
    ) -> ConfidenceBandResult:
        """计算矿石自给率与动力制费双重波动下的 EPS 置信带宽与敏感性矩阵。

        Args:
            symbol: 股票代码
            company_name: 公司名称
            scenario_key: 基准情景标识
            nominal_eps: 标称基准 EPS
            annual_capacity_w_tons: 年产能 (万吨)
            total_shares: 集团总股本
            ore_market_price: 钛精矿当前市场价格 (元/吨)
            nominal_ore_consumption: 标称单耗
            nominal_ore_captive_cost: 标称自备矿成本
            nominal_fixed_cost: 标称固定动力费用
            tax_rate: 所得税率
            base_expense_ratio: 费用率
            captive_ratio_delta: 自给率敏感性测试步长 (默认 ±10%)
            fixed_cost_delta: 固定制费敏感性测试步长 (默认 ±10%)
            sales_utilization_rate: 有效商品销量开工率

        Returns:
            ConfidenceBandResult 置信带宽测算对象
        """
        sales_tons = annual_capacity_w_tons * 10000.0 * sales_utilization_rate
        shares = max(total_shares, 1.0)
        eff_factor = (1.0 - base_expense_ratio) * (1.0 - tax_rate) / shares

        # 1. 自给率变化对 EPS 的边际敏感度:
        # 每提高 10% 自给率，每吨节省的矿石外购溢价:
        # delta_cost_per_ton = delta_alpha * (ore_consumption * ore_market_price - ore_captive_cost)
        unit_captive_spread = max(
            0.0,
            nominal_ore_consumption * ore_market_price - nominal_ore_captive_cost,
        )
        eps_shift_per_10pct_captive = (
            captive_ratio_delta * unit_captive_spread * sales_tons * eff_factor
        )

        # 2. 动力制费变化对 EPS 的边际敏感度:
        # 每提高 10% 动力制造费用，每吨增加成本 nominal_fixed_cost * 10%
        eps_shift_per_10pct_fixed = nominal_fixed_cost * fixed_cost_delta * sales_tons * eff_factor

        # 保守下界 (自给率-10%, 制费+10%)
        low_eps = round(nominal_eps - eps_shift_per_10pct_captive - eps_shift_per_10pct_fixed, 3)
        # 乐观上界 (自给率+10%, 制费-10%)
        high_eps = round(nominal_eps + eps_shift_per_10pct_captive + eps_shift_per_10pct_fixed, 3)

        bandwidth_pct = (
            round((high_eps - low_eps) / max(abs(nominal_eps), 0.01) * 100.0, 1)
            if nominal_eps != 0
            else 0.0
        )

        # 构建 3x3 敏感性二维矩阵
        # 行: 动力制费变化 (-10%, 0%, +10%)
        # 列: 自给率变化 (-10%, 0%, +10%)
        grid: list[dict[str, Any]] = []
        fixed_levels = [
            ("-10% (节能/煤跌)", -1.0),
            ("基准 (标称)", 0.0),
            ("+10% (能源通胀)", 1.0),
        ]
        captive_levels = [
            ("captive_-10%", -1.0),
            ("captive_base", 0.0),
            ("captive_+10%", 1.0),
        ]

        for fix_label, fix_mult in fixed_levels:
            row: dict[str, Any] = {"fixed_cost_scenario": fix_label}
            for cap_col, cap_mult in captive_levels:
                shift = (
                    cap_mult * eps_shift_per_10pct_captive - fix_mult * eps_shift_per_10pct_fixed
                )
                row[cap_col] = round(nominal_eps + shift, 3)
            grid.append(row)

        return ConfidenceBandResult(
            symbol=symbol,
            company_name=company_name,
            scenario_key=scenario_key,
            nominal_eps=round(nominal_eps, 3),
            low_eps=low_eps,
            high_eps=high_eps,
            bandwidth_pct=bandwidth_pct,
            sensitivity_grid=grid,
        )

    def render_markdown_section(
        self,
        calibrations: list[CalibrationResult],
        confidence_bands: list[ConfidenceBandResult] | None = None,
    ) -> str:
        """渲染工业单耗校准与敏感性带宽的 Markdown 研报章节。"""
        lines = [
            "### 工业单耗动态倒轧校准与置信带宽 (Industrial Calibration)",
            "",
            "依据企业年报披露的真实主营营业成本 (`fina_mainbz`) 与同期市场现货均价，"
            "倒轧求解当期隐含物理自给率与动力制造费用，并建立敏感性置信带宽：",
            "",
            "| 股票代码 | 公司名称 | 财报期 | 实际单吨成本 | 模型标称成本 | 成本偏差率 | 隐含自给率 | 隐含动力制费 | 工业健康状态 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ]

        for c in calibrations:
            cap_str = (
                f"{c.implied_captive_ratio * 100:.1f}%"
                if c.implied_captive_ratio is not None
                else "--"
            )
            fix_str = (
                f"{c.implied_fixed_cost_cny:.0f}元"
                if c.implied_fixed_cost_cny is not None
                else "--"
            )
            status_badge = {
                "HEALTHY": "健康吻合",
                "DRIFT_UPWARD": "成本上漂",
                "DRIFT_DOWNWARD": "超额降本",
            }.get(c.drift_status, c.drift_status)
            lines.append(
                f"| {c.symbol} | {c.company_name} | {c.report_date} | "
                f"{c.implied_unit_cost_cny:.0f}元 | {c.nominal_unit_cost_cny:.0f}元 | "
                f"{c.cost_bias_pct:+.1f}% | {cap_str} | {fix_str} | **{status_badge}** |"
            )

        lines.extend(["", "> **单耗倒轧深度诊断**："])
        for c in calibrations:
            lines.append(f"> - **{c.company_name} ({c.symbol})**：{c.details}")

        if confidence_bands:
            lines.extend(
                [
                    "",
                    "#### 二维参数置信带宽推演 (±10% 自给率 vs ±10% 动力能源成本)",
                    "",
                    "| 股票代码 | 公司名称 | 基准情景 | 标称点估计 EPS | 保守下界 (低自给+高能耗) | 乐观上界 (高自给+节能) | 置信带宽跨度 |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                ]
            )
            for b in confidence_bands:
                lines.append(
                    f"| {b.symbol} | {b.company_name} | {b.scenario_key} | "
                    f"**{b.nominal_eps:.2f} 元** | {b.low_eps:.2f} 元 | "
                    f"{b.high_eps:.2f} 元 | ±{b.bandwidth_pct / 2:.1f}% |"
                )

        return "\n".join(lines)


__all__ = [
    "CalibrationResult",
    "ConfidenceBandResult",
    "IndustrialCostCalibrator",
]
