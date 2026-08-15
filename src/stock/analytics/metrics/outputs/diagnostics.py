"""指标诊断输出辅助。"""

from stock.analytics.metrics.models import MetricDiagnostic
from stock.analytics.metrics.spec import DiagnosticLevel


def build_missing_data_diagnostic(metric_id: str, dataset: str) -> MetricDiagnostic:
    """构造缺失数据诊断。"""
    return MetricDiagnostic(
        metric_id=metric_id,
        level=DiagnosticLevel.WARNING,
        message=f"指标依赖数据集不可用: {dataset}",
    )
