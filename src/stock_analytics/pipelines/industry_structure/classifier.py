"""申万行业分类动态解析器与元数据服务 (Industry Classification Service)。

职责:
    1. 动态从 TuShare index_classify 权威字典表中提取申万各级别（L1/L2/L3）行业代码集合与层级图谱；
    2. 支持零硬编码动态解析代码与中文名称映射，全流程元数据驱动。
"""

from __future__ import annotations

import polars as pl

from stock_core.contracts import MarketDataCatalog


class IndustryClassifier:
    """申万行业分类动态解析服务。"""

    def __init__(self, catalog: MarketDataCatalog | None = None) -> None:
        """初始化分类解析器。"""
        if catalog is not None:
            self.catalog: MarketDataCatalog = catalog
        else:
            from stock_data.catalog import DataCatalog

            self.catalog = DataCatalog(data_source="tushare")
        self._cached_classify_df: pl.DataFrame | None = None

    def _load_classify_df(self) -> pl.DataFrame:
        """安全加载 index_classify 元数据表。"""
        if self._cached_classify_df is not None:
            return self._cached_classify_df
        try:
            df = self.catalog.load_dataset("index_classify")
            self._cached_classify_df = df
            return df
        except Exception:
            return pl.DataFrame()

    def get_l1_codes(self, src: str = "SW2021") -> frozenset[str]:
        """动态获取指定版本的申万一级行业代码集合 (默认 SW2021 版 31 个行业)。"""
        df = self._load_classify_df()
        if not df.is_empty() and "level" in df.columns:
            sub = df.filter(pl.col("level") == "L1")
            if "src" in sub.columns:
                sub_src = sub.filter(pl.col("src") == src)
                if not sub_src.is_empty():
                    sub = sub_src
            codes = sub.get_column("index_code").drop_nulls().unique().to_list()
            return frozenset(codes)
        return frozenset()

    def get_name_map(self, src: str | None = "SW2021") -> dict[str, str]:
        """动态构建行业代码（包含 801xxx.SI 与 6 位数字代码）到中文名称映射字典。"""
        mapping: dict[str, str] = {}
        df = self._load_classify_df()
        if not df.is_empty():
            if src is not None and "src" in df.columns:
                df = df.filter(pl.col("src") == src)
            for row in df.to_dicts():
                name = str(row.get("industry_name") or "")
                if not name:
                    continue
                for col in ("index_code", "industry_code", "symbol"):
                    val = str(row.get(col) or "")
                    if val and val != "None":
                        mapping[val] = name
                        if "." in val:
                            mapping[val.split(".")[0]] = name
        return mapping

    def resolve_name(self, code_or_name: str, src: str | None = "SW2021") -> str:
        """解析任意代码为标准行业中文名称。若无匹配则返回原名称/代码。"""
        clean = code_or_name.strip()
        name_map = self.get_name_map(src)
        if clean in name_map:
            return name_map[clean]
        prefix = clean.split(".")[0]
        return name_map.get(prefix, clean)
