"""生意社 100ppi 现货出厂基准价图表页解析器。

负责：品种目录（COMMODITY_CATALOG）、Dean Edwards Packer 混淆 JS 解包、
页面文本/JS 中的 ECharts 日期与价格数组提取，以及抓取结果的基础校验。
采集与落盘编排见 ``collectors.spot_price``，RAW/Curated 转换见 ``transforms.spot_price``。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any

from stock_data.fetcher.industry.chemicals.models import ChemicalSpotPriceRecord

logger = logging.getLogger(__name__)

COMMODITY_CATALOG: dict[str, dict[str, Any]] = {
    "SA_light": {
        "ppid": 226,
        "product_name": "轻质纯碱",
        "spec": "99.20% min;优等品",
        "region": "国内",
        "unit": "元/吨",
    },
    "SA": {
        "ppid": 737,
        "product_name": "重质纯碱",
        "spec": "99.20% min;优等品",
        "region": "国内",
        "unit": "元/吨",
    },
    "UR": {
        "ppid": 89,
        "product_name": "尿素",
        "spec": "中小颗粒",
        "region": "山东省",
        "unit": "元/吨",
    },
    "ZC": {
        "ppid": 369,
        "product_name": "动力煤",
        "spec": "发热量:5500Kcal/kg",
        "region": "河北",
        "unit": "元/吨",
    },
    "SH": {
        "ppid": 368,
        "product_name": "烧碱",
        "spec": "32%液碱;离子膜法;一等品",
        "region": "山东",
        "unit": "元/吨",
    },
    "FG": {
        "ppid": 959,
        "product_name": "玻璃",
        "spec": "浮法玻璃;5mm",
        "region": "国内",
        "unit": "元/㎡",
    },
    "TA": {
        "ppid": 356,
        "product_name": "PTA",
        "spec": "优等品",
        "region": "华东",
        "unit": "元/吨",
    },
    "PX": {
        "ppid": 968,
        "product_name": "对二甲苯",
        "spec": "优等品;纯度:≥99.7%",
        "region": "国内",
        "unit": "元/吨",
    },
    "MA": {
        "ppid": 817,
        "product_name": "甲醇",
        "spec": "合格品",
        "region": "江苏省",
        "unit": "元/吨",
    },
    "V": {
        "ppid": 107,
        "product_name": "PVC",
        "spec": "SG-5 优等品",
        "region": "华东",
        "unit": "元/吨",
    },
    "MDI": {
        "ppid": 975,
        "product_name": "聚合MDI",
        "spec": "PM200;合格品",
        "region": "华东",
        "unit": "元/吨",
    },
    "TiO2": {
        "ppid": 645,
        "product_name": "钛白粉",
        "spec": "金红石型(R2型);硫酸法",
        "region": "国内",
        "unit": "元/吨",
    },
    "NH3": {
        "ppid": 86,
        "product_name": "液氨",
        "spec": "优等品",
        "region": "山东",
        "unit": "元/吨",
    },
    "NaCl": {
        "ppid": 142,
        "product_name": "原盐",
        "spec": "海晶原盐",
        "region": "山东",
        "unit": "元/吨",
    },
    "NH4Cl": {
        "ppid": 111,
        "product_name": "氯化铵",
        "spec": "干铵;优等品",
        "region": "国内",
        "unit": "元/吨",
    },
    "coke": {
        "ppid": 371,
        "product_name": "焦炭",
        "spec": "准一级冶金焦",
        "region": "山东",
        "unit": "元/吨",
    },
    "MEG": {
        "ppid": 222,
        "product_name": "乙二醇",
        "spec": "合格品",
        "region": "华东",
        "unit": "元/吨",
    },
    "POY": {
        "ppid": 1006,
        "product_name": "涤纶长丝POY",
        "spec": "150D/48F",
        "region": "江浙",
        "unit": "元/吨",
    },
    "R134a": {
        "ppid": 1288,
        "product_name": "R134a",
        "spec": "优级品;纯度:≥99.9%",
        "region": "国内",
        "unit": "元/吨",
    },
    "R32": {
        "ppid": 1289,
        "product_name": "R32",
        "spec": "优级品;纯度:≥99.9%",
        "region": "国内",
        "unit": "元/吨",
    },
    "R22": {
        "ppid": 1287,
        "product_name": "R22",
        "spec": "优级品",
        "region": "国内",
        "unit": "元/吨",
    },
    "CH2Cl2": {
        "ppid": 939,
        "product_name": "二氯甲烷",
        "spec": "优等品",
        "region": "国内",
        "unit": "元/吨",
    },
    "HF": {
        "ppid": 123,
        "product_name": "氢氟酸",
        "spec": "无水氟化氢",
        "region": "国内",
        "unit": "元/吨",
    },
    "H2SO4": {
        "ppid": 236,
        "product_name": "硫酸",
        "spec": "98%;工业级浓硫酸",
        "region": "湖北",
        "unit": "元/吨",
    },
}

COMMODITY_CATALOG_ALIASES: dict[str, str] = {
    "sponge_titanium": "Ti_sponge",
    "titanium_sponge": "Ti_sponge",
    "海绵钛": "Ti_sponge",
    "对二甲苯": "PX",
    "px": "PX",
    "硫酸": "H2SO4",
    "h2so4": "H2SO4",
    "乙二醇": "MEG",
    "meg": "MEG",
    "涤纶长丝POY": "POY",
    "涤纶POY": "POY",
    "poy": "POY",
    "r134a": "R134a",
    "r22": "R22",
    "ch2cl2": "CH2Cl2",
    "二氯甲烷": "CH2Cl2",
    "hf": "HF",
    "氢氟酸": "HF",
    "无水氟化氢": "HF",
}

_PACKER_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def previous_weekday(value: date) -> date:
    """将周末日期回退到最近一个工作日（周六/周日 → 周五）。"""
    result = value
    while result.weekday() >= 5:
        result = result - timedelta(days=1)
    return result


def _unbase_packer_token(token: str, radix: int) -> int:
    """将 P.A.C.K.E.R. 的 base-radix 词元还原为字典下标。"""
    if 2 <= radix <= 36:
        return int(token, radix)
    if 37 <= radix <= 62:
        alphabet = _PACKER_ALPHABET[:radix]
        value = 0
        for char in token:
            value = value * radix + alphabet.index(char)
        return value
    raise ValueError(f"不支持的 Packer 基数: {radix}")


def _replace_packer_string_table(source: str) -> str:
    """展开解包结果开头的字符串查找表 var _xxx=["a","b"]; 并替换引用。"""
    match = re.search(r'var\s*(_\w+)\s*=\s*\["(.*?)"\];', source, re.DOTALL)
    if match is None:
        return source
    varname, strings = match.groups()
    startpoint = len(match.group(0))
    lookup = strings.split('","')
    for index, value in enumerate(lookup):
        source = source.replace(f"{varname}[{index}]", f'"{value}"')
    return source[startpoint:]


def unpack_100ppi_packer(html_or_js: str) -> str:
    """解包 Dean Edwards P.A.C.K.E.R. 混淆段；未检测到时原样返回。

    算法与 js-beautify python 版 packer 解包器一致：提取
    ``eval(function(p,a,c,k,e,d){...}('payload',radix,count,'a|b'.split('|'),0,{}))``
    的参数并解码，用解包结果替换整个 eval 表达式，保留前后页面上下文。
    """
    header = re.search(
        r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k\s*,\s*e\s*,\s*d\s*\)",
        html_or_js,
        re.DOTALL,
    )
    if header is None:
        return html_or_js

    args = re.search(
        r"}\('(.*)',\s*(\d+|\[\]),\s*(\d+),\s*'(.*)'\.split\('\|\'\),\s*(\d+),\s*(.*)\)\)",
        html_or_js[header.start() :],
        re.DOTALL,
    )
    if args is None:
        return html_or_js

    payload, radix_raw, count_raw, words_raw = (
        args.group(1),
        args.group(2),
        args.group(3),
        args.group(4),
    )
    radix = 62 if radix_raw == "[]" else int(radix_raw)
    symtab = words_raw.split("|")
    if int(count_raw) != len(symtab):
        return html_or_js

    def lookup(match: re.Match[str]) -> str:
        token = match.group(0)
        try:
            val = symtab[_unbase_packer_token(token, radix)]
            return val if val else token
        except (ValueError, IndexError):
            return token

    payload = payload.replace("\\\\", "\\").replace("\\'", "'")
    unpacked = re.sub(r"\b\w+\b", lookup, payload, flags=re.ASCII)
    unpacked = _replace_packer_string_table(unpacked)
    start, end = header.start(), header.start() + args.end()
    return html_or_js[:start] + unpacked + html_or_js[end:]


def validate_spot_extraction(dates: list[Any], prices: list[Any]) -> str | None:
    """校验 100ppi 提取结果；返回 None 表示可安全落盘，否则返回拒绝原因。"""
    if not dates or not prices:
        return "日期或价格数组为空"
    if len(dates) != len(prices):
        return f"日期/价格长度不一致: dates={len(dates)} prices={len(prices)}"

    valid_count = 0
    for d_str, p_val in zip(dates, prices, strict=False):
        try:
            date.fromisoformat(str(d_str).strip())
        except (TypeError, ValueError):
            return f"非法日期: {d_str!r}"
        if p_val is None or p_val == "-":
            continue
        try:
            float(p_val)
        except (TypeError, ValueError):
            return f"非法价格: {p_val!r}"
        valid_count += 1

    if valid_count == 0:
        return "无可解析的价格记录"
    return None


def parse_100ppi_chart_text(
    html_or_js: str,
    symbol: str,
    meta: dict[str, Any] | None = None,
    collected_at: str | None = None,
    raw_sha256: str = "",
    raw_snapshot_path: str = "",
) -> list[ChemicalSpotPriceRecord]:
    """从 100ppi cindex 页面或解包 JS 中提取日期与价格数组。"""
    canonical_symbol = COMMODITY_CATALOG_ALIASES.get(symbol, symbol)
    meta = meta or COMMODITY_CATALOG.get(symbol) or COMMODITY_CATALOG.get(canonical_symbol, {})
    product_name = meta.get("product_name", symbol)
    default_spec = meta.get("spec", "")
    default_region = meta.get("region", "国内")
    unit = meta.get("unit", "元/吨")
    ppid = meta.get("ppid", 0)
    source_url = f"https://www.100ppi.com/graph/cindex.php?f=graph_ave&ppid={ppid}&type=1&mode=3"

    now_iso = collected_at or datetime.now(UTC).isoformat()

    # 若页面 JS 为 Dean Edwards Packer 混淆，先解包再正则提取
    text_to_search = unpack_100ppi_packer(html_or_js)

    # 匹配 xAxis 日期数组
    m_x = re.search(r"xAxis:[\s\S]*?data:\s*(\[[^\]]+\])", text_to_search)
    # 匹配 series 价格数组
    m_y = re.search(r"series:[\s\S]*?data:\s*(\[[^\]]+\])", text_to_search)

    if not m_x or not m_y:
        return []

    try:
        raw_dates_str = m_x.group(1).replace("'", '"')
        raw_dates_str = re.sub(r",\s*\]", "]", raw_dates_str)
        dates = json.loads(raw_dates_str)

        raw_prices_str = m_y.group(1).replace("'", '"')
        raw_prices_str = re.sub(r",\s*\]", "]", raw_prices_str)
        prices = json.loads(raw_prices_str)
    except Exception as e:
        logger.debug("解析日期或价格 JSON 失败 [%s]: %s", symbol, e)
        return []

    records: list[ChemicalSpotPriceRecord] = []
    for d_str, p_val in zip(dates, prices, strict=False):
        if not d_str or p_val is None or p_val == "-":
            continue
        try:
            t_date = date.fromisoformat(str(d_str).strip())
            price = float(p_val)
        except (ValueError, TypeError):
            continue

        records.append(
            ChemicalSpotPriceRecord(
                product_name=product_name,
                symbol=symbol,
                trade_date=t_date,
                spot_price_cny=price,
                spec=default_spec,
                region=default_region,
                unit=unit,
                source="100ppi",
                source_url=source_url,
                release_date=previous_weekday(t_date),
                data_status="spot_benchmark",
                collected_at=now_iso,
                raw_content_sha256=raw_sha256,
                raw_snapshot_path=raw_snapshot_path,
            )
        )
    return records


__all__ = [
    "COMMODITY_CATALOG",
    "COMMODITY_CATALOG_ALIASES",
    "parse_100ppi_chart_text",
    "previous_weekday",
    "unpack_100ppi_packer",
    "validate_spot_extraction",
]
