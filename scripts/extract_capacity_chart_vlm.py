"""基于多模态视觉大模型 (VLM) 逆向抽取研报图表产能时序数据 CLI 工具。

用法示例:
    # 使用 .env 中配置的商汤 SenseNova / Gemini / OpenAI 逆向提取第 16 页 PVC 产能图:
    uv run python scripts/extract_capacity_chart_vlm.py \
        --pdf data/raw/industry/chemicals/capacity/raw_pdfs/2026-03-19_开源证券_氯碱行业深度报告.pdf \
        --page 16 \
        --product pvc \
        --hint "图15: PVC 产能投放接近尾声"

    # 指定模型与端点 (覆盖 .env):
    uv run python scripts/extract_capacity_chart_vlm.py \
        --pdf data/raw/industry/chemicals/capacity/raw_pdfs/2026-03-19_开源证券_氯碱行业深度报告.pdf \
        --page 16 \
        --product pvc \
        --model sensenova-6.8-flash-lite \
        --api-base https://token.sensenova.cn/v1 \
        --api-key your_sensenova_key
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from stock_data.fetcher.industry.chemicals.parsers.chart_vlm import ChartVlmParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("chart_vlm_cli")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="研报图表多模态数据逆向抽取工具")
    parser.add_argument("--pdf", type=str, required=True, help="研报 PDF 物理路径")
    parser.add_argument("--page", type=int, required=True, help="包含图表的页码 (1-indexed)")
    parser.add_argument(
        "--product", type=str, required=True, help="目标品种代码 (如 pvc, caustic_soda, methanol)"
    )
    parser.add_argument(
        "--metric",
        type=str,
        default="effective_capacity",
        help="目标指标名 (默认 effective_capacity)",
    )
    parser.add_argument("--hint", type=str, default="", help="线索提示 (如 '重点提取图15柱状图')")
    parser.add_argument(
        "--output-csv",
        type=str,
        default="",
        help="输出 CSV 路径 (留空则自动写入 data/raw/industry/chemicals/capacity/<product>_annual_capacity.csv)",
    )
    parser.add_argument("--model", type=str, default="", help="指定模型名称 (覆盖 .env)")
    parser.add_argument("--api-key", type=str, default="", help="指定 API Key (覆盖 .env)")
    parser.add_argument("--api-base", type=str, default="", help="指定 API Base URL (覆盖 .env)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        logger.error(f"指定的研报 PDF 不存在: {pdf_path}")
        return 1

    dest_csv = (
        Path(args.output_csv)
        if args.output_csv
        else Path(f"data/raw/industry/chemicals/capacity/{args.product}_annual_capacity.csv")
    )

    logger.info("================ 研报图表 VLM 逆向解析 ================")
    logger.info(f"研报文件: {pdf_path.name}")
    logger.info(f"目标页码: P.{args.page}")
    logger.info(f"目标品种: {args.product} | 指标: {args.metric}")
    if args.hint:
        logger.info(f"提示线索: {args.hint}")
    logger.info(f"输出目标: {dest_csv}")
    logger.info("======================================================")

    parser = ChartVlmParser(
        model=args.model or None,
        api_key=args.api_key or None,
        api_base=args.api_base or None,
    )
    logger.info(f"生效模型: {parser.model} | API Base: {parser.api_base or '官方默认'}")

    try:
        result = parser.extract_time_series_from_page(
            pdf_path=pdf_path,
            page_number=args.page,
            product=args.product,
            target_metric=args.metric,
            hint_text=args.hint or None,
        )
    except Exception as exc:
        logger.error(f"VLM 解析失败: {exc}")
        return 1

    logger.info("\n======================== 提取结果 ========================")
    logger.info(f"图表原标题: {result.chart_title}")
    logger.info(f"原始单位: {result.unit}")
    logger.info(f"数据来源机构: {result.source_declared}")
    logger.info(f"提取数据点数量: {len(result.data_points)} 个年份")
    for pt in result.data_points:
        logger.info(f"  - {pt.year} 年: {pt.value} {result.unit} (置信度: {pt.confidence})")

    # 落盘标准 CSV
    saved_path = parser.save_to_annual_capacity_csv(
        result=result,
        dest_csv_path=dest_csv,
        report_meta={"title": pdf_path.stem},
    )
    logger.info(f"数据已审计落盘: {saved_path}")
    logger.info("==========================================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
