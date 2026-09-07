"""海关产业数据记录与 GACC 查询模型。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal


@dataclass(frozen=True)
class CustomsTradeRecord:
    """海关重点品类进出口月度标准化记录。"""

    category_key: str
    category_name: str
    product_key: str
    product_name: str
    hs_code: str
    hs_name: str
    report_month: str
    trade_date: date
    trade_direction: str
    export_value_usd: float
    export_volume: float | None = None
    quantity_unit: str = ""
    export_asp_usd: float | None = None
    target_l1_code: str = ""
    target_l1_name: str = ""
    target_l2_codes: str = ""
    target_l2_names: str = ""
    export_value_3mma: float | None = None
    yoy_growth_3mma: float | None = None
    mom_growth_3mma: float | None = None
    source: str = "UN_Comtrade"
    source_url: str = ""
    release_date: date | None = None
    data_status: str = "actual"
    collected_at: str = ""
    target_l3_codes: str = ""
    target_l3_names: str = ""
    trade_value_currency: str = "USD"
    raw_content_sha256: str = ""
    raw_snapshot_path: str = ""
    hs_level: str = ""
    hs_parent_code: str = ""

    def __post_init__(self) -> None:
        """从税号补齐统一层级字段，避免不同来源重复维护层级。"""
        code = str(self.hs_code).strip()
        if not self.hs_level and len(code) in {6, 8}:
            object.__setattr__(self, "hs_level", str(len(code)))
        if not self.hs_parent_code and len(code) >= 6:
            object.__setattr__(self, "hs_parent_code", code[:6])


GaccFlowType = Literal["import", "export", "both"]
GaccCurrency = Literal["USD", "CNY"]

GACC_BASE_URL = "http://stats.customs.gov.cn"

FLOW_LABELS: dict[str, str] = {
    "import": "进口",
    "export": "出口",
    "both": "进出口",
}

FLOW_RADIO_VALUES: dict[str, str] = {
    "import": "1",
    "export": "0",
    "both": "2",
}

CURRENCY_LABELS: dict[str, str] = {
    "USD": "美元",
    "CNY": "人民币",
}

CURRENCY_RADIO_VALUES: dict[str, tuple[str, ...]] = {
    "USD": ("usd", "USD", "2"),
    "CNY": ("rmb", "cny", "CNY", "1"),
}

OUTPUT_FIELD_OPTIONS: tuple[dict[str, str], ...] = (
    {"value": "CODE_TS", "label": "商品"},
    {"value": "ORIGIN_COUNTRY", "label": "贸易伙伴"},
    {"value": "TRADE_MODE", "label": "贸易方式"},
    {"value": "TRADE_CO_PORT", "label": "收发货人注册地"},
)
DEFAULT_OUTPUT_FIELDS: tuple[str, ...] = tuple(option["value"] for option in OUTPUT_FIELD_OPTIONS)
# 产业月度量价表只需要商品维度；追加伙伴/贸易方式会显著放大结果行数。
DEFAULT_INDUSTRY_OUTPUT_FIELDS: tuple[str, ...] = ("CODE_TS",)
FIELD_SELECT_IDS = ("outerField1", "outerField2", "outerField3", "outerField4")


@dataclass(frozen=True)
class GaccQueryParams:
    """一次人工 GACC 导出查询的完整参数。"""

    flow_type: GaccFlowType = "export"
    currency: GaccCurrency = "USD"
    year: int = 2024
    month_start: int = 1
    month_end: int = 1
    split_by_month: bool = False
    output_fields: tuple[str, ...] = field(default_factory=lambda: DEFAULT_OUTPUT_FIELDS)

    def __post_init__(self) -> None:
        if self.flow_type not in FLOW_RADIO_VALUES:
            raise ValueError(f"不支持的 GACC 进出口方向: {self.flow_type!r}")
        if self.currency not in CURRENCY_RADIO_VALUES:
            raise ValueError(f"不支持的 GACC 币制: {self.currency!r}")
        if self.year < 2000 or self.year > 2100:
            raise ValueError(f"GACC 年份超出范围: {self.year}")
        if not 1 <= self.month_start <= 12 or not 1 <= self.month_end <= 12:
            raise ValueError("GACC 月份必须在 1 到 12 之间")
        if self.month_start > self.month_end:
            raise ValueError("GACC 起始月份不能晚于结束月份")
        fields = tuple(dict.fromkeys(str(value).strip() for value in self.output_fields if value))
        if not fields:
            raise ValueError("GACC 至少需要一个输出字段")
        if len(fields) > len(FIELD_SELECT_IDS):
            raise ValueError("GACC 输出字段最多支持四组")
        unknown = set(fields) - {option["value"] for option in OUTPUT_FIELD_OPTIONS}
        if unknown:
            raise ValueError(f"未知的 GACC 输出字段: {sorted(unknown)}")
        object.__setattr__(self, "output_fields", fields)

    @property
    def period(self) -> str:
        """返回单月或月份区间的稳定表示。"""
        if self.month_start == self.month_end:
            return f"{self.year:04d}-{self.month_start:02d}"
        return f"{self.year:04d}-{self.month_start:02d}_{self.month_end:02d}"

    def to_dict(self) -> dict[str, Any]:
        """返回可写入 manifest 的查询参数。"""
        return {
            "flow_type": self.flow_type,
            "currency": self.currency,
            "year": self.year,
            "month_start": self.month_start,
            "month_end": self.month_end,
            "split_by_month": self.split_by_month,
            "output_fields": list(self.output_fields),
        }

    def fingerprint(self) -> str:
        """根据查询参数生成稳定指纹，避免不同口径复用同一 CSV。"""
        payload = json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class GaccSnapshotManifest:
    """GACC RAW 快照的可审计元数据。"""

    query: GaccQueryParams
    source_url: str
    raw_snapshot_path: str
    raw_content_sha256: str
    downloaded_at: str
    row_count: int
    status: str = "success"

    @property
    def query_fingerprint(self) -> str:
        """返回查询参数指纹。"""
        return self.query.fingerprint()

    def to_dict(self) -> dict[str, Any]:
        """转换为 JSON manifest。"""
        return {
            "query": self.query.to_dict(),
            "query_fingerprint": self.query_fingerprint,
            "source_url": self.source_url,
            "raw_snapshot_path": self.raw_snapshot_path,
            "raw_content_sha256": self.raw_content_sha256,
            "downloaded_at": self.downloaded_at,
            "row_count": self.row_count,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GaccSnapshotManifest:
        """从 JSON manifest 恢复快照元数据。"""
        query_data = data.get("query")
        if not isinstance(query_data, dict):
            raise ValueError("GACC manifest 缺少 query 对象")
        query = GaccQueryParams(
            flow_type=query_data.get("flow_type", "export"),
            currency=query_data.get("currency", "USD"),
            year=int(query_data.get("year", 2024)),
            month_start=int(query_data.get("month_start", 1)),
            month_end=int(query_data.get("month_end", 1)),
            split_by_month=bool(query_data.get("split_by_month", False)),
            output_fields=tuple(query_data.get("output_fields") or DEFAULT_OUTPUT_FIELDS),
        )
        return cls(
            query=query,
            source_url=str(data.get("source_url", GACC_BASE_URL)),
            raw_snapshot_path=str(data.get("raw_snapshot_path", "")),
            raw_content_sha256=str(data.get("raw_content_sha256", "")),
            downloaded_at=str(data.get("downloaded_at", "")),
            row_count=int(data.get("row_count", 0)),
            status=str(data.get("status", "success")),
        )


__all__ = [
    "CURRENCY_LABELS",
    "CURRENCY_RADIO_VALUES",
    "DEFAULT_INDUSTRY_OUTPUT_FIELDS",
    "DEFAULT_OUTPUT_FIELDS",
    "FIELD_SELECT_IDS",
    "FLOW_LABELS",
    "FLOW_RADIO_VALUES",
    "GACC_BASE_URL",
    "OUTPUT_FIELD_OPTIONS",
    "CustomsTradeRecord",
    "GaccCurrency",
    "GaccFlowType",
    "GaccQueryParams",
    "GaccSnapshotManifest",
]
