"""全市场细分产业链标的与黑马自下而上发现引擎 (ChemicalUniverseScanner)。

基于本地 Curated 黄金事实表：
1. tushare.fina_mainbz (77.8万行分部主营构成) -> 识别主营纯度与全行业集中度 CR5；
2. tushare.balancesheet (在建工程与固定资产) -> 捕捉逆势扩产与 Capex 异动；
3. tushare.stock_basic -> 公司基本画像与行业分类映射。

解决传统研究“只跟踪已知龙头、遗漏高成长黑马与新兴颠覆者”的核心断层。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import polars as pl

from stock_data.catalog import DataCatalog

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DiscoveredCompany:
    """发现的细分赛道上市公司画像。"""

    symbol: str
    name: str
    industry: str
    latest_report_date: str
    target_product_matched: str
    product_sales_cny: float
    total_sales_cny: float
    purity_ratio: float
    market_rank: int
    cip_cny: float | None
    fix_assets_cny: float | None
    cip_to_fix_ratio: float | None
    is_known_leader: bool
    recommendation_tier: (
        str  # "high_conviction_hidden_gem", "scale_challenger", "upstream_supplier", "known_leader"
    )
    reason: str


class ChemicalUniverseScanner:
    """化工细分赛道标的自动扫描器。"""

    def __init__(
        self,
        catalog: DataCatalog | None = None,
        as_of_date: date | str | None = None,
    ) -> None:
        if catalog is None:
            self.catalog = DataCatalog(data_source="tushare")
        else:
            self.catalog = catalog

        if isinstance(as_of_date, date):
            self.as_of_str: str | None = as_of_date.strftime("%Y-%m-%d")
        elif isinstance(as_of_date, str) and as_of_date.strip():
            self.as_of_str = as_of_date.strip()
        else:
            self.as_of_str = None

    def scan(
        self,
        keywords: list[str],
        known_symbols: set[str] | None = None,
        min_purity_ratio: float = 0.10,
        min_sales_cny: float = 5.0e7,  # 5000 万销售额门槛
    ) -> list[DiscoveredCompany]:
        """按产品关键词全市场扫描匹配上市公司。"""
        if not keywords:
            return []

        known = set(known_symbols or set())

        # 1. 读取主营业务构成
        try:
            mbz_df = self.catalog.load_dataset(
                "fina_mainbz",
                columns=["symbol", "end_date", "bz_item", "bz_sales", "bz_profit"],
            )
        except Exception as e:
            logger.error(f"未能加载 fina_mainbz 黄金事实表: {e}")
            return []

        if mbz_df.is_empty():
            return []

        # Point-in-Time 防前视
        if self.as_of_str and "end_date" in mbz_df.columns:
            mbz_df = mbz_df.filter(pl.col("end_date").cast(pl.Utf8) <= self.as_of_str)

        # 关键词过滤
        regex_pattern = "|".join(keywords)
        matched = mbz_df.filter(
            pl.col("bz_item").str.contains(regex_pattern)
            & pl.col("bz_sales").is_not_null()
            & (pl.col("bz_sales") >= min_sales_cny)
        )
        if matched.is_empty():
            return []

        # 获取各公司最新一期匹配产品及销售额
        latest_matched = matched.sort("end_date").group_by("symbol").last()

        # 统计该公司该期的全部主营销售额总和 (用于计算纯度)
        total_by_period = (
            mbz_df.filter(pl.col("bz_sales").is_not_null())
            .group_by(["symbol", "end_date"])
            .agg(pl.col("bz_sales").sum().alias("period_total_sales"))
        )

        merged = latest_matched.join(
            total_by_period,
            on=["symbol", "end_date"],
            how="left",
        )

        # 2. 读取基础股票信息
        try:
            basic_df = self.catalog.load_dataset(
                "stock_basic",
                columns=["symbol", "name", "industry"],
            )
        except Exception:
            basic_df = pl.DataFrame()

        if not basic_df.is_empty():
            merged = merged.join(basic_df, on="symbol", how="left")
        else:
            merged = merged.with_columns(
                pl.lit("未知").alias("name"),
                pl.lit("化工").alias("industry"),
            )

        # 3. 读取在建工程与固定资产 (Capex 异动)
        try:
            bs_df = self.catalog.load_dataset(
                "balancesheet",
                columns=["symbol", "end_date", "cip", "fix_assets"],
            )
            if self.as_of_str and "end_date" in bs_df.columns:
                bs_df = bs_df.filter(pl.col("end_date").cast(pl.Utf8) <= self.as_of_str)
            latest_bs = bs_df.sort("end_date").group_by("symbol").last()
            merged = merged.join(latest_bs, on="symbol", how="left")
        except Exception:
            merged = merged.with_columns(
                pl.lit(None).cast(pl.Float64).alias("cip"),
                pl.lit(None).cast(pl.Float64).alias("fix_assets"),
            )

        # 排序计算市场排名
        sorted_df = merged.sort("bz_sales", descending=True)
        results: list[DiscoveredCompany] = []

        rank = 1
        for row in sorted_df.iter_rows(named=True):
            sym = str(row["symbol"])
            prod_sales = float(row.get("bz_sales") or 0.0)
            tot_sales = float(row.get("period_total_sales") or prod_sales)
            purity = prod_sales / tot_sales if tot_sales > 0 else 0.0

            if purity < min_purity_ratio:
                continue

            cip = float(row["cip"]) if row.get("cip") is not None else None
            fa = float(row["fix_assets"]) if row.get("fix_assets") is not None else None
            cip_ratio = (cip / fa) if (cip is not None and fa is not None and fa > 0) else None

            is_known = sym in known
            tier, reason = self._evaluate_tier(
                sym=sym,
                name=str(row.get("name") or sym),
                prod_name=str(row.get("bz_item") or ""),
                sales=prod_sales,
                purity=purity,
                cip_ratio=cip_ratio,
                is_known=is_known,
                rank=rank,
            )

            results.append(
                DiscoveredCompany(
                    symbol=sym,
                    name=str(row.get("name") or sym),
                    industry=str(row.get("industry") or "化工"),
                    latest_report_date=str(row.get("end_date") or ""),
                    target_product_matched=str(row.get("bz_item") or ""),
                    product_sales_cny=round(prod_sales, 2),
                    total_sales_cny=round(tot_sales, 2),
                    purity_ratio=round(purity, 4),
                    market_rank=rank,
                    cip_cny=round(cip, 2) if cip is not None else None,
                    fix_assets_cny=round(fa, 2) if fa is not None else None,
                    cip_to_fix_ratio=round(cip_ratio, 4) if cip_ratio is not None else None,
                    is_known_leader=is_known,
                    recommendation_tier=tier,
                    reason=reason,
                )
            )
            rank += 1

        return results

    def _evaluate_tier(
        self,
        sym: str,
        name: str,
        prod_name: str,
        sales: float,
        purity: float,
        cip_ratio: float | None,
        is_known: bool,
        rank: int,
    ) -> tuple[str, str]:
        """评定标的价值梯队与推荐理由。"""
        if is_known:
            return "known_leader", "已纳管核心观察池标的"

        reasons = []
        if "矿" in prod_name or "渣" in prod_name:
            tier = "upstream_supplier"
            reasons.append(f"上游资源端关键原料供应商 (销售额 {sales / 1e8:.2f}亿)")
        elif rank <= 3 or sales >= 1.5e9:
            tier = "scale_challenger"
            reasons.append(f"全市场第 {rank} 大规模挑战者 (销售额 {sales / 1e8:.2f}亿)")
        elif purity >= 0.60:
            tier = "high_conviction_hidden_gem"
            reasons.append(f"高主营纯度细分黑马 ({purity * 100:.1f}%)")
        else:
            tier = "niche_participant"
            reasons.append(f"细分参与者 (主营占比 {purity * 100:.1f}%)")

        if cip_ratio is not None and cip_ratio >= 0.40:
            reasons.append(f"在建工程强度显著 (CIP/FA={cip_ratio * 100:.1f}%, 扩产弹性大)")

        return tier, "; ".join(reasons)

    def to_dataframe(self, companies: list[DiscoveredCompany]) -> pl.DataFrame:
        """将发现结果转为标准 Polars DataFrame。"""
        if not companies:
            return pl.DataFrame()
        from dataclasses import asdict

        return pl.DataFrame([asdict(c) for c in companies])

    def render_markdown_report(
        self,
        sector_name: str,
        companies: list[DiscoveredCompany],
    ) -> str:
        """生成细分赛道标的发现与市场集中度报告。"""
        lines = [
            f"# {sector_name} 全市场自下而上标的发现与黑马挖掘报告",
            "",
            "> **数据源**: 本地 Curated 黄金事实表 (`fina_mainbz` + `balancesheet` + `stock_basic`)",
            f"> **发现总数**: {len(companies)} 家匹配上市公司",
            "",
            "## 一、 全市场主营规模与暴露度排名",
            "",
            "| 排名 | 代码 | 简称 | 匹配主营项目 | 最新报告期 | 产品营收 (亿元) | 主营纯度 | 在建工程比率 (CIP/FA) | 状态 | 推荐梯队与核心看点 |",
            "| :---: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |",
        ]
        for c in companies:
            known_str = "已纳管" if c.is_known_leader else "**新发现**"
            cip_str = f"{c.cip_to_fix_ratio * 100:.1f}%" if c.cip_to_fix_ratio is not None else "--"
            lines.append(
                f"| {c.market_rank} | `{c.symbol}` | {c.name} | {c.target_product_matched} | "
                f"{c.latest_report_date} | {c.product_sales_cny / 1e8:.2f} | {c.purity_ratio * 100:.1f}% | "
                f"{cip_str} | {known_str} | {c.reason} |"
            )

        lines.extend(
            [
                "",
                "## 二、 推荐纳入观察池与生成画像建议",
                "",
            ]
        )
        gems = [
            c
            for c in companies
            if not c.is_known_leader
            and c.recommendation_tier
            in ("high_conviction_hidden_gem", "scale_challenger", "upstream_supplier")
        ]
        if gems:
            for g in gems:
                lines.append(f"- **`{g.symbol}` {g.name}** [{g.recommendation_tier}]: {g.reason}")
        else:
            lines.append("- 当前暂无新的高置信度标的推荐。")

        return "\n".join(lines)
