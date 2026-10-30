"""大宗化工品期现基差时钟与交割仓单异动量化 Mart (chemical_basis_inventory_mart)。

基于第一性原理与微观市场结构：
1. 期现结构与基差时钟 (Basis Term Structure Clock):
   计算真实基差、基差率、Backwardation/Contango 结构、1Y/3Y 历史分位数及 5D/20D 基差收敛动量。
2. 交易所交割仓单蓄水池 (Warehouse Warrants Dynamics):
   按标准合约手吨数换算物理万吨量，计算仓单 1Y/3Y 历史分位、5D/20D 注销加速度与厂库显性化比率。
3. 周期微观共振评级 (Composite Microstructure Regime):
   综合基差时钟与仓单流向，生成强共振看多、挤仓风险、天量压顶与左侧收敛等微观状态。
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

logger = logging.getLogger(__name__)

CHEMICAL_BASIS_INVENTORY_MART_NAME = "chemical_basis_inventory_mart"
CHEMICAL_BASIS_INVENTORY_MART_FILE = f"{CHEMICAL_BASIS_INVENTORY_MART_NAME}.parquet"
CHEMICAL_BASIS_INVENTORY_MART_CSV = f"{CHEMICAL_BASIS_INVENTORY_MART_NAME}_latest.csv"

DEFAULT_CURATED_DIR = Path("data/curated")
DEFAULT_MART_DIR = DEFAULT_CURATED_DIR / "mart"

# 各大宗期货品种标准合约规格 (手吨数/交割属性)
FUTURES_LOT_SPECS: dict[str, dict[str, Any]] = {
    "SA": {
        "commodity_code": "SA",
        "futures_symbol": "SA",
        "product_name": "纯碱",
        "exchange": "CZCE",
        "lot_size_tons": 20.0,
        "unit": "元/吨",
    },
    "TA": {
        "commodity_code": "TA",
        "futures_symbol": "TA",
        "product_name": "精对苯二甲酸",
        "exchange": "CZCE",
        "lot_size_tons": 5.0,
        "unit": "元/吨",
    },
    "EG": {
        "commodity_code": "MEG",
        "futures_symbol": "EG",
        "product_name": "乙二醇",
        "exchange": "DCE",
        "lot_size_tons": 10.0,
        "unit": "元/吨",
    },
    "MA": {
        "commodity_code": "MA",
        "futures_symbol": "MA",
        "product_name": "甲醇",
        "exchange": "CZCE",
        "lot_size_tons": 10.0,
        "unit": "元/吨",
    },
    "V": {
        "commodity_code": "V",
        "futures_symbol": "V",
        "product_name": "聚氯乙烯",
        "exchange": "DCE",
        "lot_size_tons": 5.0,
        "unit": "元/吨",
    },
    "UR": {
        "commodity_code": "UR",
        "futures_symbol": "UR",
        "product_name": "尿素",
        "exchange": "CZCE",
        "lot_size_tons": 20.0,
        "unit": "元/吨",
    },
    "FG": {
        "commodity_code": "FG",
        "futures_symbol": "FG",
        "product_name": "玻璃",
        "exchange": "CZCE",
        "lot_size_tons": 20.0,
        "unit": "元/吨",
    },
    "SH": {
        "commodity_code": "SH",
        "futures_symbol": "SH",
        "product_name": "烧碱",
        "exchange": "CZCE",
        "lot_size_tons": 30.0,
        "unit": "元/吨",
    },
    "EB": {
        "commodity_code": "EB",
        "futures_symbol": "EB",
        "product_name": "苯乙烯",
        "exchange": "DCE",
        "lot_size_tons": 5.0,
        "unit": "元/吨",
    },
    "PP": {
        "commodity_code": "PP",
        "futures_symbol": "PP",
        "product_name": "聚丙烯",
        "exchange": "DCE",
        "lot_size_tons": 5.0,
        "unit": "元/吨",
    },
    "L": {
        "commodity_code": "L",
        "futures_symbol": "L",
        "product_name": "塑料",
        "exchange": "DCE",
        "lot_size_tons": 5.0,
        "unit": "元/吨",
    },
}

# 别名映射
SYMBOL_ALIAS_MAP: dict[str, str] = {
    "MEG": "EG",
    "SA_LIGHT": "SA",
    "POY": "TA",
}


@dataclass(frozen=True)
class MicrostructureSignal:
    """单个标的在基准日上的微观期现信号。"""

    trade_date: date
    commodity_code: str
    futures_symbol: str
    product_name: str
    spot_price_cny: float
    futures_close_cny: float
    basis_cny: float
    basis_rate_pct: float
    basis_term_structure: str
    basis_rate_pctl_1y: float | None
    basis_rate_pctl_3y: float | None
    basis_chg_5d_cny: float | None
    basis_chg_20d_cny: float | None
    basis_convergence_signal: str
    warehouse_receipts_contracts: float | None
    warehouse_receipts_w_tons: float | None
    receipts_pctl_1y: float | None
    receipts_pctl_3y: float | None
    receipts_chg_5d_w_tons: float | None
    receipts_chg_20d_w_tons: float | None
    receipts_acceleration_status: str
    receipts_overhang_status: str
    factory_inventory_w_tons: float | None
    receipts_to_factory_ratio_pct: float | None
    composite_micro_regime: str
    right_side_basis_gate_pass: bool


class ChemicalBasisInventoryMart:
    """期现基差与仓单异动量化 Mart 构建引擎。"""

    def __init__(self, curated_dir: Path | None = None) -> None:
        self.curated_dir = Path(curated_dir or DEFAULT_CURATED_DIR)
        self.mart_dir = self.curated_dir / "mart"

    def _load_raw_tables(
        self,
    ) -> tuple[pl.DataFrame | None, pl.DataFrame | None, pl.DataFrame | None]:
        """加载输入事实表。"""
        basis_path = self.curated_dir / "industry" / "chemical_futures_basis.parquet"
        inv_path = self.curated_dir / "industry" / "futures_inventory.parquet"
        survey_path = self.curated_dir / "industry" / "chemical_weekly_survey.parquet"

        basis_df = pl.read_parquet(basis_path) if basis_path.exists() else None
        inv_df = pl.read_parquet(inv_path) if inv_path.exists() else None
        survey_df = pl.read_parquet(survey_path) if survey_path.exists() else None

        return basis_df, inv_df, survey_df

    def build_mart(self) -> pl.DataFrame:
        """构建全历史逐日期现基差与交割仓单异动 Mart。"""
        basis_df, inv_df, survey_df = self._load_raw_tables()
        if basis_df is None or basis_df.is_empty():
            logger.warning("基差事实表为空或不存在，无法构建 Mart")
            return pl.DataFrame()

        # 统一符号别名
        norm_basis = basis_df.with_columns(
            pl.col("symbol").replace(SYMBOL_ALIAS_MAP).alias("futures_symbol")
        )

        all_dfs: list[pl.DataFrame] = []

        # 按品种分组计算滚动指标
        symbols = norm_basis["futures_symbol"].unique().sort().to_list()
        for f_sym in symbols:
            spec = FUTURES_LOT_SPECS.get(f_sym)
            if not spec:
                continue

            lot_size = spec["lot_size_tons"]
            comm_code = spec["commodity_code"]
            p_name = spec["product_name"]

            sub_basis = norm_basis.filter(pl.col("futures_symbol") == f_sym).sort("trade_date")
            if sub_basis.is_empty():
                continue

            # 提取仓单数据
            sub_inv = pl.DataFrame()
            if inv_df is not None and not inv_df.is_empty():
                sub_inv = inv_df.filter(pl.col("symbol") == f_sym).sort("trade_date")

            # 提取企业厂库数据
            sub_sv = pl.DataFrame()
            if survey_df is not None and not survey_df.is_empty():
                sym_col = "symbol" if "symbol" in survey_df.columns else "product_name"
                sub_sv = survey_df.filter(
                    (pl.col(sym_col).str.to_uppercase() == comm_code.upper())
                    | (pl.col("product_name").str.contains(p_name))
                ).sort("trade_date")

            # 合并日频基础序列
            merged_symbol_df = self._align_and_compute_symbol_timeseries(
                sub_basis=sub_basis,
                sub_inv=sub_inv,
                sub_sv=sub_sv,
                comm_code=comm_code,
                f_sym=f_sym,
                p_name=p_name,
                lot_size=lot_size,
            )
            if not merged_symbol_df.is_empty():
                all_dfs.append(merged_symbol_df)

        if not all_dfs:
            return pl.DataFrame()

        result_df = pl.concat(all_dfs, how="diagonal_relaxed").sort(
            ["trade_date", "commodity_code"]
        )
        self._save_mart(result_df)
        return result_df

    def _align_and_compute_symbol_timeseries(
        self,
        sub_basis: pl.DataFrame,
        sub_inv: pl.DataFrame,
        sub_sv: pl.DataFrame,
        comm_code: str,
        f_sym: str,
        p_name: str,
        lot_size: float,
    ) -> pl.DataFrame:
        """针对单一品种计算全量滚动特征。"""
        # 1. 基础期现指标
        base_df = sub_basis.select(
            [
                pl.col("trade_date").cast(pl.Date),
                pl.col("spot_price_cny").cast(pl.Float64),
                pl.col("dom_contract_price").cast(pl.Float64).alias("futures_close_cny"),
                pl.col("basis_cny").cast(pl.Float64),
                pl.col("basis_rate_pct").cast(pl.Float64),
            ]
        ).filter(
            pl.col("spot_price_cny").is_not_null()
            & (pl.col("spot_price_cny") > 0)
            & pl.col("futures_close_cny").is_not_null()
        )

        if base_df.is_empty():
            return pl.DataFrame()

        # 2. 关联仓单 (按 trade_date join)
        if not sub_inv.is_empty():
            inv_clean = sub_inv.select(
                [
                    pl.col("trade_date").cast(pl.Date),
                    pl.col("inventory").cast(pl.Float64).alias("warehouse_receipts_contracts"),
                ]
            )
            joined = base_df.join(inv_clean, on="trade_date", how="left")
        else:
            joined = base_df.with_columns(
                pl.lit(None).cast(pl.Float64).alias("warehouse_receipts_contracts")
            )

        # 3. 关联企业周度厂库 (as_of join 或前向填充)
        if not sub_sv.is_empty() and "factory_inventory_w_tons" in sub_sv.columns:
            sv_clean = (
                sub_sv.select(
                    [
                        pl.col("trade_date").cast(pl.Date),
                        pl.col("factory_inventory_w_tons").cast(pl.Float64),
                    ]
                )
                .drop_nulls()
                .sort("trade_date")
            )
            joined = joined.join_asof(sv_clean, on="trade_date", strategy="backward")
        else:
            joined = joined.with_columns(
                pl.lit(None).cast(pl.Float64).alias("factory_inventory_w_tons")
            )

        # 4. 计算物理万吨与滚动指标
        joined = joined.with_columns(
            (pl.col("warehouse_receipts_contracts") * lot_size / 10000.0).alias(
                "warehouse_receipts_w_tons"
            ),
            # 5日与20日基差变动
            (pl.col("basis_cny") - pl.col("basis_cny").shift(5)).alias("basis_chg_5d_cny"),
            (pl.col("basis_cny") - pl.col("basis_cny").shift(20)).alias("basis_chg_20d_cny"),
            (pl.col("basis_rate_pct") - pl.col("basis_rate_pct").shift(5)).alias(
                "basis_rate_chg_5d_pct"
            ),
            (pl.col("basis_rate_pct") - pl.col("basis_rate_pct").shift(20)).alias(
                "basis_rate_chg_20d_pct"
            ),
        )

        # 计算 5日与 20日仓单变动
        joined = joined.with_columns(
            (
                pl.col("warehouse_receipts_w_tons") - pl.col("warehouse_receipts_w_tons").shift(5)
            ).alias("receipts_chg_5d_w_tons"),
            (
                pl.col("warehouse_receipts_w_tons") - pl.col("warehouse_receipts_w_tons").shift(20)
            ).alias("receipts_chg_20d_w_tons"),
            (
                pl.col("warehouse_receipts_w_tons") / pl.col("factory_inventory_w_tons") * 100.0
            ).alias("receipts_to_factory_ratio_pct"),
        )

        # 5. 滚动历史分位数 (1Y=250d, 3Y=750d)
        basis_rate_list = joined["basis_rate_pct"].to_list()
        warrant_list = joined["warehouse_receipts_w_tons"].to_list()
        n = len(joined)

        pctl_1y_basis: list[float | None] = []
        pctl_3y_basis: list[float | None] = []
        pctl_1y_warrant: list[float | None] = []
        pctl_3y_warrant: list[float | None] = []

        for i in range(n):
            # 基差 1Y / 3Y 分位
            val_b = basis_rate_list[i]
            if val_b is not None:
                w1_b = [x for x in basis_rate_list[max(0, i - 250) : i + 1] if x is not None]
                w3_b = [x for x in basis_rate_list[max(0, i - 750) : i + 1] if x is not None]
                pctl_1y_basis.append(
                    round(sum(1 for x in w1_b if x <= val_b) / len(w1_b) * 100.0, 1)
                    if len(w1_b) > 1
                    else 50.0
                )
                pctl_3y_basis.append(
                    round(sum(1 for x in w3_b if x <= val_b) / len(w3_b) * 100.0, 1)
                    if len(w3_b) > 1
                    else 50.0
                )
            else:
                pctl_1y_basis.append(None)
                pctl_3y_basis.append(None)

            # 仓单 1Y / 3Y 分位
            val_w = warrant_list[i]
            if val_w is not None:
                w1_w = [x for x in warrant_list[max(0, i - 250) : i + 1] if x is not None]
                w3_w = [x for x in warrant_list[max(0, i - 750) : i + 1] if x is not None]
                pctl_1y_warrant.append(
                    round(sum(1 for x in w1_w if x <= val_w) / len(w1_w) * 100.0, 1)
                    if len(w1_w) > 1
                    else 50.0
                )
                pctl_3y_warrant.append(
                    round(sum(1 for x in w3_w if x <= val_w) / len(w3_w) * 100.0, 1)
                    if len(w3_w) > 1
                    else 50.0
                )
            else:
                pctl_1y_warrant.append(None)
                pctl_3y_warrant.append(None)

        # 6. 生成离散状态机与信号
        term_structures: list[str] = []
        convergence_signals: list[str] = []
        accel_statuses: list[str] = []
        overhang_statuses: list[str] = []
        micro_regimes: list[str] = []
        gate_passes: list[bool] = []

        chg_5d_b_list = joined["basis_rate_chg_5d_pct"].to_list()
        chg_20d_b_list = joined["basis_rate_chg_20d_pct"].to_list()
        chg_5d_w_list = joined["receipts_chg_5d_w_tons"].to_list()
        chg_20d_w_list = joined["receipts_chg_20d_w_tons"].to_list()

        for i in range(n):
            b_pct = basis_rate_list[i]
            pctl_b1 = pctl_1y_basis[i]
            pctl_w1 = pctl_1y_warrant[i]
            d5_b = chg_5d_b_list[i]
            d20_b = chg_20d_b_list[i]
            d5_w = chg_5d_w_list[i]
            d20_w = chg_20d_w_list[i]

            # A. 期现结构
            if b_pct is None:
                term = "UNKNOWN"
            elif b_pct >= 0.5:
                term = "BACKWARDATION"
            elif b_pct <= -0.5:
                term = "CONTANGO"
            else:
                term = "FLAT"
            term_structures.append(term)

            # B. 基差修复动量
            if b_pct is not None and d20_b is not None and b_pct >= 0.0 and (b_pct - d20_b) < -2.0:
                conv = "STRONG_REPAIR"
            elif d5_b is not None and d5_b > 1.5 and b_pct is not None and b_pct < 0.0:
                conv = "MILD_REPAIR"
            elif d5_b is not None and d5_b < -2.0:
                conv = "EXPANDING_CONTANGO"
            else:
                conv = "NEUTRAL"
            convergence_signals.append(conv)

            # C. 仓单注销加速度
            if d5_w is not None and d20_w is not None:
                if d5_w < 0 and d5_w < (d20_w / 4.0):
                    acc = "ACCELERATED_DRAIN"
                elif d5_w > 0 and d5_w > (d20_w / 4.0):
                    acc = "RAPID_ACCUMULATION"
                else:
                    acc = "STABLE"
            else:
                acc = "UNKNOWN"
            accel_statuses.append(acc)

            # D. 仓单积压状态
            if pctl_w1 is not None and pctl_w1 >= 80.0:
                overhang = "MASSIVE_OVERHANG"
            elif pctl_w1 is not None and pctl_w1 <= 20.0:
                overhang = "LOW_BUFFER"
            else:
                overhang = "NORMAL"
            overhang_statuses.append(overhang)

            # E. 综合微观状态
            if (term == "BACKWARDATION" or conv == "STRONG_REPAIR") and (
                acc == "ACCELERATED_DRAIN" or (d5_w is not None and d5_w < 0)
            ):
                regime = "STRONG_BULLISH_REVERSAL"
            elif term == "BACKWARDATION" and overhang == "LOW_BUFFER":
                regime = "SQUEEZE_RISK"
            elif term == "CONTANGO" and overhang == "MASSIVE_OVERHANG":
                regime = "BEARISH_CONTANGO_OVERHANG"
            elif (
                term == "CONTANGO"
                and (pctl_b1 is not None and pctl_b1 <= 15.0)
                and conv in ("STRONG_REPAIR", "MILD_REPAIR")
            ):
                regime = "LEFT_SIDE_POTENTIAL"
            else:
                regime = "NEUTRAL_WATCH"
            micro_regimes.append(regime)

            # F. 右侧门禁通过判定 (basis_rate >= 0.0)
            gate_passes.append(bool(b_pct is not None and b_pct >= 0.0))

        # 整合为完整 DataFrame
        return joined.with_columns(
            pl.lit(comm_code).alias("commodity_code"),
            pl.lit(f_sym).alias("futures_symbol"),
            pl.lit(p_name).alias("product_name"),
            pl.Series("basis_rate_pctl_1y", pctl_1y_basis, dtype=pl.Float64),
            pl.Series("basis_rate_pctl_3y", pctl_3y_basis, dtype=pl.Float64),
            pl.Series("receipts_pctl_1y", pctl_1y_warrant, dtype=pl.Float64),
            pl.Series("receipts_pctl_3y", pctl_3y_warrant, dtype=pl.Float64),
            pl.Series("basis_term_structure", term_structures, dtype=pl.Utf8),
            pl.Series("basis_convergence_signal", convergence_signals, dtype=pl.Utf8),
            pl.Series("receipts_acceleration_status", accel_statuses, dtype=pl.Utf8),
            pl.Series("receipts_overhang_status", overhang_statuses, dtype=pl.Utf8),
            pl.Series("composite_micro_regime", micro_regimes, dtype=pl.Utf8),
            pl.Series("right_side_basis_gate_pass", gate_passes, dtype=pl.Boolean),
        )

    def _save_mart(self, df: pl.DataFrame) -> None:
        """原子写入 Parquet 与最新 CSV。"""
        self.mart_dir.mkdir(parents=True, exist_ok=True)
        out_parquet = self.mart_dir / CHEMICAL_BASIS_INVENTORY_MART_FILE
        tmp_parquet = out_parquet.with_suffix(".parquet.tmp")
        df.write_parquet(tmp_parquet, compression="zstd")
        tmp_parquet.replace(out_parquet)

        out_csv = self.mart_dir / CHEMICAL_BASIS_INVENTORY_MART_CSV
        df.sort("trade_date", descending=True).head(50).write_csv(out_csv)
        logger.info("已物化期现基差与仓单 Mart: %s (共 %d 行)", out_parquet, len(df))

    def print_microstructure_dashboard(self, as_of_date: date | str | None = None) -> None:
        """打印截面微观看板。"""
        mart_path = self.mart_dir / CHEMICAL_BASIS_INVENTORY_MART_FILE
        df = self.build_mart() if not mart_path.exists() else pl.read_parquet(mart_path)

        if df.is_empty():
            print("期现基差与仓单 Mart 为空。")
            return

        if as_of_date:
            target_date = (
                date.fromisoformat(as_of_date) if isinstance(as_of_date, str) else as_of_date
            )
            sub = df.filter(pl.col("trade_date") <= target_date)
            latest_date = df["trade_date"].max() if sub.is_empty() else sub["trade_date"].max()
        else:
            latest_date = df["trade_date"].max()

        snapshot = df.filter(pl.col("trade_date") == latest_date).sort("commodity_code")

        print("=" * 118)
        print(f"大宗化工品期现基差时钟与交割仓单异动监控看板 (基准日: {latest_date!s})")
        print("=" * 118)
        header = (
            f"{'品种':<4} | {'代码':<3} | {'现货(元)':<7} | {'期货(元)':<7} | {'基差(元)':<7} | "
            f"{'基差率%':<6} | {'期现结构':<13} | {'基差分位':<8} | {'仓单(万吨)':<8} | "
            f"{'仓单分位':<8} | {'5D仓单变动':<9} | {'微观共振评级':<24} | {'右侧门禁':<6}"
        )
        print(header)
        print("-" * 118)

        for row in snapshot.iter_rows(named=True):
            pctl_b = (
                f"{row['basis_rate_pctl_1y']:.1f}%"
                if row["basis_rate_pctl_1y"] is not None
                else "-"
            )
            w_tons = (
                f"{row['warehouse_receipts_w_tons']:.2f}"
                if row["warehouse_receipts_w_tons"] is not None
                else "-"
            )
            w_pctl = (
                f"{row['receipts_pctl_1y']:.1f}%" if row["receipts_pctl_1y"] is not None else "-"
            )
            d5_w = (
                f"{row['receipts_chg_5d_w_tons']:+.2f}"
                if row["receipts_chg_5d_w_tons"] is not None
                else "-"
            )
            gate = "PASS" if row["right_side_basis_gate_pass"] else "FAIL"

            line = (
                f"{row['product_name']:<4} | {row['commodity_code']:<3} | "
                f"{row['spot_price_cny']:<8.1f} | {row['futures_close_cny']:<8.1f} | "
                f"{row['basis_cny']:<8.1f} | {row['basis_rate_pct']:<7.2f} | "
                f"{row['basis_term_structure']:<13} | {pctl_b:<8} | "
                f"{w_tons:<9} | {w_pctl:<8} | {d5_w:<10} | "
                f"{row['composite_micro_regime']:<24} | {gate:<6}"
            )
            print(line)
        print("=" * 118)


def main() -> None:
    parser = argparse.ArgumentParser(description="物化大宗化工品期现基差与交割仓单 Mart")
    parser.add_argument("--as-of-date", type=str, default=None, help="分析基准日 (YYYY-MM-DD)")
    parser.add_argument("--print-table", action="store_true", default=True, help="打印微观看板")
    args = parser.parse_args()

    mart = ChemicalBasisInventoryMart()
    mart.build_mart()
    if args.print_table:
        mart.print_microstructure_dashboard(as_of_date=args.as_of_date)


if __name__ == "__main__":
    main()
