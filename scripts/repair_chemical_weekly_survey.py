"""weekly_survey.csv 血统与残留异常一次性修复工具。

背景
----
`data/raw/industry/chemicals/operating_rates/weekly_survey.csv` 在“CFA 研报异常纠偏”重建过程中，
曾由临时会话命令重写，导致：

1. CFA 期货研报行（2021-01-19 ~ 2024-03-25）的 `source_url` 被改写为
   `cfachina.org/cfachina_SA_<快照名>.pdf` 这类**不可解析的伪 URL**，丢失原始抓取地址；
2. 少数 `raw_snapshot_path` 指向 `cfachina_SA_*.pdf` 的行仍标记为 `Longzhong_Oilchem`，
   与文档通道（CFA 期货研报）不一致；
3. `2024-02-28` 行的企业库存出现 `37.63`——该数值与 PDF 原文中“重碱周度产量 37.63 万吨”
   （细分指标、严禁入库）相同，需要按当前解析器从快照复核并修正。

本脚本执行以下修复（可重复运行，幂等）：
- 从旧 CSV 快照（会话实录 JSONL，或已落盘的 `config/data_sources/cfa_url_hash_map.csv`）
  恢复 CFA 行的真实 `https://www.cfachina.org/...pdf` 地址；
- 将快照为 cfachina 但 `source` 仍为 `Longzhong_Oilchem` 的行重标为
  `CFA_Futures_Report:Longzhong`（主键冲突时按字段合并，不丢数据）；
- 对 `factory_inventory_w_tons == 37.63` 的 CFA 行，用 `ResearchReportParser` 从对应 PDF
  快照重新提取，按解析结果修正（无有效值时置空，宁缺毋滥）；
- 输出修复前后对比、URL 恢复覆盖率与未匹配清单。

用法
----
# 首次：从会话实录生成 URL 映射并落盘 + 执行修复
uv run python scripts/repair_chemical_weekly_survey.py \
    --csv data/raw/industry/chemicals/operating_rates/weekly_survey.csv \
    --urls-csv config/data_sources/cfa_url_hash_map.csv \
    --write-urls \
    --transcript-dir <antigravity会话>.system_generated/logs/chunks

# 后续幂等重跑（只读映射文件）
uv run python scripts/repair_chemical_weekly_survey.py \
    --csv data/raw/industry/chemicals/operating_rates/weekly_survey.csv \
    --urls-csv config/data_sources/cfa_url_hash_map.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import Any

import pypdf

from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CFA_URL_RE = re.compile(
    r"(?P<url>https://www\.cfachina\.org/servicesupport/analygarden/nyhgl/cj_5769/"
    r"\d{6}/P\d{12}\.pdf)"
)
OLD_ROW_RE = re.compile(
    r"(?P<rd>\d{4}-\d{2}-\d{2}),\d{4}-\d{2}-\d{2},纯碱,SA,"
    r"[^,\r\n]*,[^,\r\n]*,[^,\r\n]*,[^,\r\n]*,"
    r"(?:Longzhong_Oilchem|CFA_Futures_Report:Longzhong),"
    r"(?P<url>https://www\.cfachina\.org/[^,\r\n\"\\\s]+\.pdf),"
    r"[^,\r\n]*,[^,\r\n]*,[^,\r\n]*,"
    r"(?P<snap>cfachina_SA_[0-9-]{10}_[0-9a-f]{16}\.pdf)"
)
SNAPSHOT_DATE_RE = re.compile(r"cfachina_SA_(\d{4}-\d{2}-\d{2})_")
PDF_PUBLISH_DATE_RE = re.compile(r"P0(\d{4})(\d{2})(\d{2})\d+\.pdf$")

CSV_FIELDS = [
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

SUSPICIOUS_INVENTORY = "37.63"  # PDF 原文为“重碱周度产量 37.63 万吨”（细分指标，严禁入库）


def _iter_jsonl_text(transcript_dir: Path):
    """逐行产出（原始行文本, 解析后的 content 文本）。"""
    for chunk in sorted(transcript_dir.rglob("*.jsonl")):
        with chunk.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                text = line
                try:
                    obj = json.loads(line)
                    content = obj.get("content", "")
                    if isinstance(content, str) and content:
                        text = content
                except (json.JSONDecodeError, ValueError):
                    pass
                yield line, text


def _publish_date_from_url(url: str) -> str | None:
    m = PDF_PUBLISH_DATE_RE.search(url)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _extract_urls(text: str, url_map: dict[str, str], snap_map: dict[str, str]) -> None:
    """从文本（去除真实换行，兼容终端折行的旧 CSV dump）提取发布日/快照 -> URL。"""
    joined = text.replace("\r\n", "").replace("\n", "")
    for m in OLD_ROW_RE.finditer(joined):
        pub = _publish_date_from_url(m.group("url"))
        if pub and pub not in url_map:
            url_map[pub] = m.group("url")
        snap = m.group("snap")
        if snap and snap not in snap_map:
            snap_map[snap] = m.group("url")


def build_url_map_from_transcript(
    transcript_dir: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """从会话实录中的旧 CSV 快照提取 URL 映射。

    返回两个映射：
    - publish_date -> URL（列表/旧 dump 均可提供）；
    - 快照文件名 -> URL（旧 dump 中绑定了 raw_snapshot_path 的行，精度最高）。

    旧 CSV dump 可能被终端折行拆成多个行片段，因此对每个文件先做整文件
    （含 JSON 转义原文）与解码后的 content 两种文本的换行剥离再匹配。
    """
    url_map: dict[str, str] = {}
    snap_map: dict[str, str] = {}
    for chunk in sorted(transcript_dir.rglob("*.jsonl")):
        raw = chunk.read_text(encoding="utf-8", errors="replace")
        _extract_urls(raw, url_map, snap_map)
        try:
            with chunk.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        obj = json.loads(line)
                        content = obj.get("content", "")
                        if isinstance(content, str) and content:
                            _extract_urls(content, url_map, snap_map)
                    except (json.JSONDecodeError, ValueError):
                        pass
        except Exception:
            pass
    return url_map, snap_map


def build_url_map_from_listing(url_map: dict[str, str]) -> dict[str, str]:
    """在线扫描 CFA China 纯碱专栏列表页，补全发布日 -> 原始 URL 映射（最大 16 页）。"""
    try:
        from bs4 import BeautifulSoup
        from curl_cffi import requests
    except ImportError:
        logger.warning("缺少 bs4/curl_cffi，跳过在线列表补全")
        return url_map

    base_prefix = "https://www.cfachina.org/servicesupport/analygarden/nyhgl/cj_5769/"
    found = 0
    for page in range(16):
        suffix = "" if page == 0 else f"_{page}"
        url = (
            f"https://www.cfachina.org/servicesupport/analygarden/nyhgl/cj_5769/index{suffix}.html"
        )
        try:
            resp = requests.get(url, impersonate="chrome120", timeout=12)
            if resp.status_code != 200:
                logger.warning("列表页 HTTP %d: %s", resp.status_code, url)
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=re.compile(r"\.pdf$")):
                href = a.get("href", "")
                pdf_url = base_prefix + href.lstrip("./")
                pub = _publish_date_from_url(pdf_url)
                if pub and pub not in url_map:
                    url_map[pub] = pdf_url
                    found += 1
        except Exception as exc:
            logger.warning("扫描列表页 %s 失败: %s", url, exc)
    logger.info("在线列表补全新增 %d 条 URL 映射", found)
    return url_map


def load_url_map(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rd = (row.get("publish_date") or row.get("report_date") or "").strip()
            url = (row.get("url") or row.get("source_url") or "").strip()
            if rd and url:
                out[rd] = url
    return out


def save_url_map(path: Path, url_map: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["publish_date", "source_url"])
        writer.writeheader()
        for rd in sorted(url_map):
            writer.writerow({"publish_date": rd, "source_url": url_map[rd]})
    logger.info("URL 映射已落盘: %s (%d 条)", path, len(url_map))


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def save_rows(csv_path: Path, rows: list[dict[str, str]]) -> None:
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def _merge_records(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    for k, v in extra.items():
        if (not merged.get(k)) and v:
            merged[k] = v
    return merged


def reparse_snapshot(raw_dir: Path, snap_path: str) -> tuple[dict[str, Any] | None, str]:
    """用当前 ResearchReportParser 从快照重提取，返回（主记录 or None, PDF 原文切片）。"""
    pdf_file = raw_dir / snap_path
    if not pdf_file.exists() or pdf_file.suffix != ".pdf":
        return None, ""
    m = SNAPSHOT_DATE_RE.search(snap_path)
    p_date = date.fromisoformat(m.group(1)) if m else None
    if p_date is None:
        return None, ""
    try:
        reader = pypdf.PdfReader(str(pdf_file))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # pragma: no cover - 防御性
        logger.warning("读取 PDF 失败 %s: %s", pdf_file, exc)
        return None, ""
    parser = ResearchReportParser(raw_dir=raw_dir)
    records = parser.extract_metrics_from_text(
        text=text,
        product_name="纯碱",
        publish_date=p_date,
        source_name="CFA_Futures_Report:Longzhong",
        source_url=str(pdf_file.name),
    )
    snippet = ""
    clean = re.sub(r"\s+", " ", text)
    for kw in ("库存", "37.63"):
        for mm in re.finditer(rf".{{0,40}}{kw}.{{0,60}}", clean):
            s = mm.group(0).strip()
            if any(w in s for w in ("万吨", "%")):
                snippet = s
                break
        if snippet:
            break
    main = next((r for r in records if r.get("trade_date") == p_date), None)
    if main is None and records:
        main = records[0]
    return main, snippet


def apply_repairs(
    rows: list[dict[str, str]],
    url_map: dict[str, str],
    snap_map: dict[str, str],
    raw_dir: Path,
) -> tuple[list[dict[str, str]], dict[str, int], list[str]]:
    """执行三项修复，返回（修复后行, 统计, 未匹配清单）。"""
    stats = {
        "url_restored": 0,
        "relabeled": 0,
        "inventory_fixed": 0,
        "unmapped": 0,
    }
    unmapped: list[str] = []

    # 先做字段级修复（URL / 标签 / 库存复核）
    for row in rows:
        if "data_status" not in row or not row["data_status"]:
            row["data_status"] = "actual"
        snap = row.get("raw_snapshot_path", "") or ""
        is_cfa = "cfachina_SA_" in snap

        if not is_cfa:
            continue

        # 1) source_url 恢复/纠偏（快照精确绑定 -> 快照发布日 -> report_date 兜底）
        snap_date = None
        snap_basename = None
        m_snap = SNAPSHOT_DATE_RE.search(snap)
        if m_snap:
            snap_date = m_snap.group(1)
        if snap:
            snap_basename = Path(snap).name

        cur_url = row.get("source_url") or ""
        cur_pub = _publish_date_from_url(cur_url) if cur_url.startswith("http") else None

        exact_url = snap_map.get(snap_basename or "")
        pub_url = url_map.get(snap_date or "") if snap_date else None
        fallback_url = url_map.get(row.get("report_date", ""))

        if exact_url and cur_url != exact_url:
            row["source_url"] = exact_url
            stats["url_restored"] += 1
        elif pub_url and cur_pub != snap_date:
            row["source_url"] = pub_url
            stats["url_restored"] += 1
        elif not cur_url.startswith("http"):
            url = pub_url or fallback_url
            if url:
                row["source_url"] = url
                stats["url_restored"] += 1
            else:
                stats["unmapped"] += 1
                unmapped.append(f"{row.get('report_date')} | {snap}")

        # 2) 标签统一
        if row.get("source") == "Longzhong_Oilchem":
            row["source"] = "CFA_Futures_Report:Longzhong"
            stats["relabeled"] += 1

        # 3) 37.63 库存复核
        if row.get("factory_inventory_w_tons") == SUSPICIOUS_INVENTORY:
            main, snippet = reparse_snapshot(raw_dir, snap)
            new_inv = main.get("factory_inventory_w_tons") if main else None
            logger.info(
                "复核 37.63 库存行: %s | 快照 %s | 新解析库存=%s | 原文: %s",
                row.get("report_date"),
                snap,
                new_inv,
                snippet[:120],
            )
            if new_inv is not None and str(new_inv) != SUSPICIOUS_INVENTORY:
                row["factory_inventory_w_tons"] = str(new_inv)
                stats["inventory_fixed"] += 1
            elif new_inv is None:
                # 解析器无法给出可信库存：宁缺毋滥，置空
                row["factory_inventory_w_tons"] = ""
                stats["inventory_fixed"] += 1

    # 主键合并（重标后可能产生 (product, report_date, source) 冲突）
    merged: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        key = (row["product_name"], row["report_date"], row["source"])
        if key in merged:
            merged[key] = _merge_records(merged[key], row)
        else:
            merged[key] = row

    return list(merged.values()), stats, unmapped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", default="data/raw/industry/chemicals/operating_rates/weekly_survey.csv"
    )
    parser.add_argument("--raw-dir", default="data/raw/industry")
    parser.add_argument("--urls-csv", default="config/data_sources/cfa_url_hash_map.csv")
    parser.add_argument(
        "--transcript-dir", default=None, help="会话实录 chunks 目录（生成 URL 映射用）"
    )
    parser.add_argument(
        "--fetch-urls", action="store_true", help="在线抓取 CFA 列表页补全 URL 映射"
    )
    parser.add_argument(
        "--write-urls", action="store_true", help="将提取的 URL 映射写入 --urls-csv"
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    urls_path = Path(args.urls_csv)
    raw_dir = Path(args.raw_dir)

    url_map = load_url_map(urls_path)
    snap_map: dict[str, str] = {}
    if args.transcript_dir:
        transcript_map, transcript_snap_map = build_url_map_from_transcript(
            Path(args.transcript_dir)
        )
        for k, v in transcript_map.items():
            url_map.setdefault(k, v)
        snap_map.update(transcript_snap_map)
        logger.info(
            "合并会话实录 URL 映射后共 %d 条，快照精确绑定 %d 条", len(url_map), len(snap_map)
        )
    if args.fetch_urls:
        url_map = build_url_map_from_listing(url_map)
        logger.info("合并在线列表 URL 映射后共 %d 条", len(url_map))
    if not url_map and not snap_map:
        parser.error("缺少 URL 映射：请提供 --transcript-dir 或 --fetch-urls")
    if args.write_urls:
        save_url_map(urls_path, url_map)

    rows = load_rows(csv_path)
    logger.info("载入 CSV %d 行（含表头校验: %d 数据行）", len(rows), len(rows))
    fixed_rows, stats, unmapped = apply_repairs(rows, url_map, snap_map, raw_dir)
    save_rows(csv_path, fixed_rows)

    logger.info("=== 修复统计 ===")
    logger.info(
        "恢复 source_url: %d | 重标标签: %d | 37.63 库存复核修正: %d | 未匹配 URL: %d",
        stats["url_restored"],
        stats["relabeled"],
        stats["inventory_fixed"],
        stats["unmapped"],
    )
    logger.info("修复后数据行数: %d", len(fixed_rows))
    if unmapped:
        logger.warning("以下 CFA 行未找到原始 URL（需人工补录）:")
        for item in unmapped[:50]:
            logger.warning("  - %s", item)


if __name__ == "__main__":
    main()
