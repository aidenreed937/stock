"""CFA 期货研报历史周报指标审计与异常值诊断脚本。

针对 weekly_survey.csv 中由研报抽取的行，检查:
1. 开工率: 是否 < 65% 或 > 94% (可能误抓单个检修装置负荷或产销比);
2. 企业库存: 是否 < 12 万吨 或 > 220 万吨 (可能误抓环比去库/累库增减量，或误抓玻璃/重碱局部库存);
3. 周度产量: 是否 < 40 万吨 或 > 85 万吨;
4. 前视偏差: report_date 是否晚于 release_date (仅对 release_date 非空的行可校验);
5. 血统: raw_snapshot_path 非空时 source_url 必须是真实 http(s) URL；
   若存在 config/data_sources/cfa_url_hash_map.csv（URL->SHA256 内容哈希映射），
   进一步做哈希级校验：URL 内容哈希必须与本地快照一致（不一致=异常），
   并统计“哈希级精确绑定/发布日级兜底”行数；
6. 追溯原始 PDF 快照，打印上下文证据链。
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any

import pypdf

HASH_MAP_CSV = Path("config/data_sources/cfa_url_hash_map.csv")


def audit_weekly_survey(raw_dir: Path) -> list[dict[str, Any]]:
    csv_file = raw_dir / "chemicals" / "operating_rates" / "weekly_survey.csv"
    if not csv_file.exists():
        print(f"File not found: {csv_file}")
        return []

    with csv_file.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    anomalies: list[dict[str, Any]] = []
    lookahead_checked = 0
    lookahead_violations = 0
    unchecked_release = 0
    # 哈希级血统状态（需要 cfa_url_hash_map.csv）
    url2shas: dict[str, set[str]] = {}
    if HASH_MAP_CSV.exists():
        with HASH_MAP_CSV.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("url") and row.get("sha256"):
                    url2shas.setdefault(row["url"], set()).add(row["sha256"])
    hash_exact = 0
    hash_conflict = 0
    hash_fallback = 0
    hash_unchecked = 0
    for idx, r in enumerate(rows, start=2):
        if r.get("product_name") != "纯碱":
            continue

        report_date = r.get("report_date", "")
        op_rate = float(r["operating_rate_pct"]) if r.get("operating_rate_pct") else None
        inv = float(r["factory_inventory_w_tons"]) if r.get("factory_inventory_w_tons") else None
        output = float(r["weekly_output_w_tons"]) if r.get("weekly_output_w_tons") else None
        source_url = r.get("source_url", "")
        snap_path = r.get("raw_snapshot_path", "")

        issues = []
        if op_rate is not None and (op_rate < 65.0 or op_rate > 94.0):
            issues.append(f"异常开工率: {op_rate}%")
        if inv is not None and (inv < 12.0 or inv > 220.0):
            issues.append(f"异常库存: {inv}万吨")
        if output is not None and (output < 40.0 or output > 85.0):
            issues.append(f"异常周产: {output}万吨")

        release_date = (r.get("release_date") or "").strip()
        if release_date:
            lookahead_checked += 1
            if report_date and report_date > release_date:
                issues.append(
                    f"前视偏差: report_date({report_date}) > release_date({release_date})"
                )
                lookahead_violations += 1
        else:
            unchecked_release += 1

        if snap_path and not source_url.startswith("http"):
            issues.append(f"血统异常: source_url 非真实 URL ({source_url})")

        # 哈希级血统校验（仅 CFA 快照；映射存在时执行）
        if "cfachina_SA_" in snap_path:
            known_shas = url2shas.get(source_url)
            if known_shas:
                local_sha = r.get("raw_content_sha256") or ""
                if not local_sha:
                    try:
                        p = raw_dir / snap_path
                        h = hashlib.sha256()
                        with p.open("rb") as pf:
                            for chunk in iter(lambda: pf.read(1 << 20), b""):
                                h.update(chunk)
                        local_sha = h.hexdigest()
                    except Exception:
                        local_sha = ""
                if len(known_shas) > 1:
                    # 同一 URL 被不同时期旧 CSV 绑到多个内容哈希：需网络复核真实文件
                    hash_conflict += 1
                    issues.append("血统异常: URL 内容哈希冲突（同一 URL 多快照，待网络复核）")
                elif local_sha and local_sha == next(iter(known_shas)):
                    hash_exact += 1
                elif not local_sha:
                    hash_unchecked += 1
                else:
                    hash_conflict += 1
                    issues.append("血统异常: URL 内容哈希与本地快照不一致")
            else:
                hash_fallback += 1

        if issues:
            anomalies.append(
                {
                    "row": idx,
                    "date": report_date,
                    "issues": issues,
                    "op_rate": op_rate,
                    "inv": inv,
                    "output": output,
                    "snap_path": snap_path,
                    "source_url": source_url,
                }
            )

    print(f"总计检查 {len(rows)} 行，发现 {len(anomalies)} 处异常点位：")
    print(f"  - 指标/血统/前视等异常合计: {len(anomalies)} 处")
    print(
        f"  - 前视偏差可校验行: {lookahead_checked}，违规: {lookahead_violations}；release_date 为空未校验: {unchecked_release}"
    )
    if url2shas:
        print(
            f"  - CFA 哈希级血统: 精确绑定 {hash_exact}，URL 哈希冲突 {hash_conflict}，发布日级兜底 {hash_fallback}，快照缺失未校验 {hash_unchecked}"
        )
    else:
        print("  - CFA 哈希级血统: 未启用（缺 config/data_sources/cfa_url_hash_map.csv）")
    print()
    for a in anomalies:
        print(f"第 {a['row']} 行 | 日期: {a['date']} | 问题: {', '.join(a['issues'])}")
        print(f"   快照: {a['snap_path']}")
        # 尝试从快照中提取上下文
        if a["snap_path"]:
            p = raw_dir / a["snap_path"]
            if not p.exists():
                p = Path(a["snap_path"])
            if p.exists() and p.suffix == ".pdf":
                try:
                    pdf_reader = pypdf.PdfReader(str(p))
                    text = "\n".join(page.extract_text() or "" for page in pdf_reader.pages)
                    text = re.sub(r"\s+", " ", text)
                    snippets = []
                    for kw in ["库存", "开工", "产量"]:
                        for m in re.finditer(rf".{{0,30}}{kw}.{{0,40}}", text):
                            snip = m.group(0).strip()
                            if any(w in snip for w in ["万吨", "%"]):
                                snippets.append(snip)
                    if snippets:
                        print("   原文切片:")
                        for s in snippets[:3]:
                            print(f"     * {s}")
                except Exception as e:
                    print(f"   读取 PDF 出错: {e}")
        print()

    return anomalies


if __name__ == "__main__":
    audit_weekly_survey(Path("data/raw/industry"))
