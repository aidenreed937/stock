from datetime import date
from pathlib import Path

import polars as pl

from stock_reporting.engine.renderer import ReportRenderer
from stock_reporting.interpretation.macro_risk.logic import evaluate_macro_risk


def render_macro_risk_report(df: pl.DataFrame, target_date: date | None = None) -> str:
    """生成宏观风控日报 Markdown。"""
    row_df = df.filter(pl.col("trade_date") == target_date) if target_date else df.tail(1)

    if row_df.is_empty():
        return f"未找到日期 {target_date} 的风险数据。"

    row_dict = row_df.to_dicts()[0]
    eval_result = evaluate_macro_risk(row_dict)

    # 渲染模板
    renderer = ReportRenderer()

    # 确保能找到刚创建的模板（如果模板路径没配置好，直接走字符串渲染）
    template_path = Path(__file__).parent / "macro_risk.md.j2"
    if not template_path.exists():
        # Fallback to loading it manually
        return "模板文件未找到: " + str(template_path)

    template_content = template_path.read_text(encoding="utf-8")

    trade_date_str = str(row_dict["trade_date"])[:10]
    context = {"trade_date": trade_date_str, "eval_result": eval_result}

    return renderer.render_string(template_content, context)
