"""每日盘后全景量化复盘流水线自动化脚本。

基于 stock_reporting.engine.renderer.ReportRenderer 模板引擎渲染标准复盘研报。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

from stock_analytics.pipelines.watchlist_scanner.pipeline import run_watchlist_scanner
from stock_core.utils.logger import logger
from stock_reporting.engine.renderer import ReportRenderer


def _load_temperature_data() -> tuple[float | None, str | None, dict[str, float]]:
    score_path = Path("data/analytics/market_temperature/latest/scores.json")
    if not score_path.exists():
        return None, None, {}
    try:
        with open(score_path, encoding="utf-8") as f:
            data = json.load(f)
        composite = data.get("composite", {})
        temp = composite.get("temperature")
        raw_dims = data.get("dimensions", [])
        dims: dict[str, float] = {}
        if isinstance(raw_dims, list):
            for d_item in raw_dims:
                name = d_item.get("name") or d_item.get("dimension_id", "")
                t_val = d_item.get("temperature")
                if name and t_val is not None:
                    dims[str(name)] = float(t_val)
        elif isinstance(raw_dims, dict):
            for k, v in raw_dims.items():
                if isinstance(v, dict) and v.get("temperature") is not None:
                    dims[str(k)] = float(v["temperature"])

        band = "中性平衡 (震荡分化区)"
        if temp is not None:
            t = float(temp)
            if t < 25.0:
                band = "极度冰点 (逆向筑底区)"
            elif t < 45.0:
                band = "冰点偏冷 (谨慎蓄势区)"
            elif t < 55.0:
                band = "中性平衡 (震荡分化区)"
            elif t < 75.0:
                band = "偏热活跃 (右侧顺势区)"
            else:
                band = "极度过热 (防范冲高回落)"
        return (float(temp) if temp is not None else None, band, dims)
    except Exception as exc:
        logger.warning(f"读取市场温度失败: {exc}")
        return None, None, {}


def _load_industry_structure_data() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    ind_path = Path("data/analytics/industry_structure/latest/scores.json")
    if not ind_path.exists():
        return [], []
    try:
        with open(ind_path, encoding="utf-8") as f:
            data = json.load(f)
        top_struct = [
            {
                "name": str(item.get("industry_name", "")),
                "score": f"{item.get('structure_score', 0.0):.1f}",
                "tags": str(item.get("tags", "")),
            }
            for item in data.get("top_structure", [])[:5]
        ]
        low_val = [
            {
                "name": str(item.get("industry_name", "")),
                "score": f"{item.get('structure_score', 0.0):.1f}",
                "tags": str(item.get("tags", "")),
            }
            for item in data.get("undervalued_improving", [])[:5]
        ]
        return top_struct, low_val
    except Exception as exc:
        logger.warning(f"读取行业结构失败: {exc}")
        return [], []


def generate_daily_review(
    target_date: date | None = None,
    output_dir: Path | str | None = None,
) -> Path:
    """运行每日盘后全景量化复盘流水线并基于 ReportRenderer 模板渲染研报。"""
    logger.info("开始执行每日盘后全景量化复盘流水线 (基于 stock_reporting 模板)...")

    # 1. 扫描自选池
    scan_res = run_watchlist_scanner(target_date=target_date)
    as_of = scan_res.as_of_date

    # 2. 读取大盘温度与行业结构
    temp_score, temp_band, dims = _load_temperature_data()
    top_ind, low_ind = _load_industry_structure_data()

    dim_summary = " ｜ ".join([f"{k}: {v:.1f}分" for k, v in dims.items()]) if dims else ""

    pos_advice = "50% - 60% (中性平衡，重结构轻指数)"
    if temp_score is not None:
        if temp_score < 30.0:
            pos_advice = "30% - 40% (冰点区域，保持耐心，分批逢低吸纳)"
        elif temp_score > 70.0:
            pos_advice = "30% - 50% (偏热过热，注意止盈，控制回撤)"

    items_ctx: list[dict[str, Any]] = []
    for item in scan_res.items:
        pe_str = (
            f"{item.pe_ttm:.1f} ({item.pe_percentile_5y:.1f}%)"
            if item.pe_ttm is not None and item.pe_percentile_5y is not None
            else f"{item.pe_ttm:.1f}"
            if item.pe_ttm is not None
            else "--"
        )
        pb_str = f"{item.pb:.2f}" if item.pb is not None else "--"
        dv_str = (
            f"{item.dv_ttm:.2f}% ({item.dividend_spread_10y:+.2f}%)"
            if item.dv_ttm is not None and item.dividend_spread_10y is not None
            else f"{item.dv_ttm:.2f}%"
            if item.dv_ttm is not None
            else "--"
        )
        roe_str = f"{item.roe:.1f}%" if item.roe is not None else "--"
        tag_str = "、".join(item.tags) if item.tags else "常规"

        items_ctx.append(
            {
                "symbol": item.symbol,
                "name": item.name,
                "industry": item.industry,
                "close": item.close,
                "pct_chg": item.pct_chg or 0.0,
                "pe_display": pe_str,
                "pb_display": pb_str,
                "dividend_display": dv_str,
                "roe_display": roe_str,
                "trend_status": item.trend_description.split(" ")[0],
                "tag_display": tag_str,
            }
        )

    context = {
        "as_of_date": as_of,
        "temperature_score": f"{temp_score:.2f}" if temp_score is not None else None,
        "temperature_band": temp_band,
        "dimension_items": dims,
        "dimension_summary": dim_summary,
        "position_advice": pos_advice,
        "top_industries": top_ind,
        "low_val_industries": low_ind,
        "total_scanned": scan_res.total_scanned,
        "golden_pit_count": len(scan_res.golden_pit_candidates),
        "high_dividend_count": len(scan_res.high_dividend_candidates),
        "value_trap_count": len(scan_res.value_trap_candidates),
        "items": items_ctx,
    }

    # 3. 基于 stock_reporting 模板渲染
    renderer = ReportRenderer.get_instance()
    report_content = renderer.render("review/daily_market_review.md.j2", context)

    # 4. 落盘
    out_dir = Path(output_dir or "output/reports/daily")
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / f"{as_of}_全景量化复盘报告.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report_content)

    logger.info(f"每日全景量化复盘研报 (基于模板) 已生成并落盘至: {report_file}")
    return report_file


def main() -> None:
    parser = argparse.ArgumentParser(
        description="每日盘后全景量化复盘自动化脚本 (Jinja2 模板驱动)",
    )
    parser.add_argument(
        "--date",
        "-d",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="复盘基准日期 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="研报落盘目录 (默认 output/reports/daily/)",
    )
    args = parser.parse_args()

    try:
        report_path = generate_daily_review(
            target_date=args.date,
            output_dir=args.output_dir,
        )
        sys.stdout.write(f"复盘研报生成成功: {report_path}\n")
    except Exception as exc:
        logger.error(f"生成每日复盘失败: {exc}")
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
