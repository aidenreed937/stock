"""商品 → 受益公司暴露度映射（company_exposure_map.csv）加载与校验。

用途：海关出口商品(109 个 product_key)下沉到公司层面，回答"真正受益标的"。
维护文件：
- `config/data/customs/company_exposure_map.csv`（utf-8-sig）——产品→公司暴露度，
  由大模型/人工共同维护；
- `config/data/customs/taxline_segments.csv`——高分化产品的税号段定义
  （如 transformer 按容量段拆分），公司可绑定到具体段以消除"产品内部税号
  yoy 分化"造成的偏差（transformer 内部 2026-07 为 +13%~+566%）。

设计要点：
- **跨申万行业映射是特性不是错误**：公司可能申万归别的 L2（如鼎胜新材主营锂电铝箔
  但申万归工业金属），sw_l2 列仅作信息展示，不约束映射；
- **comm_equipment_mixed 允许空映射**：851762 品目混合是 h6 聚合载体（0 数据行），
  按 maintenance.md 不应映射公司；
- exposure 为基于公开资料的人工估计（0-1），待 fina_mainbz（主营构成）采集后校准；
- taxline_segment 列：公司绑定的税号段（";"分隔多段），空=绑定整个产品。
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stock_data.fetcher.industry.customs.parsers.catalog import load_hs_catalog

logger = logging.getLogger(__name__)

COMPANY_EXPOSURE_REQUIRED_COLUMNS = [
    "product_key",
    "product_name",
    "stock_code",
    "company_name",
    "exposure",
    "sw_l2",
    "evidence",
    "status",
    "taxline_segment",
]

TAXLINE_SEGMENT_REQUIRED_COLUMNS = [
    "product_key",
    "segment_key",
    "segment_name",
    "hs_codes",
    "description",
]

# 允许空映射的产品（品目混合载体等，见 maintenance.md 851762）
ALLOWED_EMPTY_PRODUCTS = frozenset({"comm_equipment_mixed"})

_STOCK_CODE_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")


@dataclass(frozen=True)
class CompanyExposureEntry:
    """单条商品→公司暴露度记录。"""

    product_key: str
    product_name: str
    stock_code: str
    company_name: str
    exposure: float
    sw_l2: str
    evidence: str
    status: str
    taxline_segment: str = ""


@dataclass(frozen=True)
class TaxlineSegment:
    """产品的税号段定义（如 transformer 按容量段）。"""

    product_key: str
    segment_key: str
    segment_name: str
    hs_codes: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class TaxlineSegmentMap:
    """税号段定义表（按产品索引）。"""

    segments: tuple[TaxlineSegment, ...] = field(default_factory=tuple)

    def segments_for(self, product_key: str) -> list[TaxlineSegment]:
        return [s for s in self.segments if s.product_key == product_key]

    def hs_codes_for(self, product_key: str, segment_key: str) -> list[str]:
        for s in self.segments:
            if s.product_key == product_key and s.segment_key == segment_key:
                return list(s.hs_codes)
        return []

    @property
    def segment_keys_by_product(self) -> dict[str, set[str]]:
        keys: dict[str, set[str]] = {}
        for s in self.segments:
            keys.setdefault(s.product_key, set()).add(s.segment_key)
        return keys


@dataclass(frozen=True)
class CompanyExposureMap:
    """商品→公司映射表（按产品索引）。"""

    entries: tuple[CompanyExposureEntry, ...] = field(default_factory=tuple)

    def companies_for(self, product_key: str) -> list[CompanyExposureEntry]:
        """返回某商品下全部公司（按 exposure 降序）。"""
        return [e for e in self.entries if e.product_key == product_key]

    @property
    def product_keys(self) -> set[str]:
        return {e.product_key for e in self.entries}


def _parse_exposure(value: Any) -> float:
    text = str(value or "").strip()
    try:
        exposure = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"exposure 无法解析为数值: {text!r}") from exc
    if not 0.0 <= exposure <= 1.0:
        raise ValueError(f"exposure 越界(应为 0-1): {exposure}")
    return exposure


def _validate_stock_code(stock_code: str, product_key: str, company_name: str) -> None:
    if not _STOCK_CODE_RE.match(stock_code):
        raise ValueError(
            f"非法公司代码 {stock_code!r} ({product_key}/{company_name})，"
            "应为 6 位数字 + .SH/.SZ/.BJ"
        )


def load_taxline_segments(
    segments_path: Path | str = "config/data/customs/taxline_segments.csv",
) -> TaxlineSegmentMap:
    """读取税号段定义表（高分化产品的段拆分）。

    Raises:
        FileNotFoundError: 段定义文件不存在（此时返回空映射，公司段引用校验跳过）。
        ValueError: 列缺失或 hs_codes 为空。
    """
    p = Path(segments_path)
    if not p.exists():
        return TaxlineSegmentMap()

    segments: list[TaxlineSegment] = []
    seen: set[tuple[str, str]] = set()
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = [
            col for col in TAXLINE_SEGMENT_REQUIRED_COLUMNS if col not in (reader.fieldnames or [])
        ]
        if missing_cols:
            raise ValueError(f"taxline_segments.csv 缺少列: {missing_cols}")
        for line_no, row in enumerate(reader, start=2):
            product_key = str(row.get("product_key", "")).strip()
            segment_key = str(row.get("segment_key", "")).strip()
            hs_codes = tuple(
                c.strip() for c in str(row.get("hs_codes", "")).split(";") if c.strip()
            )
            if not product_key or not segment_key or not hs_codes:
                raise ValueError(f"第 {line_no} 行 product_key/segment_key/hs_codes 为空")
            key = (product_key, segment_key)
            if key in seen:
                raise ValueError(f"第 {line_no} 行段重复: {product_key}/{segment_key}")
            seen.add(key)
            segments.append(
                TaxlineSegment(
                    product_key=product_key,
                    segment_key=segment_key,
                    segment_name=str(row.get("segment_name", "")).strip(),
                    hs_codes=hs_codes,
                    description=str(row.get("description", "")).strip(),
                )
            )
    return TaxlineSegmentMap(tuple(segments))


def load_company_exposure_map(
    map_path: Path | str = "config/data/customs/company_exposure_map.csv",
    catalog_path: Path | str = "config/data/customs/hs_codes_catalog.csv",
    segments_path: Path | str = "config/data/customs/taxline_segments.csv",
    require_known_product: bool = True,
) -> CompanyExposureMap:
    """读取商品→公司暴露度映射，并做完整性/合法性校验。

    Args:
        map_path: company_exposure_map.csv 路径。
        catalog_path: hs_codes_catalog.csv（产品键合法性来源）。
        segments_path: taxline_segments.csv（税号段定义，校验公司段引用）。
        require_known_product: 为 True 时，产品键必须存在于 catalog（或允许空映射白名单）；
            为 False 时跳过该检查（宽松模式）。

    Raises:
        FileNotFoundError: 映射文件不存在。
        ValueError: 列缺失、产品键未知、代码非法、exposure 越界、段引用非法或重复。
    """
    p = Path(map_path)
    if not p.exists():
        raise FileNotFoundError(f"未找到商品→公司暴露度映射: {p}")

    catalog_products: set[str] = set()
    if require_known_product:
        try:
            catalog = load_hs_catalog(catalog_path)
            catalog_products = {info.get("product_key", "") for info in catalog.values()}
            catalog_products.discard("")
        except Exception:
            logger.warning("catalog 加载失败，跳过产品键校验: %s", catalog_path)
            catalog_products = set()

    known_products = catalog_products | ALLOWED_EMPTY_PRODUCTS
    segment_map = load_taxline_segments(segments_path)
    valid_segments_by_product = segment_map.segment_keys_by_product
    entries: list[CompanyExposureEntry] = []
    seen: set[tuple[str, str]] = set()

    with p.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing_cols = [
            col for col in COMPANY_EXPOSURE_REQUIRED_COLUMNS if col not in (reader.fieldnames or [])
        ]
        if missing_cols:
            raise ValueError(f"company_exposure_map.csv 缺少列: {missing_cols}")

        for line_no, row in enumerate(reader, start=2):
            product_key = str(row.get("product_key", "")).strip()
            if not product_key:
                raise ValueError(f"第 {line_no} 行 product_key 为空")
            if require_known_product and product_key not in known_products:
                raise ValueError(
                    f"第 {line_no} 行产品键 {product_key!r} 不在 catalog 中，也不在允许空映射白名单"
                )
            if product_key in ALLOWED_EMPTY_PRODUCTS:
                # 品目混合载体允许非空行存在（防御），但不强制要求有公司
                pass

            stock_code = str(row.get("stock_code", "")).strip()
            company_name = str(row.get("company_name", "")).strip()
            if not stock_code or not company_name:
                raise ValueError(f"第 {line_no} 行 stock_code/company_name 为空")
            _validate_stock_code(stock_code, product_key, company_name)

            taxline_segment = str(row.get("taxline_segment") or "").strip()
            if taxline_segment and taxline_segment.lower() != "none":
                valid = valid_segments_by_product.get(product_key, set())
                for seg in taxline_segment.split(";"):
                    seg = seg.strip()
                    if not seg:
                        continue
                    if seg not in valid:
                        raise ValueError(
                            f"第 {line_no} 行段引用 {product_key}/{seg!r} 不在"
                            " taxline_segments.csv 中"
                        )

            key = (product_key, stock_code)
            if key in seen:
                raise ValueError(f"第 {line_no} 行重复: {product_key}/{stock_code}")
            seen.add(key)

            exposure = _parse_exposure(row.get("exposure"))
            entries.append(
                CompanyExposureEntry(
                    product_key=product_key,
                    product_name=str(row.get("product_name", "")).strip(),
                    stock_code=stock_code,
                    company_name=company_name,
                    exposure=exposure,
                    sw_l2=str(row.get("sw_l2", "")).strip(),
                    evidence=str(row.get("evidence", "")).strip(),
                    status=str(row.get("status", "")).strip(),
                    taxline_segment=taxline_segment,
                )
            )

    return CompanyExposureMap(tuple(entries))


__all__ = [
    "ALLOWED_EMPTY_PRODUCTS",
    "COMPANY_EXPOSURE_REQUIRED_COLUMNS",
    "TAXLINE_SEGMENT_REQUIRED_COLUMNS",
    "CompanyExposureEntry",
    "CompanyExposureMap",
    "TaxlineSegment",
    "TaxlineSegmentMap",
    "load_company_exposure_map",
    "load_taxline_segments",
]
