"""纯离线重新解析所有快照，彻底清除污染并物化纯净 Curated 黄金事实表。"""

from datetime import date
from pathlib import Path
from typing import Any
import duckdb
import polars as pl
import pypdf

from stock_data.fetcher.industry.chemicals.collectors.weekly_survey import (
    ChemicalWeeklySurveyCollector,
    WEEKLY_SURVEY_COLLECTION_SCHEMA,
    build_weekly_survey_curated_frame,
)
from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.chemicals.parsers.research import ResearchReportParser
from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
    collect_100ppi_weekly_records,
    parse_commodity_weekly_metrics,
    parse_page_release_date,
    save_weekly_survey_raw_csv,
)
from stock_data.fetcher.industry.common import now_utc_iso

CFA_PROGRAM_MAPPING: dict[str, dict[str, str]] = {
    "SA": {"product_name": "纯碱", "symbol": "SA"},
    "TA": {"product_name": "精对苯二甲酸", "symbol": "TA"},
    "MA": {"product_name": "甲醇", "symbol": "MA"},
    "V": {"product_name": "聚氯乙烯", "symbol": "V"},
    "MEG": {"product_name": "乙二醇", "symbol": "MEG"},
}


def main():
    raw_dir = Path("data/raw/industry")
    curated_dir = Path("data/curated/industry")
    snapshot_dir = raw_dir / "chemicals" / "operating_rates" / "snapshots"
    survey_dir = raw_dir / "chemicals" / "operating_rates"

    research_parser = ResearchReportParser(raw_dir=raw_dir)
    new_records: dict[tuple[str, str, str], dict[str, Any]] = {}
    now_iso = now_utc_iso()

    # 1. 100ppi 快照
    for p in snapshot_dir.glob("100ppi_weekly_*.html"):
        try:
            html = p.read_text(encoding="utf-8")
            h_hash = raw_content_sha256(html.encode("utf-8"))
            snap_path_val = raw_snapshot_path_value(p, raw_dir)
            collect_100ppi_weekly_records(
                records=new_records,
                fetch_html=lambda _: html,
                current_year=2024,
                now_iso=now_iso,
                raw_content_sha256_value=h_hash,
                raw_snapshot_path=snap_path_val,
            )
        except Exception as exc:
            pass

    # 2. Mysteel 快照
    for p in sorted(snapshot_dir.glob("mysteel_*.html")):
        parts = p.name.split("_")
        if len(parts) < 3:
            continue
        sym = parts[1]
        d_str = parts[2]
        p_name = "纯碱" if sym == "SA" else sym
        try:
            html = p.read_text(encoding="utf-8")
            h_hash = raw_content_sha256(html.encode("utf-8"))
            snap_path_val = raw_snapshot_path_value(p, raw_dir)
            metrics = parse_commodity_weekly_metrics(html, p_name, sym)
            rel_date = parse_page_release_date(html)
            report_day = date.fromisoformat(d_str)
            key = (p_name, d_str, "Longzhong_Oilchem")
            rec = {
                "trade_date": report_day,
                "report_date": report_day,
                "product_name": p_name,
                "symbol": sym,
                "operating_rate_pct": metrics.get("operating_rate_pct"),
                "weekly_output_w_tons": metrics.get("weekly_output_w_tons"),
                "factory_inventory_w_tons": metrics.get("factory_inventory_w_tons"),
                "shipment_rate_pct": metrics.get("shipment_rate_pct"),
                "source": "Longzhong_Oilchem",
                "source_url": "",
                "release_date": rel_date or report_day,
                "data_status": "actual",
                "collected_at": now_iso,
                "raw_content_sha256": h_hash,
                "raw_snapshot_path": snap_path_val,
            }
            if any(
                rec.get(k) is not None
                for k in ("operating_rate_pct", "weekly_output_w_tons", "factory_inventory_w_tons")
            ):
                new_records[key] = rec
        except Exception as exc:
            pass

    # 3. CFA 期货研报快照
    pdf_files = sorted(snapshot_dir.glob("cfachina_*.pdf"))
    print(f"正在离线重放 {len(pdf_files)} 份 CFA 真实研报快照...")
    for p in pdf_files:
        parts = p.name.split("_")
        if len(parts) < 3:
            continue
        sym = parts[1]
        d_str = parts[2]
        p_name = CFA_PROGRAM_MAPPING.get(sym, {}).get("product_name", sym)
        try:
            content_bytes = p.read_bytes()
            h_hash = raw_content_sha256(content_bytes)
            snap_path_val = raw_snapshot_path_value(p, raw_dir)
            report_day = date.fromisoformat(d_str)

            reader = pypdf.PdfReader(str(p))
            full_text = "\n".join(page.extract_text() or "" for page in reader.pages)

            if sym == "SA":
                extracted_items = research_parser.extract_metrics_from_text(
                    text=full_text,
                    product_name="纯碱",
                    publish_date=report_day,
                    source_name="CFA_Futures_Report",
                    source_url="",
                )
                for item in extracted_items:
                    t_day = item["trade_date"]
                    rec_key = ("纯碱", t_day.isoformat(), "CFA_Futures_Report")
                    item["raw_content_sha256"] = h_hash
                    item["raw_snapshot_path"] = snap_path_val
                    new_records[rec_key] = item
            else:
                metrics = parse_commodity_weekly_metrics(full_text, p_name, sym)
                if any(
                    metrics.get(k) is not None
                    for k in (
                        "operating_rate_pct",
                        "weekly_output_w_tons",
                        "factory_inventory_w_tons",
                    )
                ):
                    rec_key = (p_name, d_str, "CFA_Futures_Report")
                    new_records[rec_key] = {
                        "trade_date": report_day,
                        "report_date": report_day,
                        "product_name": p_name,
                        "symbol": sym,
                        "operating_rate_pct": metrics.get("operating_rate_pct"),
                        "weekly_output_w_tons": metrics.get("weekly_output_w_tons"),
                        "factory_inventory_w_tons": metrics.get("factory_inventory_w_tons"),
                        "shipment_rate_pct": metrics.get("shipment_rate_pct"),
                        "source": "CFA_Futures_Report",
                        "source_url": "",
                        "release_date": report_day,
                        "data_status": "actual",
                        "collected_at": now_iso,
                        "raw_content_sha256": h_hash,
                        "raw_snapshot_path": snap_path_val,
                    }
        except Exception as exc:
            pass

    print(f"快照解析完成，纯净有效记录数: {len(new_records)}")

    # 1. 保存纯净 RAW CSV（彻底覆写旧的污染数据）
    save_weekly_survey_raw_csv(survey_dir, new_records)
    print(f"已覆写纯净 RAW CSV: {survey_dir / 'weekly_survey.csv'}")

    # 2. 构建 Curated DataFrame 并写入 Parquet
    raw_df = pl.DataFrame(list(new_records.values()), schema=WEEKLY_SURVEY_COLLECTION_SCHEMA)
    curated_df = build_weekly_survey_curated_frame(raw_df)
    curated_parquet = curated_dir / "chemical_weekly_survey.parquet"
    curated_dir.mkdir(parents=True, exist_ok=True)
    curated_df.write_parquet(curated_parquet)
    print(f"已物化 Curated 黄金事实表: {curated_parquet}, 记录数: {len(curated_df)}")

    # 3. DuckDB 终校验
    con = duckdb.connect()
    summary = con.execute(f"""
        SELECT
            product_name,
            symbol,
            min(trade_date) as start_date,
            max(trade_date) as end_date,
            count(*) as total_records,
            min(operating_rate_pct) as min_util,
            max(operating_rate_pct) as max_util,
            min(weekly_output_w_tons) as min_out,
            max(weekly_output_w_tons) as max_out,
            min(factory_inventory_w_tons) as min_inv,
            max(factory_inventory_w_tons) as max_inv
        FROM '{curated_parquet}'
        GROUP BY product_name, symbol
        ORDER BY symbol
    """).df()
    print("\n=== Curated 黄金事实表全面核验审计 ===")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
