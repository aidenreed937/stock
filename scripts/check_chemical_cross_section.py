"""只读校验 chemical_cross_section_mart 及其源头数据（不写盘）。

用法（仓库根目录）:
    uv run python scripts/check_chemical_cross_section.py

输出:
    1. Mart parquet 与 latest CSV 一致性
    2. Mart Schema 与代码 CROSS_SECTION_SCHEMA 一致性
    3. 8 大品种 x 7 类源头覆盖矩阵（成本曲线/价差/现货/周度开工库存/基差仓单/海关出口/业绩弹性）
    4. 内存重建 Mart 与落盘 parquet 逐字段对比
    5. 打分引擎按落盘行输入重算（cycle_phase/score/stance）复核
    6. 数据缺失与时效风险摘要
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import polars as pl

from stock_analytics.marts.chemical_cross_section_mart import (
    CHEMICAL_CROSS_SECTION_MART_CSV,
    CHEMICAL_CROSS_SECTION_MART_FILE,
    COMMODITY_SPECS,
    CROSS_SECTION_SCHEMA,
    ChemicalCrossSectionMart,
)

ROOT = Path(__file__).resolve().parent.parent
MART_DIR = ROOT / "data" / "curated" / "mart"
CURATED_DIR = ROOT / "data" / "curated"

NUMERIC_COLS = [
    "spot_price_cny",
    "marginal_cash_cost_cny",
    "cash_cost_coverage_pct",
    "spread_margin_cny",
    "operating_rate_pct",
    "operating_rate_pctl",
    "factory_inventory_w_tons",
    "inventory_pctl",
    "warehouse_receipts",
    "basis_cny",
    "basis_rate_pct",
    "warehouse_receipts_w_tons",
    "receipts_pctl_1y",
    "export_volume_yoy_pct",
    "export_asp_yoy_pct",
    "top_eps_delta_per_100cny",
    "composite_score",
    "cross_section_rank",
    "data_confidence_pct",
]

STRING_COLS = [
    "as_of_date",
    "commodity_code",
    "commodity_name",
    "submodule_dir",
    "category_archetype",
    "futures_symbol",
    "cost_curve_regime",
    "margin_regime",
    "basis_term_structure",
    "receipts_acceleration_status",
    "composite_micro_regime",
    "inventory_stage",
    "export_regime",
    "alpha_leader_stock",
    "alpha_leader_name",
    "beta_elastic_stock",
    "beta_elastic_name",
    "top_elastic_stock",
    "top_elastic_stock_name",
    "cycle_phase",
    "investment_stance",
]

BOOL_COLS = ["is_cash_cost_breached", "right_side_basis_gate_pass"]


def to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def num_eq(a: object, b: object, tol: float = 1e-6) -> bool:
    fa, fb = to_float(a), to_float(b)
    if fa is None and fb is None:
        return True
    if fa is None or fb is None:
        return False
    return abs(fa - fb) <= tol * max(1.0, abs(fa), abs(fb))


def str_eq(a: object, b: object) -> bool:
    sa = "" if a is None else str(a).strip()
    sb = "" if b is None else str(b).strip()
    return sa == sb


def load_latest_rows(
    df: pl.DataFrame | None, key_col: str, sort_col: str
) -> dict[str, dict[str, Any]]:
    """按品种返回每个 key 的最新（trade_date 最大）一行。"""
    result: dict[str, dict[str, Any]] = {}
    if df is None or df.is_empty() or key_col not in df.columns:
        return result
    if sort_col not in df.columns:
        sort_col = df.columns[0]
    for key in df[key_col].unique().to_list():
        if key is None:
            continue
        sub = df.filter(pl.col(key_col) == key).sort(sort_col)
        result[str(key).upper()] = sub.row(-1, named=True)
    return result


def main() -> int:
    parquet_path = MART_DIR / CHEMICAL_CROSS_SECTION_MART_FILE
    csv_path = MART_DIR / CHEMICAL_CROSS_SECTION_MART_CSV

    print("=" * 120)
    print("1. Mart 文件与 CSV 快照一致性")
    print("=" * 120)
    if not parquet_path.exists() or not csv_path.exists():
        print(f"FAIL: 缺少文件 {parquet_path.exists()=} {csv_path.exists()=}")
        return 1

    mart = pl.read_parquet(parquet_path)
    csv = pl.read_csv(csv_path)
    print(f"parquet: {parquet_path}  rows={len(mart)}")
    print(f"csv    : {csv_path}  rows={len(csv)}")
    print(f"parquet columns={len(mart.columns)}, csv columns={len(csv.columns)}")

    if len(mart) != len(csv):
        print("FAIL: parquet 与 csv 行数不一致")
    if set(mart.columns) != set(csv.columns):
        print("FAIL: parquet 与 csv 列集合不一致")

    # 逐行逐字段比较（按 commodity_code 对齐）
    mart_sorted = mart.sort("commodity_code")
    csv_sorted = csv.sort("commodity_code")
    mismatches: list[str] = []
    for mr, cr in zip(mart_sorted.to_dicts(), csv_sorted.to_dicts()):
        code = mr["commodity_code"]
        for col in mart.columns:
            mv, cv = mr.get(col), cr.get(col)
            ok = num_eq(mv, cv) if col in NUMERIC_COLS else str_eq(mv, cv)
            if not ok:
                mismatches.append(f"{code}.{col}: parquet={mv!r} csv={cv!r}")
    if mismatches:
        print(f"FAIL: parquet vs csv 不一致 {len(mismatches)} 处，前 20 处：")
        for m in mismatches[:20]:
            print("  -", m)
    else:
        print("PASS: parquet 与 csv 完全一致（数值容差 1e-6）")

    print()
    print("=" * 120)
    print("2. Schema 与代码契约")
    print("=" * 120)
    schema_diff = set(mart.columns) ^ set(CROSS_SECTION_SCHEMA.keys())
    if schema_diff:
        print(f"FAIL: 列集合与 CROSS_SECTION_SCHEMA 不一致: {sorted(schema_diff)}")
    else:
        print(f"PASS: 列集合与代码 schema 一致（{len(mart.columns)} 列）")
    for col, dtype in CROSS_SECTION_SCHEMA.items():
        if col not in mart.columns:
            continue
        if mart[col].dtype != dtype:
            print(f"  WARN: {col} dtype={mart[col].dtype} 期望 {dtype}")

    print()
    print("=" * 120)
    print(f"3. {len(mart)} 大品种 x 7 类源头覆盖矩阵（最新行）")
    print("=" * 120)

    cost = (
        pl.read_parquet(CURATED_DIR / "mart" / "chemical_cost_curves.parquet")
        if (CURATED_DIR / "mart" / "chemical_cost_curves.parquet").exists()
        else None
    )
    spreads = (
        pl.read_parquet(CURATED_DIR / "industry" / "chemical_spreads.parquet")
        if (CURATED_DIR / "industry" / "chemical_spreads.parquet").exists()
        else None
    )
    spot = (
        pl.read_parquet(CURATED_DIR / "industry" / "chemical_spot_price.parquet")
        if (CURATED_DIR / "industry" / "chemical_spot_price.parquet").exists()
        else None
    )
    survey = (
        pl.read_parquet(CURATED_DIR / "industry" / "chemical_weekly_survey.parquet")
        if (CURATED_DIR / "industry" / "chemical_weekly_survey.parquet").exists()
        else None
    )
    basis = (
        pl.read_parquet(MART_DIR / "chemical_basis_inventory_mart.parquet")
        if (MART_DIR / "chemical_basis_inventory_mart.parquet").exists()
        else None
    )
    customs = (
        pl.read_parquet(MART_DIR / "chemical_customs_export.parquet")
        if (MART_DIR / "chemical_customs_export.parquet").exists()
        else None
    )
    elasticity = (
        pl.read_parquet(MART_DIR / "chemical_elasticity_mart.parquet")
        if (MART_DIR / "chemical_elasticity_mart.parquet").exists()
        else None
    )

    cost_latest = load_latest_rows(cost, "commodity_code", "trade_date")
    spreads_latest = load_latest_rows(
        spreads,
        "symbol" if spreads is not None and "symbol" in spreads.columns else "commodity_code",
        "trade_date",
    )
    spot_latest = load_latest_rows(spot, "symbol", "trade_date")
    survey_latest = load_latest_rows(
        survey,
        "symbol" if survey is not None and "symbol" in survey.columns else "product_name",
        "trade_date",
    )
    basis_latest = load_latest_rows(basis, "commodity_code", "trade_date")
    customs_latest = load_latest_rows(
        customs,
        "commodity_code",
        "report_month"
        if customs is not None and "report_month" in customs.columns
        else "trade_date",
    )
    elasticity_top: dict[str, dict[str, Any]] = {}
    if elasticity is not None and not elasticity.is_empty():
        for code in elasticity["commodity_code"].unique().to_list():
            if code is None:
                continue
            sub = elasticity.filter(pl.col("commodity_code") == code).sort(
                "eps_delta_per_100cny", descending=True
            )
            if not sub.is_empty():
                elasticity_top[str(code).upper()] = sub.row(0, named=True)

    header = (
        f"{'code':<6}{'成本曲线':<24}{'价差':<22}{'现货':<16}{'周度开工':<26}"
        f"{'基差仓单':<30}{'海关出口':<24}{'弹性top'}"
    )
    print(header)
    print("-" * len(header))

    for spec in COMMODITY_SPECS:
        code = spec["code"]
        key = code.upper()
        cc = cost_latest.get(key)
        sp = spreads_latest.get(key)
        st = spot_latest.get(key)
        sv = survey_latest.get(key)
        bi = basis_latest.get(key)
        cu = customs_latest.get(key)
        el = elasticity_top.get(key)
        cc_s = (
            f"{cc['trade_date']} p={cc.get('spot_price_cny')} cov={cc.get('cash_cost_coverage_pct')}"
            if cc
            else "-"
        )
        sp_s = (
            f"{sp['trade_date']} m={sp.get('spread_margin_cny')} {sp.get('margin_regime')}"
            if sp
            else "-"
        )
        st_s = f"{st['trade_date']} p={st.get('spot_price_cny')}" if st else "-"
        sv_s = (
            f"{sv['trade_date']} op={sv.get('operating_rate_pct')} inv={sv.get('factory_inventory_w_tons')}"
            if sv
            else "-"
        )
        bi_s = (
            f"{bi['trade_date']} basis={bi.get('basis_rate_pct')} w={bi.get('warehouse_receipts_w_tons')}"
            if bi
            else "-"
        )
        cu_s = (
            f"{cu.get('report_month')} vol={cu.get('export_volume_yoy_pct')} asp={cu.get('export_asp_yoy_pct')} {cu.get('export_regime')}"
            if cu
            else "-"
        )
        el_s = (
            f"{el.get('symbol')} {el.get('company_name')} e={el.get('eps_delta_per_100cny')}"
            if el
            else "-"
        )
        print(f"{code:<6}{cc_s:<24}{sp_s:<22}{st_s:<16}{sv_s:<26}{bi_s:<30}{cu_s:<24}{el_s}")

    print()
    print("=" * 120)
    print("4. 内存重建 Mart 与落盘 parquet 逐字段对比")
    print("=" * 120)
    as_of = mart["as_of_date"][0]
    engine = ChemicalCrossSectionMart(as_of_date=as_of)
    rebuilt = engine.build_cross_section_frame()
    print(f"重建 as_of_date={as_of}, 行数={len(rebuilt)}")
    if len(rebuilt) != len(mart):
        print(f"FAIL: 重建行数 {len(rebuilt)} != 落盘行数 {len(mart)}")

    r_sorted = rebuilt.sort("commodity_code")
    m_sorted = mart.sort("commodity_code")
    diff_count = 0
    shown = 0
    for mr, rr in zip(m_sorted.to_dicts(), r_sorted.to_dicts()):
        code = mr["commodity_code"]
        for col in mart.columns:
            mv, rv = mr.get(col), rr.get(col)
            ok = num_eq(mv, rv) if col in NUMERIC_COLS else str_eq(mv, rv)
            if not ok:
                diff_count += 1
                if shown < 25:
                    print(f"  DIFF {code}.{col}: 落盘={mv!r} 重建={rv!r}")
                    shown += 1
    if diff_count == 0:
        print("PASS: 内存重建与落盘 parquet 完全一致")
    else:
        print(f"FAIL: 内存重建与落盘不一致 {diff_count} 处（仅列前 {shown} 处）")

    print()
    print("=" * 120)
    print("5. 打分引擎按落盘行输入重算（cycle_phase/composite_score/investment_stance）")
    print("=" * 120)
    score_bad = 0
    for row in mart_sorted.to_dicts():
        code = row["commodity_code"]
        phase, score, stance, _ = engine._evaluate_cross_section(
            code=code,
            name=row["commodity_name"],
            category=row["category_archetype"],
            spot_price=to_float(row.get("spot_price_cny")) or 0.0,
            marginal_cash_cost=to_float(row.get("marginal_cash_cost_cny")),
            cash_coverage=to_float(row.get("cash_cost_coverage_pct")),
            cost_regime=str(row.get("cost_curve_regime") or "unknown"),
            is_cash_breached=bool(row.get("is_cash_cost_breached")),
            margin_regime=str(row.get("margin_regime") or "unknown"),
            inv_stage=str(row.get("inventory_stage") or "unknown"),
            export_regime=str(row.get("export_regime") or "unknown"),
            export_vol_yoy=to_float(row.get("export_volume_yoy_pct")),
            alpha_leader=str(
                row.get("alpha_leader_name") or row.get("top_elastic_stock_name") or code
            ),
            basis_term_structure=str(row.get("basis_term_structure") or "unknown"),
            basis_rate_pct=to_float(row.get("basis_rate_pct")),
            receipts_accel_status=str(row.get("receipts_acceleration_status") or "unknown"),
            receipts_pctl=to_float(row.get("receipts_pctl_1y")),
            composite_micro_regime=str(row.get("composite_micro_regime") or "unknown"),
            operating_rate=to_float(row.get("operating_rate_pct")),
            factory_inv=to_float(row.get("factory_inventory_w_tons")),
            operating_rate_asof_date=row.get("operating_rate_asof_date"),
            inventory_asof_date=row.get("inventory_asof_date"),
            as_of_date=as_of,
        )
        ok_phase = str_eq(phase, row.get("cycle_phase"))
        ok_score = num_eq(score, row.get("composite_score"))
        ok_stance = str_eq(stance, row.get("investment_stance"))
        flag = "PASS" if (ok_phase and ok_score and ok_stance) else "FAIL"
        if flag == "FAIL":
            score_bad += 1
        print(
            f"  {code:<5} {flag}  phase={phase} score={score:.1f} stance={stance} | "
            f"落盘 phase={row['cycle_phase']} score={row['composite_score']} stance={row['investment_stance']}"
        )
    if score_bad:
        print(f"FAIL: {score_bad} 行打分重算与落盘不一致")
    else:
        print(f"PASS: {len(mart_sorted)} 行打分重算与落盘一致（说明打分规则本身自洽）")

    print()
    print("=" * 120)
    print("6. 缺失与时效风险摘要（按品种）")
    print("=" * 120)
    for row in mart_sorted.to_dicts():
        code = row["commodity_code"]
        missing = []
        if not (to_float(row.get("spot_price_cny")) or 0) > 0:
            missing.append("现货价=0/缺失")
        if row.get("marginal_cash_cost_cny") is None:
            missing.append("无边际现金成本")
        if row.get("cash_cost_coverage_pct") is None:
            missing.append("无成本覆盖分位")
        if row.get("operating_rate_pct") is None:
            missing.append("无周度开工率")
        if row.get("factory_inventory_w_tons") is None:
            missing.append("无企业库存")
        if row.get("basis_rate_pct") is None:
            missing.append("无期现基差")
        if row.get("warehouse_receipts_w_tons") is None:
            missing.append("无仓单")
        if row.get("export_volume_yoy_pct") is None:
            missing.append("无出口数据")
        rationale = str(row.get("key_rationale") or "")
        if "数据滞后提示" in rationale:
            missing.append("存在滞后提示")
        tag = "；".join(missing) if missing else "核心字段齐备"
        print(
            f"  {code:<5} score={row['composite_score']:<5} stance={row['investment_stance']:<18} {tag}"
        )

    print()
    print("提示：本脚本只读，不修改任何数据文件。")
    return 0 if (not mismatches and diff_count == 0 and score_bad == 0) else 2


if __name__ == "__main__":
    raise SystemExit(main())
