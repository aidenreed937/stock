from datetime import date
from pathlib import Path

from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser


def test_extract_metrics_soda_ash(tmp_path: Path) -> None:
    """验证纯碱期货研报真实样本指标提取 (弘业期货与大越期货)。"""
    text_hy = """
    供给方面：本周纯碱产量回升，整体高位震荡。截至8月20日当周，纯碱综合产能利用率78.31%（周环比+2.16个百分点），纯碱产量74.58万吨（周环比+2.05万吨，+2.83%）。
    库存：本周截至8月20日，纯碱厂家总库存184.49万吨，较上周四下降1.18万吨（-0.64%），结束了此前连续八周的累库态势。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    res_hy = parser.extract_metrics_from_text(
        text=text_hy,
        product_name="纯碱",
        publish_date=date(2026, 8, 21),
        source_name="弘业期货_Research",
    )
    assert len(res_hy) >= 1
    primary = res_hy[0]
    assert primary["symbol"] == "SA"
    assert primary["product_name"] == "纯碱"
    assert primary["operating_rate_pct"] == 78.31
    assert primary["weekly_output_w_tons"] == 74.58
    assert primary["factory_inventory_w_tons"] == 184.49
    assert primary["report_date"] == date(2026, 8, 20)

    text_dy = """
    纯碱周度行业开工率78.73%。
    纯碱周度产量74.98万吨，其中重质纯碱40.96万吨，产量历史高位。
    全国纯碱厂内库存175.44万吨，较前一周上涨0.42%。
    """
    res_dy = parser.extract_metrics_from_text(
        text=text_dy,
        product_name="SA",
        publish_date=date(2026, 7, 17),
        source_name="大越期货_Research",
    )
    assert len(res_dy) >= 1
    p_dy = res_dy[0]
    assert p_dy["operating_rate_pct"] == 78.73
    assert p_dy["weekly_output_w_tons"] == 74.98
    assert p_dy["factory_inventory_w_tons"] == 175.44


def test_extract_metrics_tio2(tmp_path: Path) -> None:
    """验证钛白粉近端开工率、周产量与库存提取。"""
    text_news = """
    对于本轮挺价逻辑，隆众资讯钛白粉分析师向记者分析称，多重利好构筑价格支撑。
    原料、油价年内持续高位运行，企业出厂价贴近成本红线；
    行业整体开工率不足70%，叠加全球60万吨落后产能永久退出，有效供给边际收缩；
    金九旺季备货启动带动库存快速去化，企业挺价意愿升温。
    """
    parser = ResearchReportParser(raw_dir=tmp_path)
    res_news = parser.extract_metrics_from_text(
        text=text_news,
        product_name="钛白粉",
        publish_date=date(2026, 9, 16),
        source_name="隆众卓创分析_Research",
    )
    assert len(res_news) >= 1
    assert res_news[0]["symbol"] == "TIO2"
    assert res_news[0]["product_name"] == "钛白粉"
    assert res_news[0]["operating_rate_pct"] == 70.0

    text_broker = """
    基础化工行业周报：钛白粉企业挺价意愿增强。
    截至9月10日，国内钛企样本整体开工负荷72.50%，本期钛白粉周度产量8.60万吨，厂家总库存为13.80万吨。
    下游涂料与塑料制品需求逐步进入旺季备货阶段。
    """
    res_broker = parser.extract_metrics_from_text(
        text=text_broker,
        product_name="TiO2",
        publish_date=date(2026, 9, 10),
        source_name="东方证券_Research",
    )
    assert len(res_broker) >= 1
    p_b = res_broker[0]
    assert p_b["operating_rate_pct"] == 72.5
    assert p_b["weekly_output_w_tons"] == 8.6
    assert p_b["factory_inventory_w_tons"] == 13.8


def test_extract_metrics_pvc_and_pta(tmp_path: Path) -> None:
    """验证聚氯乙烯(PVC)与精对苯二甲酸(PTA)提取。"""
    parser = ResearchReportParser(raw_dir=tmp_path)

    text_pvc = """
    PVC周报：本周PVC生产企业开工负荷率在75.20%，环比下降0.80个百分点；周度产量在43.50万吨；企业库存为38.20万吨。
    """
    res_pvc = parser.extract_metrics_from_text(
        text=text_pvc,
        product_name="聚氯乙烯",
        publish_date=date(2026, 8, 14),
    )
    assert len(res_pvc) >= 1
    assert res_pvc[0]["symbol"] == "V"
    assert res_pvc[0]["operating_rate_pct"] == 75.2
    assert res_pvc[0]["weekly_output_w_tons"] == 43.5
    assert res_pvc[0]["factory_inventory_w_tons"] == 38.2

    text_pta = """
    PTA周报：国内PTA周均产能利用率82.40%，PTA周度产量122.50万吨。下游聚酯开工负荷88.50%。
    """
    res_pta = parser.extract_metrics_from_text(
        text=text_pta,
        product_name="PTA",
        publish_date=date(2026, 8, 14),
    )
    assert len(res_pta) >= 1
    assert res_pta[0]["symbol"] == "TA"
    assert res_pta[0]["operating_rate_pct"] == 82.4
    assert res_pta[0]["weekly_output_w_tons"] == 122.5


def test_extract_metrics_negative_filtering(tmp_path: Path) -> None:
    """验证下游行业、规划产能与社会库存等干扰项拦截。"""
    parser = ResearchReportParser(raw_dir=tmp_path)
    text_neg = """
    本周纯碱市场震荡。下游浮法玻璃开工率82.5%，光伏玻璃日熔量增加。
    某企业规划新增年产能200万吨纯碱项目。
    纯碱社会库存35.5万吨，交割库库存12.3万吨。
    """
    res = parser.extract_metrics_from_text(
        text=text_neg,
        product_name="纯碱",
        publish_date=date(2026, 8, 20),
    )
    assert len(res) == 0


def test_save_survey_to_csv(tmp_path: Path) -> None:
    """验证原子去重保存至 expert_research_survey.csv。"""
    parser = ResearchReportParser(raw_dir=tmp_path)
    target_csv = tmp_path / "test_survey.csv"

    records = [
        {
            "trade_date": date(2026, 8, 20),
            "report_date": date(2026, 8, 20),
            "product_name": "纯碱",
            "symbol": "SA",
            "operating_rate_pct": 78.31,
            "weekly_output_w_tons": 74.58,
            "factory_inventory_w_tons": 184.49,
            "shipment_rate_pct": None,
            "source": "弘业期货_Research",
            "source_url": "https://example.com",
            "release_date": date(2026, 8, 21),
            "data_status": "actual",
            "collected_at": "2026-09-21T03:00:00Z",
            "raw_content_sha256": "abc123hash",
            "raw_snapshot_path": "snapshots/snap1.txt",
        }
    ]

    saved_path = parser.save_survey_to_csv(records, csv_path=target_csv)
    assert saved_path.exists()

    # 重复写入（幂等测试）
    parser.save_survey_to_csv(records, csv_path=target_csv)
    import csv

    with target_csv.open("r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 1
        assert reader[0]["product_name"] == "纯碱"
        assert float(reader[0]["operating_rate_pct"]) == 78.31
