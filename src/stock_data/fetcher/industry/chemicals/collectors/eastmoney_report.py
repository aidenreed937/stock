"""东方财富研报中心 (EastMoney) 化工产业研报自动化采集与关键产能页抽取器。

职责:
1. 在线抓取东方财富公开研报元数据列表 (行业深度报告 / 品种月报);
2. 依据化工细分品种关键词 (烧碱/PVC/PTA/甲醇/尿素/玻璃等) 进行语义过滤与匹配;
3. 下载原始 PDF 物理快照，计算 SHA-256 哈希值建立不可篡改的存证底账;
4. 运用 pypdf 定位包含“产能”、“供需平衡”、“万吨”、“开工率”的关键页并抽取结构化文本段落;
5. 生成带审计溯源的 manifest 索引表，为人工核验与入库提供生产级证据链。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from stock_data.fetcher.industry.common import now_utc_iso

logger = logging.getLogger(__name__)

# 默认监控的核心化工品关键词映射表
CHEMICAL_PRODUCT_KEYWORDS: dict[str, list[str]] = {
    "caustic_soda": ["烧碱", "离子膜", "液碱", "固碱", "氯碱"],
    "pvc": ["聚氯乙烯", "PVC", "电石法", "乙烯法", "氯碱"],
    "pta": ["PTA", "精对苯二甲酸", "对苯二甲酸", "聚酯"],
    "methanol": ["甲醇", "煤制甲醇", "天然气制甲醇"],
    "urea": ["尿素", "氮肥", "合成氨", "农化"],
    "plate_glass": ["平板玻璃", "浮法玻璃", "光伏玻璃", "玻璃"],
    "synthetic_fiber": ["合成纤维", "涤纶", "粘胶短纤", "锦纶", "化纤"],
    "soda_ash": ["纯碱", "天然碱", "联碱", "氨碱", "重碱", "轻碱"],
}

# 判定为产能供需关键页的特征关键词
CAPACITY_TRIGGER_WORDS = [
    "总产能",
    "有效产能",
    "设计产能",
    "产能及增速",
    "供需平衡",
    "供需格局",
    "新增产能",
    "扩产",
    "万吨/年",
    "万吨",
    "开工率",
    "投产",
]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


@dataclass
class ReportItem:
    """东方财富研报元数据实体。"""

    info_code: str
    title: str
    org_name: str
    publish_date: str
    industry_name: str
    authors: list[str]
    pdf_url: str
    matched_products: list[str]


@dataclass
class ExtractedSection:
    """关键页抽取结果。"""

    page_number: int
    matched_keywords: list[str]
    snippet: str


@dataclass
class ReportSnapshotRecord:
    """物理快照存证记录。"""

    info_code: str
    title: str
    org_name: str
    publish_date: str
    pdf_path: str
    sha256: str
    file_size_kb: float
    matched_products: list[str]
    extracted_sections: list[dict[str, Any]]
    collected_at: str


class EastmoneyReportCollector:
    """东方财富行业研报在线采集与 PDF 产能分析器。"""

    LIST_API_URL = "https://reportapi.eastmoney.com/report/list"

    def __init__(
        self,
        raw_pdf_dir: Path | str = "data/raw/industry/chemicals/capacity/raw_pdfs",
        enable_network: bool = True,
    ) -> None:
        self.raw_pdf_dir = Path(raw_pdf_dir)
        self.enable_network = enable_network
        self.manifest_path = self.raw_pdf_dir / "manifest.json"

    def fetch_report_list(
        self,
        page_no: int = 1,
        page_size: int = 50,
        begin_time: str = "2024-01-01",
        end_time: str | None = None,
        q_type: str = "1",  # 1 为行业研报
    ) -> list[dict[str, Any]]:
        """从东方财富分页获取研报元数据原始 JSON 列表。"""
        if not self.enable_network:
            logger.info("离线模式：跳过网络研报元数据请求")
            return []

        if end_time is None:
            end_time = date.today().strftime("%Y-%m-%d")

        params = {
            "industryCode": "*",
            "pageSize": str(page_size),
            "industry": "*",
            "rating": "*",
            "ratingChange": "*",
            "beginTime": begin_time,
            "endTime": end_time,
            "pageNo": str(page_no),
            "fields": "",
            "qType": q_type,
            "p": str(page_no),
            "pageNum": str(page_no),
            "pageNumber": str(page_no),
        }
        query_str = urllib.parse.urlencode(params)
        req = urllib.request.Request(  # noqa: S310
            f"{self.LIST_API_URL}?{query_str}",
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "https://data.eastmoney.com/report/industry.jshtml",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                data = json.loads(resp.read().decode("utf-8"))
                return list(data.get("data", []))
        except Exception as exc:
            logger.warning(f"东财研报列表 API 请求失败 (page={page_no}): {exc}")
            return []

    def filter_reports(
        self,
        raw_items: list[dict[str, Any]],
        target_products: list[str] | None = None,
    ) -> list[ReportItem]:
        """按目标化工品种关键词匹配过滤相关研报。"""
        if target_products is None:
            target_products = list(CHEMICAL_PRODUCT_KEYWORDS.keys())

        matched_list: list[ReportItem] = []
        for it in raw_items:
            info_code = str(it.get("infoCode") or "").strip()
            title = str(it.get("title") or "").strip()
            ind_name = str(it.get("industryName") or "").strip()
            org_name = str(it.get("orgSName") or it.get("orgName") or "").strip()
            pub_date = str(it.get("publishDate") or "")[:10]

            if not info_code or not title:
                continue

            # 匹配目标品种
            matched_prods: list[str] = []
            for prod in target_products:
                keywords = CHEMICAL_PRODUCT_KEYWORDS.get(prod, [prod])
                if any(kw in title or kw in ind_name for kw in keywords):
                    matched_prods.append(prod)

            if matched_prods:
                authors_str = str(it.get("researcher") or it.get("author") or "")
                authors = [a.strip() for a in authors_str.split(",") if a.strip()]
                pdf_url = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
                matched_list.append(
                    ReportItem(
                        info_code=info_code,
                        title=title,
                        org_name=org_name,
                        publish_date=pub_date,
                        industry_name=ind_name,
                        authors=authors,
                        pdf_url=pdf_url,
                        matched_products=matched_prods,
                    )
                )

        return matched_list

    def download_pdf(self, item: ReportItem, force: bool = False) -> tuple[Path | None, str | None]:
        """下载单篇研报 PDF 并计算 SHA-256 哈希值存证。"""
        self.raw_pdf_dir.mkdir(parents=True, exist_ok=True)
        pdf_filename = f"{item.publish_date}_{item.org_name}_{item.info_code}.pdf"
        # 移除非法字符
        safe_filename = re.sub(r'[\\/*?:"<>|]', "", pdf_filename)
        dest_path = self.raw_pdf_dir / safe_filename

        if dest_path.exists() and not force:
            content = dest_path.read_bytes()
            sha256_val = hashlib.sha256(content).hexdigest()
            return dest_path, sha256_val

        if not self.enable_network:
            logger.debug(f"离线模式，跳过下载: {item.pdf_url}")
            return None, None

        req = urllib.request.Request(  # noqa: S310
            item.pdf_url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Referer": "https://data.eastmoney.com/report/industry.jshtml",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
                pdf_bytes = resp.read()
                dest_path.write_bytes(pdf_bytes)
                sha256_val = hashlib.sha256(pdf_bytes).hexdigest()
                logger.info(
                    f"成功下载研报快照: {dest_path.name} "
                    f"({len(pdf_bytes) / 1024:.1f} KB, sha256={sha256_val[:12]}...)"
                )
                return dest_path, sha256_val
        except Exception as exc:
            logger.warning(f"下载研报 PDF 失败 [{item.title}]: {exc}")
            return None, None

    def extract_capacity_sections(
        self,
        pdf_path: Path,
        max_snippet_chars: int = 500,
    ) -> list[ExtractedSection]:
        """使用 pypdf 定位包含产能/供需关键字的页码，并提取文本片段。"""
        if not pdf_path.exists():
            return []

        extracted: list[ExtractedSection] = []
        try:
            reader = PdfReader(str(pdf_path))
            for page_idx, page in enumerate(reader.pages):
                text = page.extract_text() or ""
                matched_kws = [kw for kw in CAPACITY_TRIGGER_WORDS if kw in text]
                if matched_kws:
                    # 抽取前几个代表性段落
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    relevant_lines: list[str] = []
                    for line in lines:
                        if any(kw in line for kw in matched_kws):
                            relevant_lines.append(line)
                        if len("\n".join(relevant_lines)) >= max_snippet_chars:
                            break
                    snippet = "\n".join(relevant_lines[:8])
                    extracted.append(
                        ExtractedSection(
                            page_number=page_idx + 1,
                            matched_keywords=matched_kws,
                            snippet=snippet,
                        )
                    )
        except Exception as exc:
            logger.warning(f"解析 PDF 失败 [{pdf_path.name}]: {exc}")

        return extracted

    def sync_and_extract(
        self,
        target_products: list[str] | None = None,
        max_pages: int = 5,
        download_pdfs: bool = True,
    ) -> list[ReportSnapshotRecord]:
        """端到端编排：抓取元数据 -> 过滤品种 -> 下载快照 -> 提取产能段落 -> 更新 Manifest。"""
        all_raw_items: list[dict[str, Any]] = []
        for p in range(1, max_pages + 1):
            items = self.fetch_report_list(page_no=p)
            if not items:
                break
            all_raw_items.extend(items)

        matched_reports = self.filter_reports(all_raw_items, target_products=target_products)
        logger.info(f"检索到 {len(matched_reports)} 篇化工目标品种研报")

        records: list[ReportSnapshotRecord] = []
        for rep in matched_reports:
            pdf_path, sha256_val = None, None
            sections: list[ExtractedSection] = []
            file_size_kb = 0.0

            if download_pdfs:
                pdf_path, sha256_val = self.download_pdf(rep)
                if pdf_path and pdf_path.exists():
                    file_size_kb = round(pdf_path.stat().st_size / 1024.0, 1)
                    sections = self.extract_capacity_sections(pdf_path)

            rec = ReportSnapshotRecord(
                info_code=rep.info_code,
                title=rep.title,
                org_name=rep.org_name,
                publish_date=rep.publish_date,
                pdf_path=str(pdf_path) if pdf_path else "",
                sha256=sha256_val or "",
                file_size_kb=file_size_kb,
                matched_products=rep.matched_products,
                extracted_sections=[asdict(s) for s in sections],
                collected_at=now_utc_iso(),
            )
            records.append(rec)

        self._save_manifest(records)
        return records

    def _save_manifest(self, new_records: list[ReportSnapshotRecord]) -> None:
        """更新并保存物理快照 manifest 索引清单。"""
        self.raw_pdf_dir.mkdir(parents=True, exist_ok=True)
        manifest_data: dict[str, Any] = {"version": "1.0.0", "reports": {}}

        if self.manifest_path.exists():
            try:
                manifest_data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest_data = {"version": "1.0.0", "reports": {}}

        reports_map = manifest_data.setdefault("reports", {})
        for r in new_records:
            reports_map[r.info_code] = asdict(r)

        manifest_data["updated_at"] = now_utc_iso()
        manifest_data["total_count"] = len(reports_map)
        self.manifest_path.write_text(
            json.dumps(manifest_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"已更新研报存证底账: {self.manifest_path} (共 {len(reports_map)} 篇)")
