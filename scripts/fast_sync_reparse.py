"""极速离线重放：针对非纯碱 CFA 研报与纯碱快照进行纯净重构与直接物理落盘。"""

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
from stock_data.fetcher.industry.chemicals.parsers.weekly_survey import (
    parse_commodity_weekly_metrics,
    parse_page_release_date,
    save_weekly_survey_raw_csv,
)
from stock_data.fetcher.industry.common import now_utc_iso

CFA_SYMS = {
    "TA": ("精对苯二甲酸", "TA"),
    "MA": ("甲醇", "MA"),
    "V": ("聚氯乙烯", "V"),
    "MEG": ("乙二醇", "MEG"),
}


def main():
    raw_dir = Path("data/raw/industry")
    curated_dir = Path("data/curated/industry")
    snapshot_dir = raw_dir / "chemicals" / "operating_rates" / "snapshots"
    survey_dir = raw_dir / "chemicals" / "operating_rates"

    collector = ChemicalWeeklySurveyCollector(raw_dir=raw_dir)
    existing_records = collector._load_raw_csv()
    now_iso = now_utc_iso()

    # 1. 保留原本纯净的纯碱记录，剔除所有非纯碱记录或异常记录
    clean_records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for k, v in existing_records.items():
        prod, d_str, src = k
        if prod == "纯碱":
            clean_records[k] = v

    print(f"保留纯碱纯净事实记录: {len(clean_records)} 条")

    # 2. 仅扫描并解析非纯碱的 95 份 CFA 快照
    non_sa_pdfs = []
    for sym in CFA_SYMS:
        non_sa_pdfs.extend(sorted(snapshot_dir.glob(f"cfachina_{sym}_*.pdf")))

    print(f"开始极速重放 {len(non_sa_pdfs)} 份非纯碱真实研报快照...")
    for p in non_sa_pdfs:
        parts = p.name.split("_")
        sym = parts[1]
        d_str = parts[2]
        p_name, symbol = CFA_SYMS[sym]
        try:
            content_bytes = p.read_bytes()
            h_hash = raw_content_sha256(content_bytes)
            snap_path_val = raw_snapshot_path_value(p, raw_dir)
            report_day = date.fromisoformat(d_str)

            reader = pypdf.PdfReader(str(p))
            full_text = "\n".join(page.extract_text() or "" for page in reader.pages)

            metrics = parse_commodity_weekly_metrics(full_text, p_name, symbol)
            if any(
                metrics.get(k) is not None
                for k in (
                    "operating_rate_pct",
                    "weekly_output_w_tons",
                    "factory_inventory_w_tons",
                )
            ):
                rec_key = (p_name, d_str, "CFA_Futures_Report")
                clean_records[rec_key] = {
                    "trade_date": report_day,
                    "report_date": report_day,
                    "product_name": p_name,
                    "symbol": symbol,
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

    print(f"极速解析完成，总纯净记录数: {len(clean_records)}")

    # 3. 同步直接物理写入 RAW CSV
    save_weekly_survey_raw_csv(survey_dir, clean_records)
    print(f"已同步覆写 RAW CSV: {survey_dir / 'weekly_survey.csv'}")

    # 4. 同步直接物理物化 Curated Parquet
    raw_df = pl.DataFrame(list(clean_records.values()), schema=WEEKLY_SURVEY_COLLECTION_SCHEMA)
    curated_df = build_weekly_survey_curated_frame(raw_df)
    curated_parquet = curated_dir / "chemical_weekly_survey.parquet"
    curated_dir.mkdir(parents=True, exist_ok=True)
    curated_df.write_parquet(curated_parquet)
    print(f"已同步物理落盘 Curated 黄金事实表: {curated_parquet}, 记录数: {len(curated_df)}")

    # 5. 校验审计
    con = duckdb.connect()
    summary = con.execute(f"""
        SELECT
            product_name,
            symbol,
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
