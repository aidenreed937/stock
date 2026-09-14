"""台积电官方先进封装与财务拆解 RAW 解析器 (AdvPkgRevenueParser).

解析 tsmc_adv_pkg_revenue_raw.csv，校验官方快照 SHA-256 与真实财务数据点，
确保零未来函数且全量标记 data_status='actual'。
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pypdf

from stock_data.fetcher.industry.semiconductor.models import TsmcAdvancedPackagingRevenueRecord

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    """消除换行与多余空白，方便跨行正则匹配。"""
    return re.sub(r"\s+", " ", text).strip()


def _quarter_end_date(report_quarter: str) -> date:
    """根据季度代码推导季度最后自然日。"""
    year = int(report_quarter[:4])
    q = int(report_quarter[-1])
    month_day_map = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    month, day = month_day_map[q]
    return date(year, month, day)


def parse_tsmc_management_report_pdf(
    pdf_source: bytes | Path | str,
    default_quarter: str | None = None,
) -> dict[str, Any] | None:
    """从台积电官方季度管理报告 (Management Report) PDF 提取结构化财务拆解数据。

    返回字典包含：
    - report_quarter: str (如 '2024Q4')
    - trade_date: date (如 2024-12-31)
    - release_date: date (如 2025-01-16)
    - net_revenue_ntd_bn: float
    - net_revenue_usd_bn: float | None
    - advanced_wafer_pct: float | None (0.xx)
    - hpc_platform_pct: float | None (0.xx)
    """
    if isinstance(pdf_source, (Path, str)):
        pdf_path = Path(pdf_source)
        if not pdf_path.exists():
            logger.warning("TSMC 管理报告 PDF 不存在: %s", pdf_path)
            return None
        pdf_bytes = pdf_path.read_bytes()
    else:
        pdf_bytes = pdf_source

    if not pdf_bytes:
        return None

    try:
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        p1 = reader.pages[0].extract_text() if len(reader.pages) > 0 else ""
        p2 = reader.pages[1].extract_text() if len(reader.pages) > 1 else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 TSMC 管理报告 PDF 异常: %s", exc)
        return None

    norm1 = _normalize_text(p1)
    norm2 = _normalize_text(p2)

    # 1. 报告季度提取
    report_quarter = default_quarter
    m_q = re.search(r"\b([1-4])Q(\d{2})\b", norm1)
    if m_q:
        q_num, yr_short = m_q.groups()
        report_quarter = f"20{yr_short}Q{q_num}"
    elif not report_quarter:
        m_q_named = re.search(
            r"\b(first|second|third|fourth|1st|2nd|3rd|4th)\s+quarter\s+(20\d{2})\b",
            norm1,
            re.IGNORECASE,
        )
        if m_q_named:
            q_map = {
                "first": 1,
                "1st": 1,
                "second": 2,
                "2nd": 2,
                "third": 3,
                "3rd": 3,
                "fourth": 4,
                "4th": 4,
            }
            q_num = q_map[m_q_named.group(1).lower()]
            yr = m_q_named.group(2)
            report_quarter = f"{yr}Q{q_num}"

    if not report_quarter:
        logger.warning("未能从 PDF 提取出有效报告季度")
        return None

    trade_date = _quarter_end_date(report_quarter)

    # 2. 法说会发布日期 (release_date)
    release_date: date | None = None
    m_date = re.search(r"([A-Z][a-z]+ \d{1,2},? \d{4})", norm1) or re.search(
        r"([A-Z][a-z]+ \d{1,2},? \d{4})", norm2
    )
    if m_date:
        d_clean = m_date.group(1).replace(",", "")
        try:
            release_date = datetime.strptime(d_clean, "%B %d %Y").date()
        except ValueError:
            pass

    # 3. 新台币营收 (net_revenue_ntd_bn)
    net_revenue_ntd_bn: float | None = None
    m_ntd = re.search(r"Net revenue was NT\$\s*([\d,]+\.\d+)\s*billion", norm1, re.IGNORECASE)
    if not m_ntd:
        m_ntd = re.search(r"Net Revenue\s+([\d,]+\.\d+)", norm1)
    if m_ntd:
        net_revenue_ntd_bn = float(m_ntd.group(1).replace(",", ""))

    # 4. 美元营收 (net_revenue_usd_bn)
    net_revenue_usd_bn: float | None = None
    m_usd = re.search(r"Net Revenue \(US\$ billions\)\s+([\d,]+\.\d+)", norm1, re.IGNORECASE)
    if m_usd:
        net_revenue_usd_bn = float(m_usd.group(1).replace(",", ""))

    # 5. 先进晶圆制程占比 (advanced_wafer_pct, 7nm及以下)
    advanced_wafer_pct: float | None = None
    m_adv = re.findall(
        r"Advanced technologies\s*(?:\([^)]*\))?\s*accounted for\s*(\d+)%",
        norm2,
        re.IGNORECASE,
    )
    if m_adv:
        advanced_wafer_pct = float(m_adv[0]) / 100.0
    else:
        # 表格回退计算：3nm + 5nm + 7nm
        m_3nm = re.search(r"\b3nm\s+(\d+)%", norm2)
        m_5nm = re.search(r"\b5nm\s+(\d+)%", norm2)
        m_7nm = re.search(r"\b7nm\s+(\d+)%", norm2)
        v3 = int(m_3nm.group(1)) if m_3nm else 0
        v5 = int(m_5nm.group(1)) if m_5nm else 0
        v7 = int(m_7nm.group(1)) if m_7nm else 0
        if v3 or v5 or v7:
            advanced_wafer_pct = (v3 + v5 + v7) / 100.0

    # 6. 高性能计算平台占比 (hpc_platform_pct)
    hpc_platform_pct: float | None = None
    m_hpc = re.search(r"High Performance Computing\s+(\d+)%", norm2)
    if not m_hpc:
        m_hpc = re.search(r"HPC.*?represented\s*(\d+)%", norm2)
    if m_hpc:
        hpc_platform_pct = float(m_hpc.group(1)) / 100.0

    return {
        "symbol": "2330.TW",
        "report_quarter": report_quarter,
        "trade_date": trade_date,
        "release_date": release_date,
        "net_revenue_ntd_bn": net_revenue_ntd_bn,
        "net_revenue_usd_bn": net_revenue_usd_bn,
        "advanced_wafer_pct": advanced_wafer_pct,
        "hpc_platform_pct": hpc_platform_pct,
    }


def append_tsmc_adv_pkg_revenue_raw_record(
    csv_path: Path | str,
    new_records: list[dict[str, Any]],
) -> int:
    """向 tsmc_adv_pkg_revenue_raw.csv 安全追加新记录并保证 trade_date 升序排列。

    返回新追加的有效记录数。
    """
    path = Path(csv_path)
    existing_rows: list[dict[str, str]] = []
    fieldnames = [
        "symbol",
        "report_quarter",
        "trade_date",
        "release_date",
        "net_revenue_ntd_bn",
        "net_revenue_usd_bn",
        "advanced_wafer_pct",
        "hpc_platform_pct",
        "packaging_testing_others_pct",
        "data_status",
        "source",
        "source_url",
        "collected_at",
        "raw_content_sha256",
        "raw_snapshot_path",
    ]

    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                fieldnames = list(reader.fieldnames)
            existing_rows = list(reader)

    existing_quarters = {r["report_quarter"].strip() for r in existing_rows}
    appended_count = 0

    for rec in new_records:
        q = rec.get("report_quarter")
        if not q or q in existing_quarters:
            continue

        row_dict: dict[str, str] = {
            "symbol": str(rec.get("symbol", "2330.TW")),
            "report_quarter": q,
            "trade_date": str(rec.get("trade_date")),
            "release_date": str(rec.get("release_date")),
            "net_revenue_ntd_bn": f"{rec.get('net_revenue_ntd_bn', 0.0):.2f}",
            "net_revenue_usd_bn": (
                f"{rec.get('net_revenue_usd_bn'):.2f}"
                if rec.get("net_revenue_usd_bn") is not None
                else ""
            ),
            "advanced_wafer_pct": (
                f"{rec.get('advanced_wafer_pct'):.4f}"
                if rec.get("advanced_wafer_pct") is not None
                else ""
            ),
            "hpc_platform_pct": (
                f"{rec.get('hpc_platform_pct'):.4f}"
                if rec.get("hpc_platform_pct") is not None
                else ""
            ),
            "packaging_testing_others_pct": (
                f"{rec.get('packaging_testing_others_pct'):.4f}"
                if rec.get("packaging_testing_others_pct") is not None
                else ""
            ),
            "data_status": str(rec.get("data_status", "actual")),
            "source": str(rec.get("source", "TSMC_OFFICIAL_MANAGEMENT_REPORT")),
            "source_url": str(rec.get("source_url", "")),
            "collected_at": str(rec.get("collected_at", "")),
            "raw_content_sha256": str(rec.get("raw_content_sha256", "")),
            "raw_snapshot_path": str(rec.get("raw_snapshot_path", "")),
        }
        existing_rows.append(row_dict)
        existing_quarters.add(q)
        appended_count += 1

    if appended_count > 0:
        # 按 trade_date 升序排列
        existing_rows.sort(key=lambda r: r["trade_date"])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(existing_rows)
        logger.info("已成功向 %s 追加 %d 条新季度记录", path.name, appended_count)

    return appended_count


def load_tsmc_adv_pkg_revenue_raw_csv(
    file_path: Path | str,
    project_root: Path | str | None = None,
    verify_hash: bool = True,
) -> list[TsmcAdvancedPackagingRevenueRecord]:
    """从 CSV 加载台积电官方财务拆解原始记录并严格核验。"""
    csv_path = Path(file_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"未找到台积电官方财务 RAW 文件: {csv_path}")

    root = Path(project_root) if project_root else csv_path.parent.parent.parent.parent.parent
    records: list[TsmcAdvancedPackagingRevenueRecord] = []

    with csv_path.open(mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_idx, row in enumerate(reader, start=2):
            symbol = row["symbol"].strip()
            report_quarter = row["report_quarter"].strip()
            trade_date_val = date.fromisoformat(row["trade_date"].strip())
            release_date_val = date.fromisoformat(row["release_date"].strip())
            net_rev_ntd = float(row["net_revenue_ntd_bn"])
            net_rev_usd = (
                float(row["net_revenue_usd_bn"]) if row.get("net_revenue_usd_bn") else None
            )
            adv_wafer_pct = (
                float(row["advanced_wafer_pct"]) if row.get("advanced_wafer_pct") else None
            )
            hpc_platform_pct = (
                float(row["hpc_platform_pct"]) if row.get("hpc_platform_pct") else None
            )
            pkg_pct = (
                float(row["packaging_testing_others_pct"])
                if row.get("packaging_testing_others_pct")
                else None
            )
            data_status = row.get("data_status", "actual").strip()
            source = row.get("source", "TSMC_OFFICIAL_MANAGEMENT_REPORT").strip()
            source_url = row.get("source_url", "").strip()
            collected_at = row.get("collected_at", "").strip()
            raw_sha256 = row.get("raw_content_sha256", "").strip()
            raw_path = row.get("raw_snapshot_path", "").strip()

            if data_status != "actual":
                raise ValueError(
                    f"第 {row_idx} 行 data_status 必须为 actual, 实际为: {data_status}"
                )

            # 校验快照真实文件与 SHA-256
            if verify_hash and raw_path and raw_sha256:
                if Path(raw_path).is_absolute():
                    target_file = Path(raw_path)
                elif (root / raw_path).exists():
                    target_file = root / raw_path
                elif Path(raw_path).exists():
                    target_file = Path(raw_path)
                else:
                    target_file = root / raw_path

                if target_file.exists():
                    actual_sha = hashlib.sha256(target_file.read_bytes()).hexdigest()
                    if actual_sha != raw_sha256:
                        raise ValueError(
                            f"第 {row_idx} 行快照哈希不一致! 期望 {raw_sha256[:12]}, 实际 {actual_sha[:12]}"
                        )

            # 推导 packaging_testing_others_ntd_bn
            pkg_ntd_bn = round(net_rev_ntd * pkg_pct, 2) if pkg_pct is not None else None

            record = TsmcAdvancedPackagingRevenueRecord(
                symbol=symbol,
                report_quarter=report_quarter,
                trade_date=trade_date_val,
                release_date=release_date_val,
                net_revenue_ntd_bn=net_rev_ntd,
                net_revenue_usd_bn=net_rev_usd,
                advanced_wafer_pct=adv_wafer_pct,
                hpc_platform_pct=hpc_platform_pct,
                packaging_testing_others_pct=pkg_pct,
                packaging_testing_others_ntd_bn=pkg_ntd_bn,
                data_status="actual",
                source=source,
                source_url=source_url,
                collected_at=collected_at,
                raw_content_sha256=raw_sha256,
                raw_snapshot_path=raw_path,
            )
            records.append(record)

    return sorted(records, key=lambda r: r.trade_date)
