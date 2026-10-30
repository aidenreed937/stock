"""钛白粉核心企业未来营收与利润分部预测引擎 (CompanyProjectionEngine)。

提供业务分部 (SOTP Bottom-Up) 与集团财务合并 (Consolidated Bridge) 预测：
1. 分部测算：覆盖钛白粉 (硫酸法/氯化法)、海绵钛与金属锆、铁精矿外售、磷酸铁与磷矿等；
2. 集团合并：聚合分部毛利，执行费用桥梁 (OPEX Bridge) 与所得税测算；
3. 情景推演：输出周期底部磨底 (trough)、中性中枢复苏 (mid_cycle)、景气高峰繁荣 (peak) 的归母净利与目标估值；
4. 敏感性分析：生成产品售价 vs 原料成本的二维归母净利润敏感性矩阵。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import polars as pl
import yaml

from stock_analytics.pipelines.calibration import ConfidenceBandResult, IndustrialCostCalibrator

logger = logging.getLogger(__name__)

DEFAULT_PROJECTION_CONFIG_PATH = Path("config/industry/chemicals/tio2/company_projections.yaml")

_PERIOD_MONTHS_BY_SUFFIX: dict[str, int] = {
    "03-31": 3,
    "06-30": 6,
    "09-30": 9,
    "12-31": 12,
}


@dataclass(frozen=True, slots=True)
class SegmentResult:
    """单个业务分部的预测结果。"""

    segment_key: str
    segment_name: str
    sales_volume_tons: float
    unit_price_cny: float
    unit_cost_cny: float
    unit_gross_margin_cny: float
    revenue_cny: float
    gross_profit_cny: float
    gross_margin_ratio: float


@dataclass(frozen=True, slots=True)
class CompanyFinancialContext:
    """企业真实财报动态装配上下文。"""

    symbol: str
    report_date: str | None
    ann_date: str | None
    total_shares: float
    net_assets_cny: float
    bps: float
    annualized_finance_expense: float | None
    interest_bearing_debt_cny: float | None = None
    money_cap_cny: float | None = None
    historical_pb_percentiles: dict[str, float] | None = None
    latest_market_pb: float | None = None
    auxiliary_revenues_cny: dict[str, float] | None = None
    historical_3y_avg_revenue_cny: float | None = None
    source_mode: str = "static_config"  # "dynamic_catalog" 或 "static_config"


@dataclass(frozen=True, slots=True)
class CompanyProjectionResult:
    """集团综合合并测算产出。"""

    symbol: str
    company_name: str
    scenario_key: str
    scenario_name: str
    segments: list[SegmentResult]
    total_revenue_cny: float
    total_gross_profit_cny: float
    blended_gpm: float
    total_expense_cny: float
    finance_expense_cny: float
    operating_profit_cny: float
    income_tax_cny: float
    net_profit_attr_p_cny: float
    net_profit_margin: float
    eps_cny: float
    pe_multiple: float
    target_market_cap_cny: float
    target_stock_price_cny: float
    bps_cny: float = 0.0
    target_pb: float = 0.0
    target_market_cap_pb_cny: float = 0.0
    target_stock_price_pb_cny: float = 0.0
    core_tio2_gross_profit_cny: float = 0.0
    core_tio2_eps_cny: float = 0.0
    auxiliary_gross_profit_cny: float = 0.0
    auxiliary_eps_cny: float = 0.0
    export_rebate_income_cny: float = 0.0
    financial_report_date: str | None = None
    data_source_mode: str = "static_config"


def extract_auxiliary_revenues(
    recent_mbz: pl.DataFrame,
    has_iron_phosphate_seg: bool = False,
) -> dict[str, float]:
    """从最近 3 个年报主营构成提取非核心副业营收中枢（中位数，单位元）。

    - 新能源材料：龙佰 → new_energy；钛能（含 iron_phosphate 分部）→ iron_phosphate；
    - 磷矿/磷矿石 → phosphate_ore（钛能贵州开阳磷矿外售口径）；
    - 物流/贸易/供应链 → trading_other（仅保留 >1 亿元的大额主营科目）。
    """
    aux: dict[str, float] = {}

    ne_rows = recent_mbz.filter(pl.col("bz_item").str.contains("新能源"))
    if not ne_rows.is_empty():
        seg_key = "iron_phosphate" if has_iron_phosphate_seg else "new_energy"
        aux[seg_key] = round(float(str(ne_rows["bz_sales"].median())), 2)

    po_rows = recent_mbz.filter(pl.col("bz_item").str.contains("磷矿|磷矿石"))
    if not po_rows.is_empty():
        aux["phosphate_ore"] = round(float(str(po_rows["bz_sales"].median())), 2)

    yp_rows = recent_mbz.filter(pl.col("bz_item").str.contains("黄磷"))
    if not yp_rows.is_empty():
        aux["yellow_phosphorus"] = round(float(str(yp_rows["bz_sales"].median())), 2)

    tr_rows = recent_mbz.filter(
        (
            pl.col("bz_item").is_in(
                ["其他主营业务", "其他", "供应链贸易", "贸易", "物流服务", "物流类"]
            )
            | (
                pl.col("bz_item").str.contains("其他主营业务|供应链|贸易|物流")
                & ~pl.col("bz_item").is_in(["其他业务", "其他业务(地区)"])
            )
        )
        & (pl.col("bz_sales") > 1.0e8)
    )
    if not tr_rows.is_empty():
        aux["trading_other"] = round(float(str(tr_rows["bz_sales"].median())), 2)
    return aux


def extract_auxiliary_revenues_actual(
    report_mbz: pl.DataFrame,
    has_iron_phosphate_seg: bool = False,
    period_months: int | None = 12,
) -> dict[str, float]:
    """从单个最新报告期主营构成提取副业营收并按报告期月数年化（Phase 1 副业实际化）。

    - 新能源材料 → new_energy / iron_phosphate（钛能）；
    - 磷矿/磷矿石 → phosphate_ore；
    - 其他主营业务/物流/贸易（>1 亿元）→ trading_other。
    每个副业键取该期最大匹配值，避免产品/分部双重计数；period_months 为报告期覆盖月数。
    """
    if (
        report_mbz.is_empty()
        or "bz_item" not in report_mbz.columns
        or "bz_sales" not in report_mbz.columns
    ):
        return {}
    if period_months is None or period_months <= 0:
        return {}
    scale = 12.0 / float(period_months)
    aux: dict[str, float] = {}

    def pick(pattern: str) -> float | None:
        rows = report_mbz.filter(pl.col("bz_item").cast(pl.Utf8).str.contains(pattern))
        vals = rows["bz_sales"].cast(pl.Float64, strict=False).drop_nulls()
        return float(str(vals.max())) if len(vals) > 0 else None

    ne = pick("新能源")
    if ne is not None:
        aux["iron_phosphate" if has_iron_phosphate_seg else "new_energy"] = round(ne * scale, 2)
    po = pick("磷矿|磷矿石")
    if po is not None:
        aux["phosphate_ore"] = round(po * scale, 2)
    yp = pick("黄磷")
    if yp is not None:
        aux["yellow_phosphorus"] = round(yp * scale, 2)
    tr_rows = report_mbz.filter(
        (
            pl.col("bz_item").is_in(
                ["其他主营业务", "其他", "供应链贸易", "贸易", "物流服务", "物流类"]
            )
            | (
                pl.col("bz_item").cast(pl.Utf8).str.contains("其他主营业务|供应链|贸易|物流")
                & ~pl.col("bz_item").is_in(["其他业务", "其他业务(地区)"])
            )
        )
        & (pl.col("bz_sales").cast(pl.Float64, strict=False) > 1.0e8)
    )
    if not tr_rows.is_empty():
        aux["trading_other"] = round(
            float(str(tr_rows["bz_sales"].cast(pl.Float64, strict=False).drop_nulls().max()))
            * scale,
            2,
        )
    return aux


def filter_mainbz_by_disclosure(
    mbz_df: pl.DataFrame,
    ann_map: dict[str, str],
    as_of_str: str | None,
) -> pl.DataFrame:
    """按披露日对主营构成做 Point-in-Time 截断。

    fina_mainbz 无 ann_date 字段，借用 income 表的 end_date→ann_date 映射判断披露时点；
    映射缺失时降级按 end_date（报告期末）≤ as_of 截断。
    """
    if mbz_df is None or mbz_df.is_empty() or not as_of_str:
        return mbz_df
    end_dates = mbz_df["end_date"].cast(pl.Utf8).to_list()
    disclosures = [ann_map.get(d, d) for d in end_dates]
    return (
        mbz_df.with_columns(pl.Series("_disclosure", disclosures))
        .filter(pl.col("_disclosure") <= as_of_str)
        .drop("_disclosure")
    )


class CompanyProjectionEngine:
    """企业分部 SOTP 与综合财务预测引擎。"""

    def __init__(
        self,
        config_path: Path | str | None = None,
        catalog: Any | None = None,
        as_of_date: Any | None = None,
        cost_lag_days: int = 0,
    ) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_PROJECTION_CONFIG_PATH
        self.catalog: Any = None
        if catalog is None:
            try:
                from stock_data.catalog import DataCatalog

                self.catalog = DataCatalog(data_source="tushare")
            except Exception as cat_exc:
                logger.debug(f"未能自动初始化 DataCatalog: {cat_exc}")
                self.catalog = None
        elif catalog is False:
            self.catalog = None
        else:
            self.catalog = catalog

        from datetime import date

        self.as_of_date = as_of_date
        if isinstance(as_of_date, date):
            self.as_of_str: str | None = as_of_date.strftime("%Y-%m-%d")
        elif isinstance(as_of_date, str) and as_of_date.strip():
            self.as_of_str = as_of_date.strip()
        else:
            self.as_of_str = None

        self.cost_lag_days = max(0, int(cost_lag_days))

        self._config_cache: dict[str, Any] | None = None
        self._financial_context_cache: dict[str, CompanyFinancialContext] = {}
        self._export_weight_cache: dict[str, float] = {}
        self._export_premium_ratio: float | None = None
        self._ann_map_cache: dict[str, dict[str, str]] = {}

    def load_config(self) -> dict[str, Any]:
        """加载分部预测配置并自适应注入当前现货实时情景 (current_spot)。"""
        if self._config_cache is not None:
            return self._config_cache
        if not self.config_path.exists():
            legacy_path = Path("config/industry/chemicals/company_projections.yaml")
            if legacy_path.exists():
                self.config_path = legacy_path
            else:
                raise FileNotFoundError(f"未找到企业预测配置文件: {self.config_path}")
        raw_cfg = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        self._config_cache = self._inject_monthly_utilization(
            self._inject_current_spot_scenario(raw_cfg)
        )
        return self._config_cache

    def _inject_current_spot_scenario(self, cfg: dict[str, Any]) -> dict[str, Any]:
        """从本地 chemical_spot_price 黄金事实表动态构建并注入 current_spot 情景。"""
        cfg_copy = dict(cfg)
        scenarios = dict(cfg_copy.get("scenarios", {}))

        # 默认回退现货值 (若离线或缺失时)
        p_tio2 = 14200.0
        p_ore = 1555.0
        p_sponge = 48000.0
        p_coal = 950.0
        p_acid = 1812.5  # 100ppi 硫酸基准价 2026-09-18 (Curated H2SO4 缺失时回退)
        p_fe_po4 = 10000.0  # 回退值；优先取 realized_price.fe_po4_price_current
        date_tio2 = None
        date_ore = None
        date_acid = None
        try:
            rp_base = cfg_copy.get("realized_price", {}) or {}
            p_fe_po4 = float(rp_base.get("fe_po4_price_current", p_fe_po4))
        except Exception:
            pass

        spot_df = None
        if self.catalog is not None:
            try:
                spot_df = self.catalog.load_dataset("chemical_spot_price")
            except Exception:
                spot_df = None

        if spot_df is None or spot_df.is_empty():
            try:
                from stock_data.catalog import DataCatalog

                cat_ind = DataCatalog(data_source="industry")
                spot_df = cat_ind.load_dataset("chemical_spot_price")
            except Exception as e:
                logger.debug(f"加载行业现货表失败: {e}")
                spot_df = None

        if spot_df is not None and not spot_df.is_empty() and "product_name" in spot_df.columns:
            try:
                # Point-in-Time 防前视：优先按发布日 release_date ≤ as_of 截断，
                # 缺失发布日时降级按 trade_date（交易日）≤ as_of 截断。
                if self.as_of_str:
                    if (
                        "release_date" in spot_df.columns
                        and not spot_df["release_date"].is_null().all()
                    ):
                        spot_df = spot_df.filter(
                            pl.col("release_date").cast(pl.Utf8) <= self.as_of_str
                        )
                    elif "trade_date" in spot_df.columns:
                        spot_df = spot_df.filter(
                            pl.col("trade_date").cast(pl.Utf8) <= self.as_of_str
                        )

                sub_tio2 = spot_df.filter(pl.col("product_name") == "钛白粉").sort("trade_date")
                if not sub_tio2.is_empty():
                    t_row = sub_tio2.tail(1).to_dicts()[0]
                    p_tio2 = float(t_row.get("spot_price_cny") or p_tio2)
                    date_tio2 = str(t_row.get("trade_date"))

                sub_ore = spot_df.filter(pl.col("product_name") == "钛精矿").sort("trade_date")
                sub_acid = spot_df.filter(pl.col("product_name") == "硫酸").sort("trade_date")

                # 会计存货时滞结转 (Cost Lag Filter)：若开启 cost_lag_days > 0，原料价格滞后结转
                lag_applied = False
                if self.cost_lag_days > 0:
                    from datetime import date as dt_date
                    from datetime import timedelta

                    base_dt: dt_date | None = None
                    if self.as_of_str:
                        try:
                            base_dt = dt_date.fromisoformat(self.as_of_str[:10])
                        except Exception:
                            base_dt = None
                    if base_dt is None and not sub_tio2.is_empty():
                        latest_td = sub_tio2.tail(1)["trade_date"][0]
                        if isinstance(latest_td, dt_date):
                            base_dt = latest_td
                        elif isinstance(latest_td, str):
                            try:
                                base_dt = dt_date.fromisoformat(latest_td[:10])
                            except Exception:
                                base_dt = None

                    if base_dt is not None:
                        lag_dt = base_dt - timedelta(days=self.cost_lag_days)
                        ore_lag = sub_ore.filter(pl.col("trade_date") <= lag_dt)
                        if not ore_lag.is_empty():
                            o_row = ore_lag.tail(1).to_dicts()[0]
                            raw_ore = float(o_row.get("spot_price_cny") or 1205.0)
                            p_ore = raw_ore + 350.0
                            date_ore = f"{o_row.get('trade_date')}[滞后{self.cost_lag_days}d]"
                            lag_applied = True

                        acid_lag = sub_acid.filter(pl.col("trade_date") <= lag_dt)
                        if not acid_lag.is_empty():
                            acid_rows = acid_lag.tail(1).to_dicts()
                            if len(acid_rows) > 1:
                                acid_rows = [
                                    r for r in acid_rows if str(r.get("region") or "") == "湖北"
                                ] or acid_rows
                            a_row = acid_rows[0]
                            p_acid = float(a_row.get("spot_price_cny") or p_acid)
                            date_acid = f"{a_row.get('trade_date')}[滞后{self.cost_lag_days}d]"
                            lag_applied = True

                if not lag_applied:
                    if not sub_ore.is_empty():
                        o_row = sub_ore.tail(1).to_dicts()[0]
                        raw_ore = float(o_row.get("spot_price_cny") or 1205.0)
                        p_ore = raw_ore + 350.0  # 攀西出厂价 + 运费 = 到厂入库含税成本
                        date_ore = str(o_row.get("trade_date"))

                    # 浓硫酸 (H2SO4): 2026-09 起接入 Curated 现货表，湖北 98% 冶炼酸为全国参考口径
                    if not sub_acid.is_empty():
                        acid_rows = sub_acid.tail(1).to_dicts()
                        if len(acid_rows) > 1:
                            acid_rows = [
                                r for r in acid_rows if str(r.get("region") or "") == "湖北"
                            ] or acid_rows
                        a_row = acid_rows[0]
                        p_acid = float(a_row.get("spot_price_cny") or p_acid)
                        date_acid = str(a_row.get("trade_date"))

                p_sponge = 45000.0
                sub_sponge = spot_df.filter(pl.col("product_name") == "海绵钛").sort("trade_date")
                if not sub_sponge.is_empty():
                    s_row = sub_sponge.tail(1).to_dicts()[0]
                    p_sponge = float(s_row.get("spot_price_cny") or p_sponge)

                p_coal = 950.0
                sub_coal = spot_df.filter(pl.col("product_name") == "动力煤").sort("trade_date")
                if not sub_coal.is_empty():
                    c_row = sub_coal.tail(1).to_dicts()[0]
                    p_coal = float(c_row.get("spot_price_cny") or p_coal)
            except Exception as parse_e:
                logger.debug(f"解析最新现货行情异常: {parse_e}")
                p_sponge = 48000.0
                p_coal = 950.0

        date_desc = (
            f"(钛白粉 {date_tio2 or '最新'} 报 {p_tio2:.0f}元, 钛矿 {date_ore or '最新'} 入库 {p_ore:.0f}元, "
            f"硫酸 {date_acid or '最新'} {p_acid:.0f}元, 海绵钛 {p_sponge:.0f}元)"
        )
        scen_name = (
            f"当前现货实时测算(会计时滞{self.cost_lag_days}天)"
            if self.cost_lag_days > 0
            else "当前现货实时测算"
        )
        current_spot_scen = {
            "name": scen_name,
            "cost_lag_days": self.cost_lag_days,
            "description": f"基于本地黄金事实表最新报价 {date_desc} 动态自适应测算",
            "tio2_sulfate_price": round(p_tio2, 1),
            "ilmenite_market_price": round(p_ore, 1),
            "acid_price": round(p_acid, 1),
            "iron_ore_price": 800.0,
            "sponge_ti_price": round(p_sponge, 1),
            "fe_po4_price": round(p_fe_po4, 1),
            "phosphate_rock_price": 920.0,
            "pe_multiple": 15.0,
        }

        # 增加副业失血极端情景压力测试
        aux_stress_scen = {
            "name": "副业失血压力测试 (极端情景)",
            "description": "压力测试：海绵钛贴紧成本线(44000元)，磷酸铁锂业务毛利归零，检验主业自由现金流底线",
            "tio2_sulfate_price": round(p_tio2, 1),
            "ilmenite_market_price": round(p_ore, 1),
            "acid_price": round(p_acid, 1),
            "iron_ore_price": 720.0,
            "sponge_ti_price": 44000.0,
            "fe_po4_price": 8500.0,
            "phosphate_rock_price": 850.0,
            "pe_multiple": 12.0,
        }

        new_scenarios = {
            "current_spot": current_spot_scen,
            "auxiliary_stress": aux_stress_scen,
        }
        for k, v in scenarios.items():
            if k not in new_scenarios:
                new_scenarios[k] = v
        cfg_copy["scenarios"] = new_scenarios
        return cfg_copy

    def _inject_monthly_utilization(self, cfg: dict[str, Any]) -> dict[str, Any]:
        """从 chemical_monthly_survey 黄金事实表注入钛白粉行业产能利用率到情景。

        仅对声明 ``dynamic_utilization: true`` 的分部（当前为钛能化学硫酸法）生效：
        - current_spot / auxiliary_stress：采用最新可得月频产能利用率；
        - trough：采用近 6 个月最小值（行业底部负荷）；
        - mid_cycle / peak：保留配置利用率（前瞻情景，不绑定当下弱负荷）。
        数据缺失或注入失败时返回原配置，回退各分部配置的 utilization_rate。
        """
        try:
            monthly_df = None
            if self.catalog is not None:
                try:
                    monthly_df = self.catalog.load_dataset("chemical_monthly_survey")
                except Exception:
                    monthly_df = None
            if monthly_df is None or monthly_df.is_empty():
                from stock_data.catalog import DataCatalog

                cat_ind = DataCatalog(data_source="industry")
                monthly_df = cat_ind.load_dataset("chemical_monthly_survey")
            if (
                monthly_df is None
                or monthly_df.is_empty()
                or "symbol" not in monthly_df.columns
                or "operating_rate_pct" not in monthly_df.columns
            ):
                return cfg

            sub = monthly_df.filter(
                (pl.col("symbol") == "TiO2") & pl.col("operating_rate_pct").is_not_null()
            )
            if sub.is_empty():
                return cfg
            # Point-in-Time 防前视：优先按数据发布日 release_date ≤ as_of 截断，
            # 缺失发布日时降级以 report_month（数据月）≤ as_of 截断。
            if self.as_of_str:
                if "release_date" in sub.columns and not sub["release_date"].is_null().all():
                    sub = sub.filter(pl.col("release_date").cast(pl.Utf8) <= self.as_of_str)
                elif "report_month" in sub.columns:
                    sub = sub.filter(pl.col("report_month").cast(pl.Utf8) <= self.as_of_str[:7])
            if sub.is_empty():
                return cfg

            rows = sub.sort("report_month").to_dicts()
            latest_util = float(rows[-1]["operating_rate_pct"])
            recent_min = min(float(r["operating_rate_pct"]) for r in rows[-6:])
        except Exception:
            logger.debug("月频利用率注入失败，按配置利用率计算", exc_info=True)
            return cfg

        new_scenarios = dict(cfg.get("scenarios", {}))
        spot_fraction = round(latest_util / 100.0, 4)
        trough_fraction = round(recent_min / 100.0, 4)
        for key in ("current_spot", "auxiliary_stress"):
            scen = dict(new_scenarios.get(key, {}))
            scen["sulfate_utilization_rate"] = spot_fraction
            new_scenarios[key] = scen
        trough_scen = dict(new_scenarios.get("trough", {}))
        trough_scen["sulfate_utilization_rate"] = trough_fraction
        new_scenarios["trough"] = trough_scen

        new_cfg = dict(cfg)
        new_cfg["scenarios"] = new_scenarios
        return new_cfg

    # ------------------------------------------------------------------
    # Phase 1: 动态出口权重 / 实现价 / 实际成本口径
    # ------------------------------------------------------------------
    def _build_ann_map(self, company_id: str) -> dict[str, str]:
        """构建 income end_date → 最早披露日 映射（缓存）。"""
        if company_id in self._ann_map_cache:
            return self._ann_map_cache[company_id]
        ann_map: dict[str, str] = {}
        inc = pl.DataFrame()
        if self.catalog is not None:
            kwargs_list: list[dict[str, Any]] = [
                {"symbols": [company_id], "columns": ["end_date", "ann_date"]},
                {"symbols": [company_id]},
                {},
            ]
            for kw in kwargs_list:
                try:
                    inc = self.catalog.load_dataset("income", **kw)
                    if not inc.is_empty():
                        break
                except Exception:
                    continue
        if not inc.is_empty() and "end_date" in inc.columns and "ann_date" in inc.columns:
            for r in (
                inc.filter(pl.col("ann_date").is_not_null())
                .select(["end_date", "ann_date"])
                .iter_rows(named=True)
            ):
                key = str(r["end_date"])
                val = str(r["ann_date"])
                if key not in ann_map or val < ann_map[key]:
                    ann_map[key] = val
        self._ann_map_cache[company_id] = ann_map
        return ann_map

    def _load_mainbz_pit(self, company_id: str) -> pl.DataFrame:
        """加载 fina_mainbz 并按披露日（income ann_date 映射）PIT 截断。"""
        frame = pl.DataFrame()
        if self.catalog is not None:
            kw_list: list[dict[str, Any]] = [{"symbols": [company_id]}, {}]
            for kw in kw_list:
                try:
                    frame = self.catalog.load_dataset("fina_mainbz", **kw)
                    if not frame.is_empty():
                        break
                except Exception:
                    continue
        if frame.is_empty():
            return frame
        return filter_mainbz_by_disclosure(frame, self._build_ann_map(company_id), self.as_of_str)

    def _resolve_export_weight(self, company_id: str, c_cfg: dict[str, Any]) -> float:
        """动态出口权重 w_exp = 国外收入 / (国外 + 国内)，取 fina_mainbz 最新报告期。"""
        if company_id in self._export_weight_cache:
            return self._export_weight_cache[company_id]
        default = float(c_cfg.get("export_weight_fallback", 0.0))
        if c_cfg.get("export_weight_mode") != "dynamic":
            self._export_weight_cache[company_id] = default
            return default
        w = default
        region_keys = {"国外", "国际", "中国大陆", "国内", "地区"}
        try:
            mbz = self._load_mainbz_pit(company_id)
            if not mbz.is_empty() and "bz_item" in mbz.columns and "bz_sales" in mbz.columns:
                rows = mbz.filter(pl.col("bz_item").is_in(region_keys)).sort("end_date").to_dicts()
                if rows:
                    foreign_item = next(
                        (r for r in reversed(rows) if str(r["bz_item"]) in ("国外", "国际")),
                        None,
                    )
                    if foreign_item is not None:
                        end = str(foreign_item["end_date"])
                        foreign = float(foreign_item["bz_sales"] or 0.0)
                        domestic = None
                        same_period = [r for r in rows if str(r["end_date"]) == end]
                        for r in same_period:
                            if str(r["bz_item"]) in ("国内", "中国大陆"):
                                domestic = float(r["bz_sales"] or 0.0)
                        if domestic is None:
                            for r in same_period:
                                if str(r["bz_item"]) == "地区":
                                    domestic = float(r["bz_sales"] or 0.0) - foreign
                        if domestic is not None and foreign + domestic > 0:
                            w = foreign / (foreign + domestic)
        except Exception as exc:
            logger.debug(f"动态出口权重解析失败，使用 fallback: {exc}")
        w = max(0.0, min(1.0, w))
        self._export_weight_cache[company_id] = w
        return w

    def resolve_fx_rate(self) -> float:
        """解析最新可用 USD/CNY 或 USD/CNH 实时汇率。

        检索优先级：
        1. alphavantage 黄金事实表中的 CNH=X 最新收盘价（日频实时）
        2. yfinance 黄金事实表中的 CNH=X 最新收盘价（日频备用）
        3. fred 黄金事实表中的 DEXCHUS 最新收盘价（在岸官方中频）
        4. 配置文件 realized_price.fx_usd_cny 兜底 (默认 7.2)
        支持根据 as_of_date 严格执行 Point-in-Time 防前视截断。
        """
        rp = self.load_config().get("realized_price", {}) or {}
        fallback_fx = float(rp.get("fx_usd_cny", 7.2))

        from stock_data.catalog import DataCatalog

        # 1. 优先尝试日频高频 CNH=X (alphavantage, yfinance)
        for src in ("alphavantage", "yfinance"):
            try:
                cat = DataCatalog(data_source=src)
                fx_df = cat.load_dataset("macro_indicators")
                if not fx_df.is_empty() and "symbol" in fx_df.columns and "close" in fx_df.columns:
                    sub = fx_df.filter(
                        (pl.col("symbol").cast(pl.Utf8) == "CNH=X") & pl.col("close").is_not_null()
                    )
                    if self.as_of_str:
                        sub = sub.filter(pl.col("trade_date").cast(pl.Utf8) <= self.as_of_str)
                    if not sub.is_empty():
                        val = float(sub.sort("trade_date")["close"].tail(1)[0])
                        if val > 0:
                            return val
            except Exception:
                continue

        # 2. 尝试在岸官方 DEXCHUS (fred)
        try:
            cat = DataCatalog(data_source="fred")
            fx_df = cat.load_dataset("macro_indicators")
            if not fx_df.is_empty() and "symbol" in fx_df.columns and "close" in fx_df.columns:
                sub = fx_df.filter(
                    (pl.col("symbol").cast(pl.Utf8) == "DEXCHUS") & pl.col("close").is_not_null()
                )
                if self.as_of_str:
                    sub = sub.filter(pl.col("trade_date").cast(pl.Utf8) <= self.as_of_str)
                if not sub.is_empty():
                    val = float(sub.sort("trade_date")["close"].tail(1)[0])
                    if val > 0:
                        return val
        except Exception:
            pass

        return fallback_fx

    def _resolve_export_premium_ratio(self) -> float:
        """出口 ASP(RMB) / 国内出厂基准价 的最近比例（缓存）。"""
        if self._export_premium_ratio is not None:
            return self._export_premium_ratio
        rp = self.load_config().get("realized_price", {}) or {}
        fx = self.resolve_fx_rate()
        fallback = float(rp.get("export_premium_ratio_fallback", 1.12))
        ratio = fallback
        try:
            frame = pl.DataFrame()
            if self.catalog is not None:
                for name in ("chemical_customs_export", "mart/chemical_customs_export"):
                    try:
                        frame = self.catalog.load_dataset(name)
                    except Exception:
                        continue
                    if not frame.is_empty():
                        break
            if frame.is_empty():
                from stock_data.catalog import DataCatalog

                cat_ind = DataCatalog(data_source="industry")
                for name in ("chemical_customs_export", "mart/chemical_customs_export"):
                    try:
                        frame = cat_ind.load_dataset(name)
                    except Exception:
                        continue
                    if not frame.is_empty():
                        break
                if frame.is_empty():
                    frame = pl.read_parquet("data/curated/mart/chemical_customs_export.parquet")
            tio2 = frame.filter(pl.col("commodity_code") == "TiO2").sort("report_month")
            asp_usd = tio2["export_asp_usd_ton"].drop_nulls().tail(1)
            spot = pl.DataFrame()
            if self.catalog is not None:
                try:
                    spot = self.catalog.load_dataset("chemical_spot_price")
                except Exception:
                    spot = pl.DataFrame()
            if spot.is_empty() or "product_name" not in spot.columns:
                spot = DataCatalog(data_source="industry").load_dataset("chemical_spot_price")
            ti = spot.filter(pl.col("product_name") == "钛白粉").sort("trade_date")
            dom = ti["spot_price_cny"].drop_nulls().tail(1)
            if len(asp_usd) > 0 and len(dom) > 0 and float(dom[0]) > 0:
                # 实现价口径为不含退税的 FOB 混合价；出口退税单独建模为收益行（Phase 1.5）
                ratio = max(1.0, float(asp_usd[0]) * fx / float(dom[0]))
        except Exception as exc:
            logger.debug(f"出口溢价比例解析失败，使用 fallback {fallback}: {exc}")
        self._export_premium_ratio = ratio
        return ratio

    def _apply_realized_price(
        self,
        company_id: str,
        c_cfg: dict[str, Any],
        scenario: dict[str, Any],
    ) -> dict[str, Any]:
        """将情景国内出厂价转为实现价：p_eff = 价格 × (w×R + (1−w))。"""
        w = self._resolve_export_weight(company_id, c_cfg)
        if w <= 0:
            return scenario
        r = self._resolve_export_premium_ratio()
        k = w * r + (1.0 - w)
        scen = dict(scenario)
        scen["tio2_sulfate_price"] = round(float(scen.get("tio2_sulfate_price", 15500.0)) * k, 2)
        return scen

    def project_segment(
        self,
        company_id: str,
        seg_key: str,
        scenario_key: str,
    ) -> SegmentResult:
        """根据情景参数计算单个业务分部的量、价、营收与毛利。"""
        cfg = self.load_config()
        c_cfg = cfg["companies"][company_id]
        scenario = cfg["scenarios"][scenario_key]
        return self._calc_segment(company_id, seg_key, c_cfg, scenario, scenario_key)

    def _dynamic_aux_revenue(
        self,
        company_id: str,
        seg_key: str,
        seg_cfg: dict[str, Any],
    ) -> float | None:
        """读取 fina_mainbz 动态装配的副业营收中枢（source_mode=dynamic_mainbz 时）。"""
        if seg_cfg.get("source_mode") != "dynamic_mainbz":
            return None
        fin_ctx = self._financial_context_cache.get(company_id)
        if fin_ctx is None or not fin_ctx.auxiliary_revenues_cny:
            return None
        value = fin_ctx.auxiliary_revenues_cny.get(seg_key)
        return float(value) if value is not None and value > 0 else None

    def _calc_segment(
        self,
        company_id: str,
        seg_key: str,
        c_cfg: dict[str, Any],
        scenario: dict[str, Any],
        scenario_key: str = "",
    ) -> SegmentResult:
        """分部核心量本利测算内部实现。"""
        seg_cfg = c_cfg["segments"][seg_key]
        p_tio2 = float(scenario.get("tio2_sulfate_price", 15500.0))
        p_ore = float(scenario.get("ilmenite_market_price", 1900.0))
        p_acid = float(scenario.get("acid_price", 380.0))

        # 1. 硫酸法钛白粉
        if seg_key == "sulfate_tio2":
            cap_inc = float(seg_cfg.get("scenario_increments", {}).get(scenario_key, 0.0))
            cap_w_tons = float(seg_cfg["capacity_w_tons"]) + cap_inc
            # 动态利用率：声明 dynamic_utilization 的分部优先采用情景注入的行业产能利用率
            utilization = float(seg_cfg["utilization_rate"])
            if seg_cfg.get("dynamic_utilization"):
                utilization = float(scenario.get("sulfate_utilization_rate") or utilization)
            volume = cap_w_tons * utilization * 10_000.0

            captive_ratio = float(seg_cfg.get("ore_captive_ratio", 0.0))
            captive_cost = float(
                seg_cfg.get("ore_captive_cash_cost", seg_cfg.get("ore_captive_cost", 900.0))
            )
            blended_ore = captive_ratio * captive_cost + (1.0 - captive_ratio) * p_ore
            ore_consumed = float(seg_cfg.get("ore_consumption", 2.3))
            acid_consumed = float(
                seg_cfg.get("sulfate_acid_coeff", seg_cfg.get("acid_consumption", 3.0))
            )
            # Phase 1: per-company 成本校准系数（滚动回测标定）
            cal = c_cfg.get("calibration", {}) or {}
            ore_factor = float(cal.get("ore_factor", 1.0))
            acid_factor = float(cal.get("acid_factor", 1.0))
            fixed_mfg = float(cal.get("fixed_cost", seg_cfg.get("fixed_cost", 6600.0)))
            byproduct_cr = float(seg_cfg.get("byproduct_credit", 100.0))

            raw_cost = (
                ore_consumed * blended_ore * ore_factor + acid_consumed * p_acid * acid_factor
            )
            unit_cost = raw_cost + fixed_mfg - byproduct_cr
            unit_price = p_tio2
            unit_margin = unit_price - unit_cost
            revenue = volume * unit_price
            gross_profit = volume * unit_margin

        # 2. 氯化法钛白粉 (龙佰专属)
        elif seg_key == "chloride_tio2":
            cap_inc = float(seg_cfg.get("scenario_increments", {}).get(scenario_key, 0.0))
            raw_cap_w_tons = float(seg_cfg["capacity_w_tons"]) + cap_inc
            # 扣减转产海绵钛联产自用中间体四氯化钛折合产能 (消除重复计算)
            internal_deduct_w = float(seg_cfg.get("internal_conversion_deduction_w_tons", 0.0))
            eff_cap_w_tons = max(0.0, raw_cap_w_tons - internal_deduct_w)
            volume = eff_cap_w_tons * float(seg_cfg["utilization_rate"]) * 10_000.0
            unit_price = p_tio2 + float(seg_cfg.get("premium_vs_sulfate", 1800.0))
            unit_cost = float(seg_cfg.get("full_cost_approx", 13000.0))
            unit_margin = unit_price - unit_cost
            revenue = volume * unit_price
            gross_profit = volume * unit_margin

        # 3. 海绵钛及金属锆 (龙佰专属)
        elif seg_key == "sponge_ti":
            cap_inc = float(seg_cfg.get("scenario_increments", {}).get(scenario_key, 0.0))
            cap_w_tons = float(seg_cfg["capacity_w_tons"]) + cap_inc
            volume = cap_w_tons * float(seg_cfg["utilization_rate"]) * 10_000.0
            unit_price = float(scenario.get("sponge_ti_price", 52000.0))
            unit_cost = float(seg_cfg.get("full_cost_approx", 45000.0))
            unit_margin = unit_price - unit_cost
            sponge_revenue = volume * unit_price
            sponge_gp = volume * unit_margin
            zirconium_gp = float(seg_cfg.get("zirconium_gross_profit_cny", 3.5e8))
            zirconium_rev = float(seg_cfg.get("zirconium_revenue_fixed_cny", 1.2e9))
            revenue = sponge_revenue + zirconium_rev
            gross_profit = sponge_gp + zirconium_gp

        # 4. 高品位铁精矿外售 (龙佰专属)
        elif seg_key == "iron_ore":
            sales_inc = float(seg_cfg.get("scenario_increments", {}).get(scenario_key, 0.0))
            sales_w_tons = float(seg_cfg["sales_w_tons"]) + sales_inc
            volume = sales_w_tons * 10_000.0
            unit_price = float(scenario.get("iron_ore_price", 850.0))
            unit_cost = float(seg_cfg.get("unit_cash_cost", 380.0))
            unit_margin = unit_price - unit_cost
            revenue = volume * unit_price
            gross_profit = volume * unit_margin

        # 5. 电池级磷酸铁 (钛能化学专属)
        elif seg_key == "iron_phosphate":
            unit_price = float(scenario.get("fe_po4_price", 11000.0))
            unit_cost = float(seg_cfg.get("unit_cost_with_byproduct", 9000.0))
            unit_margin = unit_price - unit_cost
            dyn_rev = self._dynamic_aux_revenue(company_id, seg_key, seg_cfg)
            if dyn_rev is not None and dyn_rev > 0 and scenario_key not in ("mid_cycle", "peak"):
                # 以 fina_mainbz 历史营收中枢为底，按情景价反推销量（不套用满产产能）
                volume = dyn_rev / unit_price
                revenue = dyn_rev
                gross_profit = volume * unit_margin
            else:
                cap_inc = float(seg_cfg.get("scenario_increments", {}).get(scenario_key, 0.0))
                cap_w_tons = float(seg_cfg["capacity_w_tons"]) + cap_inc
                volume = cap_w_tons * float(seg_cfg["utilization_rate"]) * 10_000.0
                revenue = volume * unit_price
                gross_profit = volume * unit_margin

        # 6. 贵州开阳磷矿 (钛能化学专属)
        elif seg_key == "phosphate_ore":
            unit_price = float(scenario.get("phosphate_rock_price", 950.0))
            unit_cost = float(seg_cfg.get("unit_mining_cost", 380.0))
            unit_margin = unit_price - unit_cost
            dyn_rev = self._dynamic_aux_revenue(company_id, seg_key, seg_cfg)
            if dyn_rev is not None and dyn_rev > 0 and scenario_key not in ("mid_cycle", "peak"):
                volume = dyn_rev / unit_price
                revenue = dyn_rev
                gross_profit = volume * unit_margin
            else:
                sales_inc = float(seg_cfg.get("scenario_increments", {}).get(scenario_key, 0.0))
                sales_w_tons = float(seg_cfg["external_sales_w_tons"]) + sales_inc
                volume = sales_w_tons * 10_000.0
                revenue = volume * unit_price
                gross_profit = volume * unit_margin

        # 7. 其他/贸易综合分部 (支持 fina_mainbz 历史中枢动态装配)
        else:
            fin_ctx = self._financial_context_cache.get(company_id)
            dyn_rev = None
            if (
                seg_cfg.get("source_mode") == "dynamic_mainbz"
                and fin_ctx
                and fin_ctx.auxiliary_revenues_cny
            ):
                dyn_rev = fin_ctx.auxiliary_revenues_cny.get(seg_key)

            if dyn_rev is not None and dyn_rev > 0:
                revenue = dyn_rev
            else:
                revenue = float(seg_cfg.get("revenue_fixed_cny", 1.0e9))

            gpm_rate = float(seg_cfg.get("gross_margin_rate", 0.05))
            gross_profit = revenue * gpm_rate
            volume = 0.0
            unit_price = 0.0
            unit_cost = 0.0
            unit_margin = 0.0

        gpm_ratio = gross_profit / revenue if revenue > 0 else 0.0
        return SegmentResult(
            segment_key=seg_key,
            segment_name=str(seg_cfg.get("name", seg_key)),
            sales_volume_tons=round(volume, 1),
            unit_price_cny=round(unit_price, 2),
            unit_cost_cny=round(unit_cost, 2),
            unit_gross_margin_cny=round(unit_margin, 2),
            revenue_cny=round(revenue, 2),
            gross_profit_cny=round(gross_profit, 2),
            gross_margin_ratio=round(gpm_ratio, 4),
        )

    def resolve_financial_context(
        self,
        company_id: str,
        c_cfg: dict[str, Any],
    ) -> CompanyFinancialContext:
        """从本地 Curated 黄金事实表提取最新财报事实，若无则平滑降级使用静态配置。"""
        if company_id in self._financial_context_cache:
            return self._financial_context_cache[company_id]

        if self.catalog is not None:
            try:
                # 1. 尝试从 balancesheet 加载最新归母净资产、有息负债与货币资金
                bs_req_cols = [
                    "symbol",
                    "end_date",
                    "ann_date",
                    "total_hldr_eqy_exc_min_int",
                    "money_cap",
                    "st_borr",
                    "lt_borr",
                    "non_cur_liab_due_1y",
                    "bond_payable",
                ]
                try:
                    bs_df = self.catalog.load_dataset(
                        "balancesheet",
                        symbols=[company_id],
                        columns=bs_req_cols,
                    )
                except Exception:
                    # 兼容仅包含核心字段的 Mock 或降级表
                    bs_df = self.catalog.load_dataset(
                        "balancesheet",
                        symbols=[company_id],
                        columns=["symbol", "end_date", "ann_date", "total_hldr_eqy_exc_min_int"],
                    )

                # Point-in-Time 防前视：按公告日 ann_date 过滤 <= as_of_date
                if not bs_df.is_empty() and self.as_of_str:
                    if "ann_date" in bs_df.columns and not bs_df["ann_date"].is_null().all():
                        bs_df = bs_df.filter(pl.col("ann_date").cast(pl.Utf8) <= self.as_of_str)
                    elif "end_date" in bs_df.columns:
                        bs_df = bs_df.filter(pl.col("end_date").cast(pl.Utf8) <= self.as_of_str)

                # 2. 尝试从 daily_basic 加载最新总股本与历史 PB 分位数
                try:
                    db_df = self.catalog.load_dataset(
                        "daily_basic",
                        symbols=[company_id],
                        columns=["symbol", "trade_date", "total_share", "pb"],
                    )
                except Exception:
                    db_df = self.catalog.load_dataset(
                        "daily_basic",
                        symbols=[company_id],
                        columns=["symbol", "trade_date", "total_share"],
                    )

                # Point-in-Time 防前视：严格过滤 trade_date <= as_of_date
                if not db_df.is_empty() and self.as_of_str:
                    if "trade_date" in db_df.columns:
                        db_df = db_df.filter(pl.col("trade_date").cast(pl.Utf8) <= self.as_of_str)

                if not bs_df.is_empty() and not db_df.is_empty():
                    bs_sort_cols = (
                        ["ann_date", "end_date"] if "ann_date" in bs_df.columns else ["end_date"]
                    )
                    latest_bs = bs_df.sort(bs_sort_cols).tail(1).row(0, named=True)
                    latest_db = db_df.sort("trade_date").tail(1).row(0, named=True)

                    net_assets = float(latest_bs.get("total_hldr_eqy_exc_min_int") or 0.0)
                    # daily_basic.total_share 单位为万股
                    total_shares = float(latest_db.get("total_share") or 0.0) * 10_000.0

                    # 提取历史 10 年日频 PB 分位数 (仅基于 as_of 之前已发生样本)
                    pb_pct_dict = None
                    latest_market_pb = None
                    if "pb" in db_df.columns:
                        valid_pb = db_df.drop_nulls(subset=["pb"]).filter(pl.col("pb") > 0)
                        if not valid_pb.is_empty():
                            p05 = round(float(valid_pb["pb"].quantile(0.05) or 0.0), 2)
                            p50 = round(float(valid_pb["pb"].quantile(0.50) or 0.0), 2)
                            p85 = round(float(valid_pb["pb"].quantile(0.85) or 0.0), 2)
                            latest_market_pb = round(
                                float(valid_pb.sort("trade_date").tail(1)["pb"][0]), 2
                            )
                            pb_pct_dict = {
                                "p05": p05,
                                "p50": p50,
                                "p85": p85,
                                "latest": latest_market_pb,
                            }

                    if net_assets > 0 and total_shares > 0:
                        bps = net_assets / total_shares
                        rep_date = str(latest_bs.get("end_date"))
                        ann_date = str(latest_bs.get("ann_date"))

                        # 3. 尝试从 income 加载最新财务费用与历史 3 年年报平均总营收 (Point-in-Time 防前视截断)
                        ann_fin_exp = None
                        hist_3y_avg_rev = None
                        ann_map: dict[str, str] = {}
                        try:
                            inc_df = self.catalog.load_dataset(
                                "income",
                                symbols=[company_id],
                                columns=[
                                    "symbol",
                                    "end_date",
                                    "ann_date",
                                    "fin_exp",
                                    "total_revenue",
                                ],
                            )
                            # 构建 end_date -> 最早披露日 映射，供 fina_mainbz 无 ann_date 字段时做披露日截断
                            if "end_date" in inc_df.columns and "ann_date" in inc_df.columns:
                                for r in (
                                    inc_df.filter(pl.col("ann_date").is_not_null())
                                    .select(["end_date", "ann_date"])
                                    .iter_rows(named=True)
                                ):
                                    key = str(r["end_date"])
                                    val = str(r["ann_date"])
                                    if key not in ann_map or val < ann_map[key]:
                                        ann_map[key] = val
                            if not inc_df.is_empty() and self.as_of_str:
                                if (
                                    "ann_date" in inc_df.columns
                                    and not inc_df["ann_date"].is_null().all()
                                ):
                                    inc_df = inc_df.filter(
                                        pl.col("ann_date").cast(pl.Utf8) <= self.as_of_str
                                    )
                                elif "end_date" in inc_df.columns:
                                    inc_df = inc_df.filter(
                                        pl.col("end_date").cast(pl.Utf8) <= self.as_of_str
                                    )

                            if not inc_df.is_empty():
                                inc_sort_cols = (
                                    ["ann_date", "end_date"]
                                    if "ann_date" in inc_df.columns
                                    else ["end_date"]
                                )
                                latest_inc = inc_df.sort(inc_sort_cols).tail(1).row(0, named=True)
                                inc_end = str(latest_inc.get("end_date"))
                                raw_fin = float(latest_inc.get("fin_exp") or 0.0)
                                if inc_end.endswith("12-31"):
                                    ann_fin_exp = raw_fin
                                elif inc_end.endswith("06-30"):
                                    ann_fin_exp = raw_fin * 2.0
                                elif inc_end.endswith("03-31"):
                                    ann_fin_exp = raw_fin * 4.0
                                elif inc_end.endswith("09-30"):
                                    ann_fin_exp = raw_fin * (4.0 / 3.0)

                                # 计算基准日前已披露的最近 3 个完整年报平均营业总收入 (用于对账门禁)
                                annual_inc = inc_df.filter(
                                    pl.col("end_date").cast(pl.Utf8).str.ends_with("12-31")
                                    & pl.col("total_revenue").is_not_null()
                                )
                                if not annual_inc.is_empty():
                                    recent_revs = (
                                        annual_inc.sort("end_date")
                                        .tail(3)["total_revenue"]
                                        .to_list()
                                    )
                                    if recent_revs:
                                        hist_3y_avg_rev = round(
                                            sum(recent_revs) / len(recent_revs), 2
                                        )
                        except Exception as inc_exc:
                            logger.debug(f"加载 {company_id} 财务费用与历史营收均值失败: {inc_exc}")

                        # 4. 提取有息负债存量与货币资金
                        money_cap = (
                            float(latest_bs.get("money_cap") or 0.0)
                            if "money_cap" in latest_bs and latest_bs.get("money_cap") is not None
                            else None
                        )
                        st_borr = (
                            float(latest_bs.get("st_borr") or 0.0)
                            if "st_borr" in latest_bs
                            else 0.0
                        )
                        lt_borr = (
                            float(latest_bs.get("lt_borr") or 0.0)
                            if "lt_borr" in latest_bs
                            else 0.0
                        )
                        non_cur = (
                            float(latest_bs.get("non_cur_liab_due_1y") or 0.0)
                            if "non_cur_liab_due_1y" in latest_bs
                            else 0.0
                        )
                        bond_p = (
                            float(latest_bs.get("bond_payable") or 0.0)
                            if "bond_payable" in latest_bs
                            else 0.0
                        )
                        has_debt_fields = any(
                            k in latest_bs
                            for k in ["st_borr", "lt_borr", "non_cur_liab_due_1y", "bond_payable"]
                        )
                        ib_debt = (
                            (st_borr + lt_borr + non_cur + bond_p) if has_debt_fields else None
                        )

                        # 5. 尝试从 fina_mainbz 提取过去 3 年非核心副业 (新能源/磷酸铁、磷矿、贸易) 历史销售额中位数 (Point-in-Time 严防前视)
                        aux_rev_dict: dict[str, float] = {}
                        try:
                            mbz_df = self.catalog.load_dataset(
                                "fina_mainbz",
                                symbols=[company_id],
                                columns=["symbol", "end_date", "bz_item", "bz_sales"],
                            )
                            if not mbz_df.is_empty():
                                # Point-in-Time 防前视：优先按披露日截断（借 income 的 ann_date 映射），
                                # 映射缺失时降级按 end_date 截断
                                mbz_df = filter_mainbz_by_disclosure(
                                    mbz_df, ann_map, self.as_of_str
                                )
                                annual_mbz = mbz_df.filter(
                                    pl.col("end_date").cast(pl.Utf8).str.ends_with("12-31")
                                    & pl.col("bz_sales").is_not_null()
                                )
                                if not annual_mbz.is_empty():
                                    recent_dates = sorted(
                                        annual_mbz["end_date"].unique().to_list()
                                    )[-3:]
                                    recent_mbz = annual_mbz.filter(
                                        pl.col("end_date").is_in(recent_dates)
                                    )
                                    aux_rev_dict = extract_auxiliary_revenues(
                                        recent_mbz,
                                        has_iron_phosphate_seg=(
                                            "iron_phosphate" in c_cfg.get("segments", {})
                                        ),
                                    )
                                # Phase 1: 副业实际化——最新报告期（含半年报/季报）按报告期月数年化，
                                # 优先于 3Y 中位数（2026-09-20 校准）
                                latest_end = str(mbz_df.sort("end_date")["end_date"][-1])
                                period_months = _PERIOD_MONTHS_BY_SUFFIX.get(latest_end[-5:])
                                period_frame = mbz_df.filter(
                                    pl.col("end_date").cast(pl.Utf8) == latest_end
                                )
                                actual_aux = extract_auxiliary_revenues_actual(
                                    period_frame,
                                    has_iron_phosphate_seg=(
                                        "iron_phosphate" in c_cfg.get("segments", {})
                                    ),
                                    period_months=period_months,
                                )
                                if actual_aux:
                                    aux_rev_dict = actual_aux
                        except Exception as mbz_exc:
                            logger.debug(f"加载 {company_id} fina_mainbz 动态中枢失败: {mbz_exc}")

                        ctx = CompanyFinancialContext(
                            symbol=company_id,
                            report_date=rep_date,
                            ann_date=ann_date,
                            total_shares=round(total_shares, 2),
                            net_assets_cny=round(net_assets, 2),
                            bps=round(bps, 2),
                            annualized_finance_expense=round(ann_fin_exp, 2)
                            if ann_fin_exp is not None
                            else None,
                            interest_bearing_debt_cny=round(ib_debt, 2)
                            if ib_debt is not None
                            else None,
                            money_cap_cny=round(money_cap, 2) if money_cap is not None else None,
                            historical_pb_percentiles=pb_pct_dict,
                            latest_market_pb=latest_market_pb,
                            auxiliary_revenues_cny=aux_rev_dict if aux_rev_dict else None,
                            historical_3y_avg_revenue_cny=hist_3y_avg_rev,
                            source_mode="dynamic_catalog",
                        )
                        logger.info(
                            f"成功为 {company_id} 动态装配最新财报基准: report_date={rep_date}, "
                            f"net_assets={net_assets / 1e8:.2f}亿, bps={bps:.2f}元, shares={total_shares / 1e8:.2f}亿股, "
                            f"fin_exp_ann={ann_fin_exp / 1e8 if ann_fin_exp is not None else 0.0:.2f}亿, "
                            f"pb_latest={latest_market_pb}x, pb_p05={pb_pct_dict.get('p05') if pb_pct_dict else '--'}x, "
                            f"hist_3y_avg_rev={hist_3y_avg_rev / 1e8 if hist_3y_avg_rev else 0.0:.2f}亿, "
                            f"aux_revenues={aux_rev_dict}"
                        )
                        self._financial_context_cache[company_id] = ctx
                        return ctx
            except Exception as exc:
                logger.warning(f"动态提取 {company_id} 财报失败，回退静态配置: {exc}")

        # 静态配置兜底 (Fallback)
        total_shares = float(c_cfg.get("total_shares", 1.0))
        bps = float(c_cfg.get("bps", 0.0))
        if bps <= 0.0 and total_shares > 0:
            net_assets = float(c_cfg.get("net_assets_cny", 0.0))
            bps = net_assets / total_shares if total_shares > 0 else 0.0
        else:
            net_assets = float(c_cfg.get("net_assets_cny", bps * total_shares))

        ctx = CompanyFinancialContext(
            symbol=company_id,
            report_date=None,
            ann_date=None,
            total_shares=round(total_shares, 2),
            net_assets_cny=round(net_assets, 2),
            bps=round(bps, 2),
            annualized_finance_expense=None,
            interest_bearing_debt_cny=None,
            money_cap_cny=None,
            historical_pb_percentiles=None,
            latest_market_pb=None,
            source_mode="static_config",
        )
        self._financial_context_cache[company_id] = ctx
        return ctx

    def _resolve_target_pb(
        self,
        company_id: str,
        scenario_key: str,
        fin_ctx: CompanyFinancialContext,
        c_cfg: dict[str, Any],
    ) -> float:
        """解析各宏观情景的目标 PB 评价标准。

        优先支持专家显式 Override；若未配置则自适应采用 10 年日频 PB 分位数。
        """
        override_pb = c_cfg.get("target_pb_by_scenario", {}).get(scenario_key)
        if override_pb is not None and float(override_pb) > 0:
            return float(override_pb)

        pcts = fin_ctx.historical_pb_percentiles or {}
        if scenario_key == "trough":
            # 5% 历史极深坑底重置成本防守线 (龙佰约 1.59x, 钛能约 1.34x)
            val = pcts.get("p05")
            if val is not None and val > 0:
                return float(val)
        elif scenario_key == "current_spot":
            # 现货实时情景优先采用当前市场实际收盘 PB (龙佰 1.63x, 钛能 1.23x)
            val = fin_ctx.latest_market_pb or pcts.get("latest") or pcts.get("p05")
            if val is not None and val > 0:
                return float(val)
        elif scenario_key == "mid_cycle":
            # 50% 历史中位数中枢修复 (龙佰 2.25x, 钛能 2.98x)
            val = pcts.get("p50")
            if val is not None and val > 0:
                return float(val)
        elif scenario_key == "peak":
            # 85% 历史繁荣期分位 (龙佰 3.96x, 钛能历史极值偏高设 3.8x 保守门禁)
            val = pcts.get("p85")
            if val is not None and val > 0:
                return min(float(val), 3.80)

        # 静态降级安全底线
        fallback_map = {
            "002601.SZ": {"trough": 1.60, "current_spot": 1.63, "mid_cycle": 2.25, "peak": 3.80},
            "002145.SZ": {"trough": 1.20, "current_spot": 1.23, "mid_cycle": 1.80, "peak": 2.60},
        }
        return float(fallback_map.get(company_id, {}).get(scenario_key, 1.50))

    def _resolve_finance_expense(
        self,
        fin_ctx: CompanyFinancialContext,
        c_cfg: dict[str, Any],
        scenario_key: str,
    ) -> float:
        """计算指定情景下的财务费用。

        优先采用三表动态年化财务费用乘以情景去杠杆比例；
        对高出口占比企业（如龙佰集团），在中性复苏与景气情景下剔除短期外汇单边大幅波动造成的非经常性汇兑损失冲击；
        若缺失财报数据则平滑降级使用静态配置。
        """
        scale_dict = c_cfg.get("finance_expense_scale_by_scenario") or {}
        default_scales = {
            "current_spot": 1.0,  # 现货实时情景承压 100%
            "trough": 1.0,  # 磨底承压，保持当前年化实际刚性利息 (龙佰约 7.81 亿，钛能约 0.58 亿)
            "mid_cycle": 0.55,  # 中性复苏，自由现金流还债去杠杆约 45%，利息缩减至 55%
            "peak": 0.40,  # 景气繁荣，超额现金流加速还债，利息缩减至 40%
        }
        scale = float(scale_dict.get(scenario_key, default_scales.get(scenario_key, 1.0)))

        if fin_ctx.annualized_finance_expense is not None:
            base_exp = float(fin_ctx.annualized_finance_expense)
            # 对高出口企业（如龙佰海外收入 > 30%），中性/繁荣期汇率波动收敛，剔除汇兑损失脉冲，锚定刚性内生利息
            export_w = self._resolve_export_weight(fin_ctx.symbol, c_cfg)
            if scenario_key in ("mid_cycle", "peak") and export_w > 0.3:
                base_exp = min(base_exp, 4.0e8)
            return max(0.0, base_exp * scale)

        # 降级模式 (无动态财务费用时兼容老配置)
        legacy_by_scen = c_cfg.get("finance_expense_by_scenario", {})
        if scenario_key in legacy_by_scen:
            return float(legacy_by_scen[scenario_key])
        return float(c_cfg.get("finance_expense_fixed_cny", 0.0))

    def project_company(
        self,
        company_id: str,
        scenario_key: str,
    ) -> CompanyProjectionResult:
        """自下而上合并各分部，扣减费用与税收，输出集团合并归母净利与目标估值。"""
        cfg = self.load_config()
        c_cfg = cfg["companies"][company_id]
        # Phase 1: 情景国内出厂价 → 公司实现价（动态出口权重 × 出口溢价）
        scenario = self._apply_realized_price(company_id, c_cfg, cfg["scenarios"][scenario_key])

        # 先解析财务上下文，保证首个情景 (current_spot) 也能拿到 fina_mainbz 动态副业中枢
        fin_ctx = self.resolve_financial_context(company_id, c_cfg)

        segment_keys = list(c_cfg["segments"].keys())
        segments = [
            self._calc_segment(company_id, k, c_cfg, scenario, scenario_key) for k in segment_keys
        ]

        total_revenue = sum(s.revenue_cny for s in segments)
        total_gross_profit = sum(s.gross_profit_cny for s in segments)
        blended_gpm = total_gross_profit / total_revenue if total_revenue > 0 else 0.0

        # 期间四费扣减 (OPEX Bridge)
        variable_expense = total_revenue * float(c_cfg.get("base_expense_ratio", 0.08))
        fixed_finance = self._resolve_finance_expense(fin_ctx, c_cfg, scenario_key)
        total_expense = variable_expense + fixed_finance

        operating_profit = total_gross_profit - total_expense
        # Phase 1.5: 出口退税独立建模（实现价不含退税；退税 ≈ 13% × 出口收入，计入利润总额）
        rp = cfg.get("realized_price", {}) or {}
        rebate_rate = float(rp.get("export_rebate_rate", 0.0))
        w_exp = self._resolve_export_weight(company_id, c_cfg)
        premium_r = self._resolve_export_premium_ratio()
        realized_k = w_exp * premium_r + (1.0 - w_exp)
        core_rev = sum(
            s.revenue_cny for s in segments if s.segment_key in ("sulfate_tio2", "chloride_tio2")
        )
        export_rev_est = (
            w_exp * core_rev * premium_r / realized_k if realized_k > 0 and w_exp > 0 else 0.0
        )
        export_rebate = export_rev_est * rebate_rate
        operating_profit += export_rebate

        tax_rate = float(c_cfg.get("tax_rate", 0.15))
        income_tax = max(0.0, operating_profit * tax_rate)
        net_profit = operating_profit - income_tax
        net_margin = net_profit / total_revenue if total_revenue > 0 else 0.0

        total_shares = fin_ctx.total_shares
        eps = net_profit / total_shares if total_shares > 0 else 0.0
        pe_multiple = float(scenario.get("pe_multiple", 15.0))
        target_market_cap = net_profit * pe_multiple
        target_stock_price = target_market_cap / total_shares if total_shares > 0 else 0.0

        # 主辅业务解耦 (Core TiO2 vs Auxiliary)；出口退税全额计入主业
        core_keys = {"sulfate_tio2", "chloride_tio2"}
        core_gp = sum(s.gross_profit_cny for s in segments if s.segment_key in core_keys)
        aux_gp = total_gross_profit - core_gp
        profit_base = total_gross_profit + export_rebate
        core_ratio = (core_gp + export_rebate) / profit_base if profit_base > 0 else 1.0
        core_eps = eps * core_ratio
        aux_eps = eps - core_eps

        # PB / BPS 双轨估值体系 (自适应 PB 分位)
        bps = fin_ctx.bps
        net_assets = fin_ctx.net_assets_cny
        target_pb = self._resolve_target_pb(company_id, scenario_key, fin_ctx, c_cfg)
        target_market_cap_pb = net_assets * target_pb
        target_stock_price_pb = bps * target_pb

        return CompanyProjectionResult(
            symbol=company_id,
            company_name=str(c_cfg.get("name", company_id)),
            scenario_key=scenario_key,
            scenario_name=str(scenario.get("name", scenario_key)),
            segments=segments,
            total_revenue_cny=round(total_revenue, 2),
            total_gross_profit_cny=round(total_gross_profit, 2),
            blended_gpm=round(blended_gpm, 4),
            total_expense_cny=round(total_expense, 2),
            finance_expense_cny=round(fixed_finance, 2),
            operating_profit_cny=round(operating_profit, 2),
            income_tax_cny=round(income_tax, 2),
            net_profit_attr_p_cny=round(net_profit, 2),
            net_profit_margin=round(net_margin, 4),
            eps_cny=round(eps, 2),
            pe_multiple=round(pe_multiple, 1),
            target_market_cap_cny=round(target_market_cap, 2),
            target_stock_price_cny=round(target_stock_price, 2),
            bps_cny=round(bps, 2),
            target_pb=round(target_pb, 2),
            target_market_cap_pb_cny=round(target_market_cap_pb, 2),
            target_stock_price_pb_cny=round(target_stock_price_pb, 2),
            core_tio2_gross_profit_cny=round(core_gp, 2),
            core_tio2_eps_cny=round(core_eps, 2),
            auxiliary_gross_profit_cny=round(aux_gp, 2),
            auxiliary_eps_cny=round(aux_eps, 2),
            export_rebate_income_cny=round(export_rebate, 2),
            financial_report_date=fin_ctx.report_date,
            data_source_mode=fin_ctx.source_mode,
        )

    def project_all(self) -> list[CompanyProjectionResult]:
        """运行全部企业在全部基准情景下的测算 (涵盖 current_spot 与三大宏观情景)。"""
        cfg = self.load_config()
        results: list[CompanyProjectionResult] = []
        ordered_scenarios = [
            s
            for s in ["current_spot", "auxiliary_stress", "trough", "mid_cycle", "peak"]
            if s in cfg.get("scenarios", {})
        ]
        for s in cfg.get("scenarios", {}):
            if s not in ordered_scenarios:
                ordered_scenarios.append(s)

        for company_id in cfg.get("companies", {}):
            for scenario_key in ordered_scenarios:
                results.append(self.project_company(company_id, scenario_key))
        return results

    def to_dataframe(self, results: list[CompanyProjectionResult]) -> pl.DataFrame:
        """将测算结果列表展平为标准 Polars DataFrame。"""
        rows: list[dict[str, Any]] = []
        for r in results:
            rows.append(
                {
                    "symbol": r.symbol,
                    "company_name": r.company_name,
                    "scenario_key": r.scenario_key,
                    "scenario_name": r.scenario_name,
                    "total_revenue_cny": r.total_revenue_cny,
                    "total_gross_profit_cny": r.total_gross_profit_cny,
                    "core_tio2_gross_profit_cny": r.core_tio2_gross_profit_cny,
                    "auxiliary_gross_profit_cny": r.auxiliary_gross_profit_cny,
                    "export_rebate_income_cny": r.export_rebate_income_cny,
                    "blended_gpm": r.blended_gpm,
                    "total_expense_cny": r.total_expense_cny,
                    "finance_expense_cny": r.finance_expense_cny,
                    "operating_profit_cny": r.operating_profit_cny,
                    "net_profit_attr_p_cny": r.net_profit_attr_p_cny,
                    "net_profit_margin": r.net_profit_margin,
                    "eps_cny": r.eps_cny,
                    "core_tio2_eps_cny": r.core_tio2_eps_cny,
                    "auxiliary_eps_cny": r.auxiliary_eps_cny,
                    "pe_multiple": r.pe_multiple,
                    "target_market_cap_cny": r.target_market_cap_cny,
                    "target_stock_price_cny": r.target_stock_price_cny,
                    "bps_cny": r.bps_cny,
                    "target_pb": r.target_pb,
                    "target_market_cap_pb_cny": r.target_market_cap_pb_cny,
                    "target_stock_price_pb_cny": r.target_stock_price_pb_cny,
                    "financial_report_date": r.financial_report_date,
                    "data_source_mode": r.data_source_mode,
                }
            )
        return pl.DataFrame(rows)

    def generate_profit_sensitivity_grid(
        self,
        company_id: str,
        price_steps: list[float] | None = None,
        ore_steps: list[float] | None = None,
    ) -> pl.DataFrame:
        """生成产品售价 vs 原料钛精矿价格的二维归母净利润敏感性矩阵 (单位: 亿元)。"""
        cfg = self.load_config()
        c_cfg = cfg["companies"][company_id]
        p_steps = price_steps or [13500.0, 14500.0, 15500.0, 16500.0, 17500.0, 18500.0]
        o_steps = ore_steps or [1200.0, 1500.0, 1800.0, 2100.0, 2400.0]

        # 以 mid_cycle 作为基准，动态装配财务费用
        fin_ctx = self.resolve_financial_context(company_id, c_cfg)
        fix_fin = self._resolve_finance_expense(fin_ctx, c_cfg, "mid_cycle")
        base_scenario = dict(cfg["scenarios"]["mid_cycle"])
        grid_rows: list[dict[str, Any]] = []

        for p_ore in o_steps:
            row: dict[str, Any] = {"ore_price_cny": p_ore}
            for p_tio2 in p_steps:
                scen = dict(base_scenario)
                scen["tio2_sulfate_price"] = p_tio2
                scen["ilmenite_market_price"] = p_ore

                segments = [
                    self._project_segment_custom(company_id, k, scen, c_cfg)
                    for k in c_cfg["segments"]
                ]
                total_rev = sum(s.revenue_cny for s in segments)
                total_gp = sum(s.gross_profit_cny for s in segments)
                var_exp = total_rev * float(c_cfg.get("base_expense_ratio", 0.08))
                op = total_gp - (var_exp + fix_fin)
                tax = max(0.0, op * float(c_cfg.get("tax_rate", 0.15)))
                np_yi = round((op - tax) / 1.0e8, 2)
                row[f"tio2_{int(p_tio2)}"] = np_yi
            grid_rows.append(row)

        return pl.DataFrame(grid_rows)

    def _project_segment_custom(
        self,
        company_id: str,
        seg_key: str,
        scenario: dict[str, Any],
        c_cfg: dict[str, Any],
    ) -> SegmentResult:
        """内部自定义场景的分部计算辅助方法。"""
        return self._calc_segment(company_id, seg_key, c_cfg, scenario)

    def audit_reconciliation(
        self,
        results: list[CompanyProjectionResult],
    ) -> list[dict[str, Any]]:
        """执行模型 Trough 营收 vs 历史 3 年年报中枢的合理性对账门禁。"""
        audit_reports: list[dict[str, Any]] = []
        for r in results:
            if r.scenario_key == "trough":
                fin_ctx = self._financial_context_cache.get(r.symbol)
                hist_avg = fin_ctx.historical_3y_avg_revenue_cny if fin_ctx else None
                if hist_avg is not None and hist_avg > 0:
                    bias_pct = round((r.total_revenue_cny - hist_avg) / hist_avg * 100.0, 2)
                    # 允许 -25% 到 +15% 的合理磨底波动区间
                    passed = -25.0 <= bias_pct <= 15.0
                    audit_reports.append(
                        {
                            "symbol": r.symbol,
                            "company_name": r.company_name,
                            "trough_revenue_cny": r.total_revenue_cny,
                            "historical_3y_avg_revenue_cny": hist_avg,
                            "bias_pct": bias_pct,
                            "status": "PASSED" if passed else "ANOMALY",
                            "message": (
                                f"{r.company_name} Trough 营收 {r.total_revenue_cny / 1e8:.2f}亿 vs "
                                f"历史3Y年报均值 {hist_avg / 1e8:.2f}亿 (偏差 {bias_pct:+.1f}%) -> "
                                f"{'合规通过' if passed else '触发异动警告'}"
                            ),
                        }
                    )
        return audit_reports

    def build_pit_audit(self) -> list[dict[str, Any]]:
        """构建模型动态输入的 Point-in-Time (PIT) 前视审计清单。

        逐项列出动态输入、截断口径、as_of、最新可用时点与已用行数，
        并标记是否合规（最新可用时点必须 ≤ as_of）。
        """
        as_of_str = self.as_of_str
        items: list[dict[str, Any]] = []

        def load(name: str, *, industry: bool = False) -> pl.DataFrame:
            frame: pl.DataFrame | None = None
            if self.catalog is not None:
                try:
                    frame = self.catalog.load_dataset(name)
                except Exception:
                    frame = None
            if (frame is None or frame.is_empty()) and industry:
                from stock_data.catalog import DataCatalog

                try:
                    frame = DataCatalog(data_source="industry").load_dataset(name)
                except Exception:
                    frame = pl.DataFrame()
            if frame is None or frame.is_empty():
                return pl.DataFrame()
            if industry:
                frame = (
                    frame.filter(pl.col("symbol") == "TiO2") if "symbol" in frame.columns else frame
                )
            return frame

        def load_tushare(name: str) -> pl.DataFrame:
            """兼容 DataCatalog 与 Mock 的 load_dataset(symbols=...) 调用形态。"""
            if self.catalog is None:
                return pl.DataFrame()
            for symbols in (None, ["002601.SZ"], ["002145.SZ"]):
                try:
                    frame = self.catalog.load_dataset(name, symbols=symbols, columns=None)
                    if frame is not None and not frame.is_empty():
                        return cast("pl.DataFrame", frame)
                except Exception:
                    continue
            return pl.DataFrame()

        def truncate(frame: pl.DataFrame, columns: tuple[str, ...]) -> pl.DataFrame:
            if frame.is_empty() or not as_of_str:
                return frame
            col = next(
                (c for c in columns if c in frame.columns and not frame[c].is_null().all()), None
            )
            if col is not None:
                return frame.filter(pl.col(col).cast(pl.Utf8) <= as_of_str)
            fallback_col = next((c for c in columns if c in frame.columns), None)
            if fallback_col is not None:
                return frame.filter(pl.col(fallback_col).cast(pl.Utf8) <= as_of_str)
            return frame

        def latest_date(frame: pl.DataFrame, columns: tuple[str, ...]) -> str | None:
            if frame.is_empty():
                return None
            col = next((c for c in columns if c in frame.columns), None)
            if col is None:
                return None
            return str(frame[col].drop_nulls().max())

        def add(
            input_name: str,
            truncation: str,
            frame: pl.DataFrame,
            date_columns: tuple[str, ...],
            note: str = "",
        ) -> None:
            latest = latest_date(frame, date_columns)
            ok = bool(not as_of_str or (latest is not None and latest <= as_of_str))
            items.append(
                {
                    "input": input_name,
                    "truncation": truncation,
                    "as_of": as_of_str or "未设置(全量)",
                    "latest_used": latest,
                    "rows_used": int(frame.height),
                    "pit_ok": ok,
                    "note": note,
                }
            )

        # 1. 现货注入
        spot = load("chemical_spot_price", industry=True)
        spot_used = truncate(spot, ("release_date", "trade_date"))
        add(
            "chemical_spot_price(现货注入)",
            "release_date ≤ as_of（缺失降级 trade_date）",
            spot_used,
            ("release_date", "trade_date"),
        )

        # 2. 月频产能利用率注入
        monthly = load("chemical_monthly_survey", industry=True)
        if not monthly.is_empty():
            monthly = monthly.filter(pl.col("operating_rate_pct").is_not_null())
        monthly_used = truncate(monthly, ("release_date", "report_month"))
        add(
            "chemical_monthly_survey(利用率注入)",
            "release_date ≤ as_of（缺失降级 report_month）",
            monthly_used,
            ("release_date", "report_month"),
        )

        if self.catalog is None:
            # 无 catalog 时财报类输入不可审计/未使用
            for name in ("income", "balancesheet", "daily_basic", "fina_mainbz"):
                add(
                    f"{name}(财报动态装配)",
                    "未装配（catalog=None → 静态配置）",
                    pl.DataFrame(),
                    ("end_date", "trade_date"),
                    note="静态配置模式，无动态输入",
                )
            return items

        # 3-4. income / balancesheet：ann_date 截断
        for name, date_cols, label in (
            ("income", ("ann_date", "end_date"), "income(财务费用/3Y营收)"),
            ("balancesheet", ("ann_date", "end_date"), "balancesheet(净资产/负债)"),
        ):
            frame_used = truncate(load_tushare(name), date_cols)
            add(
                label, "ann_date ≤ as_of（缺失降级 end_date）", frame_used, ("ann_date", "end_date")
            )

        # 5. daily_basic：trade_date（行情同日披露）
        db_used = truncate(load_tushare("daily_basic"), ("trade_date",))
        add(
            "daily_basic(PB分位/总股本)",
            "trade_date ≤ as_of（行情同日披露）",
            db_used,
            ("trade_date",),
        )

        # 6. fina_mainbz：披露日代理（income ann_date 映射），缺失降级 end_date
        inc_for_map = load_tushare("income")
        ann_map: dict[str, str] = {}
        if "end_date" in inc_for_map.columns and "ann_date" in inc_for_map.columns:
            for r in (
                inc_for_map.filter(pl.col("ann_date").is_not_null())
                .select(["end_date", "ann_date"])
                .iter_rows(named=True)
            ):
                key = str(r["end_date"])
                val = str(r["ann_date"])
                if key not in ann_map or val < ann_map[key]:
                    ann_map[key] = val
        mbz_used = filter_mainbz_by_disclosure(load_tushare("fina_mainbz"), ann_map, as_of_str)
        add(
            "fina_mainbz(副业营收中枢)",
            "披露日(income ann_date 映射) ≤ as_of（缺失降级 end_date）",
            mbz_used,
            ("end_date",),
        )
        return items

    def compute_confidence_band(
        self,
        company_id: str,
        scenario_key: str = "mid_cycle",
        captive_ratio_delta: float = 0.10,
        fixed_cost_delta: float = 0.10,
    ) -> ConfidenceBandResult:
        """计算指定企业在特定情景下的 EPS 二维置信带宽与敏感性矩阵。

        Args:
            company_id: 股票代码
            scenario_key: 情景标识 (默认 mid_cycle)
            captive_ratio_delta: 自给率敏感性步长 (默认 ±10%)
            fixed_cost_delta: 动力制费敏感性步长 (默认 ±10%)

        Returns:
            ConfidenceBandResult: 置信带宽结果对象
        """
        cfg = self.load_config()
        c_cfg = cfg["companies"][company_id]
        proj_res = self.project_company(company_id, scenario_key)
        fin_ctx = self.resolve_financial_context(company_id, c_cfg)

        scen = cfg["scenarios"][scenario_key]
        p_ore = float(scen.get("ilmenite_market_price", 2200.0))

        # 提取硫酸法配置
        sulf_cfg = c_cfg["segments"].get("sulfate_tio2", {})
        cap_w = float(sulf_cfg.get("capacity_w_tons", 65.0))
        nominal_ore_consumption = float(sulf_cfg.get("ore_consumption", 2.3))
        nominal_ore_captive_cost = float(sulf_cfg.get("ore_captive_cost", 900.0))
        nominal_fixed_cost = float(sulf_cfg.get("fixed_cost", 6600.0))
        sales_util = float(sulf_cfg.get("utilization_rate", 0.85))

        calibrator = IndustrialCostCalibrator()
        return calibrator.compute_eps_confidence_band(
            symbol=company_id,
            company_name=c_cfg.get("name", company_id),
            scenario_key=scenario_key,
            nominal_eps=proj_res.eps_cny,
            annual_capacity_w_tons=cap_w,
            total_shares=fin_ctx.total_shares,
            ore_market_price=p_ore,
            nominal_ore_consumption=nominal_ore_consumption,
            nominal_ore_captive_cost=nominal_ore_captive_cost,
            nominal_fixed_cost=nominal_fixed_cost,
            tax_rate=float(c_cfg.get("tax_rate", 0.15)),
            base_expense_ratio=float(c_cfg.get("base_expense_ratio", 0.08)),
            captive_ratio_delta=captive_ratio_delta,
            fixed_cost_delta=fixed_cost_delta,
            sales_utilization_rate=sales_util,
        )


__all__ = [
    "DEFAULT_PROJECTION_CONFIG_PATH",
    "CompanyFinancialContext",
    "CompanyProjectionEngine",
    "CompanyProjectionResult",
    "ConfidenceBandResult",
    "IndustrialCostCalibrator",
    "SegmentResult",
]
