"""化工产业链理论利润与加工费量化计算器 (ChemicalSpreadCalculator)。

权威量化金融工程公式:
1. 纯碱联碱双吨利润 (Double-Ton Margin):
   双吨利润 = 纯碱现货价 + 氯化铵现货价 - (1.2 * 原盐价 + 0.135 * 合成氨价折纯 + 0.4 * 动力煤价) - 450
2. PTA 理论加工费 (PTA Processing Spread):
   PTA 加工费 = PTA 现货价 - 0.655 * PX (对二甲苯价格)
   (行业平均固定加工成本 450~500 元/吨)
3. 煤制甲醇理论毛利 (Coal-to-Methanol Margin):
   甲醇毛利 = 甲醇现货价 - 1.6 * 动力煤价 - 650
4. 氯碱综合 ECU 理论利润 (Electro-Chemical Unit Margin):
   ECU 利润 = 烧碱折百价 + 0.886 * 液氯价 - 1.5 * 原盐价 - 2300 * 电价 - 300
5. 钛白粉硫酸法金红石型理论毛利 (TiO2 Sulfate Margin):
   理论毛利 = 钛白粉现货价 - (2.0 * 钛精矿价 + 3.5 * 浓硫酸价) - 3800
   (边际现金保本线 = 2.0 * 钛精矿价 + 3.5 * 浓硫酸价 + 2600)

事实来源:
- RAW: data/raw/industry/chemicals/chemical_spreads.csv
- Curated: data/curated/industry/chemical_spreads.parquet
"""

from __future__ import annotations

import csv
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_data.fetcher.industry.chemicals.quality import validate_spread_raw_frame
from stock_data.fetcher.industry.chemicals.schemas import SPREAD_RAW_SCHEMA, SPREAD_SCHEMA
from stock_data.fetcher.industry.chemicals.transforms.spreads import (
    build_spread_curated_frame,
    build_spread_raw_frame,
)
from stock_data.fetcher.industry.contracts import IndustryFrameResult

logger = logging.getLogger(__name__)

RAW_SPREAD_CANDIDATES = (
    "chemicals/chemical_spreads.csv",
    "chemical_spreads.csv",
)

DEFAULT_COST_CONFIG_PATH: Path | None = None

# 品种级成本模型唯一维护源注册表 (单点维护，高内聚低耦合)
PRODUCT_COST_CONFIG_PATHS: dict[str, Path] = {
    "soda_ash": Path("config/industry/chemicals/soda_ash/cost_models.yaml"),
    "pta": Path("config/industry/chemicals/pta/cost_models.yaml"),
    "methanol": Path("config/industry/chemicals/methanol/cost_models.yaml"),
    "tio2": Path("config/industry/chemicals/tio2/cost_models.yaml"),
    "meg": Path("config/industry/chemicals/meg/cost_models.yaml"),
    "pvc": Path("config/industry/chemicals/pvc/cost_models.yaml"),
    "urea": Path("config/industry/chemicals/urea/cost_models.yaml"),
    "caustic_soda": Path("config/industry/chemicals/caustic_soda/cost_models.yaml"),
}

# 钛白粉企业微观模型单一信任源固定路径
TIO2_COMPANY_PROJECTIONS_PATH = Path("config/industry/chemicals/tio2/company_projections.yaml")


class ChemicalSpreadCalculator:
    """产业链利润与加工费计算器 (支持 YAML 配置驱动)。"""

    def __init__(
        self,
        raw_dir: Path | str,
        config_path: Path | str | None = None,
        curated_dir: Path | str | None = None,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.config_path = Path(config_path) if config_path else DEFAULT_COST_CONFIG_PATH
        self.curated_dir = (
            Path(curated_dir) if curated_dir is not None else _derive_curated_dir(self.raw_dir)
        )
        self._models_cache: dict[str, Any] | None = None
        self._spot_series_cache: dict[str, pl.DataFrame] = {}

    def load_cost_models(self) -> dict[str, Any]:
        """读取生产工艺理论成本与利润模型配置 (自适应单品种与全品种聚合)。"""
        if self._models_cache is not None:
            return self._models_cache

        # 默认模式：直接聚合所有品种级唯一维护源
        if self.config_path is None:
            data: dict[str, Any] = {"models": {}, "regime_thresholds": {}}
            for product, product_path in PRODUCT_COST_CONFIG_PATHS.items():
                if not product_path.exists():
                    continue
                try:
                    product_data = yaml.safe_load(product_path.read_text(encoding="utf-8")) or {}
                    product_models = product_data.get("models", {})
                    if isinstance(product_models, dict) and product_models:
                        data["models"][product] = product_models
                    product_thresholds = product_data.get("regime_thresholds", {})
                    if isinstance(product_thresholds, dict) and product_thresholds:
                        data["regime_thresholds"][product] = product_thresholds
                except Exception as exc:
                    logger.debug("加载 %s 品种级成本模型失败 [%s]: %s", product, product_path, exc)
            self._models_cache = data
            return self._models_cache

        # 显式指定配置路径：自适应单品种与跨品种
        if self.config_path.exists():
            try:
                data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
                # 若为单品种高内聚配置，自适应挂载至对应品种节点
                if "models" in data and isinstance(data["models"], dict):
                    sym = str(data.get("symbol", "")).upper()
                    p_name = str(data.get("product_name", ""))
                    models_dict = data["models"]
                    if sym == "SA" or "纯碱" in p_name or "hou_process" in models_dict:
                        data = {
                            "models": {"soda_ash": models_dict},
                            "regime_thresholds": {"soda_ash": data.get("regime_thresholds", {})},
                        }
                    elif sym == "TIO2" or "钛白粉" in p_name or "sulfate_process" in models_dict:
                        data = {
                            "models": {"tio2": models_dict},
                            "regime_thresholds": {"tio2": data.get("regime_thresholds", {})},
                        }
                    elif sym == "TA" or "PTA" in p_name or "standard" in models_dict:
                        data = {
                            "models": {"pta": models_dict},
                            "regime_thresholds": {"pta": data.get("regime_thresholds", {})},
                        }
                    elif sym == "MA" or "甲醇" in p_name or "coal_to_methanol" in models_dict:
                        data = {
                            "models": {"methanol": models_dict},
                            "regime_thresholds": {"methanol": data.get("regime_thresholds", {})},
                        }
                    elif sym == "MEG" or "乙二醇" in p_name or "oil_to_meg" in models_dict:
                        data = {
                            "models": {"meg": models_dict},
                            "regime_thresholds": {"meg": data.get("regime_thresholds", {})},
                        }
                    elif sym == "V" or "PVC" in p_name or "carbide_process" in models_dict:
                        data = {
                            "models": {"pvc": models_dict},
                            "regime_thresholds": {"pvc": data.get("regime_thresholds", {})},
                        }
                    elif sym == "UR" or "尿素" in p_name or "fixed_bed_coal" in models_dict:
                        data = {
                            "models": {"urea": models_dict},
                            "regime_thresholds": {"urea": data.get("regime_thresholds", {})},
                        }
                    elif (
                        sym == "SH" or "烧碱" in p_name or "membrane_process_100pct" in models_dict
                    ):
                        data = {
                            "models": {"caustic_soda": models_dict},
                            "regime_thresholds": {
                                "caustic_soda": data.get("regime_thresholds", {})
                            },
                        }
                self._models_cache = data
                return self._models_cache
            except Exception as exc:
                logger.warning(f"读取成本模型配置失败 [{self.config_path}]: {exc}，使用内置默认值")

        self._models_cache = {}
        return self._models_cache

    def calculate_soda_ash_double_ton_margin(
        self,
        soda_price: float,
        nh4cl_price: float,
        salt_price: float,
        nh3_price: float,
        coal_price: float,
        fixed_cost: float | None = None,
    ) -> float:
        """计算纯碱联产法双吨理论利润 (元/吨)。"""
        cfg = self.load_cost_models().get("models", {}).get("soda_ash", {}).get("hou_process", {})
        coeffs = cfg.get("coefficients", {})
        salt_coeff = float(coeffs.get("raw_salt", 1.2))
        nh3_coeff = float(coeffs.get("synthetic_ammonia", 0.135))
        coal_coeff = float(coeffs.get("thermal_coal", 0.4))
        fc = fixed_cost if fixed_cost is not None else float(cfg.get("fixed_cost", 450.0))

        raw_cost = salt_coeff * salt_price + nh3_coeff * nh3_price + coal_coeff * coal_price
        margin = (soda_price + nh4cl_price) - raw_cost - fc
        return round(margin, 2)

    def calculate_soda_ash_solvay_cash_cost(
        self,
        salt_price: float,
        limestone_price: float,
        coal_price: float,
        coke_price: float = 0.0,
        cash_fixed_cost: float | None = None,
    ) -> float:
        """计算纯碱氨碱法边际产能现金保本成本线 (元/吨)。"""
        cfg = (
            self.load_cost_models().get("models", {}).get("soda_ash", {}).get("solvay_process", {})
        )
        coeffs = cfg.get("coefficients", {})
        salt_coeff = float(coeffs.get("raw_salt", 1.5))
        lime_coeff = float(coeffs.get("limestone", 1.3))
        coal_coeff = float(coeffs.get("thermal_coal", 0.35))
        coke_coeff = float(coeffs.get("coke", 0.12))
        cfc = (
            cash_fixed_cost
            if cash_fixed_cost is not None
            else float(cfg.get("cash_fixed_cost", 260.0))
        )

        cash_cost = (
            salt_coeff * salt_price
            + lime_coeff * limestone_price
            + coal_coeff * coal_price
            + coke_coeff * coke_price
            + cfc
        )
        return round(cash_cost, 2)

    def calculate_pta_processing_spread(
        self,
        pta_price: float,
        px_price: float,
    ) -> float:
        """计算 PTA 理论加工费 (元/吨)。"""
        cfg = self.load_cost_models().get("models", {}).get("pta", {}).get("standard", {})
        coeff = float(cfg.get("coefficients", {}).get("feedstock_px", 0.655))
        spread = pta_price - coeff * px_price
        return round(spread, 2)

    def calculate_polyester_poy_spread(
        self,
        poy_price: float,
        pta_price: float,
        meg_price: float,
    ) -> float:
        """计算涤纶长丝 POY 理论加工差 (元/吨)。

        公式: POY 现货价 - (0.855 * PTA 现货价 + 0.335 * MEG 现货价)
        行业完全加工成本约 1100 元/吨，现金保本成本线约 800 元/吨。
        """
        cfg = self.load_cost_models().get("models", {}).get("pta", {}).get("polyester_poy", {})
        coeffs = cfg.get("coefficients", {})
        pta_coeff = float(coeffs.get("feedstock_pta", 0.855))
        meg_coeff = float(coeffs.get("feedstock_meg", 0.335))
        spread = poy_price - (pta_coeff * pta_price + meg_coeff * meg_price)
        return round(spread, 2)

    def calculate_methanol_margin(
        self,
        methanol_price: float,
        coal_price: float,
        fixed_cost: float | None = None,
    ) -> float:
        """计算煤制甲醇理论毛利 (元/吨)。"""
        cfg = (
            self.load_cost_models()
            .get("models", {})
            .get("methanol", {})
            .get("coal_to_methanol", {})
        )
        coeff = float(cfg.get("coefficients", {}).get("thermal_coal", 1.6))
        fc = fixed_cost if fixed_cost is not None else float(cfg.get("fixed_cost", 650.0))
        raw_cost = coeff * coal_price
        margin = methanol_price - raw_cost - fc
        return round(margin, 2)

    def calculate_tio2_sulfate_margin(
        self,
        tio2_price: float,
        ilmenite_price: float,
        acid_price: float,
        fixed_cost: float | None = None,
    ) -> float:
        """计算硫酸法金红石型钛白粉理论毛利 (元/吨)。"""
        cfg = self.load_cost_models().get("models", {}).get("tio2", {}).get("sulfate_process", {})
        coeffs = cfg.get("coefficients", {})
        ilmenite_coeff = float(coeffs.get("ilmenite_46", 2.0))
        acid_coeff = float(coeffs.get("sulfuric_acid_98", 3.5))
        fc = fixed_cost if fixed_cost is not None else float(cfg.get("fixed_cost", 3800.0))

        raw_cost = ilmenite_coeff * ilmenite_price + acid_coeff * acid_price
        margin = tio2_price - raw_cost - fc
        return round(margin, 2)

    def calculate_tio2_sulfate_cash_cost(
        self,
        ilmenite_price: float,
        acid_price: float,
        cash_fixed_cost: float | None = None,
    ) -> float:
        """计算硫酸法钛白粉边际产能现金保本成本线 (元/吨)。"""
        cfg = self.load_cost_models().get("models", {}).get("tio2", {}).get("sulfate_process", {})
        coeffs = cfg.get("coefficients", {})
        ilmenite_coeff = float(coeffs.get("ilmenite_46", 2.0))
        acid_coeff = float(coeffs.get("sulfuric_acid_98", 3.5))
        cfc = (
            cash_fixed_cost
            if cash_fixed_cost is not None
            else float(cfg.get("cash_fixed_cost", 2600.0))
        )
        cash_cost = ilmenite_coeff * ilmenite_price + acid_coeff * acid_price + cfc
        return round(cash_cost, 2)

    def calculate_tio2_chloride_margin(
        self,
        tio2_price: float,
        slag_price: float,
        petcoke_price: float,
        chlorine_price: float,
        fixed_cost: float | None = None,
    ) -> float:
        """计算氯化法高档钛白粉理论毛利 (元/吨)。"""
        cfg = self.load_cost_models().get("models", {}).get("tio2", {}).get("chloride_process", {})
        coeffs = cfg.get("coefficients", {})
        slag_coeff = float(coeffs.get("high_titania_slag", 1.2))
        petcoke_coeff = float(coeffs.get("petroleum_coke", 0.2))
        chlorine_coeff = float(coeffs.get("chlorine", 0.1))
        fc = fixed_cost if fixed_cost is not None else float(cfg.get("fixed_cost", 6000.0))

        raw_cost = (
            slag_coeff * slag_price
            + petcoke_coeff * petcoke_price
            + chlorine_coeff * chlorine_price
        )
        margin = tio2_price - raw_cost - fc
        return round(margin, 2)

    def calculate_tio2_chloride_cash_breakeven(
        self,
        slag_price: float,
        petcoke_price: float,
        chlorine_price: float,
        cash_fixed_cost: float | None = None,
    ) -> float:
        """计算氯化法高档钛白粉现金保本成本线 (元/吨)。"""
        cfg = self.load_cost_models().get("models", {}).get("tio2", {}).get("chloride_process", {})
        coeffs = cfg.get("coefficients", {})
        slag_coeff = float(coeffs.get("high_titania_slag", 1.2))
        petcoke_coeff = float(coeffs.get("petroleum_coke", 0.2))
        chlorine_coeff = float(coeffs.get("chlorine", 0.1))
        cfc = (
            cash_fixed_cost
            if cash_fixed_cost is not None
            else float(cfg.get("cash_fixed_cost", 4200.0))
        )

        raw_cost = (
            slag_coeff * slag_price
            + petcoke_coeff * petcoke_price
            + chlorine_coeff * chlorine_price
        )
        cash_cost = raw_cost + cfc
        return round(cash_cost, 2)

    def calculate_tio2_chloride_cash_cost(
        self,
        full_cost_approx: float | None = None,
    ) -> float:
        """获取氯化法高档钛白粉完全成本参考线 (元/吨)。

        注：方法名沿用历史约定，返回 full_cost_approx 参考完全成本；
        逐吨现金保本计算请使用 calculate_tio2_chloride_cash_breakeven。
        """
        cfg = self.load_cost_models().get("models", {}).get("tio2", {}).get("chloride_process", {})
        cost = (
            full_cost_approx
            if full_cost_approx is not None
            else float(cfg.get("full_cost_approx", 12500.0))
        )
        return round(cost, 2)

    def calculate_tio2_integrated_sulfate_margin(
        self,
        tio2_price: float,
        ilmenite_market_price: float,
        acid_price: float,
        captive_ratio: float = 0.65,
        captive_cash_cost: float = 900.0,
        acid_coeff: float = 3.0,
        fixed_cost: float = 3800.0,
        byproduct_credit: float = 150.0,
    ) -> float:
        """计算具备自备钛精矿一体化能力的硫酸法金红石型钛白粉理论毛利 (元/吨)。"""
        blended_ore = (
            captive_ratio * captive_cash_cost + (1.0 - captive_ratio) * ilmenite_market_price
        )
        raw_cost = 2.0 * blended_ore + acid_coeff * acid_price
        margin = tio2_price - raw_cost - fixed_cost + byproduct_credit
        return round(margin, 2)

    def calculate_tio2_integrated_sulfate_cash_cost(
        self,
        ilmenite_market_price: float,
        acid_price: float,
        captive_ratio: float = 0.65,
        captive_cash_cost: float = 900.0,
        acid_coeff: float = 3.0,
        cash_fixed_cost: float = 2600.0,
        byproduct_credit: float = 150.0,
    ) -> float:
        """计算具备自备钛矿一体化能力的硫酸法现金保本成本线 (元/吨)。"""
        blended_ore = (
            captive_ratio * captive_cash_cost + (1.0 - captive_ratio) * ilmenite_market_price
        )
        raw_cost = 2.0 * blended_ore + acid_coeff * acid_price
        cash_cost = raw_cost + cash_fixed_cost - byproduct_credit
        return round(cash_cost, 2)

    def _get_tio2_company_model(self, symbol: str) -> dict[str, Any]:
        """从单一信任源 company_projections.yaml 提取企业的工艺单耗与产能结构 (SSOT)。"""
        proj_path = TIO2_COMPANY_PROJECTIONS_PATH
        if not proj_path.exists():
            return {}
        try:
            data = yaml.safe_load(proj_path.read_text(encoding="utf-8")) or {}
            c_data = data.get("companies", {}).get(symbol, {})
            if not c_data:
                return {}
            sulfate_seg = c_data.get("segments", {}).get("sulfate_tio2", {})
            chloride_seg = c_data.get("segments", {}).get("chloride_tio2", {})
            sponge_seg = c_data.get("segments", {}).get("sponge_ti", {})
            iron_seg = c_data.get("segments", {}).get("iron_ore", {})

            captive_cost = float(
                sulfate_seg.get(
                    "ore_captive_cash_cost",
                    sulfate_seg.get("ore_captive_cost", 900.0),
                )
            )
            acid_coeff = float(
                sulfate_seg.get(
                    "sulfate_acid_coeff",
                    sulfate_seg.get("acid_consumption", 3.0),
                )
            )
            return {
                "name": c_data.get("name", symbol),
                "description": c_data.get("description", ""),
                "ore_captive_ratio": float(sulfate_seg.get("ore_captive_ratio", 0.0)),
                "ore_captive_cash_cost": captive_cost,
                "sulfate_ratio": float(
                    c_data.get("sulfate_ratio", 1.0 if not chloride_seg else 0.43)
                ),
                "chloride_ratio": float(
                    c_data.get("chloride_ratio", 0.0 if not chloride_seg else 0.57)
                ),
                "sulfate_acid_coeff": acid_coeff,
                "byproduct_credit": float(sulfate_seg.get("byproduct_credit", 0.0)),
                "sponge_capacity_w_tons": float(sponge_seg.get("capacity_w_tons", 0.0)),
                "sponge_cash_cost": float(c_data.get("sponge_cash_cost", 43000.0)),
                "iron_ore_capacity_w_tons": float(iron_seg.get("sales_w_tons", 0.0)),
                "expense_ratio_approx": float(c_data.get("base_expense_ratio", 0.085)),
                "fallback_chloride_margin": float(c_data.get("fallback_chloride_margin", 3500.0)),
            }
        except Exception as exc:
            logger.debug("读取微观企业模型失败 [%s]: %s", proj_path, exc)
            return {}

    def calculate_tio2_company_margins(
        self,
        symbol: str,
        tio2_price: float,
        ilmenite_price: float,
        acid_price: float,
        slag_price: float | None = None,
        petcoke_price: float | None = None,
        chlorine_price: float | None = None,
    ) -> dict[str, Any]:
        """根据公司配置计算钛白粉企业动态单吨综合理论毛利、现金毛利与阿尔法利差。"""
        cost_cfg = self.load_cost_models()
        # 1. 优先读取已注入或旧版的 company_models，若无则自适应读取单一信任源 company_projections.yaml
        company_cfg = cost_cfg.get("models", {}).get("tio2", {}).get("company_models", {}).get(
            symbol, {}
        ) or cost_cfg.get("company_models", {}).get(symbol, {})
        if not company_cfg:
            company_cfg = self._get_tio2_company_model(symbol)

        sulfate_base_cfg = cost_cfg.get("models", {}).get("tio2", {}).get("sulfate_process", {})
        chloride_base_cfg = cost_cfg.get("models", {}).get("tio2", {}).get("chloride_process", {})

        c_name = str(company_cfg.get("name", symbol))
        ore_captive_ratio = float(company_cfg.get("ore_captive_ratio", 0.0))
        ore_captive_cash_cost = float(
            company_cfg.get("ore_captive_cash_cost", company_cfg.get("ore_captive_cost", 900.0))
        )
        sulfate_ratio = float(company_cfg.get("sulfate_ratio", 1.0))
        chloride_ratio = float(company_cfg.get("chloride_ratio", 0.0))
        acid_coeff = float(
            company_cfg.get("sulfate_acid_coeff", company_cfg.get("acid_consumption", 3.0))
        )
        byproduct_credit = float(company_cfg.get("byproduct_credit", 0.0))

        fixed_sulfate = float(sulfate_base_cfg.get("fixed_cost", 3800.0))
        cash_fixed_sulfate = float(sulfate_base_cfg.get("cash_fixed_cost", 2600.0))

        # 硫酸法分部毛利与现金保本
        sulfate_margin = self.calculate_tio2_integrated_sulfate_margin(
            tio2_price=tio2_price,
            ilmenite_market_price=ilmenite_price,
            acid_price=acid_price,
            captive_ratio=ore_captive_ratio,
            captive_cash_cost=ore_captive_cash_cost,
            acid_coeff=acid_coeff,
            fixed_cost=fixed_sulfate,
            byproduct_credit=byproduct_credit,
        )
        sulfate_cash_cost = self.calculate_tio2_integrated_sulfate_cash_cost(
            ilmenite_market_price=ilmenite_price,
            acid_price=acid_price,
            captive_ratio=ore_captive_ratio,
            captive_cash_cost=ore_captive_cash_cost,
            acid_coeff=acid_coeff,
            cash_fixed_cost=cash_fixed_sulfate,
            byproduct_credit=byproduct_credit,
        )
        sulfate_cash_margin = round(tio2_price - sulfate_cash_cost, 2)

        # 氯化法分部毛利与现金保本
        chloride_margin = None
        chloride_cash_cost = None
        if chloride_ratio > 0:
            if slag_price is not None and petcoke_price is not None and chlorine_price is not None:
                chloride_margin = self.calculate_tio2_chloride_margin(
                    tio2_price=tio2_price,
                    slag_price=slag_price,
                    petcoke_price=petcoke_price,
                    chlorine_price=chlorine_price,
                )
                chloride_cash_cost = self.calculate_tio2_chloride_cash_breakeven(
                    slag_price=slag_price,
                    petcoke_price=petcoke_price,
                    chlorine_price=chlorine_price,
                )
            else:
                chloride_premium = float(company_cfg.get("chloride_premium_cny", 1800.0))
                chloride_full_cost = float(chloride_base_cfg.get("full_cost_approx", 12500.0))
                chloride_margin = round(tio2_price + chloride_premium - chloride_full_cost, 2)
                chloride_cash_cost = float(
                    chloride_base_cfg.get("cash_fixed_cost", 4200.0) + 6520.0
                )

        # 加权单吨综合指标
        if chloride_ratio > 0 and chloride_margin is not None:
            unit_gross_margin = round(
                sulfate_ratio * sulfate_margin + chloride_ratio * chloride_margin, 2
            )
            blended_cash_cost = round(
                sulfate_ratio * sulfate_cash_cost
                + chloride_ratio * (chloride_cash_cost or 10720.0),
                2,
            )
        else:
            unit_gross_margin = sulfate_margin
            blended_cash_cost = sulfate_cash_cost

        unit_cash_margin = round(tio2_price - blended_cash_cost, 2)
        gpm_ratio = round(unit_gross_margin / tio2_price, 4) if tio2_price > 0 else 0.0

        # 纯外购矿基准毛利 (对比基准：行业标准硫酸法 2.0矿 + 3.5酸 + 3800加工费)
        baseline_sulfate_margin = self.calculate_tio2_sulfate_margin(
            tio2_price=tio2_price,
            ilmenite_price=ilmenite_price,
            acid_price=acid_price,
            fixed_cost=fixed_sulfate,
        )
        alpha_spread = round(unit_gross_margin - baseline_sulfate_margin, 2)
        sulfate_alpha = round(sulfate_margin - baseline_sulfate_margin, 2)

        return {
            "symbol": symbol,
            "company_name": c_name,
            "unit_gross_margin_cny": unit_gross_margin,
            "unit_cash_margin_cny": unit_cash_margin,
            "gross_margin_ratio": gpm_ratio,
            "alpha_spread_cny": alpha_spread,
            "sulfate_alpha_cny": sulfate_alpha,
            "sulfate_margin_cny": sulfate_margin,
            "sulfate_cash_margin_cny": sulfate_cash_margin,
            "chloride_margin_cny": chloride_margin,
            "blended_cash_cost_cny": blended_cash_cost,
            "ore_captive_ratio": ore_captive_ratio,
        }

    # ------------------------------------------------------------------
    # 配置驱动价差计算引擎：cost_models.yaml 单耗系数 × 本地现货价/期货基准
    # ------------------------------------------------------------------

    def resolve_dataset_path(self, dataset: str) -> Path:
        """定位 Curated 侧数据集 parquet 路径。"""
        return self.curated_dir / f"{dataset}.parquet"

    def load_spot_series(self, symbol: str) -> pl.DataFrame:
        """加载单品种现货价序列 {trade_date, price}。

        优先级：Curated ``chemical_spot_price`` → RAW 调研价 CSV → RAW 100ppi JSON 快照。
        """
        cached = self._spot_series_cache.get(symbol)
        if cached is not None:
            return cached
        loaders = (
            self._load_curated_spot_series,
            self._load_survey_spot_series,
            self._load_raw_snapshot_series,
        )
        series = pl.DataFrame()
        for loader in loaders:
            series = loader(symbol)
            if not series.is_empty():
                break
        self._spot_series_cache[symbol] = series
        return series

    def _load_curated_spot_series(self, symbol: str) -> pl.DataFrame:
        path = self.resolve_dataset_path("chemical_spot_price")
        if not path.exists():
            return pl.DataFrame()
        try:
            frame = pl.read_parquet(path)
        except Exception as exc:  # pragma: no cover - 读取异常仅降级
            logger.debug("读取 Curated 现货失败 [%s]: %s", symbol, exc)
            return pl.DataFrame()
        if "symbol" not in frame.columns or "spot_price_cny" not in frame.columns:
            return pl.DataFrame()
        return _normalize_price_series(
            frame.filter(pl.col("symbol") == symbol).select(
                pl.col("trade_date").cast(pl.Date),
                pl.col("spot_price_cny").cast(pl.Float64, strict=False).alias("price"),
            )
        )

    def _load_survey_spot_series(self, symbol: str) -> pl.DataFrame:
        path = self.raw_dir / "chemicals" / "operating_rates" / "expert_prices_survey.csv"
        if not path.exists():
            return pl.DataFrame()
        try:
            frame = pl.read_csv(path)
        except Exception as exc:  # pragma: no cover - 读取异常仅降级
            logger.debug("读取调研价失败 [%s]: %s", symbol, exc)
            return pl.DataFrame()
        if "symbol" not in frame.columns or "spot_price_cny" not in frame.columns:
            return pl.DataFrame()
        return _normalize_price_series(
            frame.filter(pl.col("symbol") == symbol).select(
                pl.col("trade_date").cast(pl.Utf8).str.to_date(strict=False),
                pl.col("spot_price_cny").cast(pl.Float64, strict=False).alias("price"),
            )
        )

    def _load_raw_snapshot_series(self, symbol: str) -> pl.DataFrame:
        for path in self._raw_snapshot_candidates(symbol):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:  # pragma: no cover - 快照损坏仅降级
                logger.debug("解析 100ppi 快照失败 [%s]: %s", path, exc)
                continue
            rows: list[dict[str, Any]] = []
            dates = payload.get("dates") or []
            prices = payload.get("prices") or []
            for raw_date, raw_price in zip(dates, prices, strict=False):
                text = str(raw_price).strip()
                if not text or text == "-":
                    continue
                try:
                    rows.append(
                        {
                            "trade_date": date.fromisoformat(str(raw_date).strip()),
                            "price": float(text),
                        }
                    )
                except (TypeError, ValueError):
                    continue
            if rows:
                return _normalize_price_series(pl.DataFrame(rows))
        return pl.DataFrame()

    def _raw_snapshot_candidates(self, symbol: str) -> tuple[Path, ...]:
        """定位 100ppi 原始快照；显式路径优先，未命中再全局回退。"""
        explicit = (
            self.raw_dir / "chemicals" / "100ppi" / f"{symbol}.json",
            self.raw_dir / "chemicals" / "chemicals" / "100ppi" / f"{symbol}.json",
            self.raw_dir / "100ppi" / f"{symbol}.json",
        )
        found = tuple(path for path in explicit if path.exists())
        if found:
            return found
        return tuple(sorted(self.raw_dir.rglob(f"{symbol}.json")))

    def load_futures_price_series(self, symbol: str) -> pl.DataFrame:
        """加载期货结算价序列 {trade_date, price}，作现货缺失时的基准回退。"""
        path = self.resolve_dataset_path("futures_daily")
        if not path.exists():
            return pl.DataFrame()
        try:
            frame = pl.read_parquet(path)
        except Exception as exc:  # pragma: no cover - 读取异常仅降级
            logger.debug("读取期货行情失败 [%s]: %s", symbol, exc)
            return pl.DataFrame()
        if not {"symbol", "trade_date"}.issubset(set(frame.columns)):
            return pl.DataFrame()
        price_column = next((name for name in ("settle", "close") if name in frame.columns), None)
        if price_column is None:
            return pl.DataFrame()
        return _normalize_price_series(
            frame.filter(pl.col("symbol") == symbol).select(
                pl.col("trade_date").cast(pl.Date),
                pl.col(price_column).cast(pl.Float64, strict=False).alias("price"),
            )
        )

    def load_coal_price_series(self) -> pl.DataFrame:
        """加载秦皇岛 Q5500 动力煤现货价序列 {trade_date, price}。"""
        path = self.resolve_dataset_path("coal_market")
        if not path.exists():
            return pl.DataFrame()
        try:
            frame = pl.read_parquet(path)
        except Exception as exc:  # pragma: no cover - 读取异常仅降级
            logger.debug("读取煤炭市场失败: %s", exc)
            return pl.DataFrame()
        if "q5500_fob_price_cny" not in frame.columns:
            return pl.DataFrame()
        return _normalize_price_series(
            frame.select(
                pl.col("trade_date").cast(pl.Date),
                pl.col("q5500_fob_price_cny").cast(pl.Float64, strict=False).alias("price"),
            )
        )

    def load_price_input_series(self, spec_input: PriceInput) -> pl.DataFrame:
        """按声明优先级加载单个价格输入序列（多源按优先级合并）。"""
        sources: list[pl.DataFrame] = []
        if spec_input.coal_price:
            sources.append(self.load_coal_price_series())
        for symbol in spec_input.spot_symbols:
            sources.append(self.load_spot_series(symbol))
        if spec_input.futures_symbol:
            sources.append(self.load_futures_price_series(spec_input.futures_symbol))
        available = [frame for frame in sources if not frame.is_empty()]
        if not available:
            return pl.DataFrame()
        if len(available) == 1:
            return available[0]
        return _coalesce_price_sources(available)

    def build_input_panel(self, spec: SpreadProductSpec) -> pl.DataFrame:
        """把品种所需价格输入按日对齐为面板（首个可取序列作为日历基准）。

        首个可取序列作为日历基准；``constant`` 仅在序列整体缺失或存在前期缺口时
        作为显式回退，且只做前向填充，避免反向插值伪造历史。
        """
        panel: pl.DataFrame | None = None
        series_inputs: list[PriceInput] = []
        constant_inputs: list[PriceInput] = []
        for spec_input in spec.inputs:
            series = self.load_price_input_series(spec_input)
            if series.is_empty():
                if spec_input.constant is None:
                    return pl.DataFrame()
                constant_inputs.append(spec_input)
                continue
            series_inputs.append(spec_input)
            labelled = series.rename({"price": spec_input.key})
            panel = (
                labelled
                if panel is None
                else panel.join_asof(labelled, on="trade_date", strategy="backward")
            )
        if panel is None:
            return pl.DataFrame()
        expressions: list[pl.Expr] = []
        for spec_input in series_inputs:
            filled = pl.col(spec_input.key).forward_fill()
            if spec_input.constant is not None:
                filled = filled.fill_null(spec_input.constant)
            expressions.append(filled.alias(spec_input.key))
        expressions.extend(pl.lit(item.constant).alias(item.key) for item in constant_inputs)
        keys = [item.key for item in spec.inputs]
        panel = panel.with_columns(expressions).drop_nulls(subset=keys)
        if panel.is_empty():
            return pl.DataFrame()
        return panel.select(["trade_date"] + keys).sort("trade_date")

    def build_computed_spreads(self, *, as_of_date: date | None = None) -> pl.DataFrame:
        """按 cost_models.yaml 系数与本地现货价计算各品种价差（SPREAD_RAW_SCHEMA）。"""
        records: list[dict[str, object]] = []
        collected_at = datetime.now(UTC).isoformat()
        for spec in SPREAD_PRODUCT_SPECS:
            panel = self.build_input_panel(spec)
            if panel.is_empty():
                logger.debug("品种 %s 价格输入不足，跳过价差计算", spec.symbol)
                continue
            keys = [item.key for item in spec.inputs]
            for row in panel.iter_rows(named=True):
                trade_date = row["trade_date"]
                if as_of_date is not None and trade_date > as_of_date:
                    continue
                values = {key: float(row[key]) for key in keys}
                computed = spec.compute(self, values)
                regime = computed.margin_regime or self.get_margin_regime(
                    computed.spread_margin_cny, 0.0, spec.regime_key
                )
                records.append(
                    {
                        "trade_date": trade_date,
                        "product_name": spec.product_name,
                        "symbol": spec.symbol,
                        "process_type": spec.process_type,
                        "product_price_cny_raw": _format_number(computed.product_price_cny),
                        "byproduct_price_cny_raw": _format_number(computed.byproduct_price_cny),
                        "raw_material_cost_cny_raw": _format_number(computed.raw_material_cost_cny),
                        "spread_margin_cny_raw": _format_number(computed.spread_margin_cny),
                        "cash_breakeven_cost_cny_raw": _format_number(
                            computed.cash_breakeven_cost_cny
                        ),
                        "margin_regime_raw": regime,
                        "source": spec.source,
                        "release_date": trade_date,
                        "collected_at": collected_at,
                        "data_status": "benchmark",
                    }
                )
        if not records:
            return _empty_spread_raw_frame()
        return pl.DataFrame(records, schema=SPREAD_RAW_SCHEMA).sort(["product_name", "trade_date"])

    def get_margin_regime(
        self,
        spread_margin: float,
        breakeven: float = 0.0,
        product: str = "soda_ash",
    ) -> str:
        """根据理论利润与现金保本线划定盈亏状态。"""
        product_key = product.lower()
        thresholds = self.load_cost_models().get("regime_thresholds", {}).get(product_key, {})
        high_profit_th = float(thresholds.get("high_profit", 300.0))
        profitable_th = float(thresholds.get("profitable", 0.0))
        near_breakeven_th = float(thresholds.get("near_breakeven", -150.0))

        diff = spread_margin - breakeven
        if diff > high_profit_th:
            return "high_profit"  # 超额暴利
        if diff > profitable_th:
            return "profitable"  # 正常盈利
        if diff > near_breakeven_th:
            return "near_breakeven"  # 盈亏平衡/微亏
        return "deep_loss"  # 深度亏损 (倒逼装置检修)

    def build_historical_spreads(self) -> pl.DataFrame:
        """构建核心化工品历史利润与加工费时序。

        优先用 ``cost_models.yaml`` 单耗系数与本地现货价/期货基准实时计算；
        计算未覆盖的存量行（历史人工校验记录）予以保留。
        """
        return build_spread_curated_frame(self.build_raw_spreads())

    def build_raw_spreads(self, *, as_of_date: date | None = None) -> pl.DataFrame:
        """产出价差 RAW 帧（源端字段）：计算结果优先，未被覆盖的存量行保留。

        端点的 transform、回放工具与物化脚本均以本方法为唯一入口，避免各路径
        对「计算值 vs 存量事实」的取舍口径发散。
        """
        return _merge_spread_frames(
            self.build_computed_spreads(as_of_date=as_of_date),
            self.load_raw_spreads(),
        )

    def load_raw_spreads(self) -> pl.DataFrame:
        """读取价差源端字段，不执行价差计算。"""
        for rel_path in RAW_SPREAD_CANDIDATES:
            raw_file = self.raw_dir / rel_path
            if raw_file.exists():
                return _load_raw_spread_frame(raw_file)

        logger.warning("化工价差 RAW 事实表不存在，跳过 chemical_spreads 构建: %s", self.raw_dir)
        return _empty_spread_raw_frame()

    def load_raw_spreads_result(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> IndustryFrameResult:
        """读取价差源端存量事实，并保留质量问题供端点门禁判断。"""
        frame = self.load_raw_spreads()
        if start_date is not None:
            frame = frame.filter(pl.col("trade_date") >= pl.lit(start_date))
        if end_date is not None:
            frame = frame.filter(pl.col("trade_date") <= pl.lit(end_date))
        return _build_spread_result(frame)

    def load_historical_spreads_result(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
    ) -> IndustryFrameResult:
        """返回「配置驱动计算 + 存量事实」合并后的价差 RAW 帧。

        供 ``chemical_spreads`` 端点物化 Curated 使用。``force`` 仅为兼容端点调度
        约定，计算路径本身不做 RAW 缓存复用。
        """
        frame = self.build_raw_spreads(as_of_date=end_date)
        if start_date is not None:
            frame = frame.filter(pl.col("trade_date") >= pl.lit(start_date))
        if end_date is not None:
            frame = frame.filter(pl.col("trade_date") <= pl.lit(end_date))
        return _build_spread_result(frame)

    def calculate_ecu_margin(
        self,
        caustic_soda_price: float,
        chlorine_price: float = 0.0,
        is_32pct_liquid: bool = True,
    ) -> dict[str, Any]:
        """计算氯碱电化学单元 (ECU) 综合毛利与利润相位。

        1 ECU = 1.0 吨折百烧碱 + 0.886 吨氯气。
        若输入为 32% 液碱，自动折百: caustic_100 = caustic_soda_price * 3.125。
        """
        c100 = caustic_soda_price * 3.125 if is_32pct_liquid else caustic_soda_price
        revenue = c100 + 0.886 * chlorine_price
        full_cost = 2200.0
        cash_cost = 1800.0
        margin = revenue - full_cost

        if margin >= 700.0:
            regime = "super_profit"
        elif margin >= 400.0:
            regime = "high_profit"
        elif margin >= 100.0:
            regime = "profitable"
        elif margin >= -100.0:
            regime = "marginal_loss"
        else:
            regime = "deep_loss"

        return {
            "ecu_revenue": round(revenue, 2),
            "caustic_100_price": round(c100, 2),
            "ecu_full_cost": full_cost,
            "ecu_cash_cost": cash_cost,
            "ecu_margin_cny": round(margin, 2),
            "ecu_regime": regime,
            "is_cash_breached": revenue < cash_cost,
        }

    def calculate_urea_coal_margin(
        self,
        urea_price: float,
        thermal_coal_price: float = 750.0,
    ) -> dict[str, Any]:
        """计算煤制尿素加工差与利润相位。"""
        cost_baseline = 1.2 * thermal_coal_price + 450.0
        margin = urea_price - cost_baseline
        if margin >= 600.0:
            regime = "super_profit"
        elif margin >= 350.0:
            regime = "high_profit"
        elif margin >= 100.0:
            regime = "profitable"
        elif margin >= -150.0:
            regime = "marginal_loss"
        else:
            regime = "deep_loss"

        return {
            "urea_price": round(urea_price, 2),
            "cost_baseline": round(cost_baseline, 2),
            "spread_margin_cny": round(margin, 2),
            "margin_regime": regime,
            "is_cash_breached": urea_price < 1750.0,
        }


# ---------------------------------------------------------------------------
# 价差计算引擎：品种规格、输入口径与模块级辅助
# ---------------------------------------------------------------------------

# 无本地高频序列的原料，沿用仓库既有基准脚本的显式常量口径（不插值、不伪造）。
FALLBACK_SALT_PRICE_CNY = 280.0  # 工业原盐 (元/吨)
FALLBACK_CHLORINE_PRICE_CNY = 200.0  # 液氯 (元/吨)
FALLBACK_ILMENITE_PRICE_CNY = 2200.0  # 46% 钛精矿 (元/吨)
FALLBACK_SULFURIC_ACID_PRICE_CNY = 350.0  # 98% 浓硫酸 (元/吨)

# 氯化铵与合成氨无独立现货序列，按仓库既有口径以尿素价格折算。
NH4CL_TO_UREA_RATIO = 0.45
NH3_TO_UREA_RATIO = 1.15

COMPUTED_SPREAD_SOURCE = "Derived/Config_Cost_Model+Local_Spot"


@dataclass(frozen=True)
class PriceInput:
    """单个价格输入的取数声明。"""

    key: str
    spot_symbols: tuple[str, ...] = ()
    futures_symbol: str | None = None
    coal_price: bool = False
    constant: float | None = None


@dataclass(frozen=True)
class SpreadComputation:
    """单期价差计算输出。"""

    product_price_cny: float
    byproduct_price_cny: float
    raw_material_cost_cny: float
    spread_margin_cny: float
    cash_breakeven_cost_cny: float
    margin_regime: str | None = None


@dataclass(frozen=True)
class SpreadProductSpec:
    """单个品种-工艺的价差计算规格。"""

    product_name: str
    symbol: str
    process_type: str
    regime_key: str
    inputs: tuple[PriceInput, ...]
    compute: Callable[[ChemicalSpreadCalculator, dict[str, float]], SpreadComputation]
    source: str = COMPUTED_SPREAD_SOURCE


def _compute_soda_ash_double_ton(
    calc: ChemicalSpreadCalculator, prices: dict[str, float]
) -> SpreadComputation:
    """联碱法双吨利润：纯碱 + 氯化铵 - 原盐/合成氨/动力煤成本 - 固定加工费。"""
    soda_price = prices["soda_price"]
    urea_price = prices["urea_price"]
    coal_price = prices["coal_price"]
    salt_price = prices["salt_price"]
    nh4cl_price = round(urea_price * NH4CL_TO_UREA_RATIO, 2)
    nh3_price = urea_price * NH3_TO_UREA_RATIO
    margin = calc.calculate_soda_ash_double_ton_margin(
        soda_price, nh4cl_price, salt_price, nh3_price, coal_price
    )
    cfg = calc.load_cost_models().get("models", {}).get("soda_ash", {}).get("hou_process", {})
    coeffs = cfg.get("coefficients", {})
    fixed_cost = float(cfg.get("fixed_cost", 450.0))
    raw_cost = round(
        float(coeffs.get("raw_salt", 1.2)) * salt_price
        + float(coeffs.get("synthetic_ammonia", 0.135)) * nh3_price
        + float(coeffs.get("thermal_coal", 0.4)) * coal_price,
        2,
    )
    return SpreadComputation(
        product_price_cny=soda_price,
        byproduct_price_cny=nh4cl_price,
        raw_material_cost_cny=raw_cost,
        spread_margin_cny=margin,
        cash_breakeven_cost_cny=round(raw_cost + fixed_cost - nh4cl_price, 2),
    )


def _compute_caustic_soda_ecu(
    calc: ChemicalSpreadCalculator, prices: dict[str, float]
) -> SpreadComputation:
    """氯碱 ECU 综合毛利：折百烧碱 + 0.886 液氯 - 完全成本。"""
    result = calc.calculate_ecu_margin(
        prices["caustic_soda_price"], prices["chlorine_price"], is_32pct_liquid=True
    )
    return SpreadComputation(
        product_price_cny=float(result["caustic_100_price"]),
        byproduct_price_cny=prices["chlorine_price"],
        raw_material_cost_cny=float(result["ecu_full_cost"]),
        spread_margin_cny=float(result["ecu_margin_cny"]),
        cash_breakeven_cost_cny=float(result["ecu_cash_cost"]),
        margin_regime=str(result["ecu_regime"]),
    )


def _compute_pta_processing_spread(
    calc: ChemicalSpreadCalculator, prices: dict[str, float]
) -> SpreadComputation:
    """PTA 理论加工费：PTA 现货 - 0.655 × PX（系数取自 pta/standard）。"""
    pta_price = prices["pta_price"]
    px_price = prices["px_price"]
    cfg = calc.load_cost_models().get("models", {}).get("pta", {}).get("standard", {})
    px_coeff = float(cfg.get("coefficients", {}).get("feedstock_px", 0.655))
    raw_cost = round(px_coeff * px_price, 2)
    cash_fixed = float(cfg.get("cash_fixed_cost", 380.0))
    return SpreadComputation(
        product_price_cny=pta_price,
        byproduct_price_cny=0.0,
        raw_material_cost_cny=raw_cost,
        spread_margin_cny=calc.calculate_pta_processing_spread(pta_price, px_price),
        cash_breakeven_cost_cny=round(raw_cost + cash_fixed, 2),
    )


def _compute_tio2_sulfate(
    calc: ChemicalSpreadCalculator, prices: dict[str, float]
) -> SpreadComputation:
    """硫酸法金红石钛白粉理论毛利：TiO2 - 2.0 钛精矿 - 3.5 浓硫酸 - 固定费。"""
    tio2_price = prices["tio2_price"]
    ilmenite_price = prices["ilmenite_price"]
    acid_price = prices["h2so4_price"]
    return SpreadComputation(
        product_price_cny=tio2_price,
        byproduct_price_cny=0.0,
        raw_material_cost_cny=round(2.0 * ilmenite_price + 3.5 * acid_price, 2),
        spread_margin_cny=calc.calculate_tio2_sulfate_margin(
            tio2_price, ilmenite_price, acid_price
        ),
        cash_breakeven_cost_cny=calc.calculate_tio2_sulfate_cash_cost(ilmenite_price, acid_price),
    )


def _compute_methanol_margin(
    calc: ChemicalSpreadCalculator, prices: dict[str, float]
) -> SpreadComputation:
    """煤制甲醇理论毛利：甲醇 - 1.6 × 动力煤 - 固定加工费。"""
    methanol_price = prices["methanol_price"]
    coal_price = prices["coal_price"]
    cfg = calc.load_cost_models().get("models", {}).get("methanol", {}).get("coal_to_methanol", {})
    coal_coeff = float(cfg.get("coefficients", {}).get("thermal_coal", 1.6))
    raw_cost = round(coal_coeff * coal_price, 2)
    cash_fixed = float(cfg.get("cash_fixed_cost", 420.0))
    return SpreadComputation(
        product_price_cny=methanol_price,
        byproduct_price_cny=0.0,
        raw_material_cost_cny=raw_cost,
        spread_margin_cny=calc.calculate_methanol_margin(methanol_price, coal_price),
        cash_breakeven_cost_cny=round(raw_cost + cash_fixed, 2),
    )


def _compute_urea_coal_margin(
    calc: ChemicalSpreadCalculator, prices: dict[str, float]
) -> SpreadComputation:
    """煤制尿素加工差：尿素 - 1.2 × 动力煤 - 固定加工费。"""
    urea_price = prices["urea_price"]
    coal_price = prices["coal_price"]
    result = calc.calculate_urea_coal_margin(urea_price, coal_price)
    cfg = calc.load_cost_models().get("models", {}).get("urea", {}).get("fixed_bed_coal", {})
    return SpreadComputation(
        product_price_cny=urea_price,
        byproduct_price_cny=0.0,
        raw_material_cost_cny=round(1.2 * coal_price, 2),
        spread_margin_cny=float(result["spread_margin_cny"]),
        cash_breakeven_cost_cny=float(cfg.get("cash_cost_approx", 1750.0)),
        margin_regime=str(result["margin_regime"]),
    )


SPREAD_PRODUCT_SPECS: tuple[SpreadProductSpec, ...] = (
    SpreadProductSpec(
        product_name="纯碱",
        symbol="SA",
        process_type="联碱法双吨",
        regime_key="soda_ash",
        inputs=(
            PriceInput(key="soda_price", spot_symbols=("SA_light",), futures_symbol="SA"),
            PriceInput(key="urea_price", spot_symbols=("UR",), futures_symbol="UR"),
            PriceInput(key="coal_price", coal_price=True),
            PriceInput(key="salt_price", constant=FALLBACK_SALT_PRICE_CNY),
        ),
        compute=_compute_soda_ash_double_ton,
    ),
    SpreadProductSpec(
        product_name="烧碱",
        symbol="SH",
        process_type="氯碱综合ECU",
        regime_key="caustic_soda",
        inputs=(
            PriceInput(key="caustic_soda_price", spot_symbols=("SH",), futures_symbol="SH"),
            PriceInput(key="chlorine_price", constant=FALLBACK_CHLORINE_PRICE_CNY),
        ),
        compute=_compute_caustic_soda_ecu,
    ),
    SpreadProductSpec(
        product_name="PTA",
        symbol="TA",
        process_type="PTA加工费",
        regime_key="pta",
        inputs=(
            PriceInput(key="pta_price", spot_symbols=("TA",), futures_symbol="TA"),
            PriceInput(key="px_price", spot_symbols=("PX",)),
        ),
        compute=_compute_pta_processing_spread,
    ),
    SpreadProductSpec(
        product_name="钛白粉",
        symbol="TiO2",
        process_type="硫酸法金红石",
        regime_key="tio2",
        inputs=(
            PriceInput(key="tio2_price", spot_symbols=("TiO2",)),
            PriceInput(
                key="ilmenite_price",
                spot_symbols=("ilmenite",),
                constant=FALLBACK_ILMENITE_PRICE_CNY,
            ),
            PriceInput(
                key="h2so4_price",
                spot_symbols=("H2SO4",),
                constant=FALLBACK_SULFURIC_ACID_PRICE_CNY,
            ),
        ),
        compute=_compute_tio2_sulfate,
    ),
    SpreadProductSpec(
        product_name="甲醇",
        symbol="MA",
        process_type="煤制甲醇",
        regime_key="methanol",
        inputs=(
            PriceInput(key="methanol_price", spot_symbols=("MA",), futures_symbol="MA"),
            PriceInput(key="coal_price", coal_price=True),
        ),
        compute=_compute_methanol_margin,
    ),
    SpreadProductSpec(
        product_name="尿素",
        symbol="UR",
        process_type="煤制尿素",
        regime_key="urea",
        inputs=(
            PriceInput(key="urea_price", spot_symbols=("UR",), futures_symbol="UR"),
            PriceInput(key="coal_price", coal_price=True),
        ),
        compute=_compute_urea_coal_margin,
    ),
)


def _derive_curated_dir(raw_dir: Path) -> Path:
    """由 RAW 根目录推导 Curated 根目录。

    标准布局 ``data/raw/industry`` → ``data/curated/industry``；
    非标准布局（如测试临时目录）下退回 ``raw_dir`` 自身，确保不会意外读到
    仓库真实 Curated 数据。
    """
    parts = list(raw_dir.parts)
    if "raw" in parts:
        index = len(parts) - 1 - parts[::-1].index("raw")
        return Path(*parts[:index], "curated", *parts[index + 1 :])
    return raw_dir


def _coalesce_price_sources(sources: list[pl.DataFrame]) -> pl.DataFrame:
    """按优先级合并多个价格源：日期网格取并集，同日取首个有值的来源。

    各来源内部以 ``join_asof(backward)`` 前向携带最近值；来源启用之前的历史缺口
    保持为空并交由下一优先级来源承接，绝不反向插值。
    """
    grid = pl.concat([frame.select("trade_date") for frame in sources]).unique().sort("trade_date")
    names = [f"_source_{index}" for index in range(len(sources))]
    for name, source in zip(names, sources, strict=True):
        grid = grid.join_asof(source.rename({"price": name}), on="trade_date", strategy="backward")
    return (
        grid.select(
            pl.col("trade_date"),
            pl.coalesce([pl.col(name) for name in names]).alias("price"),
        )
        .drop_nulls(subset=["price"])
        .sort("trade_date")
    )


def _normalize_price_series(frame: pl.DataFrame) -> pl.DataFrame:
    """收敛为 {trade_date, price} 并按日期排序，剔除空值与非正值。"""
    if frame.is_empty() or not {"trade_date", "price"}.issubset(set(frame.columns)):
        return pl.DataFrame()
    return (
        frame.select(
            pl.col("trade_date").cast(pl.Date),
            pl.col("price").cast(pl.Float64, strict=False),
        )
        .drop_nulls()
        .filter(pl.col("price") > 0)
        .sort("trade_date")
    )


def _format_number(value: float) -> str:
    return f"{value:.2f}"


def _merge_spread_frames(computed: pl.DataFrame, existing: pl.DataFrame) -> pl.DataFrame:
    """合并计算结果与存量事实行：计算已覆盖的（品种, 工艺）整体以计算值为准。"""
    if computed.is_empty():
        return existing
    if existing.is_empty():
        return computed
    covered = computed.select(["product_name", "symbol", "process_type"]).unique()
    retained = existing.join(covered, on=["product_name", "symbol", "process_type"], how="anti")
    return pl.concat([computed, retained], how="diagonal_relaxed").sort(
        ["product_name", "trade_date"]
    )


def _build_spread_result(frame: pl.DataFrame) -> IndustryFrameResult:
    """把价差 RAW 帧封装为带质检状态的端点结果。"""
    errors = validate_spread_raw_frame(frame)
    if frame.is_empty():
        status = "EMPTY"
    elif errors:
        status = "PARTIAL"
    else:
        status = "SUCCESS"
    cached = (
        tuple(sorted(str(value) for value in frame["trade_date"].to_list()))
        if "trade_date" in frame.columns
        else ()
    )
    return IndustryFrameResult(
        frame=frame,
        status=status,
        cached_periods=cached,
        errors=errors,
        updated=False,
    )


def _empty_spread_raw_frame() -> pl.DataFrame:
    return pl.DataFrame(schema=SPREAD_RAW_SCHEMA)


def _load_raw_spread_frame(path: Path) -> pl.DataFrame:
    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {
            "trade_date",
            "product_name",
            "symbol",
            "process_type",
            "product_price_cny",
            "raw_material_cost_cny",
            "spread_margin_cny",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            logger.warning("化工价差 RAW 字段不完整，跳过: %s missing=%s", path, sorted(missing))
            return _empty_spread_raw_frame()
        for row in reader:
            status = str(row.get("data_status") or "").strip()
            if status and status not in {
                "actual",
                "source_reported",
                "verified_industry_report",
                "benchmark",
                "spot_benchmark",
            }:
                continue
            trade_date = _safe_date(row.get("trade_date"))
            if trade_date is None:
                continue
            records.append(
                {
                    "trade_date": trade_date,
                    "product_name": str(row.get("product_name") or "").strip(),
                    "symbol": str(row.get("symbol") or "").strip(),
                    "process_type": str(row.get("process_type") or "").strip().removesuffix("型"),
                    "product_price_cny_raw": str(row.get("product_price_cny") or ""),
                    "byproduct_price_cny_raw": str(row.get("byproduct_price_cny") or ""),
                    "raw_material_cost_cny_raw": str(row.get("raw_material_cost_cny") or ""),
                    "spread_margin_cny_raw": str(row.get("spread_margin_cny") or ""),
                    "cash_breakeven_cost_cny_raw": str(row.get("cash_breakeven_cost_cny") or ""),
                    "margin_regime_raw": str(row.get("margin_regime") or ""),
                    "source": str(row.get("source") or "").strip(),
                    "release_date": _safe_date(row.get("release_date")),
                    "collected_at": str(row.get("collected_at") or "").strip(),
                    "data_status": status or "actual",
                }
            )
    if not records:
        return _empty_spread_raw_frame()
    return pl.DataFrame(records, schema=SPREAD_RAW_SCHEMA).sort(["product_name", "trade_date"])


def _load_raw_spread_records(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    required = {
        "trade_date",
        "product_name",
        "symbol",
        "process_type",
        "product_price_cny",
        "raw_material_cost_cny",
        "spread_margin_cny",
    }
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = required - set(reader.fieldnames or [])
        if missing:
            logger.warning("化工价差 RAW 字段不完整，跳过: %s missing=%s", path, sorted(missing))
            return []
        for row in reader:
            status = str(row.get("data_status") or "").strip()
            if status and status not in {
                "actual",
                "source_reported",
                "verified_industry_report",
                "benchmark",
                "spot_benchmark",
            }:
                continue
            trade_date = _safe_date(row.get("trade_date"))
            if trade_date is None:
                continue
            records.append(
                {
                    "trade_date": trade_date,
                    "product_name": str(row.get("product_name") or "").strip(),
                    "symbol": str(row.get("symbol") or "").strip(),
                    "process_type": str(row.get("process_type") or "").strip(),
                    "product_price_cny": _safe_float(row.get("product_price_cny")),
                    "byproduct_price_cny": _safe_float(row.get("byproduct_price_cny")),
                    "raw_material_cost_cny": _safe_float(row.get("raw_material_cost_cny")),
                    "spread_margin_cny": _safe_float(row.get("spread_margin_cny")),
                    "cash_breakeven_cost_cny": _safe_float(row.get("cash_breakeven_cost_cny")),
                    "margin_regime": str(row.get("margin_regime") or "").strip(),
                    "source": str(row.get("source") or "").strip(),
                    "release_date": _safe_date(row.get("release_date")),
                    "collected_at": str(row.get("collected_at") or "").strip(),
                }
            )
    return records


def _safe_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"nan", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _safe_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


__all__ = [
    "SPREAD_PRODUCT_SPECS",
    "SPREAD_RAW_SCHEMA",
    "SPREAD_SCHEMA",
    "ChemicalSpreadCalculator",
    "PriceInput",
    "SpreadComputation",
    "SpreadProductSpec",
    "build_spread_curated_frame",
    "build_spread_raw_frame",
]
