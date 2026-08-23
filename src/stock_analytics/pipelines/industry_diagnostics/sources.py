"""中观产业与行业诊断数据加载与辅助函数。"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from stock_analytics.pipelines.industry_diagnostics.types import (
    IndustryConstituentsSnapshot,
    IndustryValueChainSnapshot,
)
from stock_core.utils.logger import logger
from stock_data.catalog import DataCatalog


def resolve_industry_meta(catalog_tu: DataCatalog, input_str: str) -> tuple[str, str, str, str]:
    """解析行业代码、标准名称、层级 (L1/L2) 与行业编码。"""
    clean = input_str.strip()
    try:
        ic_df = catalog_tu.load_dataset("index_classify")
        if not ic_df.is_empty() and "industry_name" in ic_df.columns:
            # 1. 精确匹配 index_code (如 801120.SI)
            matched = ic_df.filter(pl.col("index_code") == clean)
            # 2. 精确匹配行业名称 (如 "食品饮料", "白酒Ⅱ")
            if matched.is_empty():
                matched = ic_df.filter(pl.col("industry_name") == clean)
            # 3. 模糊包含匹配 (如 "白酒" 匹配 "白酒Ⅱ")
            if matched.is_empty():
                matched = ic_df.filter(pl.col("industry_name").str.contains(clean))

            if not matched.is_empty():
                row = matched.to_dicts()[0]
                lvl = "申万一级" if str(row.get("level")) == "L1" else "申万二级"
                return (
                    str(row.get("index_code", clean)),
                    str(row.get("industry_name", clean)),
                    lvl,
                    str(row.get("industry_code", "")),
                )
    except Exception as exc:
        logger.warning(f"解析行业分类失败: {exc}")

    return clean, clean, "申万行业", ""


def load_industry_constituents(
    catalog_tu: DataCatalog, industry_code: str, target_date: date | None = None
) -> IndustryConstituentsSnapshot:
    """查询行业成份股清单并提取市值前 5 龙头梯队。"""
    try:
        mem_df = catalog_tu.load_dataset("index_member")
        if mem_df.is_empty() or "index_code" not in mem_df.columns:
            return IndustryConstituentsSnapshot()

        matched_members = mem_df.filter(pl.col("index_code") == industry_code)
        if matched_members.is_empty():
            return IndustryConstituentsSnapshot()

        if "out_date" in matched_members.columns:
            matched_members = matched_members.filter(
                pl.col("out_date").is_null() | (pl.col("out_date") >= date(2026, 1, 1))
            )

        symbols = matched_members["con_code"].unique().to_list()
        total_count = len(symbols)
        if not symbols:
            return IndustryConstituentsSnapshot(total_count=0)

        # 关联 stock_basic 获取股票名称
        stock_basic = catalog_tu.load_dataset("stock_basic")
        name_map: dict[str, str] = {}
        if not stock_basic.is_empty():
            for row in stock_basic.select(["symbol", "name"]).to_dicts():
                name_map[str(row["symbol"])] = str(row["name"])

        # 关联 daily_basic 获取最新有效交易日市值与 PE
        db_df = catalog_tu.load_dataset("daily_basic", symbols=symbols[:120])
        leader_items: list[dict[str, Any]] = []
        if not db_df.is_empty() and "trade_date" in db_df.columns:
            db_df = db_df.sort("trade_date")
            if target_date is not None:
                db_df = db_df.filter(pl.col("trade_date") <= target_date)
            # 过滤最近一个月有交易的活跃成份股
            latest_month_df = db_df.filter(pl.col("trade_date") >= date(2026, 7, 1))
            if not latest_month_df.is_empty():
                latest_db = latest_month_df.group_by("symbol").last()
                for row in latest_db.to_dicts():
                    sym = str(row.get("symbol", ""))
                    total_mv = row.get("total_mv")
                    mv_billion = (
                        round(float(total_mv) / 1e8, 1)
                        if total_mv and float(total_mv) > 1e7
                        else 0.0
                    )
                    leader_items.append(
                        {
                            "symbol": sym,
                            "name": name_map.get(sym, sym),
                            "total_mv_billion": mv_billion,
                            "pe_ttm": (
                                round(float(row["pe_ttm"]), 1)
                                if row.get("pe_ttm") is not None
                                else None
                            ),
                            "roe": None,
                        }
                    )

        # 按市值从大到小排序
        leader_items.sort(key=lambda x: x["total_mv_billion"], reverse=True)
        top_5_mv = leader_items[:5]

        return IndustryConstituentsSnapshot(
            total_count=total_count,
            top_market_cap_leaders=top_5_mv,
            top_roe_leaders=[],
        )
    except Exception as exc:
        logger.warning(f"加载行业成份股失败: {exc}")
        return IndustryConstituentsSnapshot()


def load_value_chain_map(industry_name: str) -> IndustryValueChainSnapshot:
    """从本地 YAML 配置中读取该行业的上下游传导图谱与高频监测指标。"""
    cfg_path = Path("config/industry/value_chain_map.yaml")
    if not cfg_path.exists():
        return IndustryValueChainSnapshot()

    try:
        with open(cfg_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        ind_dict = data.get("industries", {})
        for name_key, details in ind_dict.items():
            if name_key in industry_name or industry_name in name_key:
                return IndustryValueChainSnapshot(
                    upstream=details.get("upstream", []),
                    downstream=details.get("downstream", []),
                    cost_sensitivity=details.get("cost_sensitivity", ""),
                    high_frequency_indicators=details.get("high_frequency_indicators", []),
                )
    except Exception as exc:
        logger.warning(f"读取产业链图谱失败: {exc}")

    return IndustryValueChainSnapshot()
