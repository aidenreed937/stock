"""报告一致性规则组兼容聚合器。"""

from __future__ import annotations

from stock_analytics.pipelines.report_consistency_brief_checks import BriefConsistencyChecksMixin
from stock_analytics.pipelines.report_consistency_industry_checks import (
    IndustryConsistencyChecksMixin,
)
from stock_analytics.pipelines.report_consistency_report_checks import ReportConsistencyChecksMixin
from stock_analytics.pipelines.report_consistency_text_checks import TextConsistencyChecksMixin


class ConsistencyChecksMixin(
    ReportConsistencyChecksMixin,
    BriefConsistencyChecksMixin,
    IndustryConsistencyChecksMixin,
    TextConsistencyChecksMixin,
):
    """组合各类报告一致性规则。"""

    pass
