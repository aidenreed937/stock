"""ASML 季度财报新闻稿采集器（SEC EDGAR 6-K 官方源，release_date = filingDate，无前视）。

Stage 1（半导体 GM 前瞻腿）：从 SEC EDGAR 6-K 采集 ASML 每季度财报新闻稿到 RAW，
原始 HTML 保真（data/raw/industry/semiconductor/equipment/asml/sec_edgar/），供下游解析成 Curated 黄金表。

- 数据源：https://data.sec.gov/submissions/CIK0000937966.json（ASML 全部提交）
- 筛选：form == "6-K" 且为季度财报（文件名含 quarterly / qNresults / results）
- 下载：6-K accession 目录下的 press release exhibit（pressreleasefinancialresul / pressreleasequarterlyresul）
- release_date = 6-K filingDate（官方披露日，无前视）

用法：uv run python scripts/asml_quarterly_collect.py
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
import urllib.request
from pathlib import Path


def _maybe_decompress(data: bytes) -> bytes:
    """SEC EDGAR 可能返回 gzip（Content-Encoding），头部 0x1f8b 时解压。"""
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    return data


logger = logging.getLogger(__name__)

CIK = "0000937966"
BASE = "https://data.sec.gov/submissions/CIK{}.json"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/937966/{}"
RAW_DIR = Path("data/raw/industry/semiconductor/equipment/asml/sec_edgar")

SEC_HEADERS = {
    "User-Agent": "AntigravityResearch/1.0 (contact@research.antigravity.org)",
    "Accept-Encoding": "gzip, deflate",
}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=SEC_HEADERS)  # noqa: S310
    with urllib.request.urlopen(req, timeout=25) as resp:  # noqa: S310
        return json.loads(_maybe_decompress(resp.read()))


def _get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers=SEC_HEADERS)  # noqa: S310
    with urllib.request.urlopen(req, timeout=25) as resp:  # noqa: S310
        return _maybe_decompress(resp.read())


def _press_release_exhibit(files: list[str]) -> str | None:
    """从 6-K accession 文件列表里挑 press release exhibit（新闻稿）。"""
    for name in files:
        low = name.lower()
        if low.endswith(".htm") and ("pressrelease" in low or "press-release" in low):
            return name
    return None


def list_quarterly_filings() -> list[dict]:
    """枚举所有 6-K 季度财报提交（按 filingDate 排序）。"""
    data = _get_json(BASE.format(CIK))
    recent = data["filings"]["recent"]
    filings: list[dict] = []
    for i, form in enumerate(recent["form"]):
        if form != "6-K":
            continue
        doc = recent["primaryDocument"][i]
        low = doc.lower()
        # 季度财报 6-K：文件名含 quarterly / qNresults / results（排除 AGM/年报/分享回购等）
        is_quarterly = (
            "quarterly" in low
            or re.search(r"q\dresults", low) is not None
            or (re.search(r"^form6kq\d", low) is not None)
        )
        if not is_quarterly:
            continue
        filings.append(
            {
                "filing_date": recent["filingDate"][i],
                "accession": recent["accessionNumber"][i],
                "doc": doc,
                "form": form,
            }
        )
    # 按披露日去重（同一天可能多个 6-K），保季度财报
    seen: set[str] = set()
    uniq: list[dict] = []
    for f in sorted(filings, key=lambda x: x["filing_date"]):
        if f["filing_date"] in seen:
            continue
        seen.add(f["filing_date"])
        uniq.append(f)
    return uniq


def fetch_press_release(filing: dict) -> dict | None:
    """下载单个季度 6-K 的 press release exhibit，RAW 保真 gzip 落盘。"""
    acc = filing["accession"]
    accn = acc.replace("-", "")
    acc_dir = ARCHIVE.format(accn)
    try:
        index = _get_json(f"{acc_dir}/index.json")
    except Exception as e:
        logger.warning("index.json 获取失败 [%s]: %s", acc, e)
        return None
    files = [it["name"] for it in index["directory"]["item"]]
    ex = _press_release_exhibit(files)
    if not ex:
        # 无独立 press release exhibit：直接抓 6-K 主文档（其正文即新闻稿）
        ex = filing["doc"]
    raw_name = f"{filing['filing_date']}__{accn}__{ex}"
    raw_path = RAW_DIR / f"{raw_name}.gz"
    if raw_path.exists():
        return {"filing_date": filing["filing_date"], "file": raw_path.name}
    try:
        content = _get_bytes(f"{acc_dir}/{ex}")
    except Exception as e:
        logger.warning("press release 下载失败 [%s/%s]: %s", acc, ex, e)
        return None
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with gzip.open(raw_path, "wb") as f:
        f.write(content)
    time.sleep(0.4)  # EDGAR 礼貌限速
    return {"filing_date": filing["filing_date"], "file": raw_path.name}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    filings = list_quarterly_filings()
    logger.info(
        "共发现 %d 个季度 6-K（%s ~ %s）",
        len(filings),
        filings[0]["filing_date"],
        filings[-1]["filing_date"],
    )
    ok = 0
    for f in filings:
        res = fetch_press_release(f)
        if res:
            ok += 1
        else:
            logger.warning("跳过 [%s %s]", f["filing_date"], f["accession"])
    logger.info("完成：成功 %d/%d，落盘 %s", ok, len(filings), RAW_DIR)


if __name__ == "__main__":
    main()
