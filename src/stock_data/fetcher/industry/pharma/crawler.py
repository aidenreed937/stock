"""创新药海外 License-out (BD) A/H 股官方交易所公告在线爬虫与提取器。

从巨潮资讯 (CNINFO) 与港交所 (HKEX) 在线抓取医药上市公司的对外许可、授权合作与重大资产出海公告，
并结构化提取首付款、总金额、靶点与模态等商业要素。
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

from curl_cffi import requests

logger = logging.getLogger(__name__)

# 全球跨国药企 (MNC) 识别名录
MNC_BUYERS_MAP: dict[str, str] = {
    "merck": "Merck & Co. / MSD",
    "msd": "Merck & Co. / MSD",
    "默沙东": "Merck & Co. / MSD",
    "novartis": "Novartis",
    "诺华": "Novartis",
    "astrazeneca": "AstraZeneca",
    "阿斯利康": "AstraZeneca",
    "bms": "Bristol Myers Squibb",
    "bristol myers squibb": "Bristol Myers Squibb",
    "百时美施贵宝": "Bristol Myers Squibb",
    "roche": "Roche / Genentech",
    "罗氏": "Roche / Genentech",
    "sanofi": "Sanofi",
    "赛诺菲": "Sanofi",
    "gsk": "GSK (GlaxoSmithKline)",
    "glaxosmithkline": "GSK (GlaxoSmithKline)",
    "葛兰素史克": "GSK (GlaxoSmithKline)",
    "pfizer": "Pfizer",
    "辉瑞": "Pfizer",
    "lilly": "Eli Lilly",
    "eli lilly": "Eli Lilly",
    "礼来": "Eli Lilly",
    "abbvie": "AbbVie",
    "艾伯维": "AbbVie",
    "johnson & johnson": "Johnson & Johnson / Janssen",
    "janssen": "Johnson & Johnson / Janssen",
    "强生": "Johnson & Johnson / Janssen",
    "takeda": "Takeda Pharmaceutical",
    "武田": "Takeda Pharmaceutical",
    "bayer": "Bayer",
    "拜耳": "Bayer",
    "gilead": "Gilead Sciences",
    "吉利德": "Gilead Sciences",
    "daiichi sankyo": "Daiichi Sankyo",
    "第一三共": "Daiichi Sankyo",
    "merck kgaa": "Merck KGaA (德国默克)",
}

# 汇率基准换算 (折算至 USD)
CNY_PER_USD = 7.2
EUR_PER_USD = 0.92
HKD_PER_USD = 7.8


def _parse_amount(snippet: str) -> float | None:
    """从局部文本片段中解析数值、单位与币种并折算为 USD。"""
    curr = "USD"
    if (
        "人民币" in snippet
        or "CNY" in snippet
        or "RMB" in snippet
        or ("元" in snippet and "美元" not in snippet)
    ):
        curr = "CNY"
    elif "欧元" in snippet or "EUR" in snippet or "€" in snippet:
        curr = "EUR"
    elif "港币" in snippet or "港元" in snippet or "HKD" in snippet:
        curr = "HKD"

    m = re.search(r"(\d+(?:\.\d+)?)\s*(亿|万|百万|千万|billion|million)?", snippet, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1))
    unit = (m.group(2) or "").lower()
    scale = 1.0
    if unit == "亿":
        scale = 1e8
    elif unit == "billion":
        scale = 1e9
    elif unit in ("万", "万元"):
        scale = 1e4
    elif unit in ("百万", "million"):
        scale = 1e6
    elif unit == "千万":
        scale = 1e7

    amount_raw = val * scale
    if curr == "CNY":
        return amount_raw / CNY_PER_USD
    if curr == "EUR":
        return amount_raw / EUR_PER_USD
    if curr == "HKD":
        return amount_raw / HKD_PER_USD
    return amount_raw


def extract_money_usd(text: str) -> tuple[float | None, float | None]:
    """从公告文本中提取首付款现金与潜在总交易金额 (转换为 USD 美元)。"""
    upfront_usd: float | None = None
    total_usd: float | None = None

    # 1. 提取首付款 (Upfront cash): 优先匹配数值在前 ("8亿美元首付款")，其次匹配关键词在前 ("首付款为8亿美元")
    m_up_pre = re.search(
        r"(\d+(?:\.\d+)?\s*(?:亿|万|百万|千万|billion|million)?\s*(?:美元|人民币|元|港币|港元|欧元|USD|CNY|RMB|EUR|HKD)?)[^\d\n，。；,;]{0,10}?(?:首付款|预付款|前期付款|首期现金|首期付款|upfront|的首期|的前期)",
        text,
        re.IGNORECASE,
    )
    if m_up_pre:
        upfront_usd = _parse_amount(m_up_pre.group(0))
    else:
        m_up_post = re.search(
            r"(?:首付款|预付款|前期付款|首期现金|首期付款|upfront)[^\d\n，。；,;]{0,15}?(\d+(?:\.\d+)?\s*(?:亿|万|百万|千万|billion|million)?\s*(?:美元|人民币|元|港币|港元|欧元|USD|CNY|RMB|EUR|HKD)?)",
            text,
            re.IGNORECASE,
        )
        if m_up_post:
            upfront_usd = _parse_amount(m_up_post.group(0))

    # 2. 提取潜在总金额 (Total potential deal value)
    m_tot_post = re.search(
        r"(?:潜在|交易|合作|里程碑)?(?:总额|总金额|总交易金额|交易总额|总对价|交易潜在总对价|里程碑.*?总额|total\s*(?:deal|value|milestones)?)[^\d\n，。；,;]{0,15}?(\d+(?:\.\d+)?\s*(?:亿|万|百万|千万|billion|million)?\s*(?:美元|人民币|元|港币|港元|欧元|USD|CNY|RMB|EUR|HKD)?)",
        text,
        re.IGNORECASE,
    )
    if m_tot_post:
        total_usd = _parse_amount(m_tot_post.group(0))
    else:
        m_tot_pre = re.search(
            r"(\d+(?:\.\d+)?\s*(?:亿|万|百万|千万|billion|million)?\s*(?:美元|人民币|元|港币|港元|欧元|USD|CNY|RMB|EUR|HKD)?)[^\d\n，。；,;]{0,15}?(?:in\s+total|total\s+milestones|in\s+total\s+milestones|总交易额|总额|总对价)",
            text,
            re.IGNORECASE,
        )
        if m_tot_pre:
            total_usd = _parse_amount(m_tot_pre.group(0))

    return upfront_usd, total_usd


def extract_modality_and_target(text: str) -> tuple[str, str]:
    """提取药物模态 (Modality) 与生物靶点 (Target)。"""
    lower_t = text.lower()
    modality = ""
    if "adc" in lower_t or "抗体偶联" in lower_t or "抗体药物偶联物" in lower_t:
        modality = "adc"
    elif "双抗" in lower_t or "双特异性" in lower_t or "bispecific" in lower_t:
        modality = "bispecific"
    elif "单抗" in lower_t or "单克隆抗体" in lower_t or "monoclonal" in lower_t:
        modality = "monoclonal"
    elif "glp-1" in lower_t or "减重" in lower_t or "降糖" in lower_t or "代谢" in lower_t:
        modality = "metabolic"
    elif "car-t" in lower_t or "细胞治疗" in lower_t:
        modality = "cell_therapy"

    # 靶点识别
    targets = []
    for pat in [
        r"claudin\s*18\.2|cldn18\.2",
        r"pd-1|pd-l1",
        r"vegf[a-z]*",
        r"her2|erbb2",
        r"her3",
        r"trop2|trop-2",
        r"b7-h3|b7-h4",
        r"cd3|cd19|cd20|cd47",
        r"egfr",
        r"glp-1|gip|gcg",
        r"prmt5",
        r"parp[1-2]?",
        r"bcr-abl",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            targets.append(m.group(0).upper())

    target_str = "/".join(sorted(set(targets))) if targets else ""
    return modality, target_str


def match_mnc_licensee(text: str) -> tuple[str, bool]:
    """从文本中匹配海外被授权方是否为跨国药企 (MNC)。"""
    lower_t = text.lower()
    for kw, mnc_name in MNC_BUYERS_MAP.items():
        if kw in lower_t or kw in text:
            return mnc_name, True

    # 尝试抽取括号或英文字符中的买方名称
    buyer_m = re.search(
        r"与\s*([A-Za-z\s]+(?:Inc|LLC|Ltd|Therapeutics|Biopharma|GmbH)?)\s*(?:签署|达成|订立)", text
    )
    if buyer_m:
        return buyer_m.group(1).strip(), False
    return "", False


class PharmaAnnouncementCrawler:
    """A/H 股官方交易所创新药对外许可 (BD) 公告在线爬虫。"""

    CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
    CNINFO_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&lastPage=index",
        "Origin": "https://www.cninfo.com.cn",
        "X-Requested-With": "XMLHttpRequest",
    }

    def __init__(self, raw_dir: Path | str = "data/raw/industry") -> None:
        self.raw_dir = Path(raw_dir)
        self.pharma_dir = self.raw_dir / "pharma"

    def fetch_latest_deals(
        self,
        start_date: date | str = "2024-01-01",
        end_date: date | str | None = None,
    ) -> list[dict[str, Any]]:
        """在线检索巨潮资讯与港交所披露的对外许可公告，并解析为标准化交易字典。"""
        self.pharma_dir.mkdir(parents=True, exist_ok=True)
        s_date = date.fromisoformat(str(start_date)) if isinstance(start_date, str) else start_date
        e_date = (
            date.fromisoformat(str(end_date))
            if isinstance(end_date, str)
            else (end_date or date.today())
        )

        deals: list[dict[str, Any]] = []
        try:
            logger.info("正在从巨潮资讯网检索创新药对外许可公告 (%s ~ %s)", s_date, e_date)
            payload = {
                "pageNum": "1",
                "pageSize": "30",
                "column": "szse",
                "tabName": "fulltext",
                "plate": "",
                "stock": "",
                "searchkey": "对外许可 合作协议 独家许可",
                "secid": "",
                "category": "",
                "trade": "医药、生物制品",
                "seDate": f"{s_date.isoformat()}~{e_date.isoformat()}",
                "sortName": "",
                "sortType": "",
                "isHLtitle": "true",
            }
            resp = requests.post(
                self.CNINFO_QUERY_URL,
                headers=self.CNINFO_HEADERS,
                data=payload,
                impersonate="chrome120",
                timeout=12,
            )
            if resp.status_code == 200:
                import json

                data = json.loads(resp.text)
                if not isinstance(data, dict):
                    logger.warning("巨潮资讯公告接口返回非预期结构: %s", type(data).__name__)
                    return deals
                ann_list = data.get("announcements") or []
                if not isinstance(ann_list, list):
                    logger.warning(
                        "巨潮资讯公告接口 announcements 字段类型异常: %s",
                        type(ann_list).__name__,
                    )
                    ann_list = []
                for item in ann_list:
                    if not isinstance(item, dict):
                        continue
                    parsed = self.parse_announcement_item(item)
                    if parsed:
                        deals.append(parsed)
            else:
                logger.warning("巨潮资讯公告接口响应状态码: HTTP %d", resp.status_code)
        except Exception as e:
            logger.warning("在线爬取创新药公告异常: %s", e)

        return deals

    def parse_announcement_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """解析单条公告 JSON 字典为标准化 Deal-Asset-Event 结构。"""
        title = str(item.get("announcementTitle", "")).replace("<em>", "").replace("</em>", "")
        sec_name = str(item.get("secName", "")).strip()
        ann_time_ms = item.get("announcementTime")
        if ann_time_ms:
            import datetime

            ann_d = datetime.datetime.fromtimestamp(ann_time_ms / 1000.0, tz=datetime.UTC).date()
        else:
            return None

        # 过滤非许可类公告
        if not any(k in title for k in ("许可", "授权", "合作", "License", "出海", "对外")):
            return None

        content = title + " " + str(item.get("announcementContent", ""))
        upfront_usd, total_usd = extract_money_usd(content)
        modality, target = extract_modality_and_target(content)
        licensee, is_mnc = match_mnc_licensee(content)

        deal_id = (
            f"DEAL-{ann_d.strftime('%Y-%m')}-{sec_name}-{licensee[:6].upper().replace(' ', '')}"
        )
        return {
            "deal_id": deal_id,
            "licensor": sec_name,
            "licensor_type": "listed_a",
            "licensee": licensee,
            "is_mnc": is_mnc,
            "transaction_type": "license_out",
            "territory_scope": "",
            "announcement_date": ann_d.isoformat(),
            "effective_date": ann_d.isoformat(),
            "source_filing": "CNINFO / Listed Company Announcement",
            "source_url": "http://www.cninfo.com.cn",
            "assets": [
                {
                    "asset_id": f"AST-{deal_id}",
                    "drug_name_code": title[:30],
                    "target": target,
                    "modality": modality,
                    "stage": "",
                    "indication": "",
                }
            ],
            "events": [
                {
                    "event_id": f"EVT-{deal_id}-01",
                    "event_type": "initial_deal",
                    "event_date": ann_d.isoformat(),
                    "upfront_cash_usd": upfront_usd,
                    "potential_total_deal_usd": total_usd,
                    "original_currency": "USD",
                }
            ],
        }
