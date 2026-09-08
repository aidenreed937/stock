"""fina_mainbz 主营构成校准 company_exposure_map.csv 的 exposure。

数据：data/curated/tushare/market=CN/fina_mainbz（type=P 产品构成，年报期最可靠）
方法：
1. 取指定期（默认最新年报 2025-12-31）type=P 数据；
2. 剔除兜底行（产品/主营业务/其他业务/合计/分部抵消等非产品细分）；
3. 同值去重（"X产品"与"X"重复披露只取一行）；
4. 按 LLM 语义别名表 bz_item_alias_map.csv 精确匹配 bz_item → 命中收入 /
   全部非兜底收入 = exposure（alias 与 ambiguous 均计命中，置信度供人工复核）；
5. 未匹配（公司披露口径不可拆分，或别名表缺失）→ 保留旧值并标记 status=manual。

别名表说明：config/data/customs/bz_item_alias_map.csv 由 LLM 批量把 fina_mainbz
的 bz_item 语义归一化到 product_key（1395 条，2026-06-30 期），产物显式可人工
修订；"电气设备系列"（金盘科技等）已标注为含 transformer。

用法：
  uv run python scripts/calibrate_company_exposure.py --period 2026-06-30 --apply
  （不带 --apply 时为 dry-run，只打印差异）
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

GENERIC_ITEMS = {
    "产品",
    "主营业务",
    "其他",
    "其他业务",
    "其他主营业务",
    "合计特别调整",
    "合计",
    "分部抵消",
    "分部间抵销",
    "主营业务收入",
    "营业收入",
    "服务收入及其他",
    "研发及检测",
    "研发及检测板块",
    "租赁业务",
    "贸易收入",
}

DEFAULT_MAINBZ_DIR = Path("data/curated/tushare/market=CN/fina_mainbz")
DEFAULT_ALIAS_MAP = Path("config/data/customs/bz_item_alias_map.csv")
DEFAULT_MAP = Path("config/data/customs/company_exposure_map.csv")


def load_mainbz(mainbz_dir: Path, period: str) -> pd.DataFrame:
    frames = [pd.read_parquet(f) for f in mainbz_dir.glob("**/*.parquet")]
    df = pd.concat(frames, ignore_index=True).drop_duplicates()
    df["end_date"] = pd.to_datetime(df["end_date"])
    sub = df[(df["bz_code"] == "P") & (df["end_date"] <= period)]
    if sub.empty:
        raise ValueError(f"fina_mainbz 无 {period} 前数据")
    # 只取每公司最近一期（docstring 口径"取指定期"，避免历史期累计稀释占比）
    latest = sub.groupby("symbol")["end_date"].transform("max")
    return sub[sub["end_date"] == latest]


def load_alias_map(path: Path) -> dict[str, tuple[str, str]]:
    """读 LLM 别名表 → {bz_item: (product_key, match_type)}（只取有映射的行）。"""
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    missing = {"bz_item", "product_key", "match_type"} - set(df.columns)
    if missing:
        raise ValueError(f"别名表 {path} 缺列: {sorted(missing)}")
    out: dict[str, tuple[str, str]] = {}
    for _, r in df.iterrows():
        pk = str(r["product_key"]).strip()
        if pk and pk.lower() != "nan":
            out[str(r["bz_item"])] = (pk, str(r["match_type"]).strip())
    return out


def calc_exposure(
    sub: pd.DataFrame,
    symbol: str,
    alias_map: dict[str, tuple[str, str]],
    product_key: str,
) -> tuple[float | None, str]:
    rows = sub[sub["symbol"] == symbol]
    if rows.empty:
        return None, "no_data"
    real = rows[~rows["bz_item"].isin(GENERIC_ITEMS)]
    real = real.drop_duplicates(subset=["bz_sales"], keep="first")
    if real.empty:
        return None, "only_generic"
    total = real["bz_sales"].sum()
    if total <= 0:
        return None, "zero_total"
    hit = real[
        real["bz_item"].map(lambda item: alias_map.get(str(item), (None, None))[0] == product_key)
    ]
    matched = hit["bz_sales"].sum()
    if matched <= 0:
        return None, "no_match"
    ratio = min(matched / total, 1.0)
    detail = "|".join(
        f"{r['bz_item']}({r['bz_sales'] / 1e8:.0f}亿,"
        f"{alias_map.get(str(r['bz_item']), ('', ''))[1]})"
        for _, r in hit.iterrows()
    )
    return ratio, detail


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--period",
        default="2026-06-30",
        help="校准报告期（默认 2026-06-30，与 bz_item_alias_map.csv 语境一致；"
        "年报 2025-12-31 披露颗粒度更细但金盘科技等无当期产品构成）",
    )
    parser.add_argument(
        "--mainbz-dir", type=Path, default=DEFAULT_MAINBZ_DIR, help="fina_mainbz 目录"
    )
    parser.add_argument(
        "--alias-map", type=Path, default=DEFAULT_ALIAS_MAP, help="LLM 语义别名表 CSV"
    )
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP, help="company map CSV")
    parser.add_argument("--apply", action="store_true", help="写回 CSV（默认 dry-run）")
    args = parser.parse_args()

    sub = load_mainbz(args.mainbz_dir, args.period)
    alias_map = load_alias_map(args.alias_map)
    map_df = pd.read_csv(args.map, dtype=str, encoding="utf-8-sig")

    updated = 0
    rows = []
    for _, row in map_df.iterrows():
        ratio, detail = calc_exposure(sub, row["stock_code"], alias_map, row["product_key"])
        new_row = dict(row)
        if ratio is not None:
            old = float(row["exposure"])
            new_row["exposure"] = f"{ratio:.2f}"
            new_row["evidence"] = f"fina_mainbz {args.period} 主营构成(LLM别名表): {detail}"
            new_row["status"] = "verified"
            updated += 1
            if abs(ratio - old) > 0.05:
                print(
                    f"[{'APPLY' if args.apply else 'DRY '}] {row['product_key']:<22} "
                    f"{row['company_name']:<8} 旧={old:.2f} → 新={ratio:.2f} ({detail})"
                )
        else:
            print(
                f"[SKIP] {row['product_key']:<22} {row['company_name']:<8} "
                f"旧={float(row['exposure']):.2f} 未校准: {detail}"
            )
        rows.append(new_row)

    if args.apply:
        out = pd.DataFrame(rows)
        out.to_csv(args.map, index=False, encoding="utf-8-sig")
        print(f"\n已写回 {args.map}: {updated} 条校准为 verified")
    else:
        print(f"\n(dry-run) 可校准 {updated} 条；加 --apply 写回")


if __name__ == "__main__":
    main()
