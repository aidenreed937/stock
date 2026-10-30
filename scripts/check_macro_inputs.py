"""宏观产物前置数据闸门：检查行情/复权/资金流是否已对齐到同一交易日。

背景（2026-10-27 事故）：`make macro-artifacts` 不负责拉数。当行情已到 T 日而复权因子
`fund_adj` 或指数 `index_daily_bar` 仍停在 T-1 时，ETF 净值会回退未复权价，产生按仓位
比例缩放的**假暴跌**（实测 v5_etf 单日 -22%，实际 +0.60%）。本脚本在产物生成前拦截。

分级：
- critical（会污染价格/净值）：``index_daily_bar``、``fund_daily``、``fund_adj``
- advisory（只会让维度成分缺失）：``moneyflow``、``opt_daily``

用法::

    uv run python scripts/check_macro_inputs.py            # critical 缺失即失败
    uv run python scripts/check_macro_inputs.py --soft     # 全部降级为告警
    uv run python scripts/check_macro_inputs.py --anchor 2026-10-27
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from stock_data.catalog import DataCatalog
from stock_data.core.runtime import DataRuntimeContext

CRITICAL_DATASETS: tuple[str, ...] = ("index_daily_bar", "fund_daily", "fund_adj")
ADVISORY_DATASETS: tuple[str, ...] = ("moneyflow", "opt_daily")


def _latest(cat: DataCatalog, name: str) -> date | None:
    try:
        value = cat.get_latest_trade_date(name)
    except Exception:
        return None
    return value if isinstance(value, date) else None


def main() -> None:
    parser = argparse.ArgumentParser(description="宏观产物前置数据闸门")
    parser.add_argument("--anchor", help="基准交易日 YYYY-MM-DD，默认取 stock_daily_bar 最新")
    parser.add_argument("--soft", action="store_true", help="全部降级为告警（不阻断）")
    args = parser.parse_args()

    rt = DataRuntimeContext.from_root("data")
    cat = DataCatalog(data_source="tushare", runtime=rt)

    anchor = date.fromisoformat(args.anchor) if args.anchor else _latest(cat, "stock_daily_bar")
    if anchor is None:
        print("[FAIL] 无法确定基准交易日：stock_daily_bar 无可用数据")
        sys.exit(1)

    print(f"[check] 基准交易日 = {anchor}（数据源 tushare）")
    failures: list[str] = []
    warnings: list[str] = []

    for name, level in (
        *((d, "critical") for d in CRITICAL_DATASETS),
        *((d, "advisory") for d in ADVISORY_DATASETS),
    ):
        latest = _latest(cat, name)
        if latest is None:
            msg = f"{name}: 无数据"
        elif latest >= anchor:
            print(f"[ ok ] {name}: {latest}")
            continue
        else:
            msg = f"{name}: 最新 {latest} < 基准 {anchor}（滞后，{(anchor - latest).days} 自然日）"
        if level == "critical":
            failures.append(msg)
            print(f"[FAIL] {msg}")
        else:
            warnings.append(msg)
            print(f"[WARN] {msg}")

    if warnings:
        print(
            "\n[WARN] advisory 数据滞后不阻断产物，但会让期权/资金维度成分缺失，"
            "建议补数后重跑：make sync SOURCE=tushare ENDPOINTS=" + ",".join(ADVISORY_DATASETS)
        )

    if failures:
        hint = ",".join(CRITICAL_DATASETS)
        print(
            "\n[FAIL] critical 数据未对齐，产物会用错价（复权因子缺失会回退原始价，产生假暴跌）。\n"
            f"       先补数再重跑：make sync SOURCE=tushare ENDPOINTS={hint}"
        )
        if not args.soft:
            sys.exit(1)
        print("[soft] 已按 --soft 放行，请自行承担口径风险")


if __name__ == "__main__":
    main()
