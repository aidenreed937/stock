"""个股诊断数据加载与辅助函数。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.pipelines.artifacts import (
    ArtifactUnavailableError,
    resolve_artifact_run,
)
from stock_analytics.pipelines.stock_diagnostics.types import (
    CapitalFlowSnapshot,
    ScreenSnapshot,
)
from stock_analytics.primitives.units import yuan_to_yi
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog
from stock_reporting.interpretation.market_temperature.bands import get_temperature_band


def resolve_symbol_meta(catalog: DataCatalog, input_symbol: str) -> tuple[str, str, str, str, str]:
    """根据输入的代码解析标准 symbol 与股票基本信息。"""
    clean = input_symbol.strip().upper()
    try:
        basic_df = catalog.load_dataset("stock_basic")
    except Exception as exc:
        logger.warning(f"无法加载 stock_basic 表: {exc}")
        return clean, clean, "未知行业", "未知地区", "主板"

    if basic_df.is_empty() or "symbol" not in basic_df.columns:
        return clean, clean, "未知行业", "未知地区", "主板"

    matched = basic_df.filter(pl.col("symbol") == clean)
    if matched.is_empty():
        sym_code = clean.split(".")[0]
        matched = basic_df.filter(pl.col("symbol").str.starts_with(sym_code))

    if not matched.is_empty():
        row = matched.to_dicts()[0]
        return (
            str(row.get("symbol", clean)),
            str(row.get("name", clean)),
            str(row.get("industry") or "其他行业"),
            str(row.get("area") or "中国"),
            str(row.get("market") or "主板"),
        )
    return clean, clean, "未知行业", "未知地区", "主板"


def compute_percentile(series: pl.Series, current_value: float) -> float | None:
    """计算当前数值在序列中的历史百分位 (0-100)。"""
    valid = series.drop_nulls()
    if valid.is_empty():
        return None
    less_or_equal = (valid <= current_value).sum()
    return round(float(less_or_equal) / len(valid) * 100.0, 1)


def norm_to_billion(v: float | None, precision: int = 2) -> float | None:
    """统一将以'元'为单位的金额/市值规格化为'亿元'。"""
    if v is None:
        return None
    return yuan_to_yi(v, precision=precision)


def load_10y_treasury_yield(storage_dir: Path | str | None = None) -> float | None:
    """读取本地最新中债 10 年期国债收益率 (%)。"""
    try:
        catalog_lx = DataCatalog("lixinger", storage_dir=storage_dir)
        df = catalog_lx.load_dataset("national_debt")
        if not df.is_empty() and "tcm_y10" in df.columns:
            df = df.sort("trade_date")
            val = df["tcm_y10"].tail(1).to_list()[0]
            if val is not None:
                f_val = float(val)
                return round(f_val * 100.0 if f_val < 0.2 else f_val, 2)
    except Exception as exc:
        logger.warning(f"读取国债收益率失败: {exc}")
    return None


def load_capital_flow(
    catalog: DataCatalog, std_symbol: str, target_date: date | None = None
) -> CapitalFlowSnapshot:
    """加载近 20 日主力大单净流入与北向资金持股比例。"""
    main_net_20d: float | None = None
    hk_ratio: float | None = None

    try:
        mf = catalog.load_dataset("moneyflow", symbols=[std_symbol])
        if not mf.is_empty() and "trade_date" in mf.columns:
            mf = mf.sort("trade_date")
            if target_date is not None:
                mf = mf.filter(pl.col("trade_date") <= target_date)
            recent_mf = mf.tail(20)
            if not recent_mf.is_empty() and all(
                c in recent_mf.columns
                for c in [
                    "buy_elg_amount",
                    "buy_lg_amount",
                    "sell_elg_amount",
                    "sell_lg_amount",
                ]
            ):
                net_series = (
                    recent_mf["buy_elg_amount"]
                    + recent_mf["buy_lg_amount"]
                    - recent_mf["sell_elg_amount"]
                    - recent_mf["sell_lg_amount"]
                )
                raw_sum = float(net_series.sum())
                main_net_20d = norm_to_billion(raw_sum)
    except Exception as exc:
        logger.warning(f"加载主力资金流失败: {exc}")

    try:
        hk = catalog.load_dataset("hk_hold", symbols=[std_symbol])
        if not hk.is_empty() and "trade_date" in hk.columns:
            hk = hk.sort("trade_date")
            if target_date is not None:
                hk = hk.filter(pl.col("trade_date") <= target_date)
            if not hk.is_empty() and "ratio" in hk.columns:
                hk_val = hk["ratio"].tail(1).to_list()[0]
                if hk_val is not None:
                    hk_ratio = round(float(hk_val), 2)
    except Exception as exc:
        logger.warning(f"加载北向持仓失败: {exc}")

    return CapitalFlowSnapshot(
        main_net_inflow_20d_billion=main_net_20d,
        northbound_hold_ratio=hk_ratio,
    )


def load_latest_forecast(
    catalog: DataCatalog, std_symbol: str, target_date: date | None = None
) -> dict[str, Any] | None:
    """加载标的最新业绩预告前瞻。"""
    try:
        fc = catalog.load_dataset("forecast", symbols=[std_symbol])
        if not fc.is_empty() and "ann_date" in fc.columns:
            fc = fc.sort("ann_date")
            if target_date is not None:
                fc = fc.filter(pl.col("ann_date") <= target_date)
            if not fc.is_empty():
                row = fc.tail(1).to_dicts()[0]
                return {
                    "ann_date": str(row.get("ann_date", "")),
                    "end_date": str(row.get("end_date", "")),
                    "type": str(row.get("type", "业绩预告")),
                    "p_change_min": (
                        float(row["p_change_min"]) if row.get("p_change_min") is not None else None
                    ),
                    "p_change_max": (
                        float(row["p_change_max"]) if row.get("p_change_max") is not None else None
                    ),
                    "summary": str(row.get("summary") or ""),
                }
    except Exception as exc:
        logger.warning(f"加载业绩预告失败: {exc}")
    return None


def classify_macro_regime(overheat: float | None, panic: float | None) -> str:
    """根据狂热与恐慌双轨指数给出宏观相态定性。"""
    if overheat is None or panic is None:
        return "数据暂缺"
    if overheat >= 65.0 and panic >= 65.0:
        return "双极值共振 (高位杠杆踩踏高危区)"
    if overheat >= 65.0:
        return "狂热极值 (泡沫冲顶区，严格防守锁润)"
    if panic >= 75.0:
        return "极度冰点 (战略级黄金底，左侧分批)"
    if panic >= 65.0:
        return "恐慌极值 (黄金坑确认期，逢低观察)"
    if overheat >= 60.0:
        return "狂热预警 (动能衰竭分歧，谨防追高)"
    if panic >= 60.0:
        return "恐慌预警 (情绪退潮承压，耐心等待出清)"
    return "情绪平稳 / 结构轮动阶段"


def load_macro_risk_context(
    *,
    artifact_root: Path | str = Path("data/analytics/macro_risk"),
    as_of_date: date | None = None,
) -> tuple[float | None, float | None, str | None, str]:
    """读取已校验的宏观双轨风控产物 (overheat_index, panic_index, macro_regime, as_of_date)。"""
    try:
        run = resolve_artifact_run(
            artifact_root,
            as_of_date=as_of_date or "latest",
            expected_artifact_type="macro_risk",
        )
        as_of_val = str(run.manifest.get("as_of_date", ""))
        overheat_val: float | None = None
        panic_val: float | None = None

        if as_of_date is not None:
            parquet_path = run.path("risk_factors.parquet")
            if parquet_path.exists():
                rf_df = pl.read_parquet(parquet_path)
                if not rf_df.is_empty() and "trade_date" in rf_df.columns:
                    rf_df = rf_df.filter(pl.col("trade_date") <= as_of_date).sort("trade_date")
                    if not rf_df.is_empty():
                        last_row = rf_df.tail(1).to_dicts()[0]
                        as_of_val = str(last_row.get("trade_date", as_of_val))
                        overheat_val = (
                            float(last_row["overheat_index"])
                            if last_row.get("overheat_index") is not None
                            else None
                        )
                        panic_val = (
                            float(last_row["panic_index"])
                            if last_row.get("panic_index") is not None
                            else None
                        )
        else:
            summary = run.manifest.get("summary", {})
            if isinstance(summary, dict):
                if summary.get("overheat_index") is not None:
                    overheat_val = float(summary["overheat_index"])
                if summary.get("panic_index") is not None:
                    panic_val = float(summary["panic_index"])
            if overheat_val is None or panic_val is None:
                parquet_path = run.path("risk_factors.parquet")
                if parquet_path.exists():
                    rf_df = pl.read_parquet(parquet_path)
                    if not rf_df.is_empty():
                        last_row = rf_df.tail(1).to_dicts()[0]
                        as_of_val = str(last_row.get("trade_date", as_of_val))
                        if overheat_val is None and last_row.get("overheat_index") is not None:
                            overheat_val = float(last_row["overheat_index"])
                        if panic_val is None and last_row.get("panic_index") is not None:
                            panic_val = float(last_row["panic_index"])

        regime_str = classify_macro_regime(overheat_val, panic_val)
        return overheat_val, panic_val, regime_str, as_of_val
    except (ArtifactUnavailableError, TypeError, ValueError, Exception) as exc:
        logger.warning(f"读取宏观风控产物失败: {exc}")
    return None, None, None, ""


def load_market_temperature_context(
    *,
    artifact_root: Path | str = Path("data/analytics/market_temperature"),
    as_of_date: date | None = None,
) -> tuple[float | None, str | None, str]:
    """读取已校验的全市场温度产物 (兼容留存)。"""
    try:
        run = resolve_artifact_run(
            artifact_root,
            as_of_date=as_of_date or "latest",
            expected_artifact_type="market_temperature",
        )
        data = run.read_json("scores.json")
        composite = data.get("composite", {})
        temp_val = composite.get("temperature") if isinstance(composite, dict) else None
        if temp_val is not None:
            temp_float = float(temp_val)
            return (
                temp_float,
                get_temperature_band(temp_float),
                str(run.manifest.get("as_of_date", "")),
            )
    except (ArtifactUnavailableError, TypeError, ValueError, Exception) as exc:
        logger.warning(f"读取市场温度产物失败: {exc}")
    return None, None, ""


def _resolve_sw_l1_industry(name: str) -> str:
    try:
        cat = DataCatalog()
        ic = cat.load_dataset("index_classify")
        if not ic.is_empty() and "industry_name" in ic.columns:
            matched = ic.filter(pl.col("industry_name") == name)
            if not matched.is_empty():
                row = matched.to_dicts()[0]
                ind_code = str(row.get("industry_code", ""))
                if len(ind_code) >= 2:
                    l1_code = ind_code[:2] + "0000"
                    l1_matched = ic.filter(
                        (pl.col("level") == "L1") & (pl.col("industry_code") == l1_code)
                    )
                    if not l1_matched.is_empty():
                        return str(l1_matched.to_dicts()[0].get("industry_name", name))
    except Exception:
        pass
    return name


def load_industry_rank(
    industry_name: str,
    *,
    artifact_root: Path | str = Path("data/analytics/industry_structure"),
    as_of_date: date | None = None,
) -> str | None:
    """读取已校验的申万行业结构排名。"""
    try:
        try:
            run = resolve_artifact_run(
                artifact_root,
                as_of_date=as_of_date or "latest",
                expected_artifact_type="industry_factor_panel",
            )
        except ArtifactUnavailableError:
            run = resolve_artifact_run(
                artifact_root,
                as_of_date=as_of_date or "latest",
                expected_artifact_type="industry_structure",
            )
        target_names = {industry_name, _resolve_sw_l1_industry(industry_name)}
        panel_path = run.path("industry_factor_panel.parquet")
        if not panel_path.exists():
            panel_path = run.path("industry_panel.parquet")
        if panel_path.exists():
            panel_df = pl.read_parquet(panel_path)
            if not panel_df.is_empty() and "industry_name" in panel_df.columns:
                date_col = (
                    "trade_date"
                    if "trade_date" in panel_df.columns
                    else ("as_of_date" if "as_of_date" in panel_df.columns else None)
                )
                if as_of_date is not None and date_col is not None:
                    panel_df = panel_df.filter(pl.col(date_col) <= as_of_date)
                if not panel_df.is_empty():
                    if date_col is not None:
                        latest_date = panel_df[date_col].max()
                        day_df = panel_df.filter(pl.col(date_col) == latest_date)
                    else:
                        day_df = panel_df

                    total_count = len(day_df)
                    if "structure_rank" in day_df.columns:
                        for row in day_df.to_dicts():
                            name = str(row.get("industry_name", ""))
                            if name and any(name in t or t in name for t in target_names):
                                rank_idx = int(row.get("structure_rank", 1))
                                score = float(row.get("structure_score", row.get("score", 0.0)))
                                mom = row.get("momentum_score", row.get("ind_momentum"))
                                crowd = row.get("crowding_score", row.get("ind_crowding"))
                                extra = []
                                if mom is not None:
                                    extra.append(f"动量: {float(mom):.1f}")
                                if crowd is not None:
                                    extra.append(f"拥挤度: {float(crowd):.1f}%")
                                extra_str = f" [{', '.join(extra)}]" if extra else ""
                                return f"申万综合排名 {rank_idx}/{total_count} ({name} 评分 {score:.1f}){extra_str}"
                    else:
                        sort_col = (
                            "composite_industry_score"
                            if "composite_industry_score" in day_df.columns
                            else ("ind_momentum" if "ind_momentum" in day_df.columns else "score")
                        )
                        day_df = day_df.sort(sort_col, descending=True)
                        for rank_idx, row in enumerate(day_df.to_dicts(), start=1):
                            name = str(row.get("industry_name", ""))
                            if name and any(name in t or t in name for t in target_names):
                                score = float(row.get(sort_col, 0.0))
                                mom = row.get("ind_momentum")
                                crowd = row.get("ind_crowding")
                                extra = []
                                if mom is not None:
                                    extra.append(f"动量: {float(mom):.1f}")
                                if crowd is not None:
                                    extra.append(f"拥挤度: {float(crowd):.1f}%")
                                extra_str = f" [{', '.join(extra)}]" if extra else ""
                                return f"申万综合排名 {rank_idx}/{total_count} ({name} 评分 {score:.1f}){extra_str}"

        try:
            data = run.read_json("scores.json")
            top_struct = data.get("top_structure", [])
            if isinstance(top_struct, list):
                total_count = data.get("scored_industry_count") or len(top_struct)
                for idx, item in enumerate(top_struct, start=1):
                    if not isinstance(item, dict):
                        continue
                    name = item.get("industry_name", "")
                    if name and any(name in t or t in name for t in target_names):
                        score = float(item.get("structure_score", item.get("score", 0.0)) or 0.0)
                        tags = item.get("tags", "")
                        tag_str = f" [{tags}]" if tags else ""
                        return (
                            f"申万综合排名 {idx}/{total_count} ({name} 评分 {score:.1f}){tag_str}"
                        )
        except Exception:
            pass
    except (ArtifactUnavailableError, TypeError, ValueError, Exception) as exc:
        logger.warning(f"读取行业结构产物失败: {exc}")
    return None


def load_screen_status(
    symbol: str,
    *,
    artifact_root: Path | str = Path("data/analytics/stock_screen"),
    as_of_date: date | None = None,
) -> ScreenSnapshot:
    """从已校验的个股排雷产物中查询标的状态。"""
    clean_sym = symbol.split(".")[0]
    try:
        run = resolve_artifact_run(
            artifact_root,
            as_of_date=as_of_date or "latest",
            expected_artifact_type="stock_screen",
        )
    except ArtifactUnavailableError as exc:
        logger.warning(f"读取排雷产物失败: {exc}")
        return ScreenSnapshot(status="unavailable", reasons=[str(exc)])

    for filename, status in (
        ("excluded.csv", "excluded"),
        ("warned.csv", "warned"),
        ("passed.csv", "passed"),
    ):
        path = run.path(filename)
        if not path.exists():
            continue
        df = _read_screen_snapshot(path)
        if df is None:
            return _unscreened_snapshot(path)
        if "symbol" in df.columns:
            matched = df.filter(pl.col("symbol").str.contains(clean_sym))
            if not matched.is_empty():
                reasons = matched["reasons"].to_list() if "reasons" in matched.columns else []
                return ScreenSnapshot(status=status, reasons=[str(r) for r in reasons])

    return ScreenSnapshot(status="unavailable", reasons=["排雷产物未包含该标的状态"])


def _read_screen_snapshot(path: Path) -> pl.DataFrame | None:
    try:
        return pl.read_csv(path)
    except Exception as exc:
        logger.warning(f"读取排雷快照失败 [{path}]: {exc}")
        return None


def _unscreened_snapshot(path: Path) -> ScreenSnapshot:
    return ScreenSnapshot(status="unscreened", reasons=[f"排雷快照读取失败: {path.name}"])
