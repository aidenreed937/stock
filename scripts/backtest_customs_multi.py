#!/usr/bin/env python3
"""多产品横向验证：出口景气信号择时的普适性检验（transformer 之外的泛化）。

对每个产品（受益公司池取自 company_exposure_map.csv）跑基础版与质量过滤版
回测（复用 backtest_customs_company_signal 的状态机/收益引擎），输出对比表：

    product, version, n_trades, win_rate, beat_rate, avg_trade_ret,
    avg_excess_pp, pl_ratio, avg_hold_months

用法:
    uv run python scripts/backtest_customs_multi.py
    uv run python scripts/backtest_customs_multi.py --products solar_cell lithium_chemicals cathode_material
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path
from typing import Any, cast

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent))
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backtest_customs_company_signal import (  # noqa: E402
    DEFAULT_FINA,
    build_weight_plan,
    filter_quality_for_product,
    load_monthly_ret,
    load_quality_layers,
    split_trades,
)

from stock_data.fetcher.industry.customs.release_calendar import effective_month  # noqa: E402

DEFAULT_YOY = Path("data/analytics/industry/customs_product_volume_price.parquet")
DEFAULT_MAP = Path("config/data/customs/company_exposure_map.csv")
DEFAULT_BENCH = "000300.SH"
DEFAULT_OUTPUT = Path("data/analytics/industry/customs_signal_multi.parquet")
DEFAULT_PRODUCTS = [
    "transformer",
    "solar_cell",
    "lithium_chemicals",
    "cathode_material",
    "battery",
    "wind_turbine",
    "semiconductor_equipment",
    "copper_unwrought",
    "aluminum_unwrought",
    "silver",
]


def companies_for(
    map_path: Path, product: str, quality: dict[str, dict[str, str]] | None = None
) -> list[str]:
    """产品受益公司（可选按同产品竞争力分层过滤，§5.4 修订）。"""
    with map_path.open("r", encoding="utf-8-sig", newline="") as f:
        syms = sorted({r["stock_code"] for r in csv.DictReader(f) if r["product_key"] == product})
    if quality is None:
        return syms
    return filter_quality_for_product(product, syms, quality)


def product_series(
    pv: pl.DataFrame, product: str
) -> tuple[list[str], list[float | None], list[str | None]]:
    """产品主段（金额最大段）全月序 yoy + 驱动类型。"""
    seg = (
        pv.filter(pl.col("product_key") == product)
        .group_by("unit_segment")
        .agg(pl.col("export_value_usd").sum().alias("v"))
        .sort("v", descending=True)
    )
    main = seg["unit_segment"][0]
    ser = (
        pv.filter((pl.col("product_key") == product) & (pl.col("unit_segment") == main))
        .select(["report_month", "value_yoy_3mma", "驱动类型"])
        .sort("report_month")
    )
    months = ser["report_month"].to_list()
    vals: list[float | None] = ser["value_yoy_3mma"].to_list()
    drives: list[str | None] = ser["驱动类型"].to_list()
    return (
        cast("list[str]", months),
        vals,
        drives,
    )


def backtest_product(
    product: str,
    symbols: list[str],
    months: list[str],
    vals: list[float | None],
    drives: list[str | None],
    quality: bool,
    retdf_all: pl.DataFrame,
    benchdf: pl.DataFrame,
) -> list[dict[str, Any]]:
    weights = build_weight_plan(vals, drives=drives, quality_gate=quality)
    retdf = retdf_all.filter(pl.col("symbol").is_in(symbols))
    port = (
        retdf.join(benchdf, on="month", how="inner")
        .group_by("month")
        .agg(pl.col("ret").mean().alias("combo_ret"), pl.col("bench_ret").first())
        .sort("month")
    )
    effective_months = [effective_month(m) for m in months]
    return split_trades(effective_months, weights, port)  # type: ignore[no-any-return]  # 跨脚本 import，mypy 无法解析


def summarize(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "n_trades": 0,
            "win_rate": float("nan"),
            "beat_rate": float("nan"),
            "avg_trade_ret": float("nan"),
            "avg_excess_pp": float("nan"),
            "pl_ratio": float("nan"),
            "avg_hold_months": float("nan"),
        }
    tdf = pl.DataFrame(
        [
            {
                "trade_ret": t["trade_ret"] - 1,
                "bench_ret": t["bench_ret"] - 1,
                "n_months": t["n_months"],
            }
            for t in trades
        ]
    )
    n = tdf.height
    wins = tdf.filter(pl.col("trade_ret") > 0).height
    beats = tdf.filter(pl.col("trade_ret") > pl.col("bench_ret")).height
    mean_pos = (
        cast("float", tdf.filter(pl.col("trade_ret") > 0)["trade_ret"].mean()) if wins else 0.0
    )
    mean_neg = (
        cast("float", tdf.filter(pl.col("trade_ret") <= 0)["trade_ret"].mean()) if n - wins else 0.0
    )
    return {
        "n_trades": n,
        "win_rate": wins / n,
        "beat_rate": beats / n,
        "avg_trade_ret": cast("float", tdf["trade_ret"].mean()),
        "avg_excess_pp": cast("float", (tdf["trade_ret"] - tdf["bench_ret"]).mean()) * 100,
        "pl_ratio": mean_pos / abs(mean_neg) if mean_neg != 0 else float("nan"),
        "avg_hold_months": cast("float", tdf["n_months"].mean()),
    }


def _fmt(v: Any, spec: str, suffix: str = "") -> str:
    """格式化输出，NaN/None → —。"""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return format(v, spec) + suffix


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", nargs="*", default=DEFAULT_PRODUCTS)
    parser.add_argument("--yoy", default=str(DEFAULT_YOY))
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--fina", type=Path, default=DEFAULT_FINA, help="fina_indicator 根目录")
    parser.add_argument(
        "--quality-filter",
        action="store_true",
        help="按同产品竞争力分层过滤受益公司（§5.4 修订：剔除亏损型 + 净利率/毛利率均低于"
        "同产品中位数的低竞争力公司），输出追加 filter 版对比",
    )
    parser.add_argument(
        "--product-gate",
        action="store_true",
        help="叠加产品级低毛利排除（中位毛利率<15% 且 ROE<10% 整产品剔除，仅静态组合下行保护）",
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--detail", action="store_true", help="打印每产品轮次明细")
    args = parser.parse_args()

    pv = pl.read_parquet(args.yoy)
    quality: dict[str, dict[str, str]] | None = (
        load_quality_layers(args.fina, args.map, product_gate=args.product_gate)
        if args.quality_filter else None
    )
    # 一次性加载：全部目标公司月收益 + 基准（avoid 每产品重载全量行情）。
    # 注意：必须用未过滤的全池加载，base/quality/quality_filter 各 variant 再按
    # 自己的公司池从 retdf_all 中过滤，否则过滤会污染基础版对比。
    all_symbols = sorted({s for p in args.products for s in companies_for(args.map, p, None)})
    retdf_all = load_monthly_ret(
        "data/curated/tushare/market=CN/stock_daily_bar/year=2*/**/*.parquet", all_symbols
    )
    benchdf = (
        load_monthly_ret(
            "data/curated/tushare/market=CN/index_daily/year=2*/**/*.parquet",
            [DEFAULT_BENCH],
            use_adj=False,
        )
        .rename({"ret": "bench_ret"})
        .drop("symbol")
    )
    summary_rows = []
    for product in args.products:
        symbols = companies_for(args.map, product, None)
        months, vals, drives = product_series(pv, product)
        if not symbols:
            print(f"[SKIP] {product}: 无受益公司")
            continue
        # 基础/质量两版（全池），+ 竞争力过滤版（quality 版再过滤）
        variants: list[tuple[list[str], str]] = [(symbols, "base"), (symbols, "quality")]
        if quality is not None:
            filt = companies_for(args.map, product, quality)
            variants.append((filt, "quality_filter"))
        for syms, label in variants:
            trades = backtest_product(
                product,
                syms,
                months,
                vals,
                drives,
                label == "quality" or label == "quality_filter",
                retdf_all,
                benchdf,
            )
            s = summarize(trades)
            s["product"], s["version"] = product, label
            s["n_symbols"] = len(syms)
            summary_rows.append(s)
            if args.detail and trades:
                detail = pl.DataFrame(
                    [
                        {
                            "start": t["start"],
                            "end": t["end"],
                            "n_months": t["n_months"],
                            "trade_ret": round(t["trade_ret"] - 1, 3),
                            "excess": round((t["trade_ret"] - 1) - (t["bench_ret"] - 1), 3),
                        }
                        for t in trades
                    ]
                )
                print(f"\n[{product}/{label}] 轮次明细:")
                print(detail.to_pandas().to_string(index=False))

    out = pl.DataFrame(summary_rows).sort(["product", "version"])
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(args.output)

    print("\n=== 多产品横向对比（基础版 vs 质量过滤版 vs 竞争力过滤版，GACC 口径 2019-2026）===")
    cols = [
        "product",
        "version",
        "n_symbols",
        "n_trades",
        "win_rate",
        "beat_rate",
        "avg_trade_ret",
        "avg_excess_pp",
        "pl_ratio",
        "avg_hold_months",
    ]
    print(
        out.select(cols)
        .with_columns(
            pl.col("n_symbols")
            .map_elements(lambda x: _fmt(x, "d"), return_dtype=pl.String)
            .alias("n_symbols"),
            pl.col("win_rate")
            .map_elements(lambda x: _fmt(x, ".0%"), return_dtype=pl.String)
            .alias("win_rate"),
            pl.col("beat_rate")
            .map_elements(lambda x: _fmt(x, ".0%"), return_dtype=pl.String)
            .alias("beat_rate"),
            pl.col("avg_trade_ret")
            .map_elements(
                lambda x: _fmt(
                    x * 100 if not (isinstance(x, float) and math.isnan(x)) else float("nan"),
                    "+.1f",
                    "%",
                ),
                return_dtype=pl.String,
            )
            .alias("avg_trade_ret"),
            pl.col("avg_excess_pp")
            .map_elements(lambda x: _fmt(x, "+.1f", "pp"), return_dtype=pl.String)
            .alias("avg_excess_pp"),
            pl.col("pl_ratio")
            .map_elements(lambda x: _fmt(x, ".2f"), return_dtype=pl.String)
            .alias("pl_ratio"),
            pl.col("avg_hold_months")
            .map_elements(lambda x: _fmt(x, ".1f", "m"), return_dtype=pl.String)
            .alias("avg_hold_months"),
        )
        .to_pandas()
        .to_string(index=False)
    )
    print(f"\n已写出: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
