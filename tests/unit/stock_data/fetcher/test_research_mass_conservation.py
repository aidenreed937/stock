"""研报解析器物理质量守恒与同周成对门禁单测 (test_research_mass_conservation.py)。"""

from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser


def test_mass_conservation_normal_output(tmp_path: Path) -> None:
    """验证符合全国物理产能闭环的正常产量保留。"""
    parser = ResearchReportParser(raw_dir=tmp_path)
    # 纯碱全国年产 3800 万吨，开工率 78.31%，理论周产 ~57.2 万吨，报告中为 58.5 万吨 (偏差 ~2.3%)
    text = "本周纯碱行业整体开工率78.31%，周度产量在58.50万吨，厂家总库存184.49万吨。"
    items = parser.extract_metrics_from_text(
        text=text,
        product_name="纯碱",
        publish_date=date(2026, 9, 10),
    )
    assert len(items) == 1
    assert items[0]["operating_rate_pct"] == 78.31
    assert items[0]["weekly_output_w_tons"] == 58.50
    assert items[0]["factory_inventory_w_tons"] == 184.49


def test_mass_conservation_filters_sample_output(tmp_path: Path) -> None:
    """验证局部样本企业产量与开工率偏差 > 35% 时被守恒门禁自动拦截。"""
    parser = ResearchReportParser(raw_dir=tmp_path)
    # 钛白粉全国年产 500 万吨，周产 ~9.6 万吨。若开工率 70%，理论周产 ~6.73 万吨。
    # 研报若混淆局部样本工厂周产为 15.0 万吨 (偏差 122%)，应被守恒门禁剥离
    text = (
        "国内钛白粉企业整体开工率达70.0%，本周部分样本企业实物产量达15.0万吨，企业总库存13.8万吨。"
    )
    items = parser.extract_metrics_from_text(
        text=text,
        product_name="钛白粉",
        publish_date=date(2026, 9, 16),
    )
    assert len(items) == 1
    assert items[0]["operating_rate_pct"] == 70.0
    # 局部样本产量被守恒门禁置为 None，防止污染全国总周产
    assert items[0]["weekly_output_w_tons"] is None
    assert items[0]["factory_inventory_w_tons"] == 13.8


def test_paired_metrics_extraction(tmp_path: Path) -> None:
    """验证同周开工率与企业库存在同一记录中成对归集。"""
    parser = ResearchReportParser(raw_dir=tmp_path)
    text = "PVC电石法开工率维持75.20%，厂家总库存降至108.47万吨。"
    items = parser.extract_metrics_from_text(
        text=text,
        product_name="PVC",
        publish_date=date(2026, 9, 11),
    )
    assert len(items) == 1
    item = items[0]
    assert item["trade_date"] == date(2026, 9, 11)
    assert item["operating_rate_pct"] == 75.20
    assert item["factory_inventory_w_tons"] == 108.47
