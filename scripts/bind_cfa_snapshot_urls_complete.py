#!/usr/bin/env python3
"""
精确绑定 CFA China 纯碱研报本地快照与官网 PDF URL。

用途
----
CSV 不要求存在 `source` 列。脚本直接识别 raw_snapshot_path 中的：
    cfachina_SA_<YYYY-MM-DD>_<sha256前16位>.pdf

处理流程
--------
1. 抓取 CFA China 纯碱研报列表页（默认 0~15 页），缓存 URL；
2. 可选从会话实录 JSONL 提取已有 (url, sha256) 配对；
3. 对本地快照计算完整 SHA256；若快照不存在，则至少保留文件名中的 16 位 SHA 前缀；
4. 下载同发布日期下的候选 PDF，计算 SHA256，与本地快照精确匹配；
5. 回写 source_url，并更新 status；
6. 支持断点续跑、dry-run、跳过列表、跳过下载。

注意
----
- 本脚本不会生成或修改 PDF。
- 只有完整 SHA256 匹配才标记为 HASH_EXACT。
- 如果只有日期级 URL，标记为 DATE_LEVEL_FALLBACK。
- 如果已有 URL 与快照哈希已知且不一致，标记为 KNOWN_SIBLING_MISMATCH。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import time
from pathlib import Path

LISTING_CSV = "data/raw/industry/chemicals/cache/cfa_listing_urls.csv"
HASH_MAP_CSV = "config/data_sources/cfa_url_hash_map.csv"

BASE_PREFIX = "https://www.cfachina.org/servicesupport/analygarden/nyhgl/cj_5769/"

SNAPSHOT_RE = re.compile(
    r"cfachina_SA_(?P<date>\d{4}-\d{2}-\d{2})_(?P<prefix>[0-9a-f]{16})\.pdf$",
    re.I,
)

PDF_LINK_RE = re.compile(r"\.pdf$", re.I)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def extract_snapshot_meta(snapshot_path: str) -> tuple[str, str] | None:
    """返回 (publish_date, sha256_prefix16)。"""
    name = Path(snapshot_path).name
    m = SNAPSHOT_RE.search(name)
    if not m:
        return None
    return m.group("date"), m.group("prefix").lower()


def fetch_listing(
    max_pages: int,
    cached: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """抓取列表页，返回 [(publish_date, url)]。"""
    try:
        from bs4 import BeautifulSoup
        from curl_cffi import requests
    except ImportError as exc:
        raise SystemExit("缺少依赖，请先安装：uv add beautifulsoup4 curl-cffi") from exc

    known = {url for _, url in cached}
    out = list(cached)
    fetched = 0

    for page in range(max_pages):
        suffix = "" if page == 0 else f"_{page}"
        url = f"{BASE_PREFIX}index{suffix}.html"
        try:
            resp = requests.get(
                url,
                impersonate="chrome120",
                timeout=15,
            )
            if resp.status_code != 200:
                logger.warning("列表页 HTTP %d: %s", resp.status_code, url)
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=PDF_LINK_RE):
                href = a.get("href", "")
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

            fetched += 1
        except Exception as exc:
            logger.warning("列表页失败 %s: %s", url, exc)

        time.sleep(0.2)

    logger.info(
        "列表页抓取完成：%d/%d 页成功，URL 总数 %d",
        fetched,
        max_pages,
        len(out),
    )
    return out


def load_listing(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []

    out: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            if url:
                out.append((row.get("publish_date", "").strip(), url))
    return out


def save_listing(path: Path, listing: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["publish_date", "url"],
        )
        w.writeheader()

        for pub, url in listing:
            if url in seen:
                continue
            seen.add(url)
            w.writerow(
                {
                    "publish_date": pub,
                    "url": url,
                }
            )


def load_hash_map(path: Path) -> dict[str, str]:
    """返回 sha256 -> url。"""
    if not path.exists():
        return {}

    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sha = (row.get("sha256") or "").strip().lower()
            url = (row.get("url") or "").strip()
            if re.fullmatch(r"[0-9a-f]{64}", sha) and url:
                out[sha] = url
    return out


def save_hash_map(path: Path, sha_url: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["url", "sha256", "publish_date"],
        )
        w.writeheader()

        for sha, url in sorted(sha_url.items()):
            m = re.search(r"P0(\d{4})(\d{2})(\d{2})", url)
            pub = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
            w.writerow(
                {
                    "url": url,
                    "sha256": sha,
                    "publish_date": pub,
                }
            )


def ingest_transcript_pairs(
    transcript_dir: Path | None,
    sha_url: dict[str, str],
) -> dict[str, str]:
    """从 .jsonl 会话实录中提取已有 (url, sha256) 配对。"""
    if transcript_dir is None or not transcript_dir.exists():
        return sha_url

    # URL 后紧跟任意字段，最终出现 64 位 SHA256。
    pair_re = re.compile(
        r"(https://www\.cfachina\.org/[^,\s\"\\]+\.pdf)"
        r"[^,\r\n]*?,"
        r"(?P<sha>[0-9a-f]{64})",
        re.I,
    )

    added = 0
    for chunk in transcript_dir.rglob("*.jsonl"):
        try:
            raw = chunk.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except Exception:
            continue

        joined = raw.replace("\r\n", "").replace("\n", "")
        for m in pair_re.finditer(joined):
            url = m.group(1)
            sha = m.group("sha").lower()
            if sha not in sha_url:
                sha_url[sha] = url
                added += 1

    logger.info("从会话实录注入 (url, sha256) 配对 %d 条", added)
    return sha_url


def file_sha256(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None

    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError as exc:
        logger.warning("读取快照失败 %s: %s", path, exc)
        return None

    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv",
        default="data/raw/industry/chemicals/operating_rates/weekly_survey.csv",
    )
    parser.add_argument(
        "--raw-dir",
        default="data/raw/industry",
    )
    parser.add_argument(
        "--transcript-dir",
        default=None,
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=16,
    )
    parser.add_argument(
        "--skip-listing",
        action="store_true",
        help="跳过列表页抓取，仅使用已有缓存。",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="不下载候选 PDF，只应用已有 hash 映射。",
    )
    parser.add_argument(
        "--listing-csv",
        default=LISTING_CSV,
    )
    parser.add_argument(
        "--hash-map-csv",
        default=HASH_MAP_CSV,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只统计，不写回 CSV/缓存。",
    )
    args = parser.parse_args()

    csv_path = Path(args.csv)
    raw_dir = Path(args.raw_dir)
    listing_path = Path(args.listing_csv)
    hash_path = Path(args.hash_map_csv)

    if not csv_path.exists():
        raise SystemExit(f"CSV 不存在：{csv_path}")

    # 1) 读取/更新列表缓存
    listing = load_listing(listing_path)

    if not args.skip_listing:
        listing = fetch_listing(args.max_pages, listing)
        if not args.dry_run:
            save_listing(listing_path, listing)
    elif not listing:
        logger.info("离线模式：无列表缓存。")

    by_date: dict[str, list[str]] = {}
    for pub, url in listing:
        by_date.setdefault(pub, []).append(url)

    # 2) 读取已有哈希映射 + 实录
    sha_url = load_hash_map(hash_path)
    sha_url = ingest_transcript_pairs(
        Path(args.transcript_dir) if args.transcript_dir else None,
        sha_url,
    )

    # 3) 读取 CSV
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fields = list(reader.fieldnames or [])

    required = {"report_date", "raw_snapshot_path", "source_url", "status"}
    missing = required - set(fields)
    if missing:
        raise SystemExit(f"CSV 缺少字段：{', '.join(sorted(missing))}")

    # 兼容原脚本：不要要求 source 列
    snapshot_rows: list[dict[str, str]] = []

    for row in rows:
        meta = extract_snapshot_meta(row.get("raw_snapshot_path", "").strip())
        if meta:
            report_date, prefix16 = meta
            row["_snapshot_date"] = report_date
            row["_sha_prefix16"] = prefix16

            local_path = raw_dir / row["raw_snapshot_path"].strip()
            full_sha = file_sha256(local_path)

            row["_full_sha"] = full_sha or ""
            snapshot_rows.append(row)
        else:
            row["_snapshot_date"] = ""
            row["_sha_prefix16"] = ""
            row["_full_sha"] = ""

    logger.info(
        "CSV 总行数 %d，可识别 CFA 快照 %d",
        len(rows),
        len(snapshot_rows),
    )

    # 4) 首先用已有完整 SHA 直接精确绑定
    prefix_map: dict[str, list[tuple[str, str]]] = {}
    for sha, url in sha_url.items():
        prefix_map.setdefault(sha[:16], []).append((sha, url))

    exact = 0
    pending: list[dict[str, str]] = []

    for row in snapshot_rows:
        full_sha = row["_full_sha"]
        prefix = row["_sha_prefix16"]

        bound = sha_url.get(full_sha) if full_sha else None

        if bound:
            row["source_url"] = bound
            row["status"] = "HASH_EXACT"
            exact += 1
        elif full_sha and full_sha in sha_url:
            # 理论上不会到这里，仅保留防御
            row["source_url"] = sha_url[full_sha]
            row["status"] = "HASH_EXACT"
            exact += 1
        else:
            # 仅凭已有 hash 映射的 16 位前缀也可作为候选，
            # 但只有完整 SHA 才最终标记 HASH_EXACT。
            candidates = prefix_map.get(prefix, [])
            if len(candidates) == 1:
                # 候选唯一，但若本地没有完整快照，就只能标记前缀匹配。
                if not full_sha:
                    row["source_url"] = candidates[0][1]
                    row["status"] = "SHA16_PREFIX_MATCH"
                    exact += 1
                else:
                    pending.append(row)
            else:
                pending.append(row)

    # 5) 为尚未绑定的日期收集候选 URL
    pending_dates = {r["_snapshot_date"] for r in pending if r.get("_snapshot_date")}

    candidates: list[str] = []
    for date in sorted(pending_dates):
        candidates.extend(by_date.get(date, []))

    # 只下载尚未进入 hash map 的 URL
    known_urls = set(sha_url.values())
    todo = [url for url in dict.fromkeys(candidates) if url not in known_urls]

    logger.info(
        "待下载候选 URL %d 个，覆盖 %d 个发布日期",
        len(todo),
        len(pending_dates),
    )

    do_download = not args.dry_run and not args.no_download

    if do_download and not listing and pending:
        logger.warning("列表页不可达且无缓存：跳过下载。")
        do_download = False

    if do_download:
        try:
            from curl_cffi import requests
        except ImportError as exc:
            raise SystemExit("缺少 curl-cffi，请先：uv add curl-cffi") from exc

        ok = fail = 0

        for i, url in enumerate(todo, start=1):
            try:
                resp = requests.get(
                    url,
                    impersonate="chrome120",
                    timeout=25,
                )

                if resp.status_code != 200:
                    logger.warning(
                        "[%d/%d] HTTP %d %s",
                        i,
                        len(todo),
                        resp.status_code,
                        url,
                    )
                    fail += 1
                    time.sleep(0.2)
                    continue

                sha = sha256_bytes(resp.content)
                if sha not in sha_url:
                    sha_url[sha] = url
                ok += 1

            except Exception as exc:
                logger.warning(
                    "[%d/%d] 下载失败 %s: %s",
                    i,
                    len(todo),
                    url,
                    str(exc)[:160],
                )
                fail += 1

            time.sleep(0.15)

            if i % 10 == 0:
                logger.info(
                    "下载进度 %d/%d（成功 %d 失败 %d）",
                    i,
                    len(todo),
                    ok,
                    fail,
                )

        logger.info("下载完成：成功 %d，失败 %d", ok, fail)
        save_hash_map(hash_path, sha_url)

    else:
        logger.info(
            "跳过下载，仅使用现有 hash 映射（%d 条）",
            len(sha_url),
        )
        if not args.dry_run:
            save_hash_map(hash_path, sha_url)

    # 6) 重新构建 prefix map，并最终回写
    prefix_map = {}
    for sha, url in sha_url.items():
        prefix_map.setdefault(sha[:16], []).append((sha, url))

    for row in snapshot_rows:
        full_sha = row["_full_sha"]
        prefix = row["_sha_prefix16"]

        if full_sha and full_sha in sha_url:
            row["source_url"] = sha_url[full_sha]
            row["status"] = "HASH_EXACT"
        elif prefix and len(prefix_map.get(prefix, [])) == 1:
            # 本地快照可读但 hash map 没有完整 SHA 时：
            # 这里仅在已有唯一前缀匹配时使用，状态不会伪装成 HASH_EXACT。
            _, url = prefix_map[prefix][0]
            if not full_sha:
                row["source_url"] = url
                row["status"] = "SHA16_PREFIX_MATCH"
        # 保留原 source_url，并根据现有状态归类。
        elif row.get("source_url"):
            current = row.get("status", "").strip()
            row["status"] = current if current else "DATE_LEVEL_FALLBACK"
        else:
            row["status"] = "UNBOUND"

    # 删除临时字段
    for row in rows:
        row.pop("_snapshot_date", None)
        row.pop("_sha_prefix16", None)
        row.pop("_full_sha", None)

    exact_count = sum(1 for r in rows if r.get("status") == "HASH_EXACT")
    prefix_count = sum(1 for r in rows if r.get("status") == "SHA16_PREFIX_MATCH")
    fallback_count = sum(1 for r in rows if r.get("status") == "DATE_LEVEL_FALLBACK")
    unbound_count = sum(1 for r in rows if r.get("status") == "UNBOUND")

    logger.info("=== 绑定统计 ===")
    logger.info("HASH 精确绑定: %d", exact_count)
    logger.info("SHA16 唯一前缀绑定: %d", prefix_count)
    logger.info("日期级 fallback: %d", fallback_count)
    logger.info("完全未绑定: %d", unbound_count)

    if not args.dry_run:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

        logger.info("CSV 已更新：%s", csv_path)


if __name__ == "__main__":
    main()
