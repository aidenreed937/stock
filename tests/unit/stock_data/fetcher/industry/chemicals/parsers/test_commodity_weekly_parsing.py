"""多品种化工周报指标专属解析单元测试。"""

from __future__ import annotations

from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
    parse_commodity_weekly_metrics,
)


def test_parse_pta_weekly_metrics_excludes_downstream_polyester() -> None:
    """验证 PTA 周报解析严格绑定 PTA 开工负荷，排除下游聚酯负荷干扰。"""
    html_text = """
    <div>
      <p>本周国内PTA装置开工负荷为78.45%，较上周提升1.20%。PTA周度产量在125.60万吨。</p>
      <p>下游聚酯工厂开工负荷在89.20%，江浙织造负荷为72.00%。</p>
      <p>库存方面：本周国内PTA工厂库存为28.50万吨，社会库存维持平稳。</p>
    </div>
    """
    res = parse_commodity_weekly_metrics(html_text, product_name="精对苯二甲酸", symbol="TA")
    assert res["operating_rate_pct"] == 78.45
    assert res["weekly_output_w_tons"] == 125.60
    assert res["factory_inventory_w_tons"] == 28.50


def test_parse_meg_weekly_metrics() -> None:
    """验证乙二醇周报解析：综合开工率与华东主港库存。"""
    html_text = """
    <div>
      <p>本周国内乙二醇综合开工负荷在64.20%，其中煤制乙二醇开工负荷58.10%。乙二醇周产量约为36.80万吨。</p>
      <p>截止到本周四，华东主港库存总量为68.30万吨，较上周去库2.40万吨。</p>
    </div>
    """
    res = parse_commodity_weekly_metrics(html_text, product_name="乙二醇", symbol="MEG")
    assert res["operating_rate_pct"] == 64.20
    assert res["weekly_output_w_tons"] == 36.80
    assert res["factory_inventory_w_tons"] == 68.30


def test_parse_methanol_weekly_metrics_excludes_mto() -> None:
    """验证甲醇周报解析：全国装置开工率与港口库存，排除下游 MTO 负荷。"""
    html_text = """
    <div>
      <p>本周全国甲醇装置产能利用率降至72.15%，西北主产区负荷在78.50%。甲醇周度产量168.40万吨。</p>
      <p>下游方面，沿海MTO装置整体开工负荷在84.50%。</p>
      <p>库存方面：沿海甲醇港口总库存合计92.40万吨，周环比累库3.10万吨。</p>
    </div>
    """
    res = parse_commodity_weekly_metrics(html_text, product_name="甲醇", symbol="MA")
    assert res["operating_rate_pct"] == 72.15
    assert res["weekly_output_w_tons"] == 168.40
    assert res["factory_inventory_w_tons"] == 92.40


def test_parse_pvc_weekly_metrics() -> None:
    """验证 PVC 周报解析：综合开工率与企业厂区库存。"""
    html_text = """
    <div>
      <p>本周国内PVC生产企业开工负荷率在76.80%，其中电石法开工77.10%，乙烯法开工75.80%。PVC周产量46.20万吨。</p>
      <p>库存数据：国内PVC企业厂区库存在38.60万吨，华东及华南社会仓库库存为48.20万吨。</p>
    </div>
    """
    res = parse_commodity_weekly_metrics(html_text, product_name="聚氯乙烯", symbol="V")
    assert res["operating_rate_pct"] == 76.80
    assert res["weekly_output_w_tons"] == 46.20
    assert res["factory_inventory_w_tons"] == 38.60


def test_parse_tio2_weekly_metrics() -> None:
    """验证钛白粉周报解析：行业综合开工率与厂家库存。"""
    html_text = """
    <div>
      <p>本周国内钛白粉行业综合开工率在71.50%，周产量约为6.80万吨。</p>
      <p>下游涂料与塑料采购偏谨慎，国内钛白粉厂家库存在12.80万吨。</p>
    </div>
    """
    res = parse_commodity_weekly_metrics(html_text, product_name="钛白粉", symbol="TiO2")
    assert res["operating_rate_pct"] == 71.50
    assert res["weekly_output_w_tons"] == 6.80
    assert res["factory_inventory_w_tons"] == 12.80


def test_parse_mysteel_real_tio2_patterns() -> None:
    """验证 Mysteel 真实钛白粉周评、日评与数据日历的开工率与周产量提取。"""
    # 模式 1: 日评生产动态
    html_1 = """
    <div>
      <p>3、生产动态</p>
      <p>国产钛白粉厂家装置开工率本周在76.56%，较上期增加0.40%，本期钛白粉产量在9.13万吨，较上期增加0.11万吨，增幅1.22%。</p>
    </div>
    """
    res1 = parse_commodity_weekly_metrics(html_1, product_name="钛白粉", symbol="TIO2")
    assert res1["operating_rate_pct"] == 76.56
    assert res1["weekly_output_w_tons"] == 9.13

    # 模式 2: 周评样本产能利用率
    html_2 = """
    <div>
      <p>截止到本周，国内钛企样本产能利用率在73.35%，环比减幅0.76%，较去年同期减幅8.44%。</p>
      <p>本期钛白粉产量在8.59万吨，较上期减少0.11万吨，减幅1.26%，产能利用率72.55%。</p>
    </div>
    """
    res2 = parse_commodity_weekly_metrics(html_2, product_name="钛白粉", symbol="TIO2")
    assert res2["operating_rate_pct"] == 73.35
    assert res2["weekly_output_w_tons"] == 8.59


def test_parse_soda_ash_weekly_metrics() -> None:
    """验证纯碱周报解析（向后兼容性）。"""
    html_text = """
    <div>
      <p>纯碱装置开工率80.44%，较上周增加2.13%；纯碱产量76.62万吨，较上周增加2.72%。</p>
      <p>本周国内纯碱厂家总库存187.27万吨，较上周增加1.51%。纯碱出货率在96.37%。</p>
    </div>
    """
    res = parse_commodity_weekly_metrics(html_text, product_name="纯碱", symbol="SA")
    assert res["operating_rate_pct"] == 80.44
    assert res["weekly_output_w_tons"] == 76.62
    assert res["factory_inventory_w_tons"] == 187.27
    assert res["shipment_rate_pct"] == 96.37
