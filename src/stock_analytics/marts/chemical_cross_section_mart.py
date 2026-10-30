"""化工多品种横向截面聚合与景气度打分领域 Mart (chemical_cross_section_mart)。

基于第一性原理与自上而下投研范式：
1. 截面全景对齐 (Cross-Sectional Alignment):
   将 8 大化工子品种（纯碱、PTA、乙二醇、甲醇、PVC、钛白粉、聚氨酯、制冷剂）
   在同一基准日（as_of_date）上对齐吨价差、边际成本击穿深度、开工率、企业与仓单库存、
   海关出口量价四象限及上市公司业绩弹性。
2. 周期相位识别 (Cycle Phase Detection):
   - LEFT_BOTTOM: 跌破边际高成本装置现金保本底线，左侧极值赔率大底；
   - RIGHT_REVERSAL: 装置实质性降负、连续去库、基差修复，右侧反转启动；
   - RIGHT_EXPANSION: 法定配额锁定供给或寡头控盘，外需量价齐升，右侧高景气扩张；
   - MID_RECESSION: 需求放缓、被动累库、开工高位钝化；
   - PEAK_OVERHEAT: 超额暴利、静态个位数低 PE 陷阱、产能密集释放。
3. 综合景气度打分 (Composite Scoring & Ranking):
   输出 0 ~ 100 分综合打分，生成横向截面配置建议（OVERWEIGHT_RIGHT / OVERWEIGHT_LEFT / NEUTRAL_WATCH / UNDERWEIGHT_TRIM）。
"""

from __future__ import annotations

import argparse
import calendar
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import yaml

logger = logging.getLogger(__name__)

CHEMICAL_CROSS_SECTION_MART_NAME = "chemical_cross_section_mart"
CHEMICAL_CROSS_SECTION_MART_FILE = f"{CHEMICAL_CROSS_SECTION_MART_NAME}.parquet"
CHEMICAL_CROSS_SECTION_MART_CSV = f"{CHEMICAL_CROSS_SECTION_MART_NAME}_latest.csv"

DEFAULT_CONFIG_DIR = Path("config/industry/chemicals")
DEFAULT_CURATED_DIR = Path("data/curated")
DEFAULT_MART_DIR = DEFAULT_CURATED_DIR / "mart"

COMMODITY_SPECS: list[dict[str, Any]] = [
    {
        "code": "SA",
        "name": "纯碱",
        "submodule": "soda_ash",
        "category": "A_commodity_futures",
        "futures_symbol": "SA",
        "benchmark_process": "氨碱法",
    },
    {
        "code": "TA",
        "name": "精对苯二甲酸",
        "submodule": "pta",
        "category": "A_commodity_futures",
        "futures_symbol": "TA",
        "benchmark_process": "大炼化一体化",
    },
    {
        "code": "MEG",
        "name": "乙二醇",
        "submodule": "meg",
        "category": "A_commodity_futures",
        "futures_symbol": "EG",
        "benchmark_process": "煤制乙二醇",
    },
    {
        "code": "MA",
        "name": "甲醇",
        "submodule": "methanol",
        "category": "A_commodity_futures",
        "futures_symbol": "MA",
        "benchmark_process": "焦炉气/天然气制",
    },
    {
        "code": "V",
        "name": "聚氯乙烯",
        "submodule": "pvc",
        "category": "A_commodity_futures",
        "futures_symbol": "V",
        "benchmark_process": "电石法/乙烯法",
    },
    {
        "code": "TiO2",
        "name": "钛白粉",
        "submodule": "tio2",
        "category": "B_oligopoly",
        "futures_symbol": None,
        "benchmark_process": "硫酸法",
    },
    {
        "code": "MDI",
        "name": "聚合MDI",
        "submodule": "polyurethane",
        "category": "B_oligopoly",
        "futures_symbol": None,
        "benchmark_process": "光气化MDI",
    },
    {
        "code": "R32",
        "name": "制冷剂R32",
        "submodule": "refrigerant",
        "category": "C_quota_regulated",
        "futures_symbol": None,
        "benchmark_process": "二氯甲烷氟化",
    },
    {
        "code": "UR",
        "name": "尿素",
        "submodule": "urea",
        "category": "A_commodity_futures",
        "futures_symbol": "UR",
        "benchmark_process": "固定床煤制",
    },
    {
        "code": "SH",
        "name": "烧碱",
        "submodule": "caustic_soda",
        "category": "A_commodity_futures",
        "futures_symbol": "SH",
        "benchmark_process": "离子膜法折百",
    },
    {
        "code": "EB",
        "name": "苯乙烯",
        "submodule": "styrene",
        "category": "A_commodity_futures",
        "futures_symbol": "EB",
        "benchmark_process": "乙苯脱氢法",
    },
    {
        "code": "PP",
        "name": "聚丙烯",
        "submodule": "polypropylene",
        "category": "A_commodity_futures",
        "futures_symbol": "PP",
        "benchmark_process": "油制/PDH/煤制",
    },
    {
        "code": "PX",
        "name": "对二甲苯",
        "submodule": "paraxylene",
        "category": "A_commodity_futures",
        "futures_symbol": "PX",
        "benchmark_process": "大炼化重整抽提/异构化",
    },
]

CROSS_SECTION_SCHEMA: dict[str, Any] = {
    "as_of_date": pl.Date,
    "commodity_code": pl.Utf8,
    "commodity_name": pl.Utf8,
    "submodule_dir": pl.Utf8,
    "category_archetype": pl.Utf8,
    "futures_symbol": pl.Utf8,
    # 价格与成本出清
    "spot_price_cny": pl.Float64,
    "spot_price_asof_date": pl.Date,
    "marginal_cash_cost_cny": pl.Float64,
    "cash_cost_coverage_pct": pl.Float64,
    "cost_curve_regime": pl.Utf8,
    "cost_curve_asof_date": pl.Date,
    "is_cash_cost_breached": pl.Boolean,
    "spread_margin_cny": pl.Float64,
    "margin_regime": pl.Utf8,
    "spread_asof_date": pl.Date,
    # 供需与库存时钟
    "operating_rate_pct": pl.Float64,
    "operating_rate_pctl": pl.Float64,
    "operating_rate_asof_date": pl.Date,
    "factory_inventory_w_tons": pl.Float64,
    "inventory_pctl": pl.Float64,
    "inventory_asof_date": pl.Date,
    "warehouse_receipts": pl.Float64,
    # 期现基差与仓单异动 (P1 新增微观特征)
    "basis_cny": pl.Float64,
    "basis_rate_pct": pl.Float64,
    "basis_term_structure": pl.Utf8,
    "basis_asof_date": pl.Date,
    "warehouse_receipts_w_tons": pl.Float64,
    "receipts_pctl_1y": pl.Float64,
    "receipts_acceleration_status": pl.Utf8,
    "composite_micro_regime": pl.Utf8,
    "right_side_basis_gate_pass": pl.Boolean,
    "inventory_stage": pl.Utf8,
    # 海关外需动量
    "export_volume_yoy_pct": pl.Float64,
    "export_asp_yoy_pct": pl.Float64,
    "export_regime": pl.Utf8,
    "customs_asof_month": pl.Utf8,
    # 标的与弹性映射
    "alpha_leader_stock": pl.Utf8,
    "alpha_leader_name": pl.Utf8,
    "beta_elastic_stock": pl.Utf8,
    "beta_elastic_name": pl.Utf8,
    "top_elastic_stock": pl.Utf8,
    "top_elastic_stock_name": pl.Utf8,
    "top_eps_delta_per_100cny": pl.Float64,
    "elasticity_asof_date": pl.Date,
    # 周期定位与截面打分
    "cycle_phase": pl.Utf8,
    "composite_score": pl.Float64,
    "cross_section_rank": pl.Int32,
    "investment_stance": pl.Utf8,
    "data_confidence_pct": pl.Float64,
    "key_rationale": pl.Utf8,
}


@dataclass(frozen=True)
class CommodityCrossSectionRecord:
    """单个化工品截面特征容器。"""

    as_of_date: date
    commodity_code: str
    commodity_name: str
    submodule_dir: str
    category_archetype: str
    futures_symbol: str | None
    spot_price_cny: float
    spot_price_asof_date: date | None
    marginal_cash_cost_cny: float | None
    cash_cost_coverage_pct: float | None
    cost_curve_regime: str
    cost_curve_asof_date: date | None
    is_cash_cost_breached: bool
    spread_margin_cny: float | None
    margin_regime: str
    spread_asof_date: date | None
    operating_rate_pct: float | None
    operating_rate_pctl: float | None
    operating_rate_asof_date: date | None
    factory_inventory_w_tons: float | None
    inventory_pctl: float | None
    inventory_asof_date: date | None
    warehouse_receipts: float | None
    basis_cny: float | None
    basis_rate_pct: float | None
    basis_term_structure: str
    basis_asof_date: date | None
    warehouse_receipts_w_tons: float | None
    receipts_pctl_1y: float | None
    receipts_acceleration_status: str
    composite_micro_regime: str
    right_side_basis_gate_pass: bool
    inventory_stage: str
    export_volume_yoy_pct: float | None
    export_asp_yoy_pct: float | None
    export_regime: str
    customs_asof_month: str | None
    alpha_leader_stock: str | None
    alpha_leader_name: str | None
    beta_elastic_stock: str | None
    beta_elastic_name: str | None
    top_elastic_stock: str | None
    top_elastic_stock_name: str | None
    top_eps_delta_per_100cny: float | None
    elasticity_asof_date: date | None
    cycle_phase: str
    composite_score: float
    cross_section_rank: int
    investment_stance: str
    data_confidence_pct: float
    key_rationale: str


class ChemicalCrossSectionMart:
    """化工多品种截面聚合与打分引擎。"""

    def __init__(
        self,
        curated_dir: Path | None = None,
        config_dir: Path | None = None,
        as_of_date: date | str | None = None,
    ) -> None:
        self.curated_dir = Path(curated_dir or DEFAULT_CURATED_DIR)
        self.config_dir = Path(config_dir or DEFAULT_CONFIG_DIR)
        self.mart_dir = self.curated_dir / "mart"

        if isinstance(as_of_date, str):
            self.as_of_date: date = date.fromisoformat(as_of_date)
        elif isinstance(as_of_date, date):
            self.as_of_date = as_of_date
        else:
            self.as_of_date = date.today()

    def _load_parquet_safe(self, relative_path: str) -> pl.DataFrame | None:
        """安全读取 Parquet 表，缺失时返回 None。"""
        full_path = self.curated_dir / relative_path
        if not full_path.exists():
            logger.warning("数据表不存在: %s", full_path)
            return None
        try:
            return pl.read_parquet(full_path)
        except Exception as exc:
            logger.warning("读取数据表异常 [%s]: %s", full_path, exc)
            return None

    def _load_submodule_universe(self, submodule: str) -> tuple[dict[str, str], dict[str, str]]:
        """从各子模块 trading_gates.yaml 中读取领跑龙头与高弹性标的。"""
        gate_file = self.config_dir / submodule / "trading_gates.yaml"
        alpha_info: dict[str, str] = {}
        beta_info: dict[str, str] = {}

        if not gate_file.exists():
            return alpha_info, beta_info

        try:
            cfg = yaml.safe_load(gate_file.read_text(encoding="utf-8")) or {}
            target_mapping = cfg.get("target_universe_mapping", {})
            alphas = target_mapping.get("alpha_leader") or []
            if alphas and isinstance(alphas, list):
                alpha_info["symbol"] = alphas[0].get("symbol", "")
                alpha_info["name"] = alphas[0].get("name", "")
            betas = target_mapping.get("beta_elastic") or []
            if betas and isinstance(betas, list):
                beta_info["symbol"] = betas[0].get("symbol", "")
                beta_info["name"] = betas[0].get("name", "")
        except Exception as exc:
            logger.debug("解析 %s 异常: %s", gate_file, exc)

        return alpha_info, beta_info

    def _get_spot_price_latest(self, spot_prices_df: pl.DataFrame | None, sym: str) -> float | None:
        """从现货表中安全读取指定品种符号的最新出厂价。"""
        if spot_prices_df is None or spot_prices_df.is_empty():
            return None
        match_p = spot_prices_df.filter(pl.col("symbol").str.to_uppercase() == sym.upper())
        if match_p.is_empty():
            return None
        row = match_p.sort("trade_date").row(-1, named=True)
        val = row.get("spot_price_cny")
        return float(val) if val is not None else None

    def build_cross_section_frame(self) -> pl.DataFrame:
        """端到端构建截面矩阵。"""
        # 1. 预加载底层表
        cost_curves_df = self._load_parquet_safe("mart/chemical_cost_curves.parquet")
        spreads_df = self._load_parquet_safe("industry/chemical_spreads.parquet")
        spot_prices_df = self._load_parquet_safe("industry/chemical_spot_price.parquet")
        survey_df = self._load_parquet_safe("industry/chemical_weekly_survey.parquet")
        monthly_survey_df = self._load_parquet_safe("industry/chemical_monthly_survey.parquet")
        futures_inv_df = self._load_parquet_safe("industry/futures_inventory.parquet")
        customs_df = self._load_parquet_safe("mart/chemical_customs_export.parquet")
        elasticity_df = self._load_parquet_safe("mart/chemical_elasticity_mart.parquet")
        basis_inv_df = self._load_parquet_safe("mart/chemical_basis_inventory_mart.parquet")

        records_raw: list[dict[str, Any]] = []

        for spec in COMMODITY_SPECS:
            code = spec["code"]
            name = spec["name"]
            submodule = spec["submodule"]
            category = spec["category"]
            f_sym = spec["futures_symbol"]

            # --- A. 成本曲线与现货价 ---
            spot_price = 0.0
            marginal_cash_cost: float | None = None
            cash_cost_coverage: float | None = None
            cost_curve_regime = "unknown"
            is_cash_breached = False
            cost_curve_asof_date: date | None = None
            spot_price_asof_date: date | None = None

            if cost_curves_df is not None and not cost_curves_df.is_empty():
                match_cc = cost_curves_df.filter(
                    pl.col("commodity_code").str.to_uppercase() == code.upper()
                )
                if not match_cc.is_empty():
                    row_cc = match_cc.sort("trade_date").row(-1, named=True)
                    cost_curve_asof_date = row_cc.get("trade_date")
                    spot_price = float(row_cc.get("spot_price_cny") or 0.0)
                    marginal_cash_cost = (
                        float(row_cc["marginal_cash_cost_cny"])
                        if row_cc.get("marginal_cash_cost_cny") is not None
                        else None
                    )
                    cash_cost_coverage = (
                        float(row_cc["cash_cost_coverage_pct"])
                        if row_cc.get("cash_cost_coverage_pct") is not None
                        else None
                    )
                    cost_curve_regime = str(row_cc.get("curve_regime") or "unknown")
                    is_cash_breached = bool(row_cc.get("bottom_signal_triggered", False))
                    if spot_price > 0.0:
                        spot_price_asof_date = row_cc.get("trade_date")

            # --- B. 理论价差与利润相位 ---
            spread_margin: float | None = None
            margin_regime = "unknown"
            spread_asof_date: date | None = None

            if spreads_df is not None and not spreads_df.is_empty():
                sym_col = "symbol" if "symbol" in spreads_df.columns else "commodity_code"
                match_sp = spreads_df.filter(pl.col(sym_col).str.to_uppercase() == code.upper())
                if not match_sp.is_empty():
                    row_sp = match_sp.sort("trade_date").row(-1, named=True)
                    spread_asof_date = row_sp.get("trade_date")
                    if spot_price <= 0.0 and row_sp.get("product_price_cny") is not None:
                        spot_price = float(row_sp["product_price_cny"])
                        spot_price_asof_date = row_sp.get("trade_date")
                    spread_margin = (
                        float(row_sp["spread_margin_cny"])
                        if row_sp.get("spread_margin_cny") is not None
                        else None
                    )
                    margin_regime = str(row_sp.get("margin_regime") or "unknown")

            # --- B2. 优先从黄金现货表 chemical_spot_price 补足真实出厂价 ---
            if spot_price <= 0.0 and spot_prices_df is not None and not spot_prices_df.is_empty():
                sym_col = "symbol" if "symbol" in spot_prices_df.columns else "commodity_code"
                match_sp = spot_prices_df.filter(pl.col(sym_col).str.to_uppercase() == code.upper())
                if not match_sp.is_empty():
                    row_sp = match_sp.sort("trade_date").row(-1, named=True)
                    spot_price = float(row_sp.get("spot_price_cny") or 0.0)
                    if spot_price > 0.0:
                        spot_price_asof_date = row_sp.get("trade_date")

            if spot_price <= 0.0:
                logger.warning(
                    "品种 %s (%s) 未从成本曲线、价差或现货事实表中匹配到有效现货价格", code, name
                )

            if code.upper() == "SH" and 0.0 < spot_price < 1200.0:
                spot_price = round(spot_price * 3.125, 2)

            # --- B3. P1 理论价差动态派生补偿 (当 chemical_spreads 未涵盖时根据现货原料自动补齐) ---
            if spread_margin is None and spot_price > 0.0:
                c_upper = code.upper()
                if c_upper == "MA":
                    coal_p = self._get_spot_price_latest(spot_prices_df, "ZC") or 750.0
                    spread_margin = round(spot_price - 1.6 * coal_p - 650.0, 2)
                    margin_regime = (
                        "high_profit"
                        if spread_margin > 300.0
                        else ("profitable" if spread_margin > 0.0 else "deep_loss")
                    )
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "MEG":
                    coal_p = self._get_spot_price_latest(spot_prices_df, "ZC") or 750.0
                    spread_margin = round(spot_price - 2.3 * coal_p - 1300.0, 2)
                    margin_regime = (
                        "super_profit"
                        if spread_margin > 600.0
                        else ("profitable" if spread_margin > 150.0 else "deep_loss")
                    )
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "R32":
                    hf_p = self._get_spot_price_latest(spot_prices_df, "HF") or 16000.0
                    ch2cl2_p = self._get_spot_price_latest(spot_prices_df, "CH2Cl2") or 2350.0
                    spread_margin = round(spot_price - 0.63 * hf_p - 1.4 * ch2cl2_p - 1800.0, 2)
                    margin_regime = "super_profit" if spread_margin > 5000.0 else "profitable"
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "V":
                    spread_margin = round(spot_price - 5800.0, 2)
                    margin_regime = (
                        "super_profit"
                        if spread_margin > 600.0
                        else (
                            "profitable"
                            if spread_margin > 100.0
                            else ("near_breakeven" if spread_margin > -300.0 else "deep_loss")
                        )
                    )
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "MDI":
                    spread_margin = round(spot_price - 17500.0, 2)
                    margin_regime = "normal_profit" if spread_margin >= 0.0 else "deep_loss"
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "UR":
                    coal_p = self._get_spot_price_latest(spot_prices_df, "ZC") or 750.0
                    spread_margin = round(spot_price - 1.2 * coal_p - 450.0, 2)
                    if spread_margin >= 600.0:
                        margin_regime = "super_profit"
                    elif spread_margin >= 350.0:
                        margin_regime = "high_profit"
                    elif spread_margin >= 100.0:
                        margin_regime = "profitable"
                    elif spread_margin >= -150.0:
                        margin_regime = "marginal_loss"
                    else:
                        margin_regime = "deep_loss"
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "SH":
                    spread_margin = round(spot_price - 2100.0, 2)
                    if spread_margin >= 400.0:
                        margin_regime = "high_profit"
                    elif spread_margin >= 100.0:
                        margin_regime = "profitable"
                    elif spread_margin >= -150.0:
                        margin_regime = "marginal_loss"
                    else:
                        margin_regime = "deep_loss"
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "EB":
                    spread_margin = round(spot_price - 8500.0, 2)
                    if spread_margin >= 400.0:
                        margin_regime = "high_profit"
                    elif spread_margin >= 100.0:
                        margin_regime = "profitable"
                    elif spread_margin >= -200.0:
                        margin_regime = "near_breakeven"
                    else:
                        margin_regime = "deep_loss"
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "PP":
                    spread_margin = round(spot_price - 8000.0, 2)
                    if spread_margin >= 500.0:
                        margin_regime = "high_profit"
                    elif spread_margin >= 100.0:
                        margin_regime = "profitable"
                    elif spread_margin >= -300.0:
                        margin_regime = "near_breakeven"
                    else:
                        margin_regime = "deep_loss"
                    spread_asof_date = spot_price_asof_date
                elif c_upper == "PX":
                    spread_margin = round(spot_price - 8200.0, 2)
                    if spread_margin >= 600.0:
                        margin_regime = "high_profit"
                    elif spread_margin >= 200.0:
                        margin_regime = "profitable"
                    elif spread_margin >= -300.0:
                        margin_regime = "near_breakeven"
                    else:
                        margin_regime = "deep_loss"
                    spread_asof_date = spot_price_asof_date

            # --- C. 开工率与企业库存 (含历史无量纲分位数与月度平滑代偿) ---
            operating_rate: float | None = None
            operating_rate_pctl: float | None = None
            factory_inv: float | None = None
            inventory_pctl: float | None = None
            stale_warnings: list[str] = []
            operating_rate_asof_date: date | None = None
            inventory_asof_date: date | None = None
            op_series: pl.Series | None = None
            inv_series: pl.Series | None = None

            if survey_df is not None and not survey_df.is_empty():
                sym_c = "symbol" if "symbol" in survey_df.columns else "product_name"
                match_sv = survey_df.filter(
                    (pl.col(sym_c).str.to_uppercase() == code.upper())
                    | (pl.col("product_name").str.contains(name))
                ).sort("trade_date")
                if not match_sv.is_empty():
                    valid_op = match_sv.filter(pl.col("operating_rate_pct").is_not_null())
                    if not valid_op.is_empty():
                        last_op_row = valid_op.row(-1, named=True)
                        operating_rate = float(last_op_row["operating_rate_pct"])
                        op_d = last_op_row.get("report_date") or last_op_row.get("trade_date")
                        if isinstance(op_d, str):
                            try:
                                op_d = date.fromisoformat(op_d)
                            except ValueError:
                                op_d = None
                        if isinstance(op_d, date):
                            operating_rate_asof_date = op_d
                        op_series = valid_op["operating_rate_pct"]

                    valid_inv = match_sv.filter(pl.col("factory_inventory_w_tons").is_not_null())
                    if not valid_inv.is_empty():
                        last_inv_row = valid_inv.row(-1, named=True)
                        factory_inv = float(last_inv_row["factory_inventory_w_tons"])
                        inv_d = last_inv_row.get("report_date") or last_inv_row.get("trade_date")
                        if isinstance(inv_d, str):
                            try:
                                inv_d = date.fromisoformat(inv_d)
                            except ValueError:
                                inv_d = None
                        if isinstance(inv_d, date):
                            inventory_asof_date = inv_d
                        inv_series = valid_inv["factory_inventory_w_tons"]

            # C2. 月度调查表回退代偿 (当周度缺失或滞后且月度有更新时平滑代偿)
            if monthly_survey_df is not None and not monthly_survey_df.is_empty():
                sym_mc = "symbol" if "symbol" in monthly_survey_df.columns else "product_name"
                match_msv = monthly_survey_df.filter(
                    (pl.col(sym_mc).str.to_uppercase() == code.upper())
                    | (pl.col("product_name").str.contains(name))
                )
                if not match_msv.is_empty():
                    valid_m_op = match_msv.filter(pl.col("operating_rate_pct").is_not_null())
                    if not valid_m_op.is_empty():
                        sort_c = (
                            "release_date"
                            if "release_date" in valid_m_op.columns
                            else "report_month"
                        )
                        last_m_op = valid_m_op.sort(sort_c).row(-1, named=True)
                        m_op_val = float(last_m_op["operating_rate_pct"])
                        m_op_d = last_m_op.get("release_date")
                        if isinstance(m_op_d, str):
                            try:
                                m_op_d = date.fromisoformat(m_op_d)
                            except ValueError:
                                m_op_d = None
                        elif not isinstance(m_op_d, date) and last_m_op.get("report_month"):
                            try:
                                ym = str(last_m_op["report_month"]).split("-")
                                _, last_day = calendar.monthrange(int(ym[0]), int(ym[1]))
                                m_op_d = date(int(ym[0]), int(ym[1]), last_day)
                            except Exception:
                                m_op_d = None

                        # 周度缺失或月度调查显著新于周度调查时激活回退
                        if operating_rate_asof_date is None or (
                            isinstance(m_op_d, date) and m_op_d > operating_rate_asof_date
                        ):
                            operating_rate = m_op_val
                            if isinstance(m_op_d, date):
                                operating_rate_asof_date = m_op_d

                    valid_m_inv = match_msv.filter(pl.col("factory_inventory_w_tons").is_not_null())
                    if not valid_m_inv.is_empty():
                        sort_c = (
                            "release_date"
                            if "release_date" in valid_m_inv.columns
                            else "report_month"
                        )
                        last_m_inv = valid_m_inv.sort(sort_c).row(-1, named=True)
                        m_inv_val = float(last_m_inv["factory_inventory_w_tons"])
                        m_inv_d = last_m_inv.get("release_date")
                        if isinstance(m_inv_d, str):
                            try:
                                m_inv_d = date.fromisoformat(m_inv_d)
                            except ValueError:
                                m_inv_d = None
                        elif not isinstance(m_inv_d, date) and last_m_inv.get("report_month"):
                            try:
                                ym = str(last_m_inv["report_month"]).split("-")
                                _, last_day = calendar.monthrange(int(ym[0]), int(ym[1]))
                                m_inv_d = date(int(ym[0]), int(ym[1]), last_day)
                            except Exception:
                                m_inv_d = None

                        # 企业库存回退：当周度无库存或月度更新，且月度时效合格 (<= 30 天) 时代偿
                        if inventory_asof_date is None or (
                            isinstance(m_inv_d, date) and m_inv_d > inventory_asof_date
                        ):
                            if isinstance(m_inv_d, date) and (self.as_of_date - m_inv_d).days <= 30:
                                factory_inv = m_inv_val
                                inventory_asof_date = m_inv_d

            # 评估最终开工率分位数与时效性
            is_op_stale = False
            if operating_rate is not None:
                op_days = (
                    (self.as_of_date - operating_rate_asof_date).days
                    if isinstance(operating_rate_asof_date, date)
                    else 999
                )
                if op_days > 30:
                    is_op_stale = True
                    stale_warnings.append(
                        f"开工率取自{operating_rate_asof_date}(过期滞后{op_days}天,隔离打分)"
                    )
                elif op_days > 14:
                    stale_warnings.append(
                        f"开工率取自{operating_rate_asof_date}(轻度滞后{op_days}天)"
                    )
                if op_series is not None and len(op_series) > 1:
                    rank = int((op_series < operating_rate).sum()) + 1
                    operating_rate_pctl = round((rank - 1) / (len(op_series) - 1) * 100.0, 1)

            # 评估最终企业库存分位数与时效性
            is_inv_stale = False
            if factory_inv is not None:
                inv_days = (
                    (self.as_of_date - inventory_asof_date).days
                    if isinstance(inventory_asof_date, date)
                    else 999
                )
                if inv_days > 30:
                    is_inv_stale = True
                    stale_warnings.append(
                        f"企业库存取自{inventory_asof_date}(过期滞后{inv_days}天,隔离打分)"
                    )
                elif inv_days > 14:
                    stale_warnings.append(
                        f"企业库存取自{inventory_asof_date}(轻度滞后{inv_days}天)"
                    )
                if inv_series is not None and len(inv_series) > 1:
                    rank = int((inv_series < factory_inv).sum()) + 1
                    inventory_pctl = round((rank - 1) / (len(inv_series) - 1) * 100.0, 1)

            # --- D. 期货基差与注册仓单异动 (消费 chemical_basis_inventory_mart) ---
            basis_cny: float | None = None
            basis_rate_pct: float | None = None
            basis_term_structure = "unknown"
            receipts: float | None = None
            receipts_w_tons: float | None = None
            receipts_pctl: float | None = None
            receipts_accel_status = "unknown"
            composite_micro_regime = "unknown"
            right_side_basis_gate_pass = False
            basis_asof_date: date | None = None

            if f_sym and basis_inv_df is not None and not basis_inv_df.is_empty():
                match_bi = basis_inv_df.filter(
                    (pl.col("commodity_code").str.to_uppercase() == code.upper())
                    | (pl.col("futures_symbol").str.to_uppercase() == f_sym.upper())
                ).sort("trade_date")
                if not match_bi.is_empty():
                    row_bi = match_bi.row(-1, named=True)
                    basis_asof_date = row_bi.get("trade_date")
                    basis_cny = (
                        float(row_bi["basis_cny"]) if row_bi.get("basis_cny") is not None else None
                    )
                    basis_rate_pct = (
                        float(row_bi["basis_rate_pct"])
                        if row_bi.get("basis_rate_pct") is not None
                        else None
                    )
                    basis_term_structure = str(row_bi.get("basis_term_structure") or "unknown")
                    receipts = (
                        float(row_bi["warehouse_receipts_contracts"])
                        if row_bi.get("warehouse_receipts_contracts") is not None
                        else None
                    )
                    receipts_w_tons = (
                        float(row_bi["warehouse_receipts_w_tons"])
                        if row_bi.get("warehouse_receipts_w_tons") is not None
                        else None
                    )
                    receipts_pctl = (
                        float(row_bi["receipts_pctl_1y"])
                        if row_bi.get("receipts_pctl_1y") is not None
                        else None
                    )
                    receipts_accel_status = str(
                        row_bi.get("receipts_acceleration_status") or "unknown"
                    )
                    composite_micro_regime = str(row_bi.get("composite_micro_regime") or "unknown")
                    right_side_basis_gate_pass = bool(
                        row_bi.get("right_side_basis_gate_pass", False)
                    )
            elif f_sym and futures_inv_df is not None and not futures_inv_df.is_empty():
                match_fi = futures_inv_df.filter(pl.col("symbol") == f_sym)
                if not match_fi.is_empty():
                    row_fi = match_fi.sort("trade_date").row(-1, named=True)
                    basis_asof_date = row_fi.get("trade_date")
                    receipts = (
                        float(row_fi["inventory"]) if row_fi.get("inventory") is not None else None
                    )

            # --- E. 海关出口量价与四象限 ---
            export_vol_yoy: float | None = None
            export_asp_yoy: float | None = None
            export_regime = "unknown"
            customs_asof_month: str | None = None

            if customs_df is not None and not customs_df.is_empty():
                match_cu = customs_df.filter(
                    pl.col("commodity_code").str.to_uppercase() == code.upper()
                )
                if not match_cu.is_empty():
                    row_cu = match_cu.sort("trade_date").row(-1, named=True)
                    cu_month = row_cu.get("report_month")
                    customs_asof_month = str(cu_month) if cu_month else None
                    export_vol_yoy = (
                        float(row_cu["export_volume_yoy_pct"])
                        if row_cu.get("export_volume_yoy_pct") is not None
                        else None
                    )
                    export_asp_yoy = (
                        float(row_cu["export_asp_yoy_pct"])
                        if row_cu.get("export_asp_yoy_pct") is not None
                        else None
                    )
                    export_regime = str(row_cu.get("export_regime") or "unknown")

            # --- F. 上市公司标的与业绩弹性 ---
            alpha_info, beta_info = self._load_submodule_universe(submodule)
            top_stock: str | None = None
            top_stock_name: str | None = None
            top_eps_delta: float | None = None
            elasticity_asof_date: date | None = None

            if elasticity_df is not None and not elasticity_df.is_empty():
                match_el = elasticity_df.filter(
                    pl.col("commodity_code").str.to_uppercase() == code.upper()
                ).sort("eps_delta_per_100cny", descending=True)
                if not match_el.is_empty():
                    top_row = match_el.row(0, named=True)
                    elasticity_asof_date = top_row.get("trade_date")
                    top_stock = str(top_row.get("symbol") or "")
                    top_stock_name = str(top_row.get("company_name") or "")
                    top_eps_delta = (
                        float(top_row["eps_delta_per_100cny"])
                        if top_row.get("eps_delta_per_100cny") is not None
                        else None
                    )

            if not top_stock and alpha_info.get("symbol"):
                top_stock = alpha_info["symbol"]
                top_stock_name = alpha_info["name"]

            # --- G. 周期状态机推断与打分 ---
            inv_stage = self._infer_inventory_stage(
                margin_regime=margin_regime,
                cost_regime=cost_curve_regime,
                export_regime=export_regime,
                category=category,
            )

            # --- P0. 综合数据时效与置信度量化打分 (data_confidence_pct) ---
            # 1. 现货价格维度 (25分)
            p_conf = 0.0
            if spot_price > 0.0 and spot_price_asof_date:
                s_days = (self.as_of_date - spot_price_asof_date).days
                p_conf = 25.0 if s_days <= 14 else (15.0 if s_days <= 30 else 5.0)

            # 2. 成本/价差模型维度 (25分)
            cost_conf = 0.0
            if marginal_cash_cost is not None or spread_margin is not None:
                c_date = spread_asof_date or cost_curve_asof_date
                c_days = (self.as_of_date - c_date).days if isinstance(c_date, date) else 999
                cost_conf = 25.0 if c_days <= 14 else (15.0 if c_days <= 30 else 10.0)

            # 3. 周度开工率维度 (15分)
            op_conf = 0.0
            if operating_rate is not None and not is_op_stale:
                op_days = (
                    (self.as_of_date - operating_rate_asof_date).days
                    if isinstance(operating_rate_asof_date, date)
                    else 999
                )
                op_conf = 15.0 if op_days <= 14 else 10.0

            # 4. 企业库存维度 (15分)
            inv_conf = 0.0
            if factory_inv is not None and not is_inv_stale:
                inv_days = (
                    (self.as_of_date - inventory_asof_date).days
                    if isinstance(inventory_asof_date, date)
                    else 999
                )
                inv_conf = 15.0 if inv_days <= 14 else 10.0

            # 5. 微观基差仓单或海关出口维度 (20分)
            micro_conf = 0.0
            if basis_cny is not None or receipts is not None:
                micro_conf = 20.0
            elif export_vol_yoy is not None or export_asp_yoy is not None:
                micro_conf = 18.0

            data_confidence_pct = round(p_conf + cost_conf + op_conf + inv_conf + micro_conf, 1)

            cycle_phase, score, stance, rationale = self._evaluate_cross_section(
                code=code,
                name=name,
                category=category,
                spot_price=spot_price,
                marginal_cash_cost=marginal_cash_cost,
                cash_coverage=cash_cost_coverage,
                cost_regime=cost_curve_regime,
                is_cash_breached=is_cash_breached,
                margin_regime=margin_regime,
                inv_stage=inv_stage,
                export_regime=export_regime,
                export_vol_yoy=export_vol_yoy,
                alpha_leader=alpha_info.get("name") or top_stock_name or name,
                basis_term_structure=basis_term_structure,
                basis_rate_pct=basis_rate_pct,
                receipts_accel_status=receipts_accel_status,
                receipts_pctl=receipts_pctl,
                composite_micro_regime=composite_micro_regime,
                stale_warnings=stale_warnings,
                operating_rate=operating_rate,
                factory_inv=factory_inv,
                operating_rate_asof_date=operating_rate_asof_date,
                inventory_asof_date=inventory_asof_date,
                as_of_date=self.as_of_date,
            )

            records_raw.append(
                {
                    "as_of_date": self.as_of_date,
                    "commodity_code": code,
                    "commodity_name": name,
                    "submodule_dir": submodule,
                    "category_archetype": category,
                    "futures_symbol": f_sym,
                    "spot_price_cny": spot_price,
                    "spot_price_asof_date": spot_price_asof_date,
                    "marginal_cash_cost_cny": marginal_cash_cost,
                    "cash_cost_coverage_pct": cash_cost_coverage,
                    "cost_curve_regime": cost_curve_regime,
                    "cost_curve_asof_date": cost_curve_asof_date,
                    "is_cash_cost_breached": is_cash_breached,
                    "spread_margin_cny": spread_margin,
                    "margin_regime": margin_regime,
                    "spread_asof_date": spread_asof_date,
                    "operating_rate_pct": operating_rate,
                    "operating_rate_pctl": operating_rate_pctl,
                    "operating_rate_asof_date": operating_rate_asof_date,
                    "factory_inventory_w_tons": factory_inv,
                    "inventory_pctl": inventory_pctl,
                    "inventory_asof_date": inventory_asof_date,
                    "warehouse_receipts": receipts,
                    "basis_cny": basis_cny,
                    "basis_rate_pct": basis_rate_pct,
                    "basis_term_structure": basis_term_structure,
                    "basis_asof_date": basis_asof_date,
                    "warehouse_receipts_w_tons": receipts_w_tons,
                    "receipts_pctl_1y": receipts_pctl,
                    "receipts_acceleration_status": receipts_accel_status,
                    "composite_micro_regime": composite_micro_regime,
                    "right_side_basis_gate_pass": right_side_basis_gate_pass,
                    "inventory_stage": inv_stage,
                    "export_volume_yoy_pct": export_vol_yoy,
                    "export_asp_yoy_pct": export_asp_yoy,
                    "export_regime": export_regime,
                    "customs_asof_month": customs_asof_month,
                    "alpha_leader_stock": alpha_info.get("symbol"),
                    "alpha_leader_name": alpha_info.get("name"),
                    "beta_elastic_stock": beta_info.get("symbol"),
                    "beta_elastic_name": beta_info.get("name"),
                    "top_elastic_stock": top_stock,
                    "top_elastic_stock_name": top_stock_name,
                    "top_eps_delta_per_100cny": top_eps_delta,
                    "elasticity_asof_date": elasticity_asof_date,
                    "cycle_phase": cycle_phase,
                    "composite_score": score,
                    "cross_section_rank": 0,  # 稍后排序
                    "investment_stance": stance,
                    "data_confidence_pct": data_confidence_pct,
                    "key_rationale": rationale,
                }
            )

        if not records_raw:
            return pl.DataFrame(schema=CROSS_SECTION_SCHEMA)

        # 氯碱 ECU 闭环双向联动增强
        v_rec = next((r for r in records_raw if r["commodity_code"] == "V"), None)
        sh_rec = next((r for r in records_raw if r["commodity_code"] == "SH"), None)
        if v_rec and sh_rec:
            if sh_rec.get("cash_cost_coverage_pct") and sh_rec["cash_cost_coverage_pct"] >= 90.0:
                if v_rec.get("margin_regime") == "deep_loss" or v_rec.get("is_cash_cost_breached"):
                    v_rat = str(v_rec["key_rationale"]).rstrip("；。 ")
                    sh_rat = str(sh_rec["key_rationale"]).rstrip("；。 ")
                    v_rec["key_rationale"] = (
                        v_rat
                        + "；[氯碱ECU平衡: 烧碱端高毛利反哺对冲PVC亏损，全行业“以碱补氯”，延缓冷修减产出清节奏]"
                    )
                    sh_rec["key_rationale"] = (
                        sh_rat
                        + "；[氯碱ECU平衡: 伴生副产氯气依赖PVC消化，PVC端深亏累库或引发胀气反噬烧碱开工负荷]"
                    )

        df = pl.DataFrame(records_raw, schema=CROSS_SECTION_SCHEMA)
        # 降序排名 (显式指定 Int32 契约)
        df = df.sort("composite_score", descending=True).with_columns(
            pl.int_range(1, pl.len() + 1, dtype=pl.Int32).alias("cross_section_rank")
        )
        return df

    def _infer_inventory_stage(
        self,
        margin_regime: str,
        cost_regime: str,
        export_regime: str,
        category: str,
    ) -> str:
        """结合价差利润与外需动量判定四阶段动态库存周期。"""
        if category == "C_quota_regulated":
            return (
                "active_restocking"
                if export_regime in ("price_driven", "volume_price_boom")
                else "passive_destocking"
            )

        if cost_regime == "deep_cash_drain_bottom" or margin_regime == "deep_loss":
            return "active_destocking"  # 倒逼减产停机甩货

        if margin_regime in ("super_profit", "high_profit"):
            if export_regime in ("double_weak", "export_contraction"):
                return "passive_accumulation"  # 景气高位需求转弱累库
            return "active_restocking"  # 繁荣期主动备库

        if margin_regime in ("normal", "moderate_profit"):
            if export_regime in ("volume_driven", "volume_price_boom"):
                return "passive_destocking"  # 需求驱动被动去库
            return "neutral_balanced"

        return "neutral_balanced"

    def _evaluate_cross_section(
        self,
        code: str,
        name: str,
        category: str,
        spot_price: float,
        marginal_cash_cost: float | None,
        cash_coverage: float | None,
        cost_regime: str,
        is_cash_breached: bool,
        margin_regime: str,
        inv_stage: str,
        export_regime: str,
        export_vol_yoy: float | None,
        alpha_leader: str,
        basis_term_structure: str = "unknown",
        basis_rate_pct: float | None = None,
        receipts_accel_status: str = "unknown",
        receipts_pctl: float | None = None,
        composite_micro_regime: str = "unknown",
        stale_warnings: list[str] | None = None,
        operating_rate: float | None = None,
        factory_inv: float | None = None,
        operating_rate_asof_date: date | None = None,
        inventory_asof_date: date | None = None,
        as_of_date: date | None = None,
    ) -> tuple[str, float, str, str]:
        """确定性量化打分规则引擎。"""
        cur_as_of = as_of_date or self.as_of_date
        effective_operating_rate = operating_rate
        effective_factory_inv = factory_inv

        if stale_warnings is None:
            stale_warnings = []
            if operating_rate is not None and isinstance(operating_rate_asof_date, date):
                op_days = (cur_as_of - operating_rate_asof_date).days
                if op_days > 30:
                    stale_warnings.append(
                        f"开工率取自{operating_rate_asof_date}(过期滞后{op_days}天,隔离打分)"
                    )
                elif op_days > 14:
                    stale_warnings.append(
                        f"开工率取自{operating_rate_asof_date}(轻度滞后{op_days}天)"
                    )
            if factory_inv is not None and isinstance(inventory_asof_date, date):
                inv_days = (cur_as_of - inventory_asof_date).days
                if inv_days > 30:
                    stale_warnings.append(
                        f"企业库存取自{inventory_asof_date}(过期滞后{inv_days}天,隔离打分)"
                    )
                elif inv_days > 14:
                    stale_warnings.append(
                        f"企业库存取自{inventory_asof_date}(轻度滞后{inv_days}天)"
                    )

        # P0 时效过期隔离：若开工率或企业库存滞后超过 30 天，判定失效不参与打分逻辑
        if operating_rate is not None and isinstance(operating_rate_asof_date, date):
            if (cur_as_of - operating_rate_asof_date).days > 30:
                effective_operating_rate = None
        if factory_inv is not None and isinstance(inventory_asof_date, date):
            if (cur_as_of - inventory_asof_date).days > 30:
                effective_factory_inv = None

        def _finish(cp: str, sc: float, st: str, rat: str) -> tuple[str, float, str, str]:
            if stale_warnings:
                tail = rat.rstrip()
                lag_text = f"[数据滞后提示: {', '.join(stale_warnings)}]"
                if tail.endswith("；") or tail.endswith("。"):
                    rat = tail + lag_text
                else:
                    rat = (tail + "；" + lag_text) if tail else lag_text
            return cp, sc, st, rat

        score = 50.0
        cycle_phase = "BALANCED"
        stance = "NEUTRAL_WATCH"
        rationale_parts: list[str] = []

        # 0. 核心数据防线：现货基准出厂价缺失或异常 (P1 守卫)
        if spot_price is None or spot_price <= 0:
            score = 50.0
            cycle_phase = "DATA_INCOMPLETE"
            stance = "NEUTRAL_WATCH"
            rationale_parts.append(
                "[数据缺失] 现货基准出厂价缺失或为0，暂无真实有效价格数据支撑周期判定；保持中性跟踪。"
            )
            return _finish(cycle_phase, score, stance, "".join(rationale_parts))

        # 1. 行政配额管制型 (制冷剂): 刚性供给 + 外需景气
        if category == "C_quota_regulated":
            if marginal_cash_cost is None:
                # 缺少多工艺边际成本曲线模型支持，置信度折价至 75 分
                score = 75.0
                cycle_phase = "RIGHT_EXPANSION"
                stance = "OVERWEIGHT_RIGHT"
                rationale_parts.append(
                    f"[维度不完整: 缺成本模型] 法定配额供给刚性，外需{export_regime}维持溢价；首选龙头{alpha_leader}。"
                )
            else:
                score = 90.0
                cycle_phase = "RIGHT_EXPANSION"
                stance = "OVERWEIGHT_RIGHT"
                if export_regime in ("price_driven", "volume_price_boom"):
                    score += 5.0
                rationale_parts.append(
                    f"法定配额冻结永久切断供给新增 Capex，外需{export_regime}支撑高溢价，右侧高景气持续；首选龙头{alpha_leader}。"
                )
            return _finish(cycle_phase, min(score, 99.0), stance, "".join(rationale_parts))

        # 2. 边际成本击穿左侧大底判定 (纯碱/PVC/甲醇等)
        if (
            is_cash_breached
            or cost_regime == "deep_cash_drain_bottom"
            or (cash_coverage is not None and cash_coverage < 80.0)
        ):
            score = 80.0
            cycle_phase = "LEFT_BOTTOM"
            stance = "OVERWEIGHT_LEFT"
            score += max(0.0, (80.0 - (cash_coverage or 75.0)) * 0.5)
            cov_str = f"覆盖率仅 {cash_coverage:.1f}%" if cash_coverage else "深度失血"
            rationale_parts.append(
                f"市价已击穿边际高成本装置现金保本底线({cov_str})，倒逼冷修减产，触发左侧极值赔率大底；逢低建仓抗亏龙头{alpha_leader}。"
            )
            if composite_micro_regime == "STRONG_BULLISH_REVERSAL":
                score += 3.0
                rationale_parts.append("期现现货升水且交易所仓单加速注销，微观结构强共振看多；")
            elif composite_micro_regime == "BEARISH_CONTANGO_OVERHANG":
                b_str = f"{basis_rate_pct:+.1f}%" if basis_rate_pct is not None else "贴水"
                p_str = f"{receipts_pctl:.0f}%" if receipts_pctl is not None else "高位"
                rationale_parts.append(
                    f"但期货深度贴水({b_str})且交易所天量仓单压顶(分位 {p_str})，右侧反转需等待显性库存消化；"
                )
            return _finish(cycle_phase, min(score, 95.0), stance, "".join(rationale_parts))

        # 3. 寡头中游与被动去库反转 (钛白粉/MDI) (P2 守卫与 TiO2 偏乐观守卫)
        if category == "B_oligopoly":
            has_weekly_data = (effective_operating_rate is not None) or (
                effective_factory_inv is not None
            )
            if not has_weekly_data:
                score = 65.0
                cycle_phase = "BALANCED"
                stance = "NEUTRAL_WATCH"
                cost_tag = (
                    "缺成本曲线与开工库存" if marginal_cash_cost is None else "缺周度开工与企业库存"
                )
                rationale_parts.append(
                    f"[维度不完整: {cost_tag}] 寡头格局平稳，外需{export_regime}，但缺乏高频库存确证，防止乐观偏差；暂持中性跟踪；首选龙头{alpha_leader}。"
                )
            elif effective_operating_rate is not None and effective_factory_inv is None:
                # 真实开工率已就绪，企业库存仍缺失
                op_str = f"开工率 {effective_operating_rate:.1f}%"
                if inv_stage == "passive_destocking" or (export_vol_yoy and export_vol_yoy > 0):
                    score = 70.0
                    cycle_phase = "RIGHT_REVERSAL"
                    stance = "OVERWEIGHT_RIGHT"
                    rationale_parts.append(
                        f"[维度部分完整: 缺周度企业库存] 寡头格局稳固，{op_str}正常运转，海外外需{export_regime}支撑出口，右侧温和向好；逢低配置龙头{alpha_leader}。"
                    )
                else:
                    score = 66.0
                    cycle_phase = "BALANCED"
                    stance = "NEUTRAL_WATCH"
                    rationale_parts.append(
                        f"[维度部分完整: 缺周度企业库存] 寡头格局平稳，{op_str}运转，供需处于观望整理态势；跟踪龙头{alpha_leader}。"
                    )
            elif inv_stage == "passive_destocking" or (export_vol_yoy and export_vol_yoy > 0):
                score = 72.0
                cycle_phase = "RIGHT_REVERSAL"
                stance = "OVERWEIGHT_RIGHT"
                rationale_parts.append(
                    f"寡头协同控盘格局稳固，海外补库驱动被动去库，龙头挂牌价具有强支撑；逢低增配{alpha_leader}。"
                )
            else:
                score = 65.0
                cycle_phase = "BALANCED"
                stance = "NEUTRAL_WATCH"
                rationale_parts.append("寡头中游格局平稳，下游需求渐进修复，保持中性跟踪。")
            return _finish(cycle_phase, score, stance, "".join(rationale_parts))

        # 4. 普通完全竞争大宗品高位钝化与累库 (A 类)
        if cost_regime == "super_profit" or margin_regime in ("super_profit", "high_profit"):
            score = 38.0
            cycle_phase = "PEAK_OVERHEAT"
            stance = "UNDERWEIGHT_TRIM"
            rationale_parts.append(
                "处于高盈利/暴利区间，警惕行业装置开工打满及远期产能投产压制，静态低PE陷阱风险大，逢高减配。"
            )
            return _finish(cycle_phase, score, stance, "".join(rationale_parts))

        if inv_stage == "passive_accumulation":
            score = 42.0
            cycle_phase = "MID_RECESSION"
            stance = "UNDERWEIGHT_TRIM"
            rationale_parts.append("需求端放缓显现，被动累库风险积聚，建议谨慎防守。")
            return _finish(cycle_phase, score, stance, "".join(rationale_parts))

        if inv_stage == "passive_destocking":
            score = 75.0
            cycle_phase = "RIGHT_REVERSAL"
            stance = "OVERWEIGHT_RIGHT"
            rationale_parts.append(
                "库存进入被动去化通道，需求边际转暖，右侧反弹动能增强；关注高弹性标的。"
            )
            return _finish(cycle_phase, score, stance, "".join(rationale_parts))

        # 默认平衡
        rationale_parts.append("供需维持弱平衡，吨毛利处于中枢窄幅震荡，暂无强方向信号。")
        return _finish(cycle_phase, score, stance, "".join(rationale_parts))

    def run_and_save(self) -> pl.DataFrame:
        """执行全流程构建并同时落盘 Parquet 与 CSV。"""
        self.mart_dir.mkdir(parents=True, exist_ok=True)
        df = self.build_cross_section_frame()

        parquet_path = self.mart_dir / CHEMICAL_CROSS_SECTION_MART_FILE
        csv_path = self.mart_dir / CHEMICAL_CROSS_SECTION_MART_CSV

        df.write_parquet(parquet_path)
        df.write_csv(csv_path)

        logger.info(
            "化工截面聚合 Mart 落盘成功: %s (%d 行), %s",
            parquet_path.name,
            len(df),
            csv_path.name,
        )
        return df


def format_cross_section_table(df: pl.DataFrame) -> str:
    """将截面 DataFrame 格式化为直观的投研 ASCII 报告大表。"""
    lines = [
        "=" * 162,
        f"  大宗化工全板块多品种横向截面景气度与配置雷达 ({df['as_of_date'][0] if not df.is_empty() else 'N/A'})",
        "=" * 162,
        (
            f"{'排名':<4} | {'代码':<5} | {'品种名称':<8} | {'分类属性':<14} | {'现货价':<7} | "
            f"{'现金成本击穿':<10} | {'开工率(分位)':<13} | {'期现结构(基差率)':<16} | "
            f"{'仓单(万吨/异动)':<18} | {'评分':<5} | {'置信度':<6} | {'配置定调':<16} | {'核心标的':<10}"
        ),
        "-" * 162,
    ]
    for row in df.iter_rows(named=True):
        rank = row["cross_section_rank"]
        code = row["commodity_code"]
        name = row["commodity_name"]
        cat = row["category_archetype"]
        price = (
            f"{row['spot_price_cny']:.0f}"
            if row.get("spot_price_cny") is not None and row["spot_price_cny"] > 0
            else "N/A"
        )
        breached = "【已击穿大底】" if row["is_cash_cost_breached"] else "正常"

        op_val = (
            f"{row['operating_rate_pct']:.1f}%"
            if row.get("operating_rate_pct") is not None
            else "-"
        )
        if row.get("operating_rate_pctl") is not None:
            op_val += f" ({row['operating_rate_pctl']:.0f}%)"

        # 期现结构与基差率
        if row.get("basis_term_structure") and row["basis_term_structure"] != "unknown":
            struct = row["basis_term_structure"][:4]
            rate = f"{row['basis_rate_pct']:+.1f}%" if row.get("basis_rate_pct") is not None else ""
            basis_str = f"{struct} {rate}"
        else:
            basis_str = "-"

        # 仓单与异动
        if row.get("warehouse_receipts_w_tons") is not None:
            w_tons = f"{row['warehouse_receipts_w_tons']:.1f}万t"
            acc = row.get("receipts_acceleration_status") or ""
            if acc == "ACCELERATED_DRAIN":
                acc_s = "加速注销"
            elif acc == "RAPID_ACCUMULATION":
                acc_s = "加速累单"
            else:
                acc_s = "平稳"
            warrant_str = f"{w_tons} ({acc_s})"
        else:
            warrant_str = "-"

        score = f"{row['composite_score']:.1f}"
        conf = f"{row.get('data_confidence_pct', 100.0):.0f}%"
        stance = row["investment_stance"]
        stock = row["alpha_leader_name"] or row["top_elastic_stock_name"] or "-"
        lines.append(
            f"{rank:<4} | {code:<5} | {name:<8} | {cat:<14} | {price:<7} | {breached:<10} | "
            f"{op_val:<13} | {basis_str:<16} | {warrant_str:<18} | {score:<5} | {conf:<6} | {stance:<16} | {stock:<10}"
        )
    lines.append("=" * 162)
    return "\n".join(lines)


def build_chemical_cross_section_mart(
    curated_dir: Path | str | None = None,
    config_dir: Path | str | None = None,
    as_of_date: date | str | None = None,
) -> pl.DataFrame:
    """构建并物化化工多品种横向截面 Mart 的便捷门面函数。"""
    engine = ChemicalCrossSectionMart(
        curated_dir=Path(curated_dir) if curated_dir else None,
        config_dir=Path(config_dir) if config_dir else None,
        as_of_date=as_of_date,
    )
    return engine.run_and_save()


def main() -> int:
    parser = argparse.ArgumentParser(description="化工多品种横向截面聚合 Mart 构建器")
    parser.add_argument("--as-of", type=date.fromisoformat, help="分析基准日 YYYY-MM-DD")
    parser.add_argument(
        "--curated-dir",
        type=Path,
        default=DEFAULT_CURATED_DIR,
        help="Curated 目录 (默认 data/curated)",
    )
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=DEFAULT_CONFIG_DIR,
        help="配置根目录 (默认 config/industry/chemicals)",
    )
    args = parser.parse_args()

    engine = ChemicalCrossSectionMart(
        curated_dir=args.curated_dir,
        config_dir=args.config_dir,
        as_of_date=args.as_of,
    )
    df = engine.run_and_save()
    print("\n" + format_cross_section_table(df) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
