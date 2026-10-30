"""化工大宗周期核心上市公司业绩与估值弹性领域 Mart (chemical_elasticity_mart)。

基于第一性原理：
商品现货价格变动 -> 扣除 13% 增值税 -> 乘以有效商品外售产能 -> 扣除所得税 -> 归母净利润增厚 -> EPS 弹性与估值收益率提升。

核心量化公式：
1. 净商品外售产能 (万吨):
   Net_Capacity_W = Annual_Capacity_W * Equity_Ratio * (1.0 - Internal_Conversion_Ratio)
2. 规范 EPS 弹性 (元/股, 每 100 元/吨含税价差变动):
   Delta_EPS_per_100 = [ (100 / (1 + VAT)) * Net_Capacity_W * (1 - Tax_Rate) ] / Total_Shares_W
3. 净利润增厚 (亿元, 每 100 元/吨含税价差变动):
   Delta_Profit_100M_per_100 = [ (100 / (1 + VAT)) * Net_Capacity_W * 10^4 * (1 - Tax_Rate) ] / 10^8
4. 市值盈利收益率提升 (%):
   Market_Cap_Yield_Boost_Pct = (Delta_Profit_CNY / Total_MV) * 100.0
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_data.catalog import DataCatalog

logger = logging.getLogger(__name__)

CHEMICAL_ELASTICITY_MART_NAME = "chemical_elasticity_mart"
CHEMICAL_ELASTICITY_MART_FILE = f"{CHEMICAL_ELASTICITY_MART_NAME}.parquet"
CHEMICAL_ELASTICITY_MART_CSV = f"{CHEMICAL_ELASTICITY_MART_NAME}_latest.csv"

DEFAULT_ELASTICITY_CONFIG_DIR = Path("config/industry/chemicals")
LEGACY_ELASTICITY_CONFIG_PATH = Path("config/industry/chemicals/company_elasticities.yaml")

CHEMICAL_ELASTICITY_SCHEMA: dict[str, Any] = {
    "trade_date": pl.Date,
    "symbol": pl.Utf8,
    "company_name": pl.Utf8,
    "commodity_code": pl.Utf8,
    "commodity_name": pl.Utf8,
    "annual_capacity_w_tons": pl.Float64,
    "equity_ratio": pl.Float64,
    "internal_conversion_ratio": pl.Float64,
    "net_capacity_w_tons": pl.Float64,
    "cost_advantage_tier": pl.Utf8,
    "effective_tax_rate": pl.Float64,
    "vat_rate": pl.Float64,
    "total_shares_w": pl.Float64,
    "close": pl.Float64,
    "total_mv_100m": pl.Float64,
    "pe_ttm": pl.Float64,
    "pb": pl.Float64,
    "eps_delta_per_100cny": pl.Float64,
    "profit_delta_100m_per_100cny": pl.Float64,
    "market_cap_yield_boost_pct": pl.Float64,
    "elasticity_rank_in_commodity": pl.Int64,
}


def _normalize_company_entry(
    company: dict[str, Any],
    default_code: str | None,
    default_name: str | None,
    default_vat: float,
) -> list[dict[str, Any]]:
    """将公司配置对象规范化为一个或多个标准商品弹性字典。"""
    sym = str(company.get("symbol", "")).strip()
    c_name = str(company.get("name", "")).strip()
    c_tier = str(company.get("cost_advantage_tier") or company.get("cost_tier", "normal"))
    c_tax = float(company.get("effective_tax_rate", 0.15))
    c_vat = float(company.get("vat_rate", default_vat))
    c_eq = float(company.get("equity_ratio", 1.0))
    c_conv = float(company.get("internal_conversion_ratio", 0.0))

    results: list[dict[str, Any]] = []

    has_products = "products" in company and isinstance(company["products"], list)
    primary_code = company.get("commodity_code") or default_code
    primary_name = company.get("commodity_name") or default_name
    primary_cap = company.get("annual_capacity_w_tons")

    if primary_code and primary_cap is not None:
        # 当存在额外衍生产品列表且主产品自用比例达到 100% 时，主产品仅为纯内部原料，不单独作为商品外售弹性项
        if not (has_products and c_conv >= 1.0):
            results.append(
                {
                    "symbol": sym,
                    "name": c_name,
                    "commodity_code": str(primary_code).upper(),
                    "commodity_name": str(primary_name or primary_code),
                    "annual_capacity_w_tons": float(primary_cap),
                    "equity_ratio": c_eq,
                    "internal_conversion_ratio": c_conv,
                    "cost_advantage_tier": c_tier,
                    "effective_tax_rate": c_tax,
                    "vat_rate": c_vat,
                    "notes": str(company.get("cost_notes") or company.get("notes", "")),
                }
            )

    if has_products:
        for p in company["products"]:
            p_code = p.get("commodity_code")
            if not p_code:
                continue
            p_name = p.get("commodity_name") or p_code
            p_cap = float(p.get("annual_capacity_w_tons", 0.0))
            p_eq = float(p.get("equity_ratio", c_eq))
            p_conv = float(p.get("internal_conversion_ratio", 0.0))
            p_tier = str(p.get("cost_advantage_tier") or p.get("cost_tier", c_tier))
            p_tax = float(p.get("effective_tax_rate", c_tax))
            p_vat = float(p.get("vat_rate", c_vat))
            p_notes = str(p.get("notes") or company.get("notes", ""))
            results.append(
                {
                    "symbol": sym,
                    "name": c_name,
                    "commodity_code": str(p_code).upper(),
                    "commodity_name": str(p_name),
                    "annual_capacity_w_tons": p_cap,
                    "equity_ratio": p_eq,
                    "internal_conversion_ratio": p_conv,
                    "cost_advantage_tier": p_tier,
                    "effective_tax_rate": p_tax,
                    "vat_rate": p_vat,
                    "notes": p_notes,
                }
            )

    return results


def _load_single_elasticity_file(path: Path) -> tuple[float, list[dict[str, Any]]]:
    """读取并解析单个弹性/公司配置文件。"""
    content = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    vat_rate = float(content.get("vat_rate_default", 0.13))
    def_code = content.get("default_commodity_code")
    def_name = content.get("default_commodity_name")

    all_entries: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for c in content.get("companies", []):
        entries = _normalize_company_entry(c, def_code, def_name, vat_rate)
        for entry in entries:
            key = (entry["commodity_code"], entry["symbol"])
            if key not in seen_keys:
                seen_keys.add(key)
                all_entries.append(entry)

    return vat_rate, all_entries


def load_company_elasticity_config(
    config_path: Path | str | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """读取化工上市公司单吨产能与弹性画像配置。

    自适应支持两种模式：
    1. 传入单个文件路径时（或 legacy 单体配置文件），直接读取该文件；
    2. 未指定路径时，自动扫描并聚合各子品种高内聚目录（config/industry/chemicals/*/companies.yaml）。
    """
    if config_path is not None:
        p = Path(config_path)
        if not p.exists():
            logger.warning(f"弹性配置文件不存在: {p}")
            return 0.13, []
        return _load_single_elasticity_file(p)

    # 优先扫描各子模块目录
    config_dir = DEFAULT_ELASTICITY_CONFIG_DIR
    sub_files = sorted(config_dir.glob("*/companies.yaml"))
    if not sub_files:
        if LEGACY_ELASTICITY_CONFIG_PATH.exists():
            return _load_single_elasticity_file(LEGACY_ELASTICITY_CONFIG_PATH)
        logger.warning(f"未找到任何子模块 companies.yaml 配置文件: {config_dir}")
        return 0.13, []

    default_vat = 0.13
    all_companies: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for file_path in sub_files:
        try:
            content = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        except Exception as exc:
            logger.warning(f"解析配置文件失败 {file_path}: {exc}")
            continue

        file_vat = float(content.get("vat_rate_default", default_vat))
        def_code = content.get("default_commodity_code")
        def_name = content.get("default_commodity_name")

        for c in content.get("companies", []):
            entries = _normalize_company_entry(c, def_code, def_name, file_vat)
            for entry in entries:
                key = (entry["commodity_code"], entry["symbol"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    all_companies.append(entry)

    all_companies.sort(key=lambda x: (x["commodity_code"], x["symbol"]))
    return default_vat, all_companies


def _load_latest_daily_market(
    catalog: DataCatalog,
    symbols: list[str],
    as_of_date: date | str | None = None,
) -> pl.DataFrame:
    """从 daily_basic 加载所有目标股票的最新交易事实与估值数据。"""
    if not symbols:
        return pl.DataFrame()

    try:
        daily_df = catalog.load_dataset("daily_basic", symbols=symbols)
    except Exception as exc:
        logger.warning(f"加载 daily_basic 失败: {exc}")
        return pl.DataFrame()

    if daily_df.is_empty():
        return pl.DataFrame()

    # Point-in-Time 过滤
    if as_of_date:
        as_of_d = (
            as_of_date
            if isinstance(as_of_date, date)
            else date.fromisoformat(str(as_of_date).strip())
        )
        daily_df = daily_df.filter(pl.col("trade_date").cast(pl.Date) <= as_of_d)

    # 选取每只股票最新一条行情
    latest_rows = (
        daily_df.sort(["symbol", "trade_date"], descending=[False, True])
        .group_by("symbol", maintain_order=True)
        .first()
    )

    cols_to_select = ["symbol", "trade_date", "close", "total_share", "total_mv", "pe_ttm", "pb"]
    available_cols = [c for c in cols_to_select if c in latest_rows.columns]
    return latest_rows.select(available_cols)


def build_chemical_elasticity_mart(
    catalog: DataCatalog | None = None,
    config_path: Path | str | None = None,
    as_of_date: date | str | None = None,
    output_dir: Path | str | None = None,
) -> pl.DataFrame:
    """构建化工上市公司单吨产能与业绩弹性领域 Mart。

    计算每 100 元/吨现货价格跳变对各上市公司 EPS 与净利润的增厚弹性，并按品种排名。
    """
    cat = catalog or DataCatalog("tushare")
    default_vat, companies_cfg = load_company_elasticity_config(config_path)

    if not companies_cfg:
        logger.warning("未找到有效企业弹性配置，返回空 Mart")
        return pl.DataFrame(schema=CHEMICAL_ELASTICITY_SCHEMA)

    unique_symbols = sorted({c["symbol"] for c in companies_cfg if "symbol" in c})
    market_df = _load_latest_daily_market(cat, unique_symbols, as_of_date=as_of_date)

    # 建立 symbol -> 市场数据字典
    market_map: dict[str, dict[str, Any]] = {}
    if not market_df.is_empty():
        for row in market_df.to_dicts():
            market_map[row["symbol"]] = row

    rows: list[dict[str, Any]] = []

    for item in companies_cfg:
        sym = item.get("symbol", "")
        c_name = item.get("name", "")
        code = item.get("commodity_code", "")
        name = item.get("commodity_name", "")
        cap_w = float(item.get("annual_capacity_w_tons", 0.0))
        eq_ratio = float(item.get("equity_ratio", 1.0))
        conv_ratio = float(item.get("internal_conversion_ratio", 0.0))
        tier = item.get("cost_advantage_tier", "normal")
        tax_rate = float(item.get("effective_tax_rate", 0.15))
        vat = float(item.get("vat_rate", default_vat))

        # 净商品外售规模 (万吨)
        net_cap_w = cap_w * eq_ratio * (1.0 - conv_ratio)

        # 获取最新行情与股本事实
        mkt = market_map.get(sym, {})
        t_date = mkt.get("trade_date")
        if t_date is None:
            t_date = (
                as_of_date
                if isinstance(as_of_date, date)
                else (date.today() if as_of_date is None else date.fromisoformat(str(as_of_date)))
            )
        close_px = float(mkt.get("close") or 0.0)
        total_share_w = float(mkt.get("total_share") or 0.0)  # 万股
        total_mv_raw = float(mkt.get("total_mv") or 0.0)  # 元
        pe_ttm_val = float(mkt.get("pe_ttm") or 0.0)
        pb_val = float(mkt.get("pb") or 0.0)

        # 若行情缺失 total_share，从 total_mv / close 回测或设为兜底
        if total_share_w <= 0.0 and close_px > 0.0 and total_mv_raw > 0.0:
            total_share_w = (total_mv_raw / close_px) / 10000.0

        # 量化核心测算 (每 100 元/吨价格跳变)
        delta_p_inc_vat = 100.0
        delta_p_ex_vat = delta_p_inc_vat / (1.0 + vat)

        # 净利润增厚 (亿元): [ex_vat * (net_cap_w * 10^4) * (1 - tax)] / 10^8
        profit_delta_100m = (delta_p_ex_vat * net_cap_w * 10000.0 * (1.0 - tax_rate)) / 1.0e8
        profit_delta_cny = profit_delta_100m * 1.0e8

        # EPS 增厚 (元/股): profit_delta_cny / (total_share_w * 10^4)
        eps_delta = profit_delta_cny / (total_share_w * 10000.0) if total_share_w > 0.0 else 0.0

        # 市值盈利收益率增厚 (百分点)
        market_cap_yield_boost = (
            (profit_delta_cny / total_mv_raw) * 100.0 if total_mv_raw > 0.0 else 0.0
        )

        total_mv_100m = total_mv_raw / 1.0e8

        rows.append(
            {
                "trade_date": t_date,
                "symbol": sym,
                "company_name": c_name,
                "commodity_code": code,
                "commodity_name": name,
                "annual_capacity_w_tons": round(cap_w, 2),
                "equity_ratio": round(eq_ratio, 4),
                "internal_conversion_ratio": round(conv_ratio, 4),
                "net_capacity_w_tons": round(net_cap_w, 2),
                "cost_advantage_tier": tier,
                "effective_tax_rate": round(tax_rate, 4),
                "vat_rate": round(vat, 4),
                "total_shares_w": round(total_share_w, 2),
                "close": round(close_px, 2),
                "total_mv_100m": round(total_mv_100m, 2),
                "pe_ttm": round(pe_ttm_val, 2),
                "pb": round(pb_val, 2),
                "eps_delta_per_100cny": round(eps_delta, 4),
                "profit_delta_100m_per_100cny": round(profit_delta_100m, 4),
                "market_cap_yield_boost_pct": round(market_cap_yield_boost, 4),
                "elasticity_rank_in_commodity": 0,  # 稍后排序填充
            }
        )

    df = pl.DataFrame(rows, schema=CHEMICAL_ELASTICITY_SCHEMA)

    # 按品类内部按 EPS 弹性降序排名
    ranked_df = df.sort(
        ["commodity_code", "eps_delta_per_100cny"], descending=[False, True]
    ).with_columns(
        pl.col("eps_delta_per_100cny")
        .rank(descending=True, method="ordinal")
        .cast(pl.Int64)
        .over("commodity_code")
        .alias("elasticity_rank_in_commodity")
    )

    # 物化落盘
    out_dir = Path(output_dir) if output_dir else Path("data/curated/mart")
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = out_dir / CHEMICAL_ELASTICITY_MART_FILE
    csv_path = out_dir / CHEMICAL_ELASTICITY_MART_CSV

    ranked_df.write_parquet(parquet_path)
    ranked_df.write_csv(csv_path)
    logger.info(f"成功物化化工上市公司业绩弹性 Mart: {parquet_path} ({len(ranked_df)} 行)")

    return ranked_df


def simulate_spot_price_shocks(
    mart_df: pl.DataFrame,
    shocks: dict[str, float],
) -> pl.DataFrame:
    """基于自定义商品现货价格冲击模拟各标的利润与 EPS 变动。

    Args:
        mart_df: chemical_elasticity_mart 数据集
        shocks: 品类代码到价格冲击 (含税元/吨) 的字典，例如 {"SA": 200.0, "TA": 150.0}

    Returns:
        包含实际模拟结果的 DataFrame，新增 custom_profit_delta_100m 与 custom_eps_delta
    """
    if mart_df.is_empty() or not shocks:
        return mart_df

    # 提取冲击乘数
    shock_mappings: list[dict[str, Any]] = []
    for code, shock_val in shocks.items():
        shock_mappings.append({"commodity_code": code, "price_shock_cny": float(shock_val)})

    shock_df = pl.DataFrame(shock_mappings)

    joined = mart_df.join(shock_df, on="commodity_code", how="left").with_columns(
        pl.col("price_shock_cny").fill_null(0.0)
    )

    multiplier = pl.col("price_shock_cny") / 100.0

    return joined.with_columns(
        (pl.col("profit_delta_100m_per_100cny") * multiplier)
        .round(4)
        .alias("custom_profit_delta_100m"),
        (pl.col("eps_delta_per_100cny") * multiplier).round(4).alias("custom_eps_delta"),
    ).drop("price_shock_cny")
