"""CFA 研报 source_url 内容哈希级精确绑定工具。

背景
----
`weekly_survey.csv` 中 CFA_Futures_Report:Longzhong 行的 `raw_snapshot_path` 指向本地 PDF 快照
（文件名 `cfachina_SA_<发布日>_<sha256前16位>.pdf`），但原始 `source_url` 只有发布日级匹配，
同日多篇研报时可能指向另一篇。本脚本通过 **URL -> 内容 SHA256** 的精确映射，把每一行
`source_url` 绑到与本地快照内容一致的真实 PDF。

实现
----
1. 抓取 CFA China 纯碱专栏列表页（0-15 页，最多 16 页）的全部 PDF 链接，
   缓存到 `data/raw/industry/chemicals/cache/cfa_listing_urls.csv`（publish_date, url）；
2. 可选 `--transcript-dir`：从会话实录提取旧 CSV 中的 (url, sha256) 配对（约 43 条），
   直接注入哈希映射，减少下载量；
3. 下载候选 URL（仅覆盖“快照 SHA 尚未绑定”的发布日）并计算内容 SHA256，
   缓存到 `config/data_sources/cfa_url_hash_map.csv`（url, sha256, publish_date）；
4. 对每个 CFA 行计算本地快照 SHA256，按哈希查 URL 并回写 `source_url`；
5. 输出统计：精确绑定数 / 仍为发布日级（下载失败或列表缺失）数 / 未绑定清单。

可断点续跑：哈希映射与列表缓存持久化，重复运行只补齐缺口。

用法
----
uv run python scripts/bind_cfa_snapshot_urls.py \
    --csv data/raw/industry/chemicals/operating_rates/weekly_survey.csv \
    --raw-dir data/raw/industry \
    --transcript-dir <会话 .system_generated/logs/chunks> \
    --max-pages 16
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LISTING_CSV = "data/raw/industry/chemicals/cache/cfa_listing_urls.csv"
HASH_MAP_CSV = "config/data_sources/cfa_url_hash_map.csv"
BASE_PREFIX = "https://www.cfachina.org/servicesupport/analygarden/nyhgl/cj_5769/"
SHA_RE = re.compile(
    r"(https://www\.cfachina\.org/[^,\s\"\\]+\.pdf),[^,\r\n]*,[^,\r\n]*,(?P<sha>[0-9a-f]{64})"
)
SNAPSHOT_DATE_RE = re.compile(r"cfachina_SA_(\d{4}-\d{2}-\d{2})_")
DIRECT_PROXIES: Any = {"http": "", "https": ""}


def fetch_listing(max_pages: int, cached: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """抓取列表页，返回 [(publish_date, url)]，并入已有缓存。"""
    known = {url for _d, url in cached}
    out = list(cached)
    fetched_pages = 0
    for page in range(max_pages):
        suffix = "" if page == 0 else f"_{page}"
        url = (
            f"https://www.cfachina.org/servicesupport/analygarden/nyhgl/cj_5769/index{suffix}.html"
        )
        try:
            from bs4 import BeautifulSoup
            from curl_cffi import requests

            resp = requests.get(url, impersonate="chrome120", timeout=12, proxies=DIRECT_PROXIES)
            if resp.status_code != 200:
                logger.warning("列表页 HTTP %d: %s", resp.status_code, url)
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=re.compile(r"\.pdf$")):
                href = str(a.get("href") or "")
                if "P0" not in href:
                    continue
                pdf_url = BASE_PREFIX + href.lstrip("./")
                m = re.search(r"P0(\d{4})(\d{2})(\d{2})", pdf_url)
                if not m:
                    continue
                pub = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
                if pdf_url not in known:
                    known.add(pdf_url)
                    out.append((pub, pdf_url))
            fetched_pages += 1
        except Exception as exc:
            logger.warning("列表页 %s 失败: %s", url, exc)
        time.sleep(0.2)
    logger.info("列表页抓取完成: %d/%d 页成功，URL 总数 %d", fetched_pages, max_pages, len(out))
    return out


def load_listing(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("url"):
                out.append((row.get("publish_date", ""), row["url"]))
    return out


def save_listing(path: Path, listing: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["publish_date", "url"])
        w.writeheader()
        for pub, url in listing:
            if url in seen:
                continue
            seen.add(url)
            w.writerow({"publish_date": pub, "url": url})


def load_hash_map(path: Path) -> dict[str, str]:
    """返回 sha256(64) -> url。"""
    if not path.exists():
        return {}
    out = {}
    with path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("sha256") and row.get("url"):
                out[row["sha256"]] = row["url"]
    return out


def save_hash_map(path: Path, sha_url: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["url", "sha256", "publish_date"])
        w.writeheader()
        for sha, url in sorted(sha_url.items()):
            m = re.search(r"P0(\d{4})(\d{2})(\d{2})", url)
            pub = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
            w.writerow({"url": url, "sha256": sha, "publish_date": pub})


def ingest_transcript_pairs(transcript_dir: Path | None, sha_url: dict[str, str]) -> dict[str, str]:
    """从会话实录提取 (url, sha256) 配对注入哈希映射。"""
    if transcript_dir is None:
        return sha_url
    added = 0
    for chunk in Path(transcript_dir).rglob("*.jsonl"):
        try:
            raw = chunk.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        joined = raw.replace("\r\n", "").replace("\n", "")
        for m in SHA_RE.finditer(joined):
            u, s = m.group(1), m.group("sha")
            if s not in sha_url:
                sha_url[s] = u
                added += 1
    logger.info("从会话实录注入 (url, sha256) 配对 %d 条", added)
    return sha_url


def snapshot_sha256(snap_abs: Path) -> str | None:
    if not snap_abs.exists():
        return None
    h = hashlib.sha256()
    with snap_abs.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv", default="data/raw/industry/chemicals/operating_rates/weekly_survey.csv"
    )
    parser.add_argument("--raw-dir", default="data/raw/industry")
    parser.add_argument("--transcript-dir", default=None)
    parser.add_argument("--max-pages", type=int, default=16)
    parser.add_argument(
        "--skip-listing",
        action="store_true",
        help="跳过列表页抓取（离线模式，仅用实录配对与已有缓存）",
    )
    parser.add_argument("--no-download", action="store_true", help="不下载候选 PDF（离线模式）")
    parser.add_argument("--listing-csv", default=LISTING_CSV)
    parser.add_argument("--hash-map-csv", default=HASH_MAP_CSV)
    parser.add_argument("--dry-run", action="store_true", help="只统计不写回 CSV")
    args = parser.parse_args()

    csv_path = Path(args.csv)
    raw_dir = Path(args.raw_dir)
    listing_path = Path(args.listing_csv)
    hash_path = Path(args.hash_map_csv)

    # 1) 列表缓存（可离线复用已缓存列表）
    listing = load_listing(listing_path)
    if not args.skip_listing:
        listing = fetch_listing(args.max_pages, listing)
        if not args.dry_run:
            save_listing(listing_path, listing)
    elif not listing:
        logger.info("离线模式：无列表缓存，仅使用会话实录配对")
    by_date: dict[str, list[str]] = {}
    for pub, url in listing:
        by_date.setdefault(pub, []).append(url)

    # 2) 哈希映射（实录注入 + 下载缓存）
    sha_url = load_hash_map(hash_path)
    sha_url = ingest_transcript_pairs(
        Path(args.transcript_dir) if args.transcript_dir else None, sha_url
    )

    # 3) 读取 CSV 行
    with csv_path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    fields = list(rows[0].keys()) if rows else []

    def is_cfa_row(row_dict: dict[str, str]) -> bool:
        if row_dict.get("source") == "CFA_Futures_Report:Longzhong":
            return True
        snap_val = (row_dict.get("raw_snapshot_path") or "").strip()
        if "cfachina_SA_" in snap_val:
            return True
        url_val = (row_dict.get("source_url") or "").strip()
        if "cfachina.org" in url_val:
            return True
        return False

    cfa_rows = [r for r in rows if is_cfa_row(r)]
    pending: list[dict[str, str]] = []
    for r in cfa_rows:
        snap = (r.get("raw_snapshot_path") or "").strip()
        local_sha = None
        if snap:
            local_sha = snapshot_sha256(raw_dir / snap)
        if local_sha is None:
            local_sha = (r.get("raw_content_sha256") or "").strip() or None
        # 若仍无本地完整哈希，尝试从文件名抽取 16 位哈希前缀 cfachina_SA_<date>_<sha16>.pdf
        if local_sha is None and snap:
            m_sha16 = re.search(r"cfachina_SA_\d{4}-\d{2}-\d{2}_([0-9a-f]{16})\.pdf", snap)
            if m_sha16:
                prefix16 = m_sha16.group(1)
                # 在已有 sha_url 映射中查找匹配的前缀
                matching_shas = [k for k in sha_url if k.startswith(prefix16)]
                if len(matching_shas) == 1:
                    local_sha = matching_shas[0]

        r["_sha256"] = local_sha or ""
        if (local_sha and local_sha not in sha_url) or not local_sha:
            pending.append(r)

    logger.info(
        "识别到 CFA 相关记录 %d 条：已精确匹配 %d，待解析/下载绑定 %d",
        len(cfa_rows),
        len(cfa_rows) - len(pending),
        len(pending),
    )

    # 4) 下载候选（仅待绑定行的发布日）
    pending_dates = set()
    for r in pending:
        m = SNAPSHOT_DATE_RE.search(r.get("raw_snapshot_path") or "")
        if m:
            pending_dates.add(m.group(1))
    candidates: list[str] = []
    for d in sorted(pending_dates):
        candidates.extend(by_date.get(d, []))
    # 去除已下载过的 URL
    known_hashes = set(sha_url.values())
    todo = [u for u in dict.fromkeys(candidates) if u not in known_hashes]
    logger.info("待下载候选 URL %d 个（覆盖 %d 个发布日）", len(todo), len(pending_dates))

    do_download = not args.dry_run and not args.no_download
    if do_download and not listing and pending:
        logger.warning(
            "列表页不可达且无缓存：跳过下载（cfachina 可能临时封禁），仅应用已有哈希映射"
        )
        do_download = False

    if do_download:
        from curl_cffi import requests

        ok = fail = 0
        for i, url in enumerate(todo, start=1):
            try:
                resp = requests.get(
                    url, impersonate="chrome120", timeout=25, proxies=DIRECT_PROXIES
                )
                if resp.status_code != 200:
                    logger.warning("[%d/%d] HTTP %d %s", i, len(todo), resp.status_code, url)
                    fail += 1
                    time.sleep(0.2)
                    continue
                h = hashlib.sha256(resp.content).hexdigest()
                if h not in sha_url:
                    sha_url[h] = url
                ok += 1
            except Exception as exc:
                logger.warning("[%d/%d] 下载失败 %s: %s", i, len(todo), url, str(exc)[:120])
                fail += 1
            time.sleep(0.15)
            if i % 10 == 0:
                logger.info("下载进度 %d/%d（成功 %d 失败 %d）", i, len(todo), ok, fail)
        logger.info("下载完成：成功 %d，失败 %d", ok, fail)
        save_hash_map(hash_path, sha_url)
    else:
        logger.info("跳过下载，仅应用已有哈希映射（%d 条）", len(sha_url))
        if not args.dry_run:
            save_hash_map(hash_path, sha_url)

    # 5) 回写 source_url
    exact = fallback = 0
    fallback_rows: list[str] = []
    for r in rows:
        if not is_cfa_row(r):
            continue
        local_sha = r.get("_sha256") or ""
        matched_url: str | None = sha_url.get(local_sha) if local_sha else None
        if matched_url:
            r["source_url"] = matched_url
            if "status" in r:
                r["status"] = "EXACT_MATCH"
            exact += 1
        else:
            fallback += 1
            fallback_rows.append(f"{r.get('report_date')} | {r.get('raw_snapshot_path') or ''}")
        r.pop("_sha256", None)

    logger.info("=== 绑定统计 ===")
    logger.info("内容哈希级精确绑定: %d | 仍为发布日级(未绑定): %d", exact, fallback)
    if fallback_rows:
        logger.warning("以下行未精确绑定（列表缺失/下载失败/快照缺失）:")
        for item in fallback_rows[:60]:
            logger.warning("  - %s", item)

    if not args.dry_run:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        logger.info("CSV 已更新: %s", csv_path)


if __name__ == "__main__":
    main()
