"""申万行业分类动态解析器与元数据服务 (Industry Classification Service)。

职责:
    1. 动态从 TuShare index_classify 权威字典表中提取申万各级别（L1/L2/L3）行业代码集合与层级图谱；
    2. 支持零硬编码动态解析代码与中文名称映射；
    3. 在离线数据缺失时提供安全的 SW2021 最小兜底。
"""

from __future__ import annotations

from typing import Final

import polars as pl

from stock.data.catalog import DataCatalog

# 申万 2021 版 31 个官方一级行业 TuShare 标准代码静态兜底
_FALLBACK_SW2021_L1_CODES: Final[frozenset[str]] = frozenset(
    {
        "801010.SI",  # 农林牧渔
        "801030.SI",  # 基础化工
        "801040.SI",  # 钢铁
        "801050.SI",  # 有色金属
        "801080.SI",  # 电子
        "801110.SI",  # 家用电器
        "801120.SI",  # 食品饮料
        "801130.SI",  # 纺织服饰
        "801140.SI",  # 轻工制造
        "801150.SI",  # 医药生物
        "801160.SI",  # 公用事业
        "801170.SI",  # 交通运输
        "801180.SI",  # 房地产
        "801200.SI",  # 商贸零售
        "801210.SI",  # 社会服务
        "801230.SI",  # 综合
        "801710.SI",  # 建筑材料
        "801720.SI",  # 建筑装饰
        "801730.SI",  # 电力设备
        "801740.SI",  # 国防军工
        "801750.SI",  # 计算机
        "801760.SI",  # 传媒
        "801770.SI",  # 通信
        "801780.SI",  # 银行
        "801790.SI",  # 非银金融
        "801880.SI",  # 汽车
        "801890.SI",  # 机械设备
        "801950.SI",  # 煤炭
        "801960.SI",  # 石油石化
        "801970.SI",  # 环保
        "801980.SI",  # 美容护理
    }
)

_FALLBACK_NAME_MAP: Final[dict[str, str]] = {
    # 6 位数字代码映射 (理杏仁/国标)
    "110000": "农林牧渔",
    "210000": "采掘",
    "220000": "基础化工",
    "230000": "钢铁",
    "240000": "有色金属",
    "270000": "电子",
    "280000": "汽车",
    "330000": "家用电器",
    "340000": "食品饮料",
    "350000": "纺织服饰",
    "360000": "轻工制造",
    "370000": "医药生物",
    "410000": "公用事业",
    "420000": "交通运输",
    "430000": "房地产",
    "450000": "商贸零售",
    "460000": "社会服务",
    "480000": "银行",
    "490000": "非银金融",
    "510000": "综合",
    "610000": "建筑材料",
    "620000": "建筑装饰",
    "630000": "电力设备",
    "640000": "机械设备",
    "650000": "国防军工",
    "710000": "计算机",
    "720000": "传媒",
    "730000": "通信",
    "740000": "煤炭",
    "750000": "石油石化",
    "760000": "环保",
    "770000": "美容护理",
    # 801xxx.SI 代码映射 (TuShare)
    "801010.SI": "农林牧渔",
    "801020.SI": "采掘",
    "801030.SI": "基础化工",
    "801040.SI": "钢铁",
    "801050.SI": "有色金属",
    "801080.SI": "电子",
    "801110.SI": "家用电器",
    "801120.SI": "食品饮料",
    "801130.SI": "纺织服饰",
    "801140.SI": "轻工制造",
    "801150.SI": "医药生物",
    "801160.SI": "公用事业",
    "801170.SI": "交通运输",
    "801180.SI": "房地产",
    "801200.SI": "商贸零售",
    "801210.SI": "社会服务",
    "801230.SI": "综合",
    "801710.SI": "建筑材料",
    "801720.SI": "建筑装饰",
    "801730.SI": "电力设备",
    "801740.SI": "国防军工",
    "801750.SI": "计算机",
    "801760.SI": "传媒",
    "801770.SI": "通信",
    "801780.SI": "银行",
    "801790.SI": "非银金融",
    "801880.SI": "汽车",
    "801890.SI": "机械设备",
    "801950.SI": "煤炭",
    "801960.SI": "石油石化",
    "801970.SI": "环保",
    "801980.SI": "美容护理",
    "801001.SI": "申万A股",
    "801003.SI": "申万电气/电子",
    "801005.SI": "申万装备",
}


class IndustryClassifier:
    """申万行业分类动态解析服务。"""

    def __init__(self, catalog: DataCatalog | None = None) -> None:
        """初始化分类解析器。"""
        self.catalog = catalog or DataCatalog(data_source="tushare")
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
        """动态获取指定版本的申万一级行业代码集合。"""
        df = self._load_classify_df()
        if not df.is_empty() and "level" in df.columns:
            sub = df.filter(pl.col("level") == "L1")
            if "src" in sub.columns:
                sub_src = sub.filter(pl.col("src") == src)
                if not sub_src.is_empty():
                    sub = sub_src
            codes = sub.get_column("index_code").drop_nulls().unique().to_list()
            if len(codes) >= 28:
                return frozenset(codes)
        return _FALLBACK_SW2021_L1_CODES

    def get_name_map(self) -> dict[str, str]:
        """动态构建行业代码（801xxx 及 6 位纯数字）到中文名称的映射字典。"""
        mapping = dict(_FALLBACK_NAME_MAP)
        df = self._load_classify_df()
        if not df.is_empty():
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

    def resolve_name(self, code_or_name: str) -> str:
        """解析任意代码为标准行业中文名称。"""
        clean = code_or_name.strip()
        name_map = self.get_name_map()
        if clean in name_map:
            return name_map[clean]
        prefix = clean.split(".")[0]
        return name_map.get(prefix, clean)
