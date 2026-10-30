"""半导体 GM 前瞻确认腿独立落盘（Stage 2 → 接入第一步）。

把跨公司 GM 前瞻腿 gm_cross（四家设备巨头 AMAT/LRCX/KLAC/ASML 前瞻信号等权合成）
落盘为独立确认腿文件，对齐 `semiconductor_structural_legs.parquet` 结构性腿范式：
- leg_type 独立分组、可空列、**不并入剪刀差**；
- 供下游把"毛利率前瞻"作为与剪刀差正交的前瞻确认腿（实证偏 IC 0.26、控剪刀差后 0.19~0.26、
  组合确认 scissors_confirm_cross 样本外 Sharpe 0.664 > 主信号 0.652）。

数据来源：scripts/semi_gm_multi_leading._load() 的 gm_cross（跨公司合成，release_date 生效，无前视）。
仅含半导体(270100)；其余行业为 null（GM 前瞻腿当前仅半导体有腿，跨行业推广待各行业自建）。

输出：data/curated/mart/semiconductor_gm_confirm_legs.parquet（trade_date, industry_code, gm_cross）

用法：uv run python scripts/semi_gm_confirm_legs.py
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from semi_gm_multi_leading import _load

_GRID = Path("data/curated/mart/global_macro_daily.parquet")
_OUT = Path("data/curated/mart/semiconductor_gm_confirm_legs.parquet")


def main() -> None:
    m = _load().select(["trade_date", "gm_cross"])
    grid = pl.read_parquet(_GRID).select(["trade_date"]).sort("trade_date")
    out = (
        grid.join(m, on="trade_date", how="left")
        .with_columns(pl.lit("270100").alias("industry_code"))
        .select(["trade_date", "industry_code", "gm_cross"])
        .sort("trade_date")
    )
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(_OUT)
    cov = out["gm_cross"].null_count()
    print(f"已写出 {_OUT}（{out.height} 行，gm_cross 非空 {out.height - cov} 行）")
    print(out.head(3))
    print(out.tail(3))


if __name__ == "__main__":
    main()
