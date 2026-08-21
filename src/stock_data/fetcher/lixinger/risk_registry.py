"""理杏仁公司风险接口元数据参数。"""

from typing import Any

LIXINGER_RISK_ENDPOINT_SPECS: dict[str, dict[str, Any]] = {
    "cn/company/measures": {
        "description": "A 股公司证监会监管措施记录",
        "frequency": "event",
        "group": "risk_control",
        "primary_keys": ["stockCode", "date", "type", "linkUrl"],
        "nullable_primary_keys": ["linkUrl"],
        "date_columns": ["date"],
        "required_columns": ["stockCode", "date", "type"],
        "update_time": "18:00",
        "update_delay_days": 0,
        "code_param_name": "stockCode",
        "max_range_days": 3650,
    },
    "cn/company/inquiry": {
        "description": "A 股公司交易所问询函记录",
        "frequency": "event",
        "group": "risk_control",
        "primary_keys": ["stockCode", "date", "type", "linkUrl"],
        "nullable_primary_keys": ["linkUrl"],
        "date_columns": ["date"],
        "required_columns": ["stockCode", "date", "type"],
        "update_time": "18:00",
        "update_delay_days": 0,
        "code_param_name": "stockCode",
        "max_range_days": 3650,
    },
    "cn/company/hot/elr": {
        "description": "A 股公司限售解禁汇总",
        "frequency": "static",
        "group": "risk_control",
        "primary_keys": ["stockCode"],
        "date_columns": ["last_data_date"],
        "required_columns": ["stockCode", "last_data_date"],
        "update_time": "18:00",
        "update_delay_days": 0,
        "code_param_name": "stockCodes",
        "support_batch_prefetch": True,
        "pagination_required": True,
    },
}
