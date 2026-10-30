"""半导体设备四巨头季度财报新闻稿采集器（SEC EDGAR 官方源，release_date = filingDate，无前视）。

Stage 2（半导体 GM 前瞻腿四巨头扩样）：从 SEC EDGAR 8-K 采集 AMAT/LRCX/KLAC 每季度
财报新闻稿到 RAW（gzip 保真），供下游解析成 Curated 黄金表后跨公司合成 gm_leading_score。

- 数据源：https://data.sec.gov/submissions/CIK{CIK}.json（每家全部提交，含 older 分页）
- 筛选：form == "8-K" 且 exhibit 含 earnings release（新闻稿，最大 .htm exhibit）
- release_date = 8-K filingDate（官方披露日，无前视）
- 财年错位：不按财年末对齐，统一以 release_date 对齐日频（规避 roadmap 封存的财年错位硬对齐）

TEL（Tokyo Electron，日股 8035.T）不在 EDGAR，需日本 IR 单独适配器（本脚本暂不覆盖，
由 equipment_giants_parse 的 TEL 适配标记为待办）。

用法：uv run python scripts/equipment_giants_collect.py
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


def _maybe_decompress(data: bytes) -> bytes:
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


BASE = "https://data.sec.gov/submissions/CIK{}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{}/{}"

GIANTS: dict[str, dict] = {
    "AMAT": {"cik": "0000006951", "name": "APPLIED MATERIALS INC /DE"},
    "LRCX": {"cik": "0000707549", "name": "LAM RESEARCH CORP"},
    "KLAC": {"cik": "0000319201", "name": "KLA CORP"},
}

SEC_HEADERS = {
    "User-Agent": "AntigravityResearch/1.0 (contact@research.antigravity.org)",
    "Accept-Encoding": "gzip, deflate",
}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(_maybe_decompress(resp.read()))


def _get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=SEC_HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return _maybe_decompress(resp.read())


def _list_all_filings(cik: str) -> list[dict]:
    """枚举全部提交（recent + older 分页），按 filingDate 排序。"""
    data = _get_json(BASE.format(cik))
    out: list[dict] = []
    # 当前批次
    recent = data["filings"]["recent"]
    for i, form in enumerate(recent["form"]):
        out.append(
            {
                "form": form,
                "filing_date": recent["filingDate"][i],
                "accession": recent["accessionNumber"][i],
                "doc": recent["primaryDocument"][i],
            }
        )
    # 历史分页
    page = data["filings"].get("files")
    guard = 0
    while page and guard < 50:
        url = "https://data.sec.gov/submissions/" + page[0]["name"]
        try:
            older = _get_json(url)
        except Exception as e:
            logger.warning("older 分页失败 [%s]: %s", url, e)
            break
        # older 分页文件为扁平数组（无 recent 包装）
        batch = older.get("recent", older)
        for i, form in enumerate(batch["form"]):
            out.append(
                {
                    "form": form,
                    "filing_date": batch["filingDate"][i],
                    "accession": batch["accessionNumber"][i],
                    "doc": batch["primaryDocument"][i],
                }
            )
        page = older.get("files")
        guard += 1
    return sorted(out, key=lambda x: x["filing_date"])


def _pick_earnings_exhibit(files: list[str], primary_doc: str, ticker: str) -> str | None:
    """从 8-K accession 里挑财报新闻稿 exhibit；非财报 8-K 返回 None。

    按公司精确匹配（已实测各年代命名）：
    - AMAT:  exhibit991q{期}earningsre / exhibit991earningsrelease / ex991pressrelease
    - LRCX:  lrcx_exhibitx991xq{期}x{年}（q1/q2/q3/q4 财季）；不含 8kx（非财报）
    - KLAC:  exhibit991earningsrelease / earningsrelease6{年}；不含 dividend/joint
    """
    htm = [
        f
        for f in files
        if f.lower().endswith((".htm", ".html"))
        and "r1.htm" not in f.lower()
        and "index" not in f.lower()
    ]
    if not htm:
        return None
    low = [f.lower() for f in htm]

    def is_earnings(i: int) -> bool:
        name = low[i]
        if ticker == "LRCX":
            # 财季新闻稿：lrcx_exhibitx991xq[1-4]x20.. 或含 'q1x'/'q2x' 且非 '8kx'
            if "8kx" in name or "8k" in name.replace("x", "").replace("_", ""):
                return False
            return (
                "lrcx_exhibit" in name and "991" in name and re.search(r"xq[1-4]x\d{4}", name)
            ) or ("pressrelease" in name and "q" in name and re.search(r"\d{4}", name))
        if ticker == "KLAC":
            if "dividend" in name or "joint" in name or "director" in name or "hanley" in name:
                return False
            return ("earningsrelease" in name) or ("exhibit991earnings" in name)
        # AMAT
        if "dividend" in name or "eml" in name or "credit" in name:
            return False
        return ("earnings" in name) or ("pressrelease" in name)

    for i, f in enumerate(htm):
        if is_earnings(i):
            return f
    return None


def fetch_company(ticker: str, cik: str, raw_dir: Path) -> tuple[int, int]:
    """下载某家公司 2015-10 以来 8-K 财报新闻稿 exhibit。返回 (成功数, 8-K总数)。"""
    filings = _list_all_filings(cik)
    # 只取 2015-10-01 后的 8-K（12 季滚动分位预热需要 2015 起，对齐 ASML 覆盖）
    _8ks = [f for f in filings if f["form"] == "8-K" and f["filing_date"] >= "2015-10-01"]
    ok = 0
    cik_num = str(int(cik))  # 去前导零（EDGAR 路径用无前导零 CIK）
    for f in _8ks:
        acc = f["accession"]
        accn = acc.replace("-", "")
        acc_dir = ARCHIVE.format(cik_num, accn)
        try:
            index = _get_json(f"{acc_dir}/index.json")
        except Exception as e:
            logger.warning("index.json 获取失败 [%s %s]: %s", ticker, acc, e)
            time.sleep(0.3)
            continue
        time.sleep(0.2)  # EDGAR 礼貌限速（index.json 枚举）
        files = [it["name"] for it in index["directory"]["item"]]
        ex = _pick_earnings_exhibit(files, f["doc"], ticker)
        if not ex:
            # 非财报 8-K（credit agreement/股权激励/拆股等），跳过
            logger.debug("非财报 8-K 跳过 [%s %s %s]", ticker, acc, f["doc"])
            continue
        raw_path = raw_dir / f"{ticker}__{f['filing_date']}__{accn}__{ex}.gz"
        if raw_path.exists():
            ok += 1
            continue
        try:
            content = _get_bytes(f"{acc_dir}/{ex}")
        except Exception as e:
            logger.warning("下载失败 [%s %s/%s]: %s", ticker, acc, ex, e)
            continue
        if len(content) < 5000:
            # 选中的 exhibit 过小（占位/跳转页）→ 回退到 8-K 主文档（常含同一新闻稿）
            logger.debug("exhibit 过小回退主文档 [%s %s/%s len=%d]", ticker, acc, ex, len(content))
            ex = f["doc"]
            raw_path = raw_dir / f"{ticker}__{f['filing_date']}__{accn}__{ex}.gz"
            if raw_path.exists():
                ok += 1
                continue
            try:
                content = _get_bytes(f"{acc_dir}/{ex}")
            except Exception as e:
                logger.warning("回退下载失败 [%s %s/%s]: %s", ticker, acc, ex, e)
                continue
            # 主文档须含财报关键词（revenue/gross margin），否则视为非财报
            low = content.decode("utf-8", "ignore").lower()
            if "gross margin" not in low and "revenue" not in low:
                logger.debug("主文档非财报，跳过 [%s %s]", ticker, acc)
                continue
        raw_dir.mkdir(parents=True, exist_ok=True)
        with gzip.open(raw_path, "wb") as fh:
            fh.write(content)
        ok += 1
        time.sleep(0.4)  # EDGAR 礼貌限速
    return ok, len(_8ks)


def fetch_10q_company(ticker: str, cik: str, raw_dir: Path) -> tuple[int, int]:
    """下载某家公司 2015-10 以来 10-Q（GM/指引补充源，KLAC 新闻稿无 GM）。返回 (成功数, 10-Q总数)。"""
    filings = _list_all_filings(cik)
    _10qs = [f for f in filings if f["form"] == "10-Q" and f["filing_date"] >= "2015-10-01"]
    ok = 0
    cik_num = str(int(cik))
    for f in _10qs:
        accn = f["accession"].replace("-", "")
        acc_dir = ARCHIVE.format(cik_num, accn)
        try:
            index = _get_json(f"{acc_dir}/index.json")
        except Exception as e:
            logger.warning("10-Q index.json 失败 [%s %s]: %s", ticker, accn, e)
            continue
        time.sleep(0.2)
        # 主文档即 10-Q 全文（通常最大）
        raw_path = raw_dir / f"{ticker}__{f['filing_date']}__{accn}__10Q_{f['doc']}.gz"
        if raw_path.exists():
            ok += 1
            continue
        try:
            content = _get_bytes(f"{acc_dir}/{f['doc']}")
        except Exception as e:
            logger.warning("10-Q 下载失败 [%s %s]: %s", ticker, accn, e)
            continue
        raw_dir.mkdir(parents=True, exist_ok=True)
        with gzip.open(raw_path, "wb") as fh:
            fh.write(content)
        ok += 1
        time.sleep(0.4)
    return ok, len(_10qs)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raw_root = Path("data/raw/industry/semiconductor/equipment/sec_edgar")
    raw_root.mkdir(parents=True, exist_ok=True)
    for ticker, info in GIANTS.items():
        sub = raw_root / ticker
        sub.mkdir(parents=True, exist_ok=True)
        ok, total = fetch_company(ticker, info["cik"], sub)
        logger.info("%s: 8-K 财报新闻稿 下载成功 %d/%d → %s", ticker, ok, total, sub)
        okq, totalq = fetch_10q_company(ticker, info["cik"], sub)
        logger.info("%s: 10-Q 下载成功 %d/%d → %s", ticker, okq, totalq, sub)


if __name__ == "__main__":
    main()
