"""券商与期货研究所研报 PDF 自动化下载与产业基本面特征提取器 (ResearchReportParser)。

功能与 2-Tier ETL 架构:
1. 自动化检索: 对接东方财富研报中心 API (ak.stock_research_report_em);
2. 文本解析: 基于 pypdf 提取研报全页文本，针对纯碱/PTA/尿素/甲醇/聚酯等大宗化工品;
3. 智能正则提取: 自动抽取各周/各季度的真实开工率、企业库存、行业有效产能与产量;
4. 2-Tier 存储: 提取到的历史序列持久化至 data/raw/industry/chemicals/operating_rates/expert_research_survey.csv;
5. 消除前视偏差: release_date 为研报官方发布当日。
"""

from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pypdf
import requests

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

STANDARD_PRODUCT_SPECS: dict[str, dict[str, Any]] = {
    "SA": {
        "name": "纯碱",
        "aliases": ["纯碱", "SA", "SODA_ASH"],
        "keywords": ["纯碱", "碱厂", "氨碱", "联碱"],
        "downstream_excludes": ["玻璃", "浮法", "光伏", "碳酸锂", "LOW-E", "下游"],
        "rate_range": (60.0, 98.0),
        "output_range": (40.0, 85.0),
        "inventory_range": (15.0, 250.0),
        "national_annual_capacity_w_tons": 3800.0,
    },
    "TIO2": {
        "name": "钛白粉",
        "aliases": ["钛白粉", "TIO2", "TiO2", "TITANIUM_DIOXIDE"],
        "keywords": ["钛白粉", "TiO2", "钛企", "钛白", "二氧化钛"],
        "downstream_excludes": ["涂料", "油漆", "塑料", "造纸", "油墨", "下游"],
        "rate_range": (40.0, 95.0),
        "output_range": (4.0, 18.0),
        "inventory_range": (4.0, 45.0),
        "national_annual_capacity_w_tons": 500.0,
    },
    "V": {
        "name": "聚氯乙烯",
        "aliases": ["聚氯乙烯", "PVC", "V"],
        "keywords": ["聚氯乙烯", "PVC", "电石法", "乙烯法"],
        "downstream_excludes": ["管材", "型材", "薄膜", "地板", "下游", "制品"],
        "rate_range": (50.0, 92.0),
        "output_range": (30.0, 60.0),
        "inventory_range": (15.0, 150.0),
        "national_annual_capacity_w_tons": 2800.0,
    },
    "TA": {
        "name": "精对苯二甲酸",
        "aliases": ["精对苯二甲酸", "PTA", "TA", "对苯二甲酸"],
        "keywords": ["PTA", "精对苯二甲酸", "对苯二甲酸"],
        "downstream_excludes": ["聚酯", "长丝", "短纤", "切片", "瓶片", "织造", "下游"],
        "rate_range": (55.0, 95.0),
        "output_range": (85.0, 165.0),
        "inventory_range": (10.0, 120.0),
        "national_annual_capacity_w_tons": 8000.0,
    },
    "MEG": {
        "name": "乙二醇",
        "aliases": ["乙二醇", "MEG", "EG"],
        "keywords": ["乙二醇", "MEG", "煤制", "乙烯制"],
        "downstream_excludes": ["聚酯", "防冻液", "下游"],
        "rate_range": (40.0, 88.0),
        "output_range": (20.0, 60.0),
        "inventory_range": (20.0, 160.0),
        "national_annual_capacity_w_tons": 2800.0,
    },
    "MA": {
        "name": "甲醇",
        "aliases": ["甲醇", "MA"],
        "keywords": ["甲醇", "MA", "西北甲醇"],
        "downstream_excludes": ["MTO", "烯烃", "甲醛", "二甲醚", "醋酸", "下游"],
        "rate_range": (55.0, 92.0),
        "output_range": (110.0, 230.0),
        "inventory_range": (20.0, 140.0),
        "national_annual_capacity_w_tons": 10500.0,
    },
    "UR": {
        "name": "尿素",
        "aliases": ["尿素", "UR"],
        "keywords": ["尿素", "气头", "煤头", "固定床", "水煤浆"],
        "downstream_excludes": ["复合肥", "三聚氰胺", "车用尿素", "下游"],
        "rate_range": (55.0, 95.0),
        "output_range": (70.0, 160.0),
        "inventory_range": (15.0, 160.0),
        "national_annual_capacity_w_tons": 7200.0,
    },
    "SH": {
        "name": "烧碱",
        "aliases": ["烧碱", "SH", "离子膜烧碱", "液碱", "片碱"],
        "keywords": ["烧碱", "离子膜", "液碱", "32%液碱"],
        "downstream_excludes": ["氧化铝", "印染", "造纸", "化纤", "下游"],
        "rate_range": (65.0, 92.0),
        "output_range": (50.0, 100.0),
        "inventory_range": (15.0, 85.0),
        "national_annual_capacity_w_tons": 4600.0,
    },
    "EB": {
        "name": "苯乙烯",
        "aliases": ["苯乙烯", "EB"],
        "keywords": ["苯乙烯", "EB", "乙苯脱氢", "PO/SM", "共氧化法"],
        "downstream_excludes": ["PS", "EPS", "ABS", "UPR", "SBR", "下游", "树脂"],
        "rate_range": (45.0, 95.0),
        "output_range": (20.0, 48.0),
        "inventory_range": (3.0, 40.0),
        "national_annual_capacity_w_tons": 2100.0,
    },
    "PP": {
        "name": "聚丙烯",
        "aliases": ["聚丙烯", "PP"],
        "keywords": ["聚丙烯", "PP", "油制PP", "煤制PP", "PDH", "丙烷脱氢"],
        "downstream_excludes": ["编织袋", "BOPP", "注塑", "纤维", "下游", "制品", "无纺布"],
        "rate_range": (50.0, 95.0),
        "output_range": (40.0, 85.0),
        "inventory_range": (10.0, 95.0),
        "national_annual_capacity_w_tons": 3800.0,
    },
    "PX": {
        "name": "对二甲苯",
        "aliases": ["对二甲苯", "PX"],
        "keywords": ["对二甲苯", "PX", "歧化", "重整", "芳烃"],
        "downstream_excludes": ["PTA", "聚酯", "长丝", "短纤", "织造", "下游"],
        "rate_range": (50.0, 95.0),
        "output_range": (45.0, 90.0),
        "inventory_range": (5.0, 60.0),
        "national_annual_capacity_w_tons": 4200.0,
    },
}


def _resolve_product_spec(product_or_symbol: str) -> tuple[str, dict[str, Any]]:
    """根据输入的品种名称或代码解析出标准 symbol 及规格配置。"""
    p_norm = (product_or_symbol or "").strip().upper()
    for sym, spec in STANDARD_PRODUCT_SPECS.items():
        if p_norm == sym or p_norm in [a.upper() for a in spec["aliases"]]:
            return sym, spec
    for sym, spec in STANDARD_PRODUCT_SPECS.items():
        if spec["name"] in product_or_symbol or any(
            a in product_or_symbol for a in spec["aliases"]
        ):
            return sym, spec
    return "SA", STANDARD_PRODUCT_SPECS["SA"]


class ResearchReportParser:
    """研报 PDF 与摘要基本面指标解析器。"""

    def __init__(self, raw_dir: Path | str) -> None:
        self.raw_dir = Path(raw_dir)
        self.out_dir = self.raw_dir / "chemicals" / "operating_rates"
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/128.0.0.0",
        }

    def download_pdf_text(self, pdf_url: str) -> str:
        """下载并解析 PDF 文本。"""
        try:
            r = self.session.get(pdf_url, headers=self.headers, timeout=20)
            if r.status_code != 200:
                return ""
            reader = pypdf.PdfReader(io.BytesIO(r.content))
            full_text = ""
            for page in reader.pages:
                full_text += "\n" + (page.extract_text() or "")
            return full_text
        except Exception as e:
            logger.warning(f"下载或解析 PDF 失败 [{pdf_url}]: {e}")
            return ""

    def extract_metrics_from_text(
        self,
        text: str,
        product_name: str = "纯碱",
        publish_date: date | None = None,
        source_name: str = "Broker_Research",
        source_url: str = "",
        raw_content_sha256: str = "",
        raw_snapshot_path: str = "",
    ) -> list[dict[str, Any]]:
        """从研报文本中通用正则提取多品种周度开工率、企业库存与周产量指标。"""
        results: list[dict[str, Any]] = []
        now_iso = now_utc_iso()
        p_date = _normalize_publish_date(publish_date)
        if p_date is None:
            return results

        sym, spec = _resolve_product_spec(product_name)
        canon_name = spec["name"]
        rate_min, rate_max = spec["rate_range"]
        out_min, out_max = spec["output_range"]
        inv_min, inv_max = spec["inventory_range"]
        keywords = spec["keywords"]
        downstream_kw = spec["downstream_excludes"]

        cleaned = _clean_report_text(text)

        # 尝试从正文中提取更精确的调查截止日 (如 "截止至2022年10月21日")
        survey_date = p_date
        m_sdate = re.search(r"截止[至到]?\s*(\d{4})年(\d{1,2})月(\d{1,2})日", cleaned)
        if m_sdate:
            try:
                candidate_sdate = date(
                    int(m_sdate.group(1)), int(m_sdate.group(2)), int(m_sdate.group(3))
                )
                if candidate_sdate <= p_date and (p_date - candidate_sdate).days <= 30:
                    survey_date = candidate_sdate
            except ValueError:
                pass
        else:
            m_short = re.search(r"(?:截至|本周截至|截至到)\s*(\d{1,2})月(\d{1,2})日", cleaned)
            if m_short:
                try:
                    candidate_sdate = date(
                        p_date.year, int(m_short.group(1)), int(m_short.group(2))
                    )
                    if candidate_sdate <= p_date and (p_date - candidate_sdate).days <= 30:
                        survey_date = candidate_sdate
                except ValueError:
                    pass

        # 1. 匹配开工率 / 产能利用率:
        rate_candidates: list[float] = []

        # 模式 1A: 包含品种主语的主动表述 (如 "纯碱综合产能利用率78.31%", "钛白粉开工率不足70%")
        for kw in keywords:
            for m in re.finditer(
                rf"{re.escape(kw)}[^\d%。\n]{{0,25}}?(?:综合产能利用率|产能利用率|开工率|开工负荷|整体负荷)[^\d%]{{0,15}}?(?:为|至|在|达|来到|不足|约为|:|：)?\s*([3-9]\d(?:\.\d+)?)%",
                cleaned,
                re.IGNORECASE,
            ):
                rate_candidates.append(float(m.group(1)))

            for m in re.finditer(
                rf"{re.escape(kw)}[^\d%。\n]{{0,35}}?(?:开工率|产能利用率|开工负荷)[^。；\n]{{0,30}}?(?:至|来到|在|达|为)\s*([3-9]\d(?:\.\d+)?)%",
                cleaned,
                re.IGNORECASE,
            ):
                rate_candidates.append(float(m.group(1)))

        # 模式 1B: 通用主体陈述 (如 "行业整体开工率不足70%", "国内企业整体产能利用率78.31%")
        if not rate_candidates:
            for m in re.finditer(
                r"(?:行业整体|行业|综合|全国|国内)?(?:产能利用率|开工率|开工负荷)[^\d%]{0,15}?(?:为|至|在|达|来到|不足|约为|:|：)?\s*([3-9]\d(?:\.\d+)?)%",
                cleaned,
            ):
                start = max(0, m.start() - 40)
                end = min(len(cleaned), m.end() + 20)
                ctx = cleaned[start:end]
                if any(dk in ctx for dk in downstream_kw):
                    continue
                if any(
                    bad in ctx
                    for bad in [
                        "个别企业",
                        "两家",
                        "龙头企业",
                        "降负荷",
                        "下降到",
                        "上升到",
                        "产销比",
                        "产销率",
                    ]
                ):
                    continue
                rate_candidates.append(float(m.group(1)))

        valid_rates = [r for r in rate_candidates if rate_min <= r <= rate_max]
        op_rate = valid_rates[0] if valid_rates else None

        # 2. 匹配企业库存 (万吨):
        inv_candidates: list[float] = []
        for kw in keywords:
            # 带变动达到的目标库存 (如 "纯碱厂家总库存较上周下降1.18万吨至184.49万吨")
            for m in re.finditer(
                rf"{re.escape(kw)}[^\d万吨。\n]{{0,25}}?(?:厂家总库存|厂内库存|企业总库存|企业库存|厂家库存|工厂库存|总库存)[^。；\n]{{0,35}}?(?:去库|去|增加|累库|减少|降|增)[\d.]+\s*万吨[^。；\n]{{0,15}}?(?:至|来到|在|达)\s*([1-9]\d{{0,2}}(?:\.\d+)?)\s*万吨",
                cleaned,
                re.IGNORECASE,
            ):
                inv_candidates.append(float(m.group(1)))

            # 直接陈述总库存 (如 "纯碱厂家总库存184.49万吨")
            for m in re.finditer(
                rf"{re.escape(kw)}[^\d万吨。\n]{{0,25}}?(?:厂家总库存|厂内库存|企业总库存|企业库存|厂家库存|工厂库存)[^。；\n]{{0,15}}?(?:为|在|达|至|达到|约为|:|：)?\s*([1-9]\d{{0,2}}(?:\.\d+)?)\s*万吨",
                cleaned,
                re.IGNORECASE,
            ):
                pre_start = max(0, m.start() - 20)
                pre_text = cleaned[pre_start : m.start()]
                last_punct = max(
                    pre_text.rfind("，"),
                    pre_text.rfind("。"),
                    pre_text.rfind("；"),
                    pre_text.rfind(" "),
                    pre_text.rfind("："),
                    pre_text.rfind(":"),
                )
                clause_pre = pre_text[last_punct + 1 :] if last_punct != -1 else pre_text
                if any(
                    bad in clause_pre
                    for bad in [
                        "增幅",
                        "降幅",
                        "环比",
                        "较上周",
                        "去库",
                        "累库",
                        "减少",
                        "增加",
                        "最低达到",
                        "最高达到",
                        "轻碱",
                        "重碱",
                        "交割库",
                        "社会",
                        "贸易",
                    ]
                ):
                    continue
                inv_candidates.append(float(m.group(1)))

        if not inv_candidates:
            for m in re.finditer(
                r"(?:国内|全国|行业)?(?:厂家总库存|厂内库存|企业总库存|企业库存|厂家库存)[^。；\n]{0,15}?(?:为|在|达|至|达到|约为|:|：)?\s*([1-9]\d{0,2}(?:\.\d+)?)\s*万吨",
                cleaned,
            ):
                pre_start = max(0, m.start() - 20)
                pre_text = cleaned[pre_start : m.start()]
                last_punct = max(
                    pre_text.rfind("，"),
                    pre_text.rfind("。"),
                    pre_text.rfind("；"),
                    pre_text.rfind(" "),
                    pre_text.rfind("："),
                    pre_text.rfind(":"),
                )
                clause_pre = pre_text[last_punct + 1 :] if last_punct != -1 else pre_text
                if any(
                    bad in clause_pre
                    for bad in [
                        "增幅",
                        "降幅",
                        "环比",
                        "较上周",
                        "去库",
                        "累库",
                        "减少",
                        "增加",
                        "最低达到",
                        "最高达到",
                        "轻碱",
                        "重碱",
                        "交割库",
                        "社会",
                        "贸易",
                    ]
                ):
                    continue
                if any(dk in clause_pre for dk in downstream_kw):
                    continue
                inv_candidates.append(float(m.group(1)))

        valid_invs = [iv for iv in inv_candidates if inv_min <= iv <= inv_max]
        inv_val = valid_invs[0] if valid_invs else None

        # 3. 匹配周度产量 (万吨):
        out_candidates: list[float] = []
        for kw in keywords:
            for m in re.finditer(
                rf"(?:周内|本周|当周)?{re.escape(kw)}[^\d万吨。\n]{{0,20}}?(?:周度产量|周产量|实物产量|产量)[^。；\n]{{0,25}}?(?:至|来到|在|达|为|约为|:|：)?\s*([1-9]\d{{0,2}}(?:\.\d+)?)\s*万吨",
                cleaned,
                re.IGNORECASE,
            ):
                matched_str = m.group(0)
                pre_start = max(0, m.start() - 15)
                pre_text = cleaned[pre_start : m.start()]
                last_punct = max(
                    pre_text.rfind("，"),
                    pre_text.rfind("。"),
                    pre_text.rfind("；"),
                    pre_text.rfind(" "),
                )
                clause_pre = pre_text[last_punct + 1 :] if last_punct != -1 else pre_text
                check_text = clause_pre + matched_str
                if not any(
                    bad in check_text
                    for bad in [
                        "重碱",
                        "轻碱",
                        "预计",
                        "预期",
                        "重心",
                        "展望",
                        "规划",
                        "月度",
                        "年产能",
                        "总产能",
                        "年产",
                    ]
                ):
                    out_candidates.append(float(m.group(1)))

        if not out_candidates:
            for m in re.finditer(
                r"(?:周内|本周|当周)?(?:行业|全国|国内)?(?:周度产量|周产量)[^\d]{0,15}?(?:为|在|达|至|来到|约为|:|：)?\s*([1-9]\d{0,2}(?:\.\d+)?)\s*万吨",
                cleaned,
            ):
                matched_str = m.group(0)
                pre_start = max(0, m.start() - 15)
                pre_text = cleaned[pre_start : m.start()]
                last_punct = max(
                    pre_text.rfind("，"),
                    pre_text.rfind("。"),
                    pre_text.rfind("；"),
                    pre_text.rfind(" "),
                )
                clause_pre = pre_text[last_punct + 1 :] if last_punct != -1 else pre_text
                check_text = clause_pre + matched_str
                if not any(
                    bad in check_text
                    for bad in [
                        "重碱",
                        "轻碱",
                        "预计",
                        "预期",
                        "重心",
                        "展望",
                        "规划",
                        "月度",
                        "年产能",
                        "总产能",
                        "年产",
                    ]
                ):
                    if not any(dk in check_text for dk in downstream_kw):
                        out_candidates.append(float(m.group(1)))

        valid_outs = [ov for ov in out_candidates if out_min <= ov <= out_max]
        out_val = valid_outs[0] if valid_outs else None

        # P2 物理质量守恒闭环校验 (Mass Conservation Gate)
        annual_cap = spec.get("national_annual_capacity_w_tons")
        if annual_cap and op_rate is not None and out_val is not None:
            expected_weekly_output = (annual_cap / 52.0) * (op_rate / 100.0)
            deviation = abs(out_val - expected_weekly_output) / expected_weekly_output
            if deviation > 0.35:
                logger.warning(
                    "品种 %s 周产量 (%.2f万吨) 与开工率 (%.1f%%) 折算理论全国周产 (%.2f万吨) 偏差 %.1f%% > 35%%，判定为局部样本产量隔离",
                    sym,
                    out_val,
                    op_rate,
                    expected_weekly_output,
                    deviation * 100.0,
                )
                out_val = None

        if op_rate is not None or inv_val is not None or out_val is not None:
            results.append(
                {
                    "trade_date": survey_date,
                    "report_date": survey_date,
                    "product_name": canon_name,
                    "symbol": sym,
                    "operating_rate_pct": op_rate,
                    "weekly_output_w_tons": out_val,
                    "factory_inventory_w_tons": inv_val,
                    "shipment_rate_pct": None,
                    "source": source_name,
                    "source_url": source_url,
                    "release_date": p_date,
                    "data_status": "actual",
                    "collected_at": now_iso,
                    "raw_content_sha256": raw_content_sha256,
                    "raw_snapshot_path": raw_snapshot_path,
                }
            )

        # 双周补全：检查是否披露“上周”指标
        prev_rate = None
        m_pr = re.search(
            r"(?:环比上周|上周(?:同期)?|较上周)[^\d%]{0,12}?(?:为|在|达|至)?\s*([3-9]\d(?:\.\d+)?)%",
            cleaned,
        )
        if m_pr:
            cand_pr = float(m_pr.group(1))
            if rate_min <= cand_pr <= rate_max:
                prev_rate = cand_pr

        prev_inv = None
        m_pi = re.search(
            r"上周(?:厂家总库存|厂内库存|企业库存|厂家库存|总库存)[^\d]{0,12}?(?:为|在|达|至)?\s*([1-9]\d{0,2}(?:\.\d+)?)\s*万吨",
            cleaned,
        )
        if m_pi:
            cand_pi = float(m_pi.group(1))
            if inv_min <= cand_pi <= inv_max:
                prev_inv = cand_pi

        if prev_rate is not None or prev_inv is not None:
            prev_date = survey_date - timedelta(days=7)
            results.append(
                {
                    "trade_date": prev_date,
                    "report_date": prev_date,
                    "product_name": canon_name,
                    "symbol": sym,
                    "operating_rate_pct": prev_rate,
                    "weekly_output_w_tons": None,
                    "factory_inventory_w_tons": prev_inv,
                    "shipment_rate_pct": None,
                    "source": source_name,
                    "source_url": source_url,
                    "release_date": p_date,
                    "data_status": "actual",
                    "collected_at": now_iso,
                    "raw_content_sha256": raw_content_sha256,
                    "raw_snapshot_path": raw_snapshot_path,
                }
            )

        return results

    def save_survey_to_csv(
        self,
        records: list[dict[str, Any]],
        csv_path: Path | str | None = None,
    ) -> Path:
        """将提取到的周度调查指标原子去重保存至 CSV (默认 expert_research_survey.csv)。"""
        target = Path(csv_path) if csv_path else self.out_dir / "expert_research_survey.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "trade_date",
            "report_date",
            "product_name",
            "symbol",
            "operating_rate_pct",
            "weekly_output_w_tons",
            "factory_inventory_w_tons",
            "shipment_rate_pct",
            "source",
            "source_url",
            "release_date",
            "data_status",
            "collected_at",
            "raw_content_sha256",
            "raw_snapshot_path",
        ]
        existing_rows: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str, str]] = set()

        if target.exists():
            with target.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (
                        str(row.get("product_name") or ""),
                        str(row.get("report_date") or ""),
                        str(row.get("source") or ""),
                    )
                    if key not in seen_keys:
                        seen_keys.add(key)
                        existing_rows.append(row)

        for rec in records:
            key = (
                str(rec.get("product_name") or ""),
                str(rec.get("report_date") or ""),
                str(rec.get("source") or ""),
            )
            clean_rec = {k: rec.get(k, "") for k in fieldnames}
            if key not in seen_keys:
                seen_keys.add(key)
                existing_rows.append(clean_rec)
            else:
                for item in existing_rows:
                    if (
                        str(item.get("product_name") or ""),
                        str(item.get("report_date") or ""),
                        str(item.get("source") or ""),
                    ) == key:
                        for fn in fieldnames:
                            val = rec.get(fn)
                            if val not in (None, "", "None"):
                                item[fn] = val
                        break

        existing_rows.sort(
            key=lambda item: (
                str(item.get("product_name") or ""),
                str(item.get("report_date") or ""),
                str(item.get("source") or ""),
            )
        )

        with target.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)

        return target

    def batch_parse_local_directory(
        self,
        pdf_dir: Path | str,
        product_name: str = "纯碱",
        default_source: str = "Broker_Research",
    ) -> list[dict[str, Any]]:
        """批量解析本地目录中的研报 PDF 文件。"""
        dir_path = Path(pdf_dir)
        if not dir_path.exists():
            return []

        all_records: list[dict[str, Any]] = []
        for pdf_file in sorted(dir_path.glob("*.pdf")):
            try:
                reader = pypdf.PdfReader(str(pdf_file))
                full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
                # 尝试从文件名推断发布日期 (如 2024-05-16_中信期货_纯碱周报.pdf)
                date_match = re.search(r"(20\d{2}[-_/]\d{1,2}[-_/]\d{1,2})", pdf_file.name)
                p_date = None
                if date_match:
                    p_date = _normalize_publish_date(date_match.group(1))
                if p_date is None:
                    # 尝试从正文首段匹配发布日期
                    doc_date_match = re.search(r"(20\d{2}年\d{1,2}月\d{1,2}日)", full_text[:500])
                    if doc_date_match:
                        p_date = _normalize_publish_date(doc_date_match.group(1))

                if p_date is None:
                    logger.warning("跳过未找到发布日期的研报: %s", pdf_file.name)
                    continue

                records = self.extract_metrics_from_text(
                    text=full_text,
                    product_name=product_name,
                    publish_date=p_date,
                    source_name=f"{default_source}:{pdf_file.stem}",
                    source_url=str(pdf_file.name),
                )
                all_records.extend(records)
            except Exception as exc:
                logger.warning("解析 PDF 失败 [%s]: %s", pdf_file.name, exc)

        return all_records

    def parse_symbol_reports(
        self,
        symbol: str = "000683",
        product_name: str = "纯碱",
        max_reports: int = 15,
    ) -> list[dict[str, Any]]:
        """批量拉取并解析指定股票的深度研报。"""
        import akshare as ak

        records: list[dict[str, Any]] = []
        try:
            df_rep = ak.stock_research_report_em(symbol=symbol)
            if df_rep is None or df_rep.empty:
                return []

            for _, row in df_rep.head(max_reports).iterrows():
                p_d = row["日期"]
                org = str(row["机构"])
                title = str(row["报告名称"])
                pdf_url = str(row["报告PDF链接"])

                # 优先解析标题与摘要
                text = f"{title}\n"
                # 下载并解析 PDF
                if pdf_url and pdf_url.startswith("http"):
                    pdf_text = self.download_pdf_text(pdf_url)
                    text += "\n" + pdf_text

                extracted = self.extract_metrics_from_text(
                    text=text,
                    product_name=product_name,
                    publish_date=p_d,
                    source_name=f"{org}_Research",
                    source_url=pdf_url,
                )
                records.extend(extracted)
        except Exception as e:
            logger.warning(f"批量拉取研报失败 [{symbol}]: {e}")

        return records

    def extract_prices_from_text(
        self,
        text: str,
        publish_date: date | None = None,
        source_name: str = "Broker_Research",
        source_url: str = "",
    ) -> list[dict[str, Any]]:
        """从券商化工周报文本中结构化提取大宗原料与产品现货均价。

        覆盖关键品种：
        1. 钛精矿 (ilmenite): 攀西 46% 钛精矿 (合理区间 1500 ~ 3200 元/吨)
        2. 浓硫酸 (H2SO4): 98% 工业级浓硫酸 (合理区间 80 ~ 1500 元/吨)
        3. 钛白粉 (TiO2): 金红石型硫酸法出厂价 (合理区间 10000 ~ 26000 元/吨)

        严格消除前视偏差：release_date 绑定研报官方发布日。
        """
        results: list[dict[str, Any]] = []
        now_iso = now_utc_iso()
        p_date = _normalize_publish_date(publish_date)
        if p_date is None:
            return results

        cleaned = _clean_report_text(text)

        # 尝试从正文中提取精确调查截止日
        survey_date = p_date
        m_sdate = re.search(r"截止[至到]?\s*(\d{4})年(\d{1,2})月(\d{1,2})日", cleaned)
        m_drange = re.search(
            r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*[-~至到—]\s*(?:(\d{4})年)?(?:(\d{1,2})月)?(\d{1,2})日",
            cleaned,
        )
        if m_sdate:
            try:
                candidate = date(
                    int(m_sdate.group(1)), int(m_sdate.group(2)), int(m_sdate.group(3))
                )
                if candidate <= p_date and (p_date - candidate).days <= 30:
                    survey_date = candidate
            except ValueError:
                pass
        elif m_drange:
            try:
                y2 = int(m_drange.group(4)) if m_drange.group(4) else int(m_drange.group(1))
                m2 = int(m_drange.group(5)) if m_drange.group(5) else int(m_drange.group(2))
                d2 = int(m_drange.group(6))
                candidate = date(y2, m2, d2)
                if candidate <= p_date and (p_date - candidate).days <= 30:
                    survey_date = candidate
            except ValueError:
                pass
        else:
            m_short = re.search(r"截至\s*(\d{1,2})月(\d{1,2})日", cleaned)
            if m_short:
                try:
                    candidate = date(p_date.year, int(m_short.group(1)), int(m_short.group(2)))
                    if candidate <= p_date and (p_date - candidate).days <= 30:
                        survey_date = candidate
                except ValueError:
                    pass

        # 1. 钛精矿 (ilmenite 46%)
        # 模式: "攀西钛精矿(46%)价格为 2220 元/吨" / "攀西10钛精矿（TiO2≥46%，低磷）主流报价现金不含税出厂1440～1600元/吨" / "2200-2250元/吨"
        ilmenite_price: float | None = None
        m_range = re.search(
            r"(?:攀西)?(?:10#?|46%?)?钛精矿[（(][^）)]*[）)]?[^\d元]{0,35}?(?:出厂|在|为|报|：|:)?\s*([12]\d{3})\s*[-~～–—至到]\s*([12]\d{3})\s*(?:元/吨|元)",
            cleaned,
        )
        if m_range:
            p_low, p_high = float(m_range.group(1)), float(m_range.group(2))
            if 1000.0 <= p_low <= 3200.0 and 1000.0 <= p_high <= 3200.0:
                ilmenite_price = round((p_low + p_high) / 2.0, 1)

        if ilmenite_price is None:
            m_range_simple = re.search(
                r"(?:攀西)?钛精矿[^\d元]{0,25}?(?:在|为)?\s*([12]\d{3})\s*[-~～–—至到]\s*([12]\d{3})\s*(?:元/吨|元)",
                cleaned,
            )
            if m_range_simple:
                p_low, p_high = float(m_range_simple.group(1)), float(m_range_simple.group(2))
                if 1000.0 <= p_low <= 3200.0 and 1000.0 <= p_high <= 3200.0:
                    ilmenite_price = round((p_low + p_high) / 2.0, 1)

        if ilmenite_price is None:
            for m in re.finditer(
                r"(?:攀西)?(?:10#?|46%?)?钛精矿(?:[（(][^）)]*[）)])?[^\d元]{0,35}?(?:为|在|达|至|报|:|：)?\s*([12]\d{3}(?:\.\d+)?)\s*(?:元/吨|元)",
                cleaned,
            ):
                val = float(m.group(1))
                if 1000.0 <= val <= 3200.0:
                    ilmenite_price = val
                    break

        if ilmenite_price is not None:
            results.append(
                {
                    "trade_date": survey_date,
                    "report_date": survey_date,
                    "product_name": "钛精矿",
                    "symbol": "ilmenite",
                    "spec": "46%;攀西",
                    "spot_price_cny": ilmenite_price,
                    "unit": "元/吨",
                    "source": source_name,
                    "source_url": source_url,
                    "release_date": p_date,
                    "data_status": "verified_industry_report",
                    "collected_at": now_iso,
                }
            )

        # 2. 浓硫酸 (H2SO4 98%)
        # 模式: "98%浓硫酸价格为 350 元/吨" / "浓硫酸(98%) 350元/吨" / "硫酸(98%工业级)报350元/吨"
        acid_price: float | None = None
        m_acid_range = re.search(
            r"(?:98%|工业级)?(?:浓硫酸|硫酸)(?:[（(]98%[）)])?[^\d元]{0,25}?(?:为|在|达|至|报|:|：)?\s*([1-9]\d{1,3})\s*[-~～–—至到]\s*([1-9]\d{1,3})\s*(?:元/吨|元)",
            cleaned,
        )
        if m_acid_range:
            a_low, a_high = float(m_acid_range.group(1)), float(m_acid_range.group(2))
            if 80.0 <= a_low <= 2500.0 and 80.0 <= a_high <= 2500.0:
                acid_price = round((a_low + a_high) / 2.0, 1)

        if acid_price is None:
            for m in re.finditer(
                r"(?:98%|工业级)?(?:浓硫酸|硫酸)(?:[（(]98%[）)])?[^\d元]{0,25}?(?:为|在|达|至|报|:|：)?\s*([1-9]\d{1,3}(?:\.\d+)?)\s*(?:元/吨|元)",
                cleaned,
            ):
                start = max(0, m.start() - 20)
                prefix = cleaned[start : m.start()]
                if any(
                    bad in prefix for bad in ["折百", "运费", "跌", "涨", "跌幅", "涨幅", "环比"]
                ):
                    continue
                val = float(m.group(1))
                if 80.0 <= val <= 2500.0:
                    acid_price = val
                    break

        if acid_price is not None:
            results.append(
                {
                    "trade_date": survey_date,
                    "report_date": survey_date,
                    "product_name": "硫酸",
                    "symbol": "H2SO4",
                    "spec": "98%;工业级浓硫酸",
                    "spot_price_cny": acid_price,
                    "unit": "元/吨",
                    "source": source_name,
                    "source_url": source_url,
                    "release_date": p_date,
                    "data_status": "verified_industry_report",
                    "collected_at": now_iso,
                }
            )

        # 3. 钛白粉 (TiO2 金红石型硫酸法)
        # 模式: "金红石型钛白粉出厂价为 14500 元/吨" / "硫酸法金红石钛白粉主流报价含税承兑16200～17000元/吨"
        tio2_price: float | None = None
        m_tio2_range = re.search(
            r"(?:硫酸法)?(?:金红石(?:型)?)?钛白粉[^\d元]{0,35}?(?:出厂|在|为|报|：|:)?\s*(1[0-9]\d{3})\s*[-~～–—至到]\s*(1[0-9]\d{3})\s*(?:元/吨|元)",
            cleaned,
        )
        if m_tio2_range:
            t_low, t_high = float(m_tio2_range.group(1)), float(m_tio2_range.group(2))
            if 10000.0 <= t_low <= 26000.0 and 10000.0 <= t_high <= 26000.0:
                tio2_price = round((t_low + t_high) / 2.0, 1)

        if tio2_price is None:
            for m in re.finditer(
                r"(?:硫酸法)?(?:金红石(?:型)?)?钛白粉(?:[（(][^）)]*[）)])?[^\d元]{0,35}?(?:为|在|达|至|报|:|：)?\s*(1[0-9]\d{3}(?:\.\d+)?)\s*(?:元/吨|元)",
                cleaned,
            ):
                val = float(m.group(1))
                if 10000.0 <= val <= 26000.0:
                    tio2_price = val
                    break

        if tio2_price is not None:
            results.append(
                {
                    "trade_date": survey_date,
                    "report_date": survey_date,
                    "product_name": "钛白粉",
                    "symbol": "TiO2",
                    "spec": "金红石型;硫酸法",
                    "spot_price_cny": tio2_price,
                    "unit": "元/吨",
                    "source": source_name,
                    "source_url": source_url,
                    "release_date": p_date,
                    "data_status": "verified_industry_report",
                    "collected_at": now_iso,
                }
            )

        # 4. 海绵钛 (Ti_sponge 0#/1# 主流现货)
        sponge_price: float | None = None
        # 4.1 区间匹配 (元/吨)
        m_sponge_range = re.search(
            r"(?:0#|1#|2#|0级|1级|国内)?海绵钛[^\d元万]{0,35}?(?:出厂|现货|在|为|报|：|:)?\s*([3-9]\d{4})\s*[-~～–—至到]\s*([3-9]\d{4})\s*(?:元/吨|元)",
            cleaned,
        )
        if m_sponge_range:
            s_low, s_high = float(m_sponge_range.group(1)), float(m_sponge_range.group(2))
            if 30000.0 <= s_low <= 100000.0 and 30000.0 <= s_high <= 100000.0:
                sponge_price = round((s_low + s_high) / 2.0, 1)

        # 4.2 区间匹配 (万元/吨)
        if sponge_price is None:
            m_sponge_wan_range = re.search(
                r"(?:0#|1#|2#|0级|1级|国内)?海绵钛[^\d元万]{0,35}?(?:出厂|现货|在|为|报|：|:)?\s*([3-9](?:\.\d+)?)\s*[-~～–—至到]\s*([3-9](?:\.\d+)?)\s*(?:万元/吨|万元)",
                cleaned,
            )
            if m_sponge_wan_range:
                w_low = float(m_sponge_wan_range.group(1)) * 10000.0
                w_high = float(m_sponge_wan_range.group(2)) * 10000.0
                if 30000.0 <= w_low <= 100000.0 and 30000.0 <= w_high <= 100000.0:
                    sponge_price = round((w_low + w_high) / 2.0, 1)

        # 4.3 单值匹配 (元/吨)
        if sponge_price is None:
            for m in re.finditer(
                r"(?:0#|1#|2#|0级|1级|国内)?海绵钛(?:[（(][^）)]*[）)])?[^\d元万]{0,35}?(?:为|在|达|至|报|约|:|：)?\s*([3-9]\d{4}(?:\.\d+)?)\s*(?:元/吨|元)",
                cleaned,
            ):
                start = max(0, m.start() - 20)
                prefix = cleaned[start : m.start()]
                if any(bad in prefix for bad in ["跌", "涨", "跌幅", "涨幅", "环比", "同比"]):
                    continue
                val = float(m.group(1))
                if 30000.0 <= val <= 100000.0:
                    sponge_price = val
                    break

        # 4.4 单值匹配 (万元/吨)
        if sponge_price is None:
            for m in re.finditer(
                r"(?:0#|1#|2#|0级|1级|国内)?海绵钛(?:[（(][^）)]*[）)])?[^\d元万]{0,35}?(?:为|在|达|至|报|约|:|：)?\s*([3-9](?:\.\d+)?)\s*(?:万元/吨|万元)",
                cleaned,
            ):
                start = max(0, m.start() - 20)
                prefix = cleaned[start : m.start()]
                if any(bad in prefix for bad in ["跌", "涨", "跌幅", "涨幅", "环比", "同比"]):
                    continue
                val = float(m.group(1)) * 10000.0
                if 30000.0 <= val <= 100000.0:
                    sponge_price = val
                    break

        if sponge_price is not None:
            results.append(
                {
                    "trade_date": survey_date,
                    "report_date": survey_date,
                    "product_name": "海绵钛",
                    "symbol": "Ti_sponge",
                    "spec": "0级/1级;国内主流",
                    "spot_price_cny": sponge_price,
                    "unit": "元/吨",
                    "source": source_name,
                    "source_url": source_url,
                    "release_date": p_date,
                    "data_status": "verified_industry_report",
                    "collected_at": now_iso,
                }
            )

        return results

    def save_prices_to_csv(
        self,
        records: list[dict[str, Any]],
        csv_path: Path | str | None = None,
    ) -> Path:
        """将提取到的价格记录保存至指定 CSV，支持原子去重更新。"""
        target = Path(csv_path) if csv_path else self.out_dir / "expert_prices_survey.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "trade_date",
            "report_date",
            "product_name",
            "symbol",
            "spec",
            "spot_price_cny",
            "unit",
            "source",
            "source_url",
            "release_date",
            "data_status",
            "collected_at",
        ]
        existing_rows: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()

        if target.exists():
            with target.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = (str(row.get("symbol") or ""), str(row.get("trade_date") or ""))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        existing_rows.append(row)

        for rec in records:
            key = (str(rec.get("symbol") or ""), str(rec.get("trade_date") or ""))
            if key not in seen_keys:
                seen_keys.add(key)
                existing_rows.append(rec)

        existing_rows.sort(
            key=lambda item: (
                str(item.get("product_name") or ""),
                str(item.get("trade_date") or ""),
            )
        )

        with target.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)

        return target


def _clean_report_text(text: str) -> str:
    """清理 PDF 抽取文本中的空格断裂与格式问题。"""
    t = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
    t = re.sub(r"(\d)\s*\.\s*(\d)", r"\1.\2", t)
    t = re.sub(r"(\d)\s*%", r"\1%", t)
    t = re.sub(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", r"\1年\2月\3日", t)
    return re.sub(r"\s+", " ", t)


def _normalize_publish_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10].replace("/", "-"))
    except ValueError:
        return None
