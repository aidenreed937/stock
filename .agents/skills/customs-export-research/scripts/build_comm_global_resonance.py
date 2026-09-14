#!/usr/bin/env python3
"""通信设备（光模块）全球 AI 资本开支 6 信号共振小面板。

数据基础: data/curated/industry/ 下 6 个本地黄金表（Ground Truth First）：
  1. cloud_capex_quarterly           云 CapEx 合计 yoy（光模块最终需求）
  2. semiconductor_equipment         SEMI 设备销售 3MMA yoy（资本开支先行腿）
  3. semiconductor_lead              台积电月度收入 yoy（代工景气）
  4. semiconductor_sales             SIA 全球半导体销售 yoy（需求侧）
  5. semiconductor_equipment_gm      ASML 毛利率（供给端定价权）
  6. semiconductor_channel_inventory 渠道库存 DOI（无堆积确认）

产出: data/analytics/industry/comm_global_resonance_panel.parquet
      （signal 长表：最新一期 + 上期对照，含 trend/status 判定）
      + 终端打印最新快照。

判定口径（对应 12 报告 §通信专题与 industry-trend-tracking 拐点规则）：
  - trend: 当期 vs 上期变化方向（加剧/缓解/持平；DOI 上升=恶化、下降=改善）；
  - status: 扩张=增长为正（渠道 DOI 取近 10 年历史分位经验标尺：≤80 天健康——
    p50≈54、p90≈78、max≈86，非权威阈值，见 14 文档 §5）；收缩=增长转负（DOI >80 天堆积）；
  - direction 预警：云 CapEx 与 SEMI 设备任一由扩张转加速下滑即触发拐点预警
    （全球资本开支见顶 = 拐点正确信号，见 industry-trend-tracking 拐点规则）。

用法:
    uv run python scripts/build_comm_global_resonance.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

DEFAULT_OUTPUT = Path("data/analytics/industry/comm_global_resonance_panel.parquet")
CURATED = Path("data/curated/industry")
DOI_HEALTHY_MAX = 80  # 渠道（分销商）DOI 健康分位经验上沿：p50≈54 / p90≈78 / max≈86（非权威阈值）


def _series(name: str, as_of: str, value: float, date: pl.Date) -> pl.DataFrame:
    return pl.DataFrame(
        {"signal": [name], "as_of": [as_of], "date": [date], "value": [round(value, 2)]}
    )


def build(output: Path | str = DEFAULT_OUTPUT) -> pl.DataFrame:
    cc = pl.read_parquet(CURATED / "cloud_capex_quarterly.parquet").sort("report_quarter")
    eq = pl.read_parquet(CURATED / "semiconductor_equipment.parquet").sort("report_month")
    lead = pl.read_parquet(CURATED / "semiconductor_lead.parquet").sort("report_month")
    sia = pl.read_parquet(CURATED / "semiconductor_sales.parquet").sort("report_month")
    gm = pl.read_parquet(CURATED / "semiconductor_equipment_gm.parquet").sort("report_quarter")
    inv = pl.read_parquet(CURATED / "semiconductor_channel_inventory.parquet").sort("trade_date")

    rows = [
        _series(
            "云CapEx合计yoy",
            cc[-1]["report_quarter"][0],
            cc[-1]["yoy_growth"][0] * 100,
            cc[-1]["trade_date"][0],
        ),
        _series(
            "SEMI设备销售3MMAyoy",
            eq[-1]["report_month"][0],
            eq[-1]["yoy_growth_3mma"][0] * 100,
            eq[-1]["trade_date"][0],
        ),
        _series(
            "台积电收入yoy",
            lead[-1]["report_month"][0],
            lead[-1]["tsmc_revenue_yoy"][0] * 100,
            lead[-1]["trade_date"][0],
        ),
        _series(
            "SIA全球销售yoy",
            sia[-1]["report_month"][0],
            sia[-1]["yoy_growth"][0] * 100,
            sia[-1]["trade_date"][0],
        ),
        _series(
            "设备商毛利率pct",
            gm[-1]["report_quarter"][0],
            gm[-1]["gross_margin_pct"][0],
            gm[-1]["trade_date"][0],
        ),
        _series(
            "渠道库存DOI天数",
            inv[-1]["trade_date"][0].strftime("%Y-%m-%d"),
            inv[-1]["channel_weighted_doi_days"][0],
            inv[-1]["trade_date"][0],
        ),
    ]

    prev_rows = [
        _series(
            "云CapEx合计yoy",
            cc[-2]["report_quarter"][0],
            cc[-2]["yoy_growth"][0] * 100,
            cc[-2]["trade_date"][0],
        ),
        _series(
            "SEMI设备销售3MMAyoy",
            eq[-2]["report_month"][0],
            eq[-2]["yoy_growth_3mma"][0] * 100,
            eq[-2]["trade_date"][0],
        ),
        _series(
            "台积电收入yoy",
            lead[-2]["report_month"][0],
            lead[-2]["tsmc_revenue_yoy"][0] * 100,
            lead[-2]["trade_date"][0],
        ),
        _series(
            "SIA全球销售yoy",
            sia[-2]["report_month"][0],
            sia[-2]["yoy_growth"][0] * 100,
            sia[-2]["trade_date"][0],
        ),
        _series(
            "设备商毛利率pct",
            gm[-2]["report_quarter"][0],
            gm[-2]["gross_margin_pct"][0],
            gm[-2]["trade_date"][0],
        ),
        _series(
            "渠道库存DOI天数",
            inv[-2]["trade_date"][0].strftime("%Y-%m-%d"),
            inv[-2]["channel_weighted_doi_days"][0],
            inv[-2]["trade_date"][0],
        ),
    ]

    latest = pl.concat(rows).sort("signal")
    prev = pl.concat(prev_rows).sort("signal")

    merged = latest.join(prev, on="signal", how="left", suffix="_prev").with_columns(
        (pl.col("value") - pl.col("value_prev")).alias("delta")
    )

    merged = merged.with_columns(
        pl.when(pl.col("signal") == "渠道库存DOI天数")
        .then(
            pl.when(pl.col("delta") < -0.1)
            .then(pl.lit("改善"))
            .when(pl.col("delta") > 0.1)
            .then(pl.lit("恶化"))
            .otherwise(pl.lit("持平"))
        )
        .otherwise(
            pl.when(pl.col("delta") < -0.1)
            .then(pl.lit("缓解"))
            .when(pl.col("delta") > 0.1)
            .then(pl.lit("加剧"))
            .otherwise(pl.lit("持平"))
        )
        .alias("trend"),
        pl.when(pl.col("signal") == "渠道库存DOI天数")
        .then(pl.when(pl.col("value") <= DOI_HEALTHY_MAX).then(pl.lit("健康")).otherwise(pl.lit("堆积")))
        .otherwise(pl.when(pl.col("value") > 0).then(pl.lit("扩张")).otherwise(pl.lit("收缩")))
        .alias("status"),
    ).select(["signal", "as_of", "value", "value_prev", "delta", "trend", "status"])

    # 全球资本开支见顶预警：云 CapEx 或 SEMI 设备由扩张转加速下滑
    triggers = []
    for sig in ("云CapEx合计yoy", "SEMI设备销售3MMAyoy"):
        row = merged.filter(pl.col("signal") == sig)
        if row.height and row["value"][0] > 0 and row["delta"][0] < -10:
            triggers.append(f"{sig} 增速单期回落 {row['delta'][0]:.1f}pp")
    merged = merged.with_columns(
        pl.lit("；".join(triggers) if triggers else "无").alias("warning")
    )

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.write_parquet(out_path)

    print("=== 通信设备（光模块）全球 6 信号共振（最新 vs 上期）===")
    print(
        merged.select(["signal", "as_of", "value", "value_prev", "trend", "status"])
        .to_pandas()
        .to_string(index=False)
    )
    print(f"\n拐点预警: {merged['warning'][0]}")
    print(f"已写出: {out_path}")
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="构建通信全球资本开支共振小面板")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出路径")
    args = parser.parse_args()
    build(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
