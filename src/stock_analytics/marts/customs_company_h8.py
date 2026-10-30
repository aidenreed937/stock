"""报告期无前视的公司主营构成 → H8 出口暴露 Mart。

这条链路不依赖人工维护的 ``bz_item_alias_map.csv`` 或
``company_exposure_map.csv``：

``fina_mainbz(P)`` → 分词/模糊匹配 → 公司-产品报告期暴露 →
``good_h8_codes.csv`` → 公司-H8 月度出口加权。

``fina_mainbz`` 只有报告期而没有公告日，因此本模块的 point-in-time 约束是：
月度 M 只能使用 ``end_date < M 月第一天`` 的最近一份主营构成。这个口径比直接
使用当前最新财报保守，但不等同于公告日级别的无前视。
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import jieba
import polars as pl
from rapidfuzz import fuzz, process

MAPPING_MART_NAME = "customs_company_product_mapping"
H8_EXPOSURE_MART_NAME = "customs_company_h8_exposure"
MAPPING_FILE = f"{MAPPING_MART_NAME}.parquet"
H8_EXPOSURE_FILE = f"{H8_EXPOSURE_MART_NAME}.parquet"
MAPPING_LATEST_FILE = f"{MAPPING_MART_NAME}_latest.csv"
H8_EXPOSURE_LATEST_FILE = f"{H8_EXPOSURE_MART_NAME}_latest.csv"

DEFAULT_CATALOG_PATH = Path("config/data/customs/good_h8_codes.csv")
DEFAULT_PRODUCTS_PATH = Path("config/data/customs/good_products.csv")
DEFAULT_MAINBZ_PATH = Path("data/curated/tushare/market=CN/fina_mainbz")
DEFAULT_STOCK_BASIC_PATH = Path("data/curated/tushare/market=CN/stock_basic/data.parquet")
DEFAULT_CUSTOMS_TRADE_PATH = Path("data/curated/industry/customs_trade_gacc.parquet")
DEFAULT_OVERSEAS_REVENUE_PATH = Path("data/curated/mart/overseas_revenue.parquet")
DEFAULT_SEGMENT_BINDING_PATH = Path("config/data/customs/company_segment_binding.csv")
DEFAULT_TAXLINE_SEGMENTS_PATH = Path("config/data/customs/taxline_segments.csv")
DEFAULT_MART_DIR = Path("data/curated/mart")

# 研究口径：只消费 GACC 官方数据（source=GACC，2018-01 起）；
# customs_trade_gacc.parquet 为纯 GACC（UN 数据见 customs_trade.parquet）。
RESEARCH_SOURCES = ("GACC",)

_CATALOG_TEXT_COLUMNS = (
    "category_name",
    "product_name",
    "hs_name",
    "description",
    "target_l1_name",
    "target_l2_names",
    "target_l3_names",
)
_GENERIC_BZ_ITEMS = frozenset(
    {
        "产品",
        "主营业务",
        "主营业务收入",
        "营业收入",
        "其他",
        "其他业务",
        "其他主营业务",
        "合计",
        "合计特别调整",
        "分部抵消",
        "分部间抵销",
        "服务收入及其他",
        "贸易收入",
        "租赁业务",
        "研发及检测",
        "研发及检测板块",
    }
)
_STOP_TOKENS = frozenset({"产品", "业务", "系列", "项目", "收入", "其他", "相关"})
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
# 部件/下游头词：bz_item 以这些词结尾且产品语料不含该词时，公司做的是部件/下游
# （如"电动工具零部件"做的是零部件、不是电动工具），不是产品本身，应降级
_PART_DOWNSTREAM_HEAD = frozenset(
    {
        "零部件",
        "配件",
        "部件",
        "耗材",
        "散件",
        "备件",
        "组件",
        "发动机",
        "服务",
        "处理",
    }
)

# 电池系产品匹配同义词（2026-10 修复：动态映射对"锂电池/动力电池/储能电池/电芯"等
# 命中 ambiguous/no_match（top-8 进不去或与电池链产品平顶），"磷酸铁锂电池"误绑
# phosphoric_acid）——精确命中给 99 分（selected 门槛 88+margin6），其余词仅作候选
# 语料注入 match_choices / search_text。仅覆盖已验证失效的电池系词，不扩大维护面。
_BATTERY_SYNONYM_TERMS: dict[str, tuple[str, ...]] = {
    "battery": (
        "锂电池",
        "锂离子电池",
        "动力电池",
        "动力电池系统",
        "储能电池",
        "储能电芯",
        "锂电",
        "电芯",
        "电池组",
        "蓄电池",
        "磷酸铁锂电池",
        "三元锂电池",
        # 储能整机/系统词（2026-10 修复：GACC 无储能整机税号，整机按部件归类，
        # 阳光/派能/艾罗/昱能/禾迈 的"储能系统/储能产品/储能电池系统"等此前 no_match，
        # 归 battery 电芯口径近似——catalog product_name 即"锂电池与储能"）
        "储能系统",
        "储能产品",
        "储能电池系统",
        "储能电池包",
        "储能电站",
        "工商业储能系统",
        "工商业储能业务",
        "户用储能系统及产品",
        "户用储能产品",
    ),
    "cathode_material": (
        "磷酸铁锂",
        "磷酸铁锂正极材料",
        "三元正极材料",
        "正极材料",
    ),
    "robot_vacuum": (
        "智能清洁产品及配件",
        "智能清洁产品",
        "销售智能清洁设备",
        "智能清洁设备",
        "扫地机器人",
        "智能扫地机器人",
        "服务机器人",
        "清洁小家电",
    ),
    "thermal_expansion_valve": (
        "制冷空调电器零部件",
        "制冷配件",
        "制冷空调零部件产业",
        "电子膨胀阀",
    ),
    "hand_tools": (
        "手工具",
        "工具及五金",
        "工业工具",
    ),
    "power_tools": (
        "电动工具",
        "新能源园林机械",
        "交流电园林机械",
        "园林机械",
    ),
    "small_appliance": (
        "厨房小家电",
        "厨房电器",
        "烹饪电器",
        "食物料理电器",
        "西式电器系列",
        "西式小家电系列",
        "营养煲系列",
        "食品加工机系列",
    ),
    "air_conditioner": (
        "暖通空调",
        "家用空调",
    ),
    "television": (
        "彩电",
        "电视机",
        "智能显示终端",
    ),
    "projector": (
        "彩色投影机",
        "智能微投",
        "投影设备",
    ),
    "refrigerant": (
        "制冷剂",
        "氟制冷剂",
        "氟碳化学品",
        "氟化工原料",
        "含氟高分子材料",
    ),
    "mdi": (
        "聚氨酯",
        "聚氨酯系列",
        "MDI",
        "聚合MDI",
        "纯MDI",
        "异氰酸酯",
        "TDI",
    ),
    "tio2": (
        "钛白粉",
        "金红石型钛白粉",
        "二氧化钛",
        "二氧化钛颜料",
    ),
    "pesticide": (
        "农药",
        "农药原药",
        "农药制剂",
        "原药",
        "制剂",
        "除草剂",
        "杀虫剂",
        "杀菌剂",
        "草甘膦",
        "草铵膦",
    ),
    "feed_additives": (
        "饲料添加剂",
        "赖氨酸",
        "苏氨酸",
        "饲料氨基酸",
        "蛋氨酸",
    ),
    "msg": (
        "味精",
        "谷氨酸",
        "谷氨酸钠",
    ),
    "xanthan_gum": (
        "黄原胶",
        "生物发酵胶体",
    ),
    "soda_ash": (
        "纯碱",
        "碳酸钠",
        "轻质纯碱",
        "重质纯碱",
        "小苏打",
    ),
    "caustic_soda": (
        "烧碱",
        "氢氧化钠",
        "离子膜烧碱",
    ),
    "potash_fertilizer": (
        "钾肥",
        "氯化钾",
        "硫酸钾",
        "钾产品",
    ),
    "phosphate_fertilizer": (
        "磷肥",
        "磷酸一铵",
        "磷酸二铵",
        "磷酸二氢钙",
        "过磷酸钙",
        "磷复肥",
    ),
    "compound_fertilizer": (
        "复合肥",
        "复混肥",
        "新型复合肥",
        "三元复合肥",
    ),
    "urea": (
        "尿素",
        "化学肥料",
    ),
    "phosphoric_acid": (
        "磷酸",
        "工业磷酸",
        "湿法磷酸",
        "热法磷酸",
    ),
    "polyester_filament": (
        "涤纶长丝",
        "涤纶预取向丝",
        "涤纶加弹丝",
        "涤纶牵伸丝",
        "POY",
        "FDY",
        "DTY",
    ),
    "polyester_staple": (
        "涤纶短纤",
        "聚酯短纤",
    ),
    "nylon_filament": (
        "锦纶长丝",
        "锦纶丝",
        "锦纶单纱",
        "尼龙丝",
        "聚酰胺长丝",
    ),
    "viscose_staple": (
        "粘胶短纤",
        "粘胶短纤维",
        "人造棉",
    ),
    "methanol": (
        "甲醇",
        "精甲醇",
        "煤制甲醇",
    ),
    "ethylene_glycol": (
        "乙二醇",
        "MEG",
        "环氧乙烷",
    ),
    "rare_earth_magnet": (
        "稀土永磁",
        "钕铁硼",
        "钕铁硼磁钢",
        "钕铁硼永磁材料",
        "永磁材料",
        "磁材产品",
        "磁钢成品",
    ),
    "aluminum_sheet": (
        "铝板带",
        "铝板带箔",
        "铝合金板",
        "铝卷板",
        "冷轧卷/板",
        "热轧卷/板",
        "铝加工产品",
    ),
    "aluminum_foil": (
        "铝箔",
        "铝板带箔",
        "高精度铝箔",
        "包装铝箔",
        "空调铝箔",
    ),
    "battery_aluminum_foil": (
        "电池铝箔",
        "锂电池铝箔",
        "动力电池铝箔",
        "电池箔",
    ),
    "battery_copper_foil": (
        "锂电铜箔",
        "电池铜箔",
        "标准铜箔",
        "电子铜箔",
        "极薄铜箔",
    ),
    "aluminum_unwrought": (
        "未锻轧铝",
        "电解铝",
        "原铝",
        "铝锭",
        "自产铝锭",
        "铝合金锭",
    ),
    "copper_wire": (
        "精炼铜丝",
        "铜线",
        "铜杆线",
        "铜杆",
        "铜管",
        "铜基材料",
    ),
    "copper_unwrought": (
        "阴极铜",
        "精炼铜",
        "电解铜",
        "粗铜",
        "铜产品",
    ),
    "zinc": (
        "锌",
        "铅锌",
        "锌精矿",
        "锌精粉",
        "未锻轧锌",
        "锌合金",
        "铅锌采选冶",
    ),
}


def _battery_synonyms(product_key: str) -> tuple[str, ...]:
    """给定产品的电池系同义词（未命中返回空元组）。"""
    return _BATTERY_SYNONYM_TERMS.get(product_key, ())


def _is_generic_item(item_text: str) -> bool:
    """兜底/杂项项判定：精确命中表或「其他/合计」前缀（数据里「其他*」无目录产品名）。"""
    return (
        item_text in _GENERIC_BZ_ITEMS
        or item_text.startswith("其他")
        or item_text.startswith("合计")
    )


@dataclass(frozen=True, slots=True)
class ProductCandidate:
    """good_h8_codes 中一个产品键的匹配语料。"""

    product_key: str
    product_name: str
    search_text: str
    product_norm: str
    match_norm: str
    search_norm: str
    product_specific_norm: str
    token_text: str
    tokens: tuple[str, ...]
    hs_codes: tuple[str, ...]
    category_name: str
    target_l1_code: str
    target_l1_name: str
    target_l2_codes: str
    target_l2_names: str
    target_l3_codes: str
    target_l3_names: str


@dataclass(frozen=True, slots=True)
class MatchResult:
    """一个 bz_item 的候选匹配结果。"""

    status: str
    product_key: str | None
    score: float
    margin: float
    candidate_product_keys: str
    candidate_scores: str


class ProductMatcher:
    """对产品语料建立一次索引，避免每个主营行扫描完整 H8 目录。"""

    def __init__(self, candidates: list[ProductCandidate]) -> None:
        self.candidates = candidates
        self.match_choices = [candidate.match_norm for candidate in candidates]

    def match(self, item: object) -> MatchResult:
        item_text = str(item or "").strip()
        if not item_text or _is_generic_item(item_text):
            return MatchResult("generic", None, 0.0, 0.0, "", "")
        item_norm = _normalise_text(item_text)
        exact_indices = {
            index
            for index, candidate in enumerate(self.candidates)
            if candidate.product_norm and candidate.product_norm in item_norm
        }
        if len(item_norm.replace(" ", "")) > 24 and not exact_indices:
            return MatchResult("no_match", None, 0.0, 0.0, "", "")
        candidate_rows = process.extract(
            item_norm,
            self.match_choices,
            scorer=fuzz.WRatio,
            limit=min(8, len(self.candidates)),
        )
        indices = {int(row[2]) for row in candidate_rows}
        indices.update(exact_indices)
        item_tokens = " ".join(_tokens(item_text, use_jieba=False))
        ranked = sorted(
            (
                (
                    _score_item(item_text, self.candidates[index], item_tokens),
                    self.candidates[index],
                )
                for index in indices
            ),
            key=lambda pair: (-pair[0], pair[1].product_key),
        )
        return _result_from_ranked(ranked)


def _parse_period(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 7:
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, calendar.monthrange(year, month)[1])
    return date.fromisoformat(text)


def _read_parquets(path: Path | str, columns: list[str]) -> pl.DataFrame:
    root = Path(path)
    files = [root] if root.is_file() else sorted(root.rglob("*.parquet"))
    files = [
        f
        for f in files
        if not f.name.endswith((".bak.parquet", ".tmp.parquet", ".migration.tmp.parquet"))
    ]
    if not files:
        raise FileNotFoundError(f"未找到 Parquet 数据: {root}")
    frames: list[pl.DataFrame] = []
    for file in files:
        schema = pl.read_parquet_schema(file)
        missing = [column for column in columns if column not in schema]
        if missing:
            raise ValueError(f"{file} 缺少字段: {missing}")
        frames.append(pl.read_parquet(file, columns=columns))
    return pl.concat(frames, how="vertical_relaxed").unique()


def load_h8_catalog(catalog_path: Path | str = DEFAULT_CATALOG_PATH) -> pl.DataFrame:
    """读取并校验 H8 主表，H6 父码必须等于 H8 前六位。"""
    path = Path(catalog_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到 H8 主表: {path}")
    frame = pl.read_csv(path, infer_schema_length=0).with_columns(pl.all().cast(pl.String))
    required = {"hs_code", "hs_parent_code", "product_key", "product_name", "hs_level"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"good_h8_codes.csv 缺少列: {missing}")
    for column in _CATALOG_TEXT_COLUMNS:
        if column not in frame.columns:
            frame = frame.with_columns(pl.lit("").alias(column))
    h8 = frame.filter((pl.col("hs_level") == "8") & pl.col("hs_code").str.contains(r"^\d{8}$"))
    if h8.is_empty():
        raise ValueError("good_h8_codes.csv 没有合法 H8 行")
    bad_parent = h8.filter(pl.col("hs_parent_code") != pl.col("hs_code").str.slice(0, 6))
    if not bad_parent.is_empty():
        sample = bad_parent.select("hs_code").head(5).to_series().to_list()
        raise ValueError(f"H8/H6 父码不一致: {sample}")
    bad_l3 = h8.filter(
        (pl.col("target_l3_codes").str.strip_chars() == "")
        | (pl.col("target_l3_names").str.strip_chars() == "")
    )
    if not bad_l3.is_empty():
        sample = bad_l3.select("hs_code").head(5).to_series().to_list()
        raise ValueError(f"H8 缺少三级行业映射: {sample}")
    duplicates = h8.group_by("hs_code").len().filter(pl.col("len") > 1)
    if not duplicates.is_empty():
        sample = duplicates.select("hs_code").head(5).to_series().to_list()
        raise ValueError(f"H8 编码重复或挂载多个 product_key: {sample}")
    return h8


def _normalise_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[_/|;,，。；、()（）\[\]【】+\-]+", " ", text)
    return " ".join(text.split())


def _tokens(value: object, *, use_jieba: bool = True) -> tuple[str, ...]:
    normalized = _normalise_text(value)
    if not normalized:
        return ()
    segmented = (
        jieba.lcut_for_search(normalized.replace(" ", ""), HMM=False) if use_jieba else [normalized]
    )
    tokens: list[str] = []
    for piece in segmented:
        for token in _TOKEN_RE.findall(piece.lower()):
            if token not in _STOP_TOKENS:
                tokens.append(token)
    if not tokens:
        tokens = _TOKEN_RE.findall(normalized)
    return tuple(dict.fromkeys(tokens))


def _head_token(value: object) -> str:
    """bz_item 的头词（最后一个有意义的 jieba 词），用于部件/下游误归判定。"""
    normalized = _normalise_text(value).replace(" ", "")
    if not normalized:
        return ""
    for token in reversed(jieba.lcut_for_search(normalized, HMM=False)):
        token = token.strip()
        if token and _TOKEN_RE.fullmatch(token) and token not in _STOP_TOKENS:
            return str(token)
    return ""


def _part_head_word(head: str) -> str:
    """头词若以部件/下游词结尾，返回该词（如"柴油发动机"→"发动机"），否则返回空串。"""
    return next((word for word in _PART_DOWNSTREAM_HEAD if head.endswith(word)), "")


def _candidate_index(catalog: pl.DataFrame) -> list[ProductCandidate]:
    canonical_names: dict[str, str] = {}
    if DEFAULT_PRODUCTS_PATH.exists():
        try:
            prod_df = pl.read_csv(DEFAULT_PRODUCTS_PATH).select(["product_key", "product_name"])
            canonical_names = dict(
                zip(prod_df["product_key"].to_list(), prod_df["product_name"].to_list())
            )
        except Exception:
            pass
    products: dict[str, dict[str, Any]] = {}
    for row in catalog.iter_rows(named=True):
        product_key = str(row["product_key"] or "").strip()
        if not product_key:
            continue
        p_name = canonical_names.get(product_key) or str(row["product_name"] or "").strip()
        product = products.setdefault(
            product_key,
            {
                "product_key": product_key,
                "product_name": p_name,
                "texts": [],
                "specific_texts": [],
                "hs_codes": [],
                "category_name": str(row["category_name"] or "").strip(),
                "target_l1_code": str(row.get("target_l1_code") or "").strip(),
                "target_l1_name": str(row.get("target_l1_name") or "").strip(),
                "target_l2_codes": str(row.get("target_l2_codes") or "").strip(),
                "target_l2_names": str(row.get("target_l2_names") or "").strip(),
                "target_l3_codes": str(row.get("target_l3_codes") or "").strip(),
                "target_l3_names": str(row.get("target_l3_names") or "").strip(),
            },
        )
        product["hs_codes"].append(str(row["hs_code"]).strip())
        product["texts"].extend(
            str(row.get(column) or "").strip()
            for column in _CATALOG_TEXT_COLUMNS
            if str(row.get(column) or "").strip()
        )
        for column in ("hs_name", "description"):
            value = str(row.get(column) or "").strip()
            if value:
                product["specific_texts"].append(value)
        product["texts"].extend(_battery_synonyms(product_key))

    candidates: list[ProductCandidate] = []
    for product in products.values():
        search_text = " ".join(dict.fromkeys(product["texts"]))
        candidates.append(
            ProductCandidate(
                product_key=product["product_key"],
                product_name=product["product_name"],
                search_text=search_text,
                product_norm=_normalise_text(product["product_name"]),
                match_norm=_normalise_text(
                    " ".join(
                        [
                            product["product_name"],
                            product["category_name"],
                            product["target_l2_names"],
                            product["target_l3_names"],
                            " ".join(_battery_synonyms(product["product_key"])),
                        ]
                    )
                ),
                search_norm=_normalise_text(search_text),
                product_specific_norm=_normalise_text(
                    " ".join(dict.fromkeys([product["product_name"], *product["specific_texts"]]))
                ),
                token_text=" ".join(_tokens(search_text)),
                tokens=_tokens(search_text),
                hs_codes=tuple(sorted(set(product["hs_codes"]))),
                category_name=product["category_name"],
                target_l1_code=product["target_l1_code"],
                target_l1_name=product["target_l1_name"],
                target_l2_codes=product["target_l2_codes"],
                target_l2_names=product["target_l2_names"],
                target_l3_codes=product["target_l3_codes"],
                target_l3_names=product["target_l3_names"],
            )
        )
    return sorted(candidates, key=lambda item: item.product_key)


def _score_item(item: str, candidate: ProductCandidate, item_tokens: str | None = None) -> float:
    item_norm = _normalise_text(item)
    if not item_norm:
        return 0.0
    product_norm = candidate.product_norm
    search_norm = candidate.search_norm
    item_tokens = (
        item_tokens if item_tokens is not None else " ".join(_tokens(item, use_jieba=False))
    )
    candidate_tokens = candidate.token_text
    if item_norm == product_norm:
        return 100.0
    token_score = fuzz.token_set_ratio(item_tokens, candidate_tokens) if item_tokens else 0.0
    char_score = fuzz.ratio(item_norm, product_norm) if product_norm else 0.0
    search_score = fuzz.partial_ratio(item_norm, search_norm) if search_norm else 0.0
    score = max(char_score * 0.75 + search_score * 0.25, token_score * 0.6 + search_score * 0.2)
    if item_norm in product_norm or product_norm in item_norm:
        score = max(score, 92.0)
    else:
        score = min(score, 86.0)
    # 部件/下游头词降级：头词以部件/下游词结尾（"柴油发动机"→"发动机"）且产品特定
    # 语料（product_name+hs_name+description，排除宽泛行业词）不含该词 → 公司做的是
    # 部件/下游，不是产品本身，压到 selected 阈值（88）以下
    part_word = _part_head_word(_head_token(item))
    if part_word and part_word not in candidate.product_specific_norm:
        score = min(score, 87.0)
    if len(item_norm.replace(" ", "")) < 3:
        score = min(score, 72.0)
    if item_norm in _battery_synonyms(candidate.product_key):
        score = max(score, 99.0)
    return round(score, 4)


def _result_from_ranked(ranked: list[tuple[float, ProductCandidate]]) -> MatchResult:
    top = ranked[:3]
    if not top:
        return MatchResult("no_match", None, 0.0, 0.0, "", "")
    top_score, top_candidate = top[0]
    second_score = top[1][0] if len(top) > 1 else 0.0
    margin = round(top_score - second_score, 4)
    if top_score >= 88.0 and margin >= 6.0:
        status = "selected"
        product_key: str | None = top_candidate.product_key
    elif top_score >= 65.0:
        status = "ambiguous"
        product_key = None
    else:
        status = "no_match"
        product_key = None
    return MatchResult(
        status,
        product_key,
        top_score,
        margin,
        ";".join(candidate.product_key for _, candidate in top),
        ";".join(f"{candidate.product_key}:{score:.2f}" for score, candidate in top),
    )


def _match_item(item: object, candidates: list[ProductCandidate]) -> MatchResult:
    item_text = str(item or "").strip()
    if not item_text or _is_generic_item(item_text):
        return MatchResult("generic", None, 0.0, 0.0, "", "")
    item_tokens = " ".join(_tokens(item_text, use_jieba=False))
    ranked = sorted(
        ((_score_item(item_text, candidate, item_tokens), candidate) for candidate in candidates),
        key=lambda pair: (-pair[0], pair[1].product_key),
    )
    return _result_from_ranked(ranked)


def load_mainbz(
    mainbz_path: Path | str = DEFAULT_MAINBZ_PATH,
    *,
    as_of_period: date | str | None = None,
) -> pl.DataFrame:
    """读取主营产品构成 P 类数据，并按报告期截断。"""
    frame = _read_parquets(
        mainbz_path,
        ["symbol", "end_date", "bz_item", "bz_sales", "bz_code"],
    )
    frame = frame.with_columns(
        pl.col("symbol").cast(pl.String).str.strip_chars(),
        pl.col("bz_item").cast(pl.String).fill_null("").str.strip_chars(),
        pl.col("bz_code").cast(pl.String).str.to_uppercase(),
        pl.col("bz_sales").cast(pl.Float64, strict=False),
        pl.col("end_date").cast(pl.Date),
    ).filter(
        (pl.col("bz_code") == "P") & pl.col("end_date").is_not_null() & (pl.col("bz_sales") > 0)
    )
    cutoff = _parse_period(as_of_period)
    if cutoff is not None:
        frame = frame.filter(pl.col("end_date") <= cutoff)
    if frame.is_empty():
        raise ValueError(f"fina_mainbz 在报告期 {cutoff or '全量'} 前没有有效 P 类数据")
    return frame.unique(subset=["symbol", "end_date", "bz_item", "bz_code"], keep="last")


def load_company_table(stock_basic_path: Path | str = DEFAULT_STOCK_BASIC_PATH) -> pl.DataFrame:
    """读取公司维度表，仅保留动态匹配所需字段（含上市日用于无前视过滤）。"""
    frame = _read_parquets(stock_basic_path, ["symbol", "name", "industry", "list_date"])
    return (
        frame.with_columns(
            pl.col("symbol").cast(pl.String).str.strip_chars(),
            pl.col("name").cast(pl.String).fill_null("").str.strip_chars(),
            pl.col("industry").cast(pl.String).fill_null("").str.strip_chars(),
            pl.col("list_date").cast(pl.Date, strict=False),
        )
        .unique(subset=["symbol"], keep="last")
        .rename({"name": "company_name", "industry": "stock_industry"})
    )


def _load_overseas_revenue(path: Path | str) -> pl.DataFrame:
    """读取海外营收 Mart 的 PIT 字段（symbol × 报告期 × 公告日）。"""
    frame = pl.read_parquet(path)
    required = {"symbol", "ann_date", "end_date", "overseas_revenue"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"overseas_revenue Mart 缺少字段: {missing}")
    return frame.select(["symbol", "ann_date", "end_date", "overseas_revenue"]).with_columns(
        pl.col("ann_date").cast(pl.Date),
        pl.col("end_date").cast(pl.Date),
        pl.col("overseas_revenue").cast(pl.Float64, strict=False),
    )


def _load_segment_binding(path: Path | str) -> pl.DataFrame:
    """读取公司人工修正表（company_segment_binding.csv）。

    一表两用：binding-only 行 exposure 为空；exposure 非空的行同时是 override 行
    （原 company_product_override.csv 已并入本表）。返回字段含可选的
    company_name / exposure / evidence。
    """
    frame = pl.read_csv(path).with_columns(pl.all().cast(pl.String))
    required = {"product_key", "segment_key", "stock_code"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"company_segment_binding.csv 缺少字段: {missing}")
    cols = ["product_key", "segment_key", "stock_code"]
    for extra in ("company_name", "exposure", "evidence"):
        if extra in frame.columns:
            cols.append(extra)
    return frame.select(cols)


def _validate_override_segments(override: pl.DataFrame, binding: pl.DataFrame) -> None:
    """校验 override.segment_key ⊆ 同(产品,公司)的 binding 段，防段错位。

    override 行 = company_segment_binding.csv 中 exposure 非空的行；其每个段都必须
    在同一张表里对同一 (product_key, stock_code) 存在；否则段级展开会过滤成 0 或
    挂错段。
    """
    if override.is_empty() or binding.is_empty():
        return
    bind_segs: dict[tuple[str, str], set[str]] = {}
    for r in binding.iter_rows(named=True):
        key = (str(r["product_key"]).strip(), str(r["stock_code"]).strip())
        bind_segs.setdefault(key, set()).update(
            s.strip() for s in str(r["segment_key"]).split(";") if s.strip()
        )
    bad: list[tuple[tuple[str, str], list[str], list[str]]] = []
    for r in override.iter_rows(named=True):
        key = (str(r["product_key"]).strip(), str(r["stock_code"]).strip())
        segs = {s.strip() for s in str(r["segment_key"] or "").split(";") if s.strip()}
        if not segs:
            continue
        if not segs <= bind_segs.get(key, set()):
            bad.append((key, sorted(segs), sorted(bind_segs.get(key, set()))))
    if bad:
        sample = ", ".join(f"{key}:override={ov} binding={bd}" for key, ov, bd in bad[:10])
        raise ValueError(
            "company_segment_binding.csv 段错位（override 行 segment_key 必须⊆ "
            f"同产品同公司段）: {sample}"
        )


def _product_metadata(catalog: pl.DataFrame) -> pl.DataFrame:
    candidates = _candidate_index(catalog)
    return pl.DataFrame(
        [
            {
                "product_key": candidate.product_key,
                "product_name": candidate.product_name,
                "catalog_h8_count": len(candidate.hs_codes),
                "catalog_h8_codes": ";".join(candidate.hs_codes),
                "category_name": candidate.category_name,
                "target_l1_code": candidate.target_l1_code,
                "target_l1_name": candidate.target_l1_name,
                "target_l2_codes": candidate.target_l2_codes,
                "target_l2_names": candidate.target_l2_names,
                "target_l3_codes": candidate.target_l3_codes,
                "target_l3_names": candidate.target_l3_names,
            }
            for candidate in candidates
        ]
    )


def _attach_product_exposure(mapping: pl.DataFrame) -> pl.DataFrame:
    real = mapping.filter(pl.col("match_status") != "generic")
    totals = real.group_by(["symbol", "report_period"]).agg(
        pl.col("bz_sales").sum().alias("total_bz_sales")
    )
    selected = mapping.filter(pl.col("match_status") == "selected")
    if selected.is_empty():
        return mapping.with_columns(
            pl.lit(None).cast(pl.Float64).alias("product_bz_sales"),
            pl.lit(None).cast(pl.Float64).alias("product_exposure"),
            pl.lit(None).cast(pl.Float64).alias("total_bz_sales"),
        )
    product_sales = selected.group_by(["symbol", "report_period", "product_key"]).agg(
        pl.col("bz_sales").sum().alias("product_bz_sales")
    )
    exposure = product_sales.join(totals, on=["symbol", "report_period"], how="left").with_columns(
        (pl.col("product_bz_sales") / pl.col("total_bz_sales")).alias("product_exposure")
    )
    return mapping.join(totals, on=["symbol", "report_period"], how="left").join(
        exposure.select(
            ["symbol", "report_period", "product_key", "product_bz_sales", "product_exposure"]
        ),
        on=["symbol", "report_period", "product_key"],
        how="left",
    )


def build_company_product_mapping(
    mainbz: pl.DataFrame,
    company_table: pl.DataFrame,
    catalog: pl.DataFrame,
) -> pl.DataFrame:
    """将每个报告期的主营构成转为可审计的候选产品映射。"""
    matcher = ProductMatcher(_candidate_index(catalog))
    cache: dict[str, MatchResult] = {}
    rows: list[dict[str, Any]] = []
    for row in mainbz.iter_rows(named=True):
        item = str(row["bz_item"] or "").strip()
        result = cache.get(item)
        if result is None:
            result = matcher.match(item)
            cache[item] = result
        rows.append(
            {
                "symbol": row["symbol"],
                "report_period": row["end_date"],
                "bz_item": item,
                "bz_sales": row["bz_sales"],
                "match_status": result.status,
                "match_engine": "jieba+rapidfuzz",
                "product_key": result.product_key,
                "match_score": result.score,
                "match_margin": result.margin,
                "candidate_product_keys": result.candidate_product_keys,
                "candidate_scores": result.candidate_scores,
            }
        )
    mapping = pl.DataFrame(rows, infer_schema_length=None).join(
        company_table, on="symbol", how="inner"
    )
    mapping = mapping.with_columns(pl.col("stock_industry").fill_null(""))
    mapping = _attach_product_exposure(mapping)
    # 保留 list_date：暴露展开需用它做无前视过滤，最终由组装层剥离
    return mapping.join(_product_metadata(catalog), on="product_key", how="left").sort(
        ["symbol", "report_period", "bz_item"]
    )


def _load_trade_h8(customs_trade: pl.DataFrame, catalog: pl.DataFrame) -> pl.DataFrame:
    required = {"hs_code", "report_month", "export_value_usd"}
    missing = sorted(required - set(customs_trade.columns))
    if missing:
        raise ValueError(f"海关黄金表缺少字段: {missing}")
    columns = ["hs_code", "report_month", "export_value_usd"]
    optional = ["export_volume", "quantity_unit_norm", "unit_known", "trade_direction", "hs_level"]
    columns.extend(column for column in optional if column in customs_trade.columns)
    trade = customs_trade.select(columns).with_columns(
        pl.col("hs_code").cast(pl.String).str.strip_chars().str.zfill(8),
        pl.col("report_month").cast(pl.String),
        pl.col("export_value_usd").cast(pl.Float64, strict=False),
    )
    if "trade_direction" in trade.columns:
        trade = trade.filter(pl.col("trade_direction") == "export")
    if "hs_level" in trade.columns:
        trade = trade.filter(pl.col("hs_level") == "8")
    for column, dtype in (("export_volume", pl.Float64), ("quantity_unit_norm", pl.String)):
        if column not in trade.columns:
            trade = trade.with_columns(pl.lit(None).cast(dtype).alias(column))
    if "unit_known" not in trade.columns:
        trade = trade.with_columns(pl.lit(False).alias("unit_known"))
    catalog_columns = catalog.select(
        [
            "hs_code",
            "product_key",
            "product_name",
            "hs_name",
            "category_name",
            "target_l1_code",
            "target_l1_name",
            "target_l2_codes",
            "target_l2_names",
            "target_l3_codes",
            "target_l3_names",
        ]
    )
    return (
        trade.join(catalog_columns, on="hs_code", how="inner")
        .with_columns(pl.col("unit_known").fill_null(False))
        .group_by(
            [
                "report_month",
                "hs_code",
                "product_key",
                "product_name",
                "hs_name",
                "category_name",
                "target_l1_code",
                "target_l1_name",
                "target_l2_codes",
                "target_l2_names",
                "target_l3_codes",
                "target_l3_names",
            ]
        )
        .agg(
            pl.col("export_value_usd").sum().alias("export_value_usd"),
            pl.col("export_volume").sum().alias("_volume_sum"),
            pl.col("quantity_unit_norm")
            .filter(pl.col("unit_known"))
            .n_unique()
            .alias("_unit_count"),
            pl.col("unit_known").all().alias("_all_unit_known"),
        )
        .with_columns(
            pl.when(pl.col("_all_unit_known") & (pl.col("_unit_count") <= 1))
            .then(pl.col("_volume_sum"))
            .otherwise(None)
            .alias("export_volume")
        )
        .drop(["_volume_sum", "_unit_count", "_all_unit_known"])
    )


def validate_company_h8_exposure(mart: pl.DataFrame, catalog: pl.DataFrame) -> None:
    """校验最终 Mart 的 H8 合法性和报告期无前视约束。"""
    if mart.is_empty():
        return
    valid_codes = set(catalog["hs_code"].to_list())
    actual_codes = set(mart["hs_code"].to_list())
    unknown = sorted(actual_codes - valid_codes)
    if unknown:
        raise ValueError(f"公司-H8 Mart 出现主表外编码: {unknown[:5]}")
    future = mart.filter(pl.col("mapping_report_period") >= pl.col("report_date"))
    if not future.is_empty():
        raise ValueError("公司-H8 Mart 使用了报告期当月或未来的主营构成")
    duplicates = (
        mart.group_by(["symbol", "report_month", "hs_code"]).len().filter(pl.col("len") > 1)
    )
    if not duplicates.is_empty():
        raise ValueError("公司-H8 Mart 存在 symbol×report_month×hs_code 重复行")


def _attach_overseas_revenue(exposure: pl.DataFrame, overseas: pl.DataFrame | None) -> pl.DataFrame:
    """附公司海外营收（ann_date≤月末 PIT）→ 公司级 H8 海外营收估计（亿元）。

    ``company_h8_overseas_rev_est = overseas_revenue × product_exposure ×
    h8_export_share_within_product``，量纲随公司海外营收（跨公司可比，用于横截面
    选股）；不替代 ``company_h8_export_value_usd``（全国出口加权，时间序列 yoy 用）。
    """
    est_col = "company_h8_overseas_rev_est"
    if overseas is None or overseas.is_empty():
        return exposure.with_columns(
            pl.lit(None, dtype=pl.Float64).alias(est_col),
            pl.lit(None, dtype=pl.Float64).alias("overseas_revenue"),
            pl.lit(None, dtype=pl.Date).alias("overseas_report_period"),
        )
    src = (
        overseas.filter(pl.col("overseas_revenue").is_not_null() & pl.col("ann_date").is_not_null())
        .rename({"end_date": "overseas_report_period"})
        .sort(["symbol", "ann_date"])
    )
    key = exposure.with_columns(pl.col("report_date").dt.month_end().alias("_asof")).sort(
        ["symbol", "_asof"]
    )
    joined = key.join_asof(
        src,
        left_on="_asof",
        right_on="ann_date",
        by="symbol",
        strategy="backward",
    ).drop("_asof")
    return joined.with_columns(
        (
            pl.col("overseas_revenue")
            * pl.col("product_exposure")
            * pl.col("h8_export_share_within_product")
        ).alias(est_col)
    )


def _attach_segment(
    exposure: pl.DataFrame,
    binding: pl.DataFrame | None,
    taxline: pl.DataFrame | None,
) -> pl.DataFrame:
    """按 company_segment_binding 过滤段内 H8 码，附 segment_key / segment_name。

    绑定公司只保留其绑定段的 H8 码（段级暴露）；未绑定公司保留全产品（产品级）。
    """
    if binding is None or binding.is_empty() or taxline is None or taxline.is_empty():
        return exposure.with_columns(
            pl.lit("", dtype=pl.String).alias("segment_key"),
            pl.lit("", dtype=pl.String).alias("segment_name"),
        )
    seg_hs: dict[tuple[str, str], set[str]] = {}
    seg_name: dict[tuple[str, str], str] = {}
    for r in taxline.iter_rows(named=True):
        key = (str(r["product_key"]), str(r["segment_key"]))
        seg_hs[key] = {c.strip() for c in str(r["hs_codes"]).split(";") if c.strip()}
        seg_name[key] = str(r["segment_name"] or "").strip()
    company_seg: dict[tuple[str, str], list[str]] = {}
    for r in binding.iter_rows(named=True):
        key = (str(r["stock_code"]), str(r["product_key"]))
        segs = [s.strip() for s in str(r["segment_key"]).split(";") if s.strip()]
        if segs:
            # 同一 (公司,产品) 可能有多行绑定（如 silver_unwrought + silver_wrought），
            # 必须合并累加，不能用后行覆盖前行，否则段级展开会挂错段
            existing = company_seg.setdefault(key, [])
            for s in segs:
                if s not in existing:
                    existing.append(s)

    rows: list[dict[str, object]] = []
    for r in exposure.iter_rows(named=True):
        bound_segs = company_seg.get((str(r["symbol"]), str(r["product_key"])))
        if bound_segs:
            allowed: set[str] = set()
            for s in bound_segs:
                allowed |= seg_hs.get((str(r["product_key"]), s), set())
            if str(r["hs_code"]) not in allowed:
                continue
            r["segment_key"] = ";".join(bound_segs)
            r["segment_name"] = ";".join(
                seg_name.get((str(r["product_key"]), s), s) for s in bound_segs
            )
        else:
            r["segment_key"] = ""
            r["segment_name"] = ""
        rows.append(r)
    return pl.DataFrame(rows)


def build_company_h8_exposure_mart(
    mapping: pl.DataFrame,
    customs_trade: pl.DataFrame,
    catalog: pl.DataFrame,
    overseas_revenue: pl.DataFrame | None = None,
    segment_binding: pl.DataFrame | None = None,
    taxline_segments: pl.DataFrame | None = None,
    manual_exposure: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """用报告期暴露度展开 H8，并生成公司-H8 月度出口加权序列。"""
    selected = (
        mapping.filter(
            (pl.col("match_status") == "selected")
            & pl.col("product_key").is_not_null()
            & pl.col("product_exposure").is_not_null()
        )
        .select(
            [
                "symbol",
                "company_name",
                "stock_industry",
                "report_period",
                "product_key",
                "product_exposure",
                "match_score",
                "list_date",
            ]
        )
        .unique(subset=["symbol", "report_period", "product_key"])
    )
    if manual_exposure is not None and not manual_exposure.is_empty():
        selected = selected.vstack(manual_exposure.select(selected.columns))
        # manual override 只用于自动匹配未覆盖的公司；若同一 (公司,报告期,产品)
        # 已有自动行，保留自动行（先出现），避免双权重
        selected = selected.unique(subset=["symbol", "report_period", "product_key"])
    if selected.is_empty():
        return pl.DataFrame()
    trade = _load_trade_h8(customs_trade, catalog).with_columns(
        pl.col("report_month").str.to_date("%Y-%m").alias("report_date")
    )
    joined = selected.join(trade, on="product_key", how="inner").filter(
        # 双重点-in-time：主营构成报告期早于数据月 + 公司该月已上市（无未来公司）
        (pl.col("report_period") < pl.col("report_date"))
        & (pl.col("report_date") >= pl.col("list_date"))
    )
    if joined.is_empty():
        return pl.DataFrame()
    joined = (
        joined.sort(["symbol", "report_date", "product_key", "hs_code", "report_period"])
        .unique(
            subset=["symbol", "report_date", "product_key", "hs_code"],
            keep="last",
        )
        .with_columns(
            (pl.col("export_value_usd") * pl.col("product_exposure")).alias(
                "company_h8_export_value_usd"
            )
        )
    )
    product_totals = trade.group_by(["report_date", "product_key"]).agg(
        pl.col("export_value_usd").sum().alias("product_export_value_usd")
    )
    joined = joined.join(
        product_totals, on=["report_date", "product_key"], how="left"
    ).with_columns(
        (pl.col("export_value_usd") / pl.col("product_export_value_usd")).alias(
            "h8_export_share_within_product"
        )
    )
    joined = joined.with_columns(
        (pl.col("product_exposure") * pl.col("h8_export_share_within_product")).alias(
            "company_h8_weight"
        )
    )
    company_totals = joined.group_by(["symbol", "report_date"]).agg(
        pl.col("company_h8_export_value_usd").sum().alias("company_export_exposure_usd")
    )
    result = joined.join(company_totals, on=["symbol", "report_date"], how="left").with_columns(
        (pl.col("company_h8_export_value_usd") / pl.col("company_export_exposure_usd")).alias(
            "company_h8_exposure_share"
        ),
        pl.col("report_date").dt.strftime("%Y-%m").alias("report_month"),
        pl.col("report_period").alias("mapping_report_period"),
    )
    result = result.drop("report_period").drop("list_date", strict=False)
    result = _attach_overseas_revenue(result, overseas_revenue)
    result = _attach_segment(result, segment_binding, taxline_segments).sort(
        ["symbol", "report_date", "hs_code"]
    )
    validate_company_h8_exposure(result, catalog)
    return result


def build_customs_company_h8_marts(
    *,
    mainbz_path: Path | str = DEFAULT_MAINBZ_PATH,
    stock_basic_path: Path | str = DEFAULT_STOCK_BASIC_PATH,
    catalog_path: Path | str = DEFAULT_CATALOG_PATH,
    customs_trade_path: Path | str = DEFAULT_CUSTOMS_TRADE_PATH,
    overseas_revenue_path: Path | str | None = DEFAULT_OVERSEAS_REVENUE_PATH,
    segment_binding_path: Path | str | None = DEFAULT_SEGMENT_BINDING_PATH,
    taxline_segments_path: Path | str | None = DEFAULT_TAXLINE_SEGMENTS_PATH,
    as_of_period: date | str | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """加载本地事实表并构建产品映射 Mart 与公司-H8 Mart。"""
    catalog = load_h8_catalog(catalog_path)
    mainbz = load_mainbz(mainbz_path, as_of_period=as_of_period)
    company_table = load_company_table(stock_basic_path)
    mapping = build_company_product_mapping(mainbz, company_table, catalog)
    trade = pl.read_parquet(customs_trade_path)
    if "source" in trade.columns:
        trade = trade.filter(pl.col("source").is_in(RESEARCH_SOURCES))
    overseas = (
        _load_overseas_revenue(Path(overseas_revenue_path)) if overseas_revenue_path else None
    )
    binding = _load_segment_binding(Path(segment_binding_path)) if segment_binding_path else None
    taxline = (
        pl.read_csv(taxline_segments_path).with_columns(pl.all().cast(pl.String))
        if taxline_segments_path and Path(taxline_segments_path).exists()
        else None
    )
    manual_exposure = None
    if binding is not None:
        # 段级接线：优先使用 taxline_segments.csv 维护的产品集合；兜底为已知重点品类
        if taxline is not None and not taxline.is_empty():
            segment_enabled = set(taxline["product_key"].unique().to_list())
        else:
            segment_enabled = {
                "transformer",
                "inverter",
                "solar_cell",
                "battery",
                "power_cable",
                "uav_drone",
                "electronic_cigarette",
                "auto_parts",
                "semiconductor_equipment",
                "lithium_chemicals",
                "silver",
                "cathode_material",
                "bearing",
                "hydraulics",
                "industrial_valve",
                "semiconductor_material",
                "ev_charger",
            }
        binding = binding.filter(pl.col("product_key").is_in(list(segment_enabled)))
        # override 行 = 同一张表里 exposure 非空的行（原 company_product_override.csv）
        if "exposure" in binding.columns:
            override = binding.filter(
                pl.col("exposure").cast(pl.Float64, strict=False).is_not_null()
            )
        else:
            override = binding.slice(0, 0)
        _validate_override_segments(override, binding)
        if not override.is_empty():
            periods = mapping.select(["symbol", "report_period"]).unique()
            company_cols = mapping.select(
                ["symbol", "company_name", "stock_industry", "list_date"]
            ).unique()
            manual_exposure = (
                override.select(
                    [
                        "stock_code",
                        "product_key",
                        pl.col("exposure").cast(pl.Float64, strict=False).alias("product_exposure"),
                    ]
                )
                .rename({"stock_code": "symbol"})
                .join(periods, on="symbol", how="inner")
                .join(company_cols, on="symbol", how="inner")
                .with_columns(
                    pl.lit(100.0).alias("match_score"),
                    pl.col("stock_industry").fill_null(""),
                )
            )
    exposure = build_company_h8_exposure_mart(
        mapping, trade, catalog, overseas, binding, taxline, manual_exposure
    )
    # list_date 仅用于暴露展开的无前视过滤，不属于最终 Mart 契约列
    return mapping.drop("list_date", strict=False), exposure


def save_customs_company_h8_marts(
    mapping: pl.DataFrame,
    exposure: pl.DataFrame,
    output_dir: Path | str = DEFAULT_MART_DIR,
) -> dict[str, Path]:
    """落盘两个 Parquet Mart，并附带最新报告期/月快照。"""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    mapping_path = root / MAPPING_FILE
    exposure_path = root / H8_EXPOSURE_FILE
    mapping_latest = root / MAPPING_LATEST_FILE
    exposure_latest = root / H8_EXPOSURE_LATEST_FILE
    mapping.write_parquet(mapping_path)
    exposure.write_parquet(exposure_path)
    if mapping.is_empty():
        mapping.head(0).write_csv(mapping_latest)
    else:
        mapping.filter(pl.col("report_period") == pl.col("report_period").max()).write_csv(
            mapping_latest
        )
    if exposure.is_empty():
        exposure.head(0).write_csv(exposure_latest)
    else:
        exposure.filter(pl.col("report_month") == pl.col("report_month").max()).write_csv(
            exposure_latest
        )
    return {
        "mapping": mapping_path,
        "mapping_latest": mapping_latest,
        "exposure": exposure_path,
        "exposure_latest": exposure_latest,
    }


__all__ = [
    "DEFAULT_CATALOG_PATH",
    "DEFAULT_CUSTOMS_TRADE_PATH",
    "DEFAULT_MAINBZ_PATH",
    "DEFAULT_MART_DIR",
    "DEFAULT_OVERSEAS_REVENUE_PATH",
    "DEFAULT_SEGMENT_BINDING_PATH",
    "DEFAULT_STOCK_BASIC_PATH",
    "DEFAULT_TAXLINE_SEGMENTS_PATH",
    "H8_EXPOSURE_FILE",
    "H8_EXPOSURE_LATEST_FILE",
    "H8_EXPOSURE_MART_NAME",
    "MAPPING_FILE",
    "MAPPING_LATEST_FILE",
    "MAPPING_MART_NAME",
    "build_company_h8_exposure_mart",
    "build_company_product_mapping",
    "build_customs_company_h8_marts",
    "load_company_table",
    "load_h8_catalog",
    "load_mainbz",
    "save_customs_company_h8_marts",
    "validate_company_h8_exposure",
]
