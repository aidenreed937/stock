"""钛白粉季度化业绩推演引擎（Phase 2：月频构建 + 季度输出）。

设计目标（docs/research/tio2_model_calibration_design_2026_09.md Phase 2）：
- 以月频价格/成本/利用率路径构建分部量本利，输出 Q1~Q4 与 FY 归母净利；
- 期间费用按最新季度实际 × 情景去杠杆比例摊销，不再做年化折半；
- 数据缺失月份显式回退情景价并记录 assumption 备注（Ground Truth First）；
- 复用 CompanyProjectionEngine._calc_segment 的分部公式，避免两套成本体系。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import polars as pl

from stock_analytics.pipelines.tio2.projections import SegmentResult

logger = logging.getLogger(__name__)

QUARTER_MONTH_OFFSETS: dict[str, tuple[int, ...]] = {
    "Q1": (1, 2, 3),
    "Q2": (4, 5, 6),
    "Q3": (7, 8, 9),
    "Q4": (10, 11, 12),
}

_PERIOD_MONTHS_BY_SUFFIX: dict[str, int] = {
    "03-31": 3,
    "06-30": 6,
    "09-30": 9,
    "12-31": 12,
}


def quarter_months(quarter_key: str) -> list[str]:
    """'2026Q1' -> ['2026-01', '2026-02', '2026-03']。"""
    year, q = quarter_key[:4], quarter_key[4:]
    offsets = QUARTER_MONTH_OFFSETS.get(q)
    if not offsets:
        raise ValueError(f"无效季度键: {quarter_key}")
    return [f"{year}-{m:02d}" for m in offsets]


@dataclass(frozen=True, slots=True)
class QuarterlyProjectionResult:
    """单个季度、单个情景的公司归母净利推演结果。"""

    symbol: str
    company_name: str
    quarter_key: str
    scenario_key: str
    scenario_name: str
    segments: list[Any] = field(default_factory=list)
    total_revenue_cny: float = 0.0
    total_gross_profit_cny: float = 0.0
    blended_gpm: float = 0.0
    variable_expense_cny: float = 0.0
    finance_expense_cny: float = 0.0
    total_expense_cny: float = 0.0
    operating_profit_cny: float = 0.0
    income_tax_cny: float = 0.0
    net_profit_attr_p_cny: float = 0.0
    net_profit_margin: float = 0.0
    eps_cny: float = 0.0
    core_tio2_gross_profit_cny: float = 0.0
    auxiliary_gross_profit_cny: float = 0.0
    export_rebate_income_cny: float = 0.0
    months_used: list[str] = field(default_factory=list)
    assumption_notes: list[str] = field(default_factory=list)
    financial_report_date: str | None = None
    data_source_mode: str = "static_config"


class QuarterlyProjectionEngine:
    """基于月频路径的季度化推演引擎（包装 CompanyProjectionEngine）。"""

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self._spot_monthly_cache: dict[str, dict[str, float]] | None = None
        self._util_monthly_cache: dict[str, float] | None = None
        self._export_asp_cache: dict[str, float] | None = None
        self._income_cache: dict[str, pl.DataFrame] = {}

    # ------------------------------------------------------------------
    # 数据装配（PIT 截断 + 缺失回退）
    # ------------------------------------------------------------------
    def _load_spot(self) -> pl.DataFrame:
        spot: pl.DataFrame | None = None
        if self.engine.catalog is not None:
            try:
                spot = self.engine.catalog.load_dataset("chemical_spot_price")
            except Exception:
                spot = None
        if spot is None or spot.is_empty():
            try:
                from stock_data.catalog import DataCatalog

                spot = DataCatalog(data_source="industry").load_dataset("chemical_spot_price")
            except Exception:
                spot = pl.DataFrame()
        if spot is None:
            return pl.DataFrame()
        return spot

    def _pit_truncate(self, frame: pl.DataFrame, date_cols: tuple[str, ...]) -> pl.DataFrame:
        if frame.is_empty() or not self.engine.as_of_str:
            return frame
        col = next(
            (c for c in date_cols if c in frame.columns and not frame[c].is_null().all()),
            None,
        )
        if col is None:
            return frame
        return frame.filter(pl.col(col).cast(pl.Utf8) <= self.engine.as_of_str)

    def _monthly_spot(self) -> dict[str, dict[str, float]]:
        """Month -> {'tio2': 元/吨, 'ore_plant': 攀西46%+350 到厂, 'acid': 湖北98%}。"""
        if self._spot_monthly_cache is not None:
            return self._spot_monthly_cache
        spot = self._pit_truncate(self._load_spot(), ("release_date", "trade_date"))
        result: dict[str, dict[str, float]] = {}
        if spot.is_empty() or "product_name" not in spot.columns:
            self._spot_monthly_cache = result
            return result
        spot = spot.with_columns(pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("_m"))
        for prod, region in (("钛白粉", None), ("钛精矿", "攀西"), ("硫酸", "湖北")):
            sub = spot.filter(pl.col("product_name") == prod)
            if region:
                sub = sub.filter(pl.col("region").cast(pl.Utf8) == region)
            for row in (
                sub.group_by("_m")
                .agg(pl.col("spot_price_cny").mean().alias("avg"))
                .iter_rows(named=True)
            ):
                m = str(row["_m"])
                bucket = result.setdefault(m, {})
                if prod == "钛白粉":
                    bucket["tio2"] = float(row["avg"])
                elif prod == "钛精矿":
                    bucket["ore_plant"] = float(row["avg"]) + 350.0  # 坑口 + 运费
                elif prod == "硫酸":
                    bucket["acid"] = float(row["avg"])
        self._spot_monthly_cache = result
        return result

    def _monthly_utilization(self) -> dict[str, float]:
        """Month -> 行业开工率（%），chemical_monthly_survey PIT 截断后月内均值。"""
        if self._util_monthly_cache is not None:
            return self._util_monthly_cache
        result: dict[str, float] = {}
        frame = pl.DataFrame()
        if self.engine.catalog is not None:
            try:
                frame = self.engine.catalog.load_dataset("chemical_monthly_survey")
            except Exception:
                frame = pl.DataFrame()
        if frame.is_empty():
            try:
                from stock_data.catalog import DataCatalog

                frame = DataCatalog(data_source="industry").load_dataset("chemical_monthly_survey")
            except Exception:
                frame = pl.DataFrame()
        if frame.is_empty() or "operating_rate_pct" not in frame.columns:
            self._util_monthly_cache = result
            return result
        if "symbol" in frame.columns:
            frame = frame.filter(pl.col("symbol") == "TiO2")
        frame = self._pit_truncate(frame, ("release_date", "report_month"))
        frame = frame.filter(pl.col("operating_rate_pct").is_not_null())
        if not frame.is_empty():
            frame = frame.with_columns(
                pl.col("report_month").cast(pl.Utf8).str.slice(0, 7).alias("_m")
            )
            for row in (
                frame.group_by("_m")
                .agg(pl.col("operating_rate_pct").mean().alias("avg"))
                .iter_rows(named=True)
            ):
                result[str(row["_m"])] = float(row["avg"])
        self._util_monthly_cache = result
        return result

    def _actual_quarter_net(self, company_id: str, quarter_key: str) -> dict[str, Any] | None:
        """已披露报告期实际归母净利（PIT：ann_date ≤ as_of；季差额口径）。

        返回 {"net", "revenue", "report_date"}；当季报未披露或无 n_income_attr_p 时返回 None。
        """
        year, q = quarter_key[:4], quarter_key[4:]
        offsets = QUARTER_MONTH_OFFSETS.get(q)
        if offsets is None:
            return None
        end_months = {"Q1": "03-31", "Q2": "06-30", "Q3": "09-30", "Q4": "12-31"}
        end_str = f"{year}-{end_months[q]}"
        inc = (
            self._income_cache.get(company_id, pl.DataFrame())
            if hasattr(self, "_income_cache")
            else pl.DataFrame()
        )
        if inc.is_empty():
            if self.engine.catalog is not None:
                for kwargs in (
                    {
                        "symbols": [company_id],
                        "columns": [
                            "symbol",
                            "end_date",
                            "ann_date",
                            "n_income_attr_p",
                            "total_revenue",
                        ],
                    },
                    {"symbols": [company_id]},
                    {},
                ):
                    try:
                        inc = self.engine.catalog.load_dataset("income", **kwargs)
                        if not inc.is_empty():
                            break
                    except Exception:
                        continue
        if inc.is_empty() or "n_income_attr_p" not in inc.columns:
            return None
        inc = self._pit_truncate(inc, ("ann_date", "end_date"))
        hit = inc.filter(
            (pl.col("end_date").cast(pl.Utf8) == end_str) & pl.col("n_income_attr_p").is_not_null()
        )
        if hit.is_empty():
            return None
        cum = float(str(hit["n_income_attr_p"].cast(pl.Float64, strict=False).max()))
        # 季度净利 = 当期累计 − 上一报告期末累计（季差额）
        prev_months = {2: "03-31", 3: "06-30", 4: "09-30"}
        q_num = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}[q]
        prev = 0.0
        if q_num in prev_months:
            prev_hit = inc.filter(
                (pl.col("end_date").cast(pl.Utf8) == f"{year}-{prev_months[q_num]}")
                & pl.col("n_income_attr_p").is_not_null()
            )
            if not prev_hit.is_empty():
                prev = float(str(prev_hit["n_income_attr_p"].cast(pl.Float64, strict=False).max()))
        rev = 0.0
        if "total_revenue" in hit.columns:
            rev_vals = hit["total_revenue"].cast(pl.Float64, strict=False).drop_nulls()
            if len(rev_vals) > 0:
                rev = float(str(rev_vals.max()))
        return {"net": cum - prev, "revenue": rev, "report_date": end_str}

    def _latest_quarterly_finance_expense(self, company_id: str) -> float | None:
        """最新报告期单季财务费用（元），income 表 PIT 截断；缺失返回 None。"""
        if company_id in self._income_cache:
            inc = self._income_cache[company_id]
        else:
            inc = pl.DataFrame()
            if self.engine.catalog is not None:
                # 缓存全字段 income（供财务费用与已披露季度锚定共用）
                for kwargs in (
                    {"symbols": [company_id]},
                    {},
                ):
                    try:
                        inc = self.engine.catalog.load_dataset("income", **kwargs)
                        if not inc.is_empty():
                            break
                    except Exception:
                        continue
            self._income_cache[company_id] = inc
        if inc.is_empty() or "fin_exp" not in inc.columns or "end_date" not in inc.columns:
            return None
        inc = self._pit_truncate(inc, ("ann_date", "end_date"))
        inc = inc.filter(pl.col("fin_exp").is_not_null())
        if inc.is_empty():
            return None
        latest = inc.sort("end_date").tail(1).to_dicts()[0]
        end_str = str(latest["end_date"])
        months = _PERIOD_MONTHS_BY_SUFFIX.get(end_str[-5:])
        fin_exp = float(latest["fin_exp"])
        if months is None or months <= 0:
            return None
        return fin_exp / months * 3.0  # 单季摊销

    # ------------------------------------------------------------------
    # 月频路径构建
    # ------------------------------------------------------------------
    def _monthly_fx(self) -> dict[str, float]:
        """Month -> USD/CNY 月均收盘（单一口径：FRED DEXCHUS 在岸人民币）。

        - 缺口月份用最近可得值前向填充（如 2026-09 用 2026-08），不跨源到离岸 CNH；
        - DEXCHUS 完全缺失才回退配置 fx_usd_cny（7.2）。
        """
        fx_default = 7.2
        try:
            rp = self.engine.load_config().get("realized_price", {}) or {}
            fx_default = float(rp.get("fx_usd_cny", fx_default))
        except Exception:
            pass

        frame = pl.DataFrame()
        if self.engine.catalog is not None:
            try:
                frame = self.engine.catalog.load_dataset("macro_indicators")
            except Exception:
                frame = pl.DataFrame()
        if frame.is_empty() or "symbol" not in frame.columns:
            try:
                from stock_data.catalog import DataCatalog

                frame = DataCatalog(data_source="fred").load_dataset("macro_indicators")
            except Exception:
                frame = pl.DataFrame()
        if frame.is_empty() or "symbol" not in frame.columns or "close" not in frame.columns:
            return {}
        sub = frame.filter(
            (pl.col("symbol").cast(pl.Utf8) == "DEXCHUS") & pl.col("close").is_not_null()
        )
        if sub.is_empty():
            return {}
        sub = self._pit_truncate(sub, ("release_date", "trade_date"))
        sub = sub.with_columns(pl.col("trade_date").cast(pl.Utf8).str.slice(0, 7).alias("_m"))
        result: dict[str, float] = {}
        for row in (
            sub.group_by("_m").agg(pl.col("close").mean().alias("avg")).iter_rows(named=True)
        ):
            result[str(row["_m"])] = float(row["avg"])
        if not result:
            return {}
        # 前向填充缺口月份（单调月份排序；缺失月取最近可得值）
        months = sorted(result)
        last = result[months[0]]
        filled: dict[str, float] = {}
        import datetime as _dt

        first = _dt.date(int(months[0][:4]), int(months[0][5:7]), 1)
        last_m = _dt.date(int(months[-1][:4]), int(months[-1][5:7]), 1)
        cur = first
        while cur <= last_m:
            key = f"{cur.year:04d}-{cur.month:02d}"
            if key in result:
                last = result[key]
            filled[key] = last
            if cur.month == 12:
                cur = cur.replace(year=cur.year + 1, month=1)
            else:
                cur = cur.replace(month=cur.month + 1)
        return filled

    def _monthly_export_asp_rmb(self) -> dict[str, float]:
        """Month -> GACC 出口离岸均价（RMB/吨），chemical_customs_export PIT 截断。"""
        if self._export_asp_cache is not None:
            return self._export_asp_cache
        result: dict[str, float] = {}
        fx = 7.2
        rp: dict[str, Any] = {}
        try:
            rp = self.engine.load_config().get("realized_price", {}) or {}
        except Exception:
            rp.clear()
        fx_default = float(rp.get("fx_usd_cny", fx))
        fx_map = self._monthly_fx()
        frame = pl.DataFrame()
        if self.engine.catalog is not None:
            for name in ("chemical_customs_export", "mart/chemical_customs_export"):
                try:
                    frame = self.engine.catalog.load_dataset(name)
                except Exception:
                    continue
                if not frame.is_empty():
                    break
        if frame.is_empty():
            try:
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
            except Exception:
                frame = pl.DataFrame()
        if frame.is_empty() or "commodity_code" not in frame.columns:
            self._export_asp_cache = result
            return result
        frame = self._pit_truncate(frame, ("report_month", "trade_date"))
        tio2 = frame.filter(pl.col("commodity_code") == "TiO2").sort("report_month")
        if not tio2.is_empty():
            for row in tio2.select(["report_month", "export_asp_usd_ton"]).iter_rows(named=True):
                asp = row.get("export_asp_usd_ton")
                if asp is not None:
                    m = str(row["report_month"])
                    fx_m = fx_map.get(m, fx_default)  # 黄金表 CNH 月均，缺失回退配置
                    # FOB 离岸价（RMB/吨，不含出口退税；退税在季度合并时单独建模）
                    result[m] = float(asp) * fx_m
        self._export_asp_cache = result
        return result

    def _build_monthly_path(
        self,
        company_id: str,
        c_cfg: dict[str, Any],
        scenario: dict[str, Any],
        months: list[str],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        spot = self._monthly_spot()
        utils = self._monthly_utilization()
        export_asp = self._monthly_export_asp_rmb()
        rp: dict[str, Any] = {}
        try:
            rp = self.engine.load_config().get("realized_price", {}) or {}
        except Exception:
            rp.clear()
        hist_ore = rp.get("historical_ore_plant_fallback", {}) or {}
        hist_util = rp.get("historical_utilization_fallback", {}) or {}
        w_exp = self.engine._resolve_export_weight(company_id, c_cfg)
        premium_r = self.engine._resolve_export_premium_ratio()
        realized_k = w_exp * premium_r + (1.0 - w_exp)
        path: list[dict[str, Any]] = []
        notes: list[str] = []
        for m in months:
            scen = dict(scenario)
            bucket = spot.get(m, {})
            if "tio2" in bucket:
                p_dom = bucket["tio2"]
            else:
                p_dom = float(scen.get("tio2_sulfate_price", 15500.0))
                notes.append(f"{m}: 钛白粉现货缺失，回退情景价 {p_dom:.0f}")
            # 出口加权实现价（Phase 1）：优先逐月 GACC 出口 ASP，缺失用 premium ratio 外推
            if w_exp > 0:
                asp = export_asp.get(m)
                if asp is not None:
                    p_eff = w_exp * asp + (1.0 - w_exp) * p_dom
                else:
                    p_eff = p_dom * realized_k
                    notes.append(f"{m}: 出口ASP缺失，按实现价系数 {realized_k:.3f} 外推")
                scen["tio2_sulfate_price"] = round(p_eff, 2)
            else:
                scen["tio2_sulfate_price"] = round(p_dom, 2)
            if m in hist_ore:
                scen["ilmenite_market_price"] = float(hist_ore[m])
            elif "ore_plant" in bucket:
                scen["ilmenite_market_price"] = bucket["ore_plant"]
            else:
                notes.append(
                    f"{m}: 钛精矿现货缺失，回退情景到厂价 {scen['ilmenite_market_price']:.0f}"
                )
            if "acid" in bucket:
                scen["acid_price"] = bucket["acid"]
            else:
                notes.append(f"{m}: 硫酸现货缺失，回退情景价 {scen['acid_price']:.0f}")
            if "sulfate_utilization_rate" in scenario:
                if m in hist_util:
                    scen["sulfate_utilization_rate"] = float(hist_util[m])
                elif m in utils:
                    scen["sulfate_utilization_rate"] = utils[m] / 100.0
                else:
                    notes.append(
                        f"{m}: 开工率调研缺失，回退情景利用率 "
                        f"{scenario['sulfate_utilization_rate']:.1%}"
                    )
            path.append(scen)
        return path, notes

    # ------------------------------------------------------------------
    # 季度推演
    # ------------------------------------------------------------------
    def project_quarters(
        self,
        company_id: str,
        scenario_key: str,
        quarter_keys: list[str] | None = None,
    ) -> list[QuarterlyProjectionResult]:
        cfg = self.engine.load_config()
        c_cfg = cfg["companies"][company_id]
        scenario = cfg["scenarios"][scenario_key]
        if quarter_keys is None:
            year = getattr(self.engine.as_of_date, "year", 2026)
            quarter_keys = [f"{year}Q{i}" for i in (1, 2, 3, 4)]

        fin_ctx = self.engine.resolve_financial_context(company_id, c_cfg)
        shares = fin_ctx.total_shares
        tax_rate = float(c_cfg.get("tax_rate", 0.15))
        exp_ratio = float(c_cfg.get("base_expense_ratio", 0.08))
        scale_dict = c_cfg.get("finance_expense_scale_by_scenario") or {}
        fin_scale = float(scale_dict.get(scenario_key, 1.0))

        quarterly_fin = self._latest_quarterly_finance_expense(company_id)
        if quarterly_fin is None:
            annual_fin = self.engine._resolve_finance_expense(fin_ctx, c_cfg, scenario_key)
            quarterly_fin = annual_fin / 4.0
            fin_note = "财务费用: 财报缺失，按年化/4 回退"
        else:
            quarterly_fin *= fin_scale
            fin_note = f"财务费用: 最新报告期单季摊销 × 情景系数 {fin_scale:.2f}"

        results: list[QuarterlyProjectionResult] = []
        for qk in quarter_keys:
            months = quarter_months(qk)
            # Phase 1.5: 已披露报告期直接锚定实际财报（Ground Truth），模型仅外推未披露季度
            actual_q = self._actual_quarter_net(company_id, qk)
            if actual_q is not None:
                results.append(
                    QuarterlyProjectionResult(
                        symbol=company_id,
                        company_name=str(c_cfg.get("name", company_id)),
                        quarter_key=qk,
                        scenario_key=scenario_key,
                        scenario_name=str(scenario.get("name", scenario_key)),
                        segments=[],
                        total_revenue_cny=round(actual_q["revenue"], 2),
                        net_profit_attr_p_cny=round(actual_q["net"], 2),
                        eps_cny=round(actual_q["net"] / shares, 2) if shares > 0 else 0.0,
                        months_used=months,
                        assumption_notes=["已披露报告期，使用实际财报（n_income_attr_p）"],
                        financial_report_date=str(actual_q["report_date"])
                        if actual_q.get("report_date")
                        else None,
                        data_source_mode="actual_report",
                    )
                )
                continue
            path, notes = self._build_monthly_path(company_id, c_cfg, scenario, months)
            notes.append(fin_note)

            # 分部月频聚合（_calc_segment 返回年化值，/12 折算月频；季度=3个月）
            seg_agg: dict[str, dict[str, float]] = {}
            seg_names: dict[str, str] = {}
            for m_scen in path:
                for seg_key in c_cfg["segments"]:
                    seg = self.engine._calc_segment(company_id, seg_key, c_cfg, m_scen)
                    agg = seg_agg.setdefault(
                        seg_key,
                        {"revenue": 0.0, "gp": 0.0, "volume": 0.0, "price_w": 0.0, "cost_w": 0.0},
                    )
                    agg["revenue"] += seg.revenue_cny / 12.0
                    agg["gp"] += seg.gross_profit_cny / 12.0
                    agg["volume"] += seg.sales_volume_tons / 12.0
                    agg["price_w"] += seg.unit_price_cny * seg.sales_volume_tons / 12.0
                    agg["cost_w"] += seg.unit_cost_cny * seg.sales_volume_tons / 12.0
                    seg_names[seg_key] = seg.segment_name

            segments: list[SegmentResult] = []
            for seg_key, agg in seg_agg.items():
                vol = agg["volume"]
                price = agg["price_w"] / vol if vol > 0 else 0.0
                cost = agg["cost_w"] / vol if vol > 0 else 0.0
                segments.append(
                    SegmentResult(
                        segment_key=seg_key,
                        segment_name=seg_names.get(seg_key, seg_key),
                        sales_volume_tons=round(vol, 1),
                        unit_price_cny=round(price, 2),
                        unit_cost_cny=round(cost, 2),
                        unit_gross_margin_cny=round(price - cost, 2),
                        revenue_cny=round(agg["revenue"], 2),
                        gross_profit_cny=round(agg["gp"], 2),
                        gross_margin_ratio=round(
                            agg["gp"] / agg["revenue"] if agg["revenue"] > 0 else 0.0, 4
                        ),
                    )
                )

            total_rev = sum(s.revenue_cny for s in segments)
            total_gp = sum(s.gross_profit_cny for s in segments)
            var_exp = total_rev * exp_ratio
            total_exp = var_exp + quarterly_fin
            op = total_gp - total_exp
            # Phase 1.5: 出口退税独立建模（实现价不含退税；退税 ≈ 13% × 出口收入）
            rp = self.engine.load_config().get("realized_price", {}) or {}
            rebate_rate = float(rp.get("export_rebate_rate", 0.0))
            w_exp = self.engine._resolve_export_weight(company_id, c_cfg)
            premium_r = self.engine._resolve_export_premium_ratio()
            realized_k = w_exp * premium_r + (1.0 - w_exp)
            core_keys = {"sulfate_tio2", "chloride_tio2"}
            core_rev = sum(s.revenue_cny for s in segments if s.segment_key in core_keys)
            export_rev_est = (
                w_exp * core_rev * premium_r / realized_k if realized_k > 0 and w_exp > 0 else 0.0
            )
            export_rebate = export_rev_est * rebate_rate
            op += export_rebate
            tax = max(0.0, op * tax_rate)
            net = op - tax
            core_gp = sum(s.gross_profit_cny for s in segments if s.segment_key in core_keys)
            # Phase 1.6: 年末减值惯例调整（Q4 外推，非已披露季度）
            adj = 0.0
            try:
                rp_adj = self.engine.load_config().get("quarterly_adjustments", {}) or {}
                adj = float(
                    rp_adj.get(company_id, {}).get(qk[4:], {}).get("impairment_expected_cny", 0.0)
                )
            except Exception:
                adj = 0.0
            if adj != 0.0:
                op += adj  # 减值在营业利润内（税前）
                tax = max(0.0, op * tax_rate)
                net = op - tax
                notes.append(
                    f"年末减值惯例调整（税前 {adj / 1e8:.2f} 亿，2023-25 Q4 计提均值，税后约 {-adj * (1 - tax_rate) / 1e8:.2f} 亿）"
                )

            results.append(
                QuarterlyProjectionResult(
                    symbol=company_id,
                    company_name=str(c_cfg.get("name", company_id)),
                    quarter_key=qk,
                    scenario_key=scenario_key,
                    scenario_name=str(scenario.get("name", scenario_key)),
                    segments=segments,
                    total_revenue_cny=round(total_rev, 2),
                    total_gross_profit_cny=round(total_gp, 2),
                    blended_gpm=round(total_gp / total_rev if total_rev > 0 else 0.0, 4),
                    variable_expense_cny=round(var_exp, 2),
                    finance_expense_cny=round(quarterly_fin, 2),
                    total_expense_cny=round(total_exp, 2),
                    operating_profit_cny=round(op, 2),
                    income_tax_cny=round(tax, 2),
                    net_profit_attr_p_cny=round(net, 2),
                    net_profit_margin=round(net / total_rev if total_rev > 0 else 0.0, 4),
                    eps_cny=round(net / shares, 2) if shares > 0 else 0.0,
                    core_tio2_gross_profit_cny=round(core_gp, 2),
                    auxiliary_gross_profit_cny=round(total_gp - core_gp, 2),
                    export_rebate_income_cny=round(export_rebate, 2),
                    months_used=months,
                    assumption_notes=notes,
                    financial_report_date=fin_ctx.report_date,
                    data_source_mode=fin_ctx.source_mode,
                )
            )
        return results

    def to_dataframe(self, results: list[QuarterlyProjectionResult]) -> pl.DataFrame:
        """季度推演结果展平为标准 Polars DataFrame。"""
        rows: list[dict[str, Any]] = []
        for r in results:
            rows.append(
                {
                    "symbol": r.symbol,
                    "company_name": r.company_name,
                    "quarter_key": r.quarter_key,
                    "scenario_key": r.scenario_key,
                    "scenario_name": r.scenario_name,
                    "total_revenue_cny": r.total_revenue_cny,
                    "total_gross_profit_cny": r.total_gross_profit_cny,
                    "core_tio2_gross_profit_cny": r.core_tio2_gross_profit_cny,
                    "auxiliary_gross_profit_cny": r.auxiliary_gross_profit_cny,
                    "export_rebate_income_cny": r.export_rebate_income_cny,
                    "blended_gpm": r.blended_gpm,
                    "variable_expense_cny": r.variable_expense_cny,
                    "finance_expense_cny": r.finance_expense_cny,
                    "total_expense_cny": r.total_expense_cny,
                    "operating_profit_cny": r.operating_profit_cny,
                    "net_profit_attr_p_cny": r.net_profit_attr_p_cny,
                    "net_profit_margin": r.net_profit_margin,
                    "eps_cny": r.eps_cny,
                    "months_used": ",".join(r.months_used),
                    "assumption_notes": "；".join(r.assumption_notes),
                    "financial_report_date": r.financial_report_date,
                    "data_source_mode": r.data_source_mode,
                }
            )
        return pl.DataFrame(rows)

    def build_reconciliation(
        self,
        scenario_key: str = "current_spot",
    ) -> list[dict[str, Any]]:
        """Phase 0 对账门禁：季度引擎 H1 模型 vs 最新实际中报。

        判定：|偏差| > 20% 且 |偏差| > 2 亿 → flag=model_abs_unreliable（绝对数字不可信）。
        period 取 as_of 当年 06-30（2026 中报）。
        """
        cfg = self.engine.load_config()
        as_of_year = getattr(self.engine.as_of_date, "year", 2026)
        period = f"{as_of_year}-06-30"
        out: list[dict[str, Any]] = []
        for cid, c_cfg in cfg.get("companies", {}).items():
            qs = self.project_quarters(cid, scenario_key, [f"{as_of_year}Q1", f"{as_of_year}Q2"])
            model = sum(r.net_profit_attr_p_cny for r in qs)
            actual: float | None = None
            inc = pl.DataFrame()
            if self.engine.catalog is not None:
                for kwargs in (
                    {
                        "symbols": [cid],
                        "columns": ["symbol", "end_date", "ann_date", "n_income_attr_p"],
                    },
                    {"symbols": [cid]},
                    {},
                ):
                    try:
                        inc = self.engine.catalog.load_dataset("income", **kwargs)
                        if not inc.is_empty():
                            break
                    except Exception:
                        continue
            if not inc.is_empty() and "n_income_attr_p" in inc.columns:
                inc = self._pit_truncate(inc, ("ann_date", "end_date"))
                hit = inc.filter(pl.col("end_date").cast(pl.Utf8) == period)
                if not hit.is_empty():
                    vals = hit["n_income_attr_p"].cast(pl.Float64, strict=False).drop_nulls()
                    if len(vals) > 0:
                        actual = float(str(vals.max()))
            flag = "n/a"
            bias_pct = None
            if actual is not None and abs(actual) > 0:
                bias = model - actual
                bias_pct = round(bias / abs(actual) * 100.0, 1)
                flag = (
                    "ok"
                    if (abs(bias_pct) <= 20.0 or abs(bias) <= 2.0e8)
                    else "model_abs_unreliable"
                )
            # Phase 1.6: 外推季度（Q3）主业毛利率 vs 公司报表口径的结构对账
            margin_gap = None
            structure_flag = "n/a"
            company_margin = self._company_tio2_margin(cid)
            if company_margin is not None:
                q3 = self.project_quarters(cid, scenario_key, [f"{as_of_year}Q3"])
                if q3 and q3[0].segments:
                    cr = sum(
                        s.revenue_cny
                        for s in q3[0].segments
                        if s.segment_key in ("sulfate_tio2", "chloride_tio2")
                    )
                    cg = sum(
                        s.gross_profit_cny
                        for s in q3[0].segments
                        if s.segment_key in ("sulfate_tio2", "chloride_tio2")
                    )
                    model_margin = cg / cr * 100.0 if cr > 0 else None
                    if model_margin is not None:
                        margin_gap = round(model_margin - company_margin, 1)
                        structure_flag = "ok" if abs(margin_gap) <= 3.0 else "structural_mismatch"
            out.append(
                {
                    "symbol": cid,
                    "company_name": str(c_cfg.get("name", cid)),
                    "period": period,
                    "scenario_key": scenario_key,
                    "model_net_cny": round(model, 2),
                    "actual_net_cny": actual,
                    "bias_pct": bias_pct,
                    "flag": flag,
                    "rule": "|bias|>20% 且 |bias|>2亿 → model_abs_unreliable",
                    "forward_q_core_margin_gap_pct": margin_gap,
                    "structure_flag": structure_flag,
                    "structure_rule": "Q3 外推主业毛利率 vs 公司报表口径 |gap|>3pct → structural_mismatch",
                }
            )
        return out

    def _company_tio2_margin(self, company_id: str) -> float | None:
        """公司报表钛白粉板块毛利率（最新报告期，fina_mainbz 口径）。"""
        mbz = self.engine._load_mainbz_pit(company_id)
        if mbz.is_empty() or "bz_sales" not in mbz.columns or "bz_profit" not in mbz.columns:
            return None
        latest_end = str(mbz.sort("end_date")["end_date"][-1])
        frame = mbz.filter(
            (pl.col("end_date").cast(pl.Utf8) == latest_end)
            & pl.col("bz_item").cast(pl.Utf8).str.contains("钛白粉")
        )
        if frame.is_empty():
            return None
        rev = float(frame["bz_sales"].cast(pl.Float64, strict=False).drop_nulls().sum())
        gp = float(frame["bz_profit"].cast(pl.Float64, strict=False).drop_nulls().sum())
        return gp / rev * 100.0 if rev > 0 else None


__all__ = [
    "QuarterlyProjectionEngine",
    "QuarterlyProjectionResult",
    "quarter_months",
]
