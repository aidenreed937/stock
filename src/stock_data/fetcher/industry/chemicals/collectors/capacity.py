"""10年大周期化工行业官方产能利用率与实物产量大底座 (ChemicalCapacityUtilization10Y)。

数据属性与 10 年跨周期架构:
1. 真实分子: 国家统计局 (NBS) 官方公布的真实实物月度产量 (2016-09 至今);
2. 真实分母: 中国纯碱工业协会 / 石化联合会 (CPCIF) 历年行业有效产能年鉴数据;
3. RAW 历史底表原则: 严格不做任何计算，仅保存源端物理量文本与日期，利用率计算下沉至 Curated Transform;
4. 存储位置:
   - RAW: data/raw/industry/chemicals/capacity/data.parquet (强类型无计算底表);
   - Curated: data/curated/industry/chemical_capacity_utilization_10y.parquet (包含折算与利用率).
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl

from stock_data.fetcher.industry.chemicals.lineage import (
    raw_content_sha256,
    raw_snapshot_path_value,
)
from stock_data.fetcher.industry.chemicals.paths import ChemicalsRawPaths
from stock_data.fetcher.industry.chemicals.quality import validate_capacity_raw_frame
from stock_data.fetcher.industry.chemicals.schemas import (
    CAPACITY_RAW_SCHEMA,
    CAPACITY_UTILIZATION_SCHEMA,
)
from stock_data.fetcher.industry.chemicals.transforms.capacity import (
    build_capacity_raw_frame,
    build_capacity_utilization_frame,
)
from stock_data.fetcher.industry.common import (
    now_utc_iso,
    parse_month_string,
    save_raw_snapshot,
)
from stock_data.fetcher.industry.contracts import IndustryFrameResult

logger = logging.getLogger(__name__)

NBS_PRODUCT_PATH_MAPPING: dict[str, str] = {
    "纯碱": "工业 > 工业主要产品产量 > 纯碱（碳酸钠）",
    "碳酸钠": "工业 > 工业主要产品产量 > 纯碱（碳酸钠）",
    "SA": "工业 > 工业主要产品产量 > 纯碱（碳酸钠）",
    "平板玻璃": "工业 > 工业主要产品产量 > 平板玻璃",
    "玻璃": "工业 > 工业主要产品产量 > 平板玻璃",
    "FG": "工业 > 工业主要产品产量 > 平板玻璃",
    "烧碱": "工业 > 工业主要产品产量 > 烧碱（折100％）",
    "SH": "工业 > 工业主要产品产量 > 烧碱（折100％）",
    "硫酸": "工业 > 工业主要产品产量 > 硫酸（折100％）",
    "乙烯": "工业 > 工业主要产品产量 > 乙烯",
    "化学纤维": "工业 > 工业主要产品产量 > 化学纤维",
}

CAPACITY_RAW_CANDIDATES = (
    "chemicals/capacity/soda_ash_annual_capacity.csv",
    "chemicals/nbs/soda_ash_annual_capacity.csv",
    "chemicals/soda_ash_annual_capacity.csv",
    "soda_ash_annual_capacity.csv",
)

NBS_PRODUCT_SPECS: tuple[dict[str, Any], ...] = (
    {
        "product_name": "纯碱",
        "symbol": "SA",
        "csv_filename": "nbs_soda_ash_monthly.csv",
        "unit": "万吨",
        "capacity_type": "soda_ash",
    },
    {
        "product_name": "烧碱",
        "symbol": "SH",
        "csv_filename": "nbs_caustic_soda_monthly.csv",
        "unit": "万吨",
        "capacity_type": "caustic_soda",
    },
    {
        "product_name": "PTA",
        "symbol": "TA",
        "csv_filename": "nbs_pta_monthly.csv",
        "unit": "万吨",
        "capacity_type": "pta",
    },
    {
        "product_name": "甲醇",
        "symbol": "MA",
        "csv_filename": "nbs_methanol_monthly.csv",
        "unit": "万吨",
        "capacity_type": "methanol",
    },
    {
        "product_name": "初级形态塑料",
        "symbol": "PL",
        "csv_filename": "nbs_plastics_monthly.csv",
        "unit": "万吨",
        "capacity_type": None,
    },
    {
        "product_name": "农用化肥",
        "symbol": "CF",
        "csv_filename": "nbs_fertilizer_monthly.csv",
        "unit": "万吨",
        "capacity_type": None,
    },
    {
        "product_name": "平板玻璃",
        "symbol": "FG",
        "csv_filename": "nbs_plate_glass_monthly.csv",
        "unit": "万重量箱",
        "capacity_type": "plate_glass",
    },
    {
        "product_name": "合成纤维",
        "symbol": "SF",
        "csv_filename": "nbs_synthetic_fiber_monthly.csv",
        "unit": "万吨",
        "capacity_type": "synthetic_fiber",
    },
    {
        "product_name": "尿素",
        "symbol": "UR",
        "csv_filename": "nbs_urea_monthly.csv",
        "unit": "万吨",
        "capacity_type": "urea",
    },
    {
        "product_name": "PVC",
        "symbol": "V",
        "csv_filename": "nbs_pvc_monthly.csv",
        "unit": "万吨",
        "capacity_type": "pvc",
    },
)


def _has_capacity_csv(raw_dir: Path, capacity_type: str | None) -> bool:
    """检查本地磁盘是否真实存在该品种的经审计年度产能 CSV 文件。"""
    if not capacity_type:
        return False
    candidates = (
        f"chemicals/capacity/{capacity_type}_annual_capacity.csv",
        f"chemicals/nbs/{capacity_type}_annual_capacity.csv",
        f"chemicals/{capacity_type}_annual_capacity.csv",
        f"{capacity_type}_annual_capacity.csv",
    )
    return any((raw_dir / c).exists() for c in candidates)


class NbsChemicalsCrawler:
    """国家统计局 (NBS) 官方公开月度化工行业实物产量在线采集器。

    架构说明：
        底层基于 akshare 封装的国家统计局官方目录树接口 (macro_china_nbs_nation)
        执行多品种 (纯碱/平板玻璃/烧碱等) 在线采集与 2-Tier RAW 快照落盘。
    """

    def __init__(
        self,
        raw_dir: Path | str,
        timeout: int = 15,
        enable_network: bool = False,
    ) -> None:
        self.raw_root = Path(raw_dir)
        self.timeout = timeout
        self.enable_network = enable_network

    def fetch_month(
        self,
        report_month: str,
        product_name: str = "纯碱",
    ) -> dict[str, Any] | None:
        """从国家统计局 (NBS) 官方宏观月度发布获取指定月份化工品产量原始数据。"""
        return self._fetch_nbs_product(report_month, product_name=product_name)

    def _fetch_nbs_soda_ash(self, report_month: str) -> dict[str, Any] | None:
        """从国家统计局接口获取指定月份纯碱产量原始数据（兼容旧方法调用与单测 mock）。"""
        return self._fetch_nbs_product(report_month, product_name="纯碱")

    def _fetch_nbs_product(
        self,
        report_month: str,
        product_name: str = "纯碱",
    ) -> dict[str, Any] | None:
        """从国家统计局接口获取指定月份产品产量原始数据（通过 akshare 官方目录树）。"""
        # 1. 优先尝试本地物理快照回放（消除网络依赖与前视偏差，保证幂等离线可复现）
        snapshot_file = (
            self.raw_root
            / "chemicals"
            / "capacity"
            / "snapshots"
            / f"nbs_{product_name}_{report_month}.json.gz"
        )
        if snapshot_file.exists():
            try:
                import gzip

                with gzip.open(snapshot_file, "rt", encoding="utf-8") as f:
                    snap_data = json.load(f)
                metrics = snap_data.get("metrics") or {}
                mo_val = int(report_month[5:7])
                yr_val = int(report_month[:4])
                rel_date = date(yr_val, mo_val + 1, 18) if mo_val < 12 else date(yr_val + 1, 1, 18)
                spec = next(
                    (s for s in NBS_PRODUCT_SPECS if s["product_name"] == product_name), None
                )
                payload_bytes = snapshot_file.read_bytes()
                return {
                    "product_name": product_name,
                    "symbol": spec["symbol"] if spec else "OTHER",
                    "unit": spec["unit"] if spec else "万吨",
                    "report_month": report_month,
                    "output_current_raw": metrics.get("output_current"),
                    "output_cumulative_raw": metrics.get("output_cumulative"),
                    "output_yoy_raw": metrics.get("output_yoy"),
                    "output_cum_yoy_raw": metrics.get("output_cum_yoy"),
                    "source": "NBS_Official",
                    "release_date": rel_date,
                    "raw_content_sha256": raw_content_sha256(payload_bytes),
                    "raw_snapshot_path": raw_snapshot_path_value(snapshot_file, self.raw_root),
                }
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"快照回放失败 [{snapshot_file}]: {exc}")

        if not self.enable_network:
            logger.debug(
                "NbsChemicalsCrawler 处于离线安全模式 (enable_network=False)，跳过 NBS 请求 [%s, %s]",
                report_month,
                product_name,
            )
            return None

        path = NBS_PRODUCT_PATH_MAPPING.get(product_name)
        if not path:
            logger.debug(f"未配置 NBS 目录树路径: {product_name}")
            return None

        year = report_month[:4]
        try:
            import akshare as ak

            period_arg = f"{year}-{year}"
            df = ak.macro_china_nbs_nation(
                kind="月度数据",
                path=path,
                period=period_arg,
            )
            if df is None or df.empty:
                return None

            month_int = int(report_month[5:7])
            col_name = f"{year}年{month_int}月"
            if col_name not in df.columns:
                return None

            output_current: str | None = None
            output_cumulative: str | None = None
            output_yoy: str | None = None
            output_cum_yoy: str | None = None

            for idx, val in df[col_name].items():
                row_label = str(idx)
                val_str = str(val).strip() if pd.notna(val) else None
                if val_str is None or val_str.lower() in ("nan", "none", ""):
                    continue
                if "当期值" in row_label or "本月" in row_label:
                    output_current = val_str
                elif "累计值" in row_label:
                    output_cumulative = val_str
                elif "同比增长" in row_label:
                    output_yoy = val_str
                elif "累计增长" in row_label:
                    output_cum_yoy = val_str

            if output_current is None and output_yoy is None and output_cumulative is None:
                return None

            payload_bytes = json.dumps(
                {
                    "product_name": product_name,
                    "report_month": report_month,
                    "metrics": {
                        "output_current": output_current,
                        "output_cumulative": output_cumulative,
                        "output_yoy": output_yoy,
                        "output_cum_yoy": output_cum_yoy,
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")

            snapshot_path = save_raw_snapshot(
                "chemicals",
                f"capacity/snapshots/nbs_{product_name}_{report_month}.json.gz",
                payload_bytes,
                base_dir=self.raw_root,
                compress=True,
            )

            mo_val = int(report_month[5:7])
            yr_val = int(year)
            rel_date = date(yr_val, mo_val + 1, 18) if mo_val < 12 else date(yr_val + 1, 1, 18)

            spec = next((s for s in NBS_PRODUCT_SPECS if s["product_name"] == product_name), None)
            parsed: dict[str, Any] = {
                "product_name": product_name,
                "symbol": spec["symbol"] if spec else "OTHER",
                "unit": spec["unit"] if spec else "万吨",
                "report_month": report_month,
                "output_current_raw": output_current,
                "output_cumulative_raw": output_cumulative,
                "output_yoy_raw": output_yoy,
                "output_cum_yoy_raw": output_cum_yoy,
                "source": "NBS_Official",
                "release_date": rel_date,
                "raw_content_sha256": raw_content_sha256(payload_bytes),
                "raw_snapshot_path": raw_snapshot_path_value(snapshot_path, self.raw_root),
            }
            return parsed
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"NBS [{product_name}] 在线采集失败 [{report_month}]: {exc}")
            return None

    def fetch_range(
        self,
        periods: list[str],
        product_name: str = "纯碱",
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """批量获取指定范围的月份原始数据。"""
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        for period in periods:
            record = self.fetch_month(period, product_name=product_name)
            if record is not None:
                results.append(record)
            else:
                errors.append(f"{period}: NBS [{product_name}] 未获取到数据或暂未发布")
        return results, errors


# 向后兼容别名
NbsSodaAshCrawler = NbsChemicalsCrawler


class ChemicalCapacityUtilization10Y:
    """10年大周期产能利用率构建器与增量采集适配器。"""

    NBS_RELEASE_DAY = 18

    def __init__(
        self,
        raw_dir: Path | str,
        crawler: Any = None,
        enable_online: bool = False,
    ) -> None:
        self.raw_dir = Path(raw_dir)
        self.paths = ChemicalsRawPaths(self.raw_dir)
        self.nbs_dir = self.raw_dir / "chemicals" / "nbs"
        self._custom_crawler = crawler is not None
        self.enable_online = enable_online
        self.crawler = crawler or NbsChemicalsCrawler(
            raw_dir=self.raw_dir, enable_network=enable_online
        )

    def build_raw_utilization(self) -> pl.DataFrame:
        """优先读取自包含的多品种统一 RAW data.parquet；若不存在或有新品种且存在对应 CSV 则从备用源构建。"""
        # 1. 优先读取标准统一底表 data/raw/industry/chemicals/data.parquet
        parquet_path = self.paths.chemicals_parquet
        if parquet_path.exists():
            try:
                df = pl.read_parquet(parquet_path)
                if not df.is_empty():
                    existing_products = (
                        set(df.get_column("product_name").to_list())
                        if "product_name" in df.columns
                        else set()
                    )
                    missing_with_csv = [
                        s
                        for s in NBS_PRODUCT_SPECS
                        if s["product_name"] not in existing_products
                        and (self.nbs_dir / s["csv_filename"]).exists()
                    ]
                    missing_caps = [
                        s["product_name"]
                        for s in NBS_PRODUCT_SPECS
                        if s.get("capacity_type") is not None
                        and _has_capacity_csv(self.raw_dir, s.get("capacity_type"))
                        and s["product_name"] in existing_products
                        and "annual_capacity_raw" in df.columns
                        and df.filter(pl.col("product_name") == s["product_name"])
                        .select(pl.col("annual_capacity_raw").drop_nulls())
                        .is_empty()
                    ]
                    if not missing_with_csv and not missing_caps:
                        aligned = _align_to_raw_schema(df).sort(["product_name", "trade_date"])
                        return self._backfill_annual_capacities(aligned)
            except Exception as exc:
                logger.warning(f"读取 RAW Parquet 底表失败: {exc}，尝试备用路径")

        # 2. 兼容旧版路径 data/raw/industry/chemicals/capacity/data.parquet
        legacy_parquet = self.paths.capacity_dir / "data.parquet"
        if legacy_parquet.exists() and legacy_parquet != parquet_path:
            try:
                df = pl.read_parquet(legacy_parquet)
                if not df.is_empty():
                    existing_products = (
                        set(df.get_column("product_name").to_list())
                        if "product_name" in df.columns
                        else set()
                    )
                    missing_with_csv = [
                        s
                        for s in NBS_PRODUCT_SPECS
                        if s["product_name"] not in existing_products
                        and (self.nbs_dir / s["csv_filename"]).exists()
                    ]
                    missing_caps = [
                        s["product_name"]
                        for s in NBS_PRODUCT_SPECS
                        if s.get("capacity_type") is not None
                        and _has_capacity_csv(self.raw_dir, s.get("capacity_type"))
                        and s["product_name"] in existing_products
                        and "annual_capacity_raw" in df.columns
                        and df.filter(pl.col("product_name") == s["product_name"])
                        .select(pl.col("annual_capacity_raw").drop_nulls())
                        .is_empty()
                    ]
                    if not missing_with_csv and not missing_caps:
                        aligned = _align_to_raw_schema(df).sort(["product_name", "trade_date"])
                        return self._backfill_annual_capacities(aligned)
            except Exception as exc:
                logger.warning(f"读取旧版 RAW Parquet 失败: {exc}，回退至 CSV 备用源")

        built_df = self._build_from_csv_candidates()
        if not built_df.is_empty():
            try:
                self.paths.chemicals_dir.mkdir(parents=True, exist_ok=True)
                built_df.write_parquet(parquet_path)
                logger.info(f"成功将多品种 RAW 底表保存至: {parquet_path} ({len(built_df)} 行)")
            except Exception as exc:
                logger.warning(f"保存 RAW Parquet 失败: {exc}")
        return built_df

    def _backfill_annual_capacities(self, df: pl.DataFrame) -> pl.DataFrame:
        """用最新的 *_annual_capacity.csv 对齐/回填 RAW 表中的年度产能和来源。"""
        if df.is_empty() or "product_name" not in df.columns or "trade_date" not in df.columns:
            return df

        caps_by_product: dict[str, dict[int, dict[str, float | str]]] = {}
        for spec in NBS_PRODUCT_SPECS:
            c_type = spec.get("capacity_type")
            if c_type:
                caps_by_product[spec["product_name"]] = _load_annual_capacity_for_spec(
                    self.raw_dir, c_type
                )

        if not caps_by_product:
            return df

        rows = df.to_dicts()
        changed = False
        for r in rows:
            p_name = str(r.get("product_name") or "")
            caps = caps_by_product.get(p_name, {})
            t_date = r.get("trade_date")
            yr = t_date.year if isinstance(t_date, date) else None
            if yr is None:
                m_str = str(r.get("report_month") or "")
                try:
                    yr = int(m_str[:4])
                except Exception:
                    continue
            cap_rec = caps.get(yr) if caps else None
            if cap_rec is not None:
                expected_cap: str | None = str(cap_rec["capacity"])
                expected_src: str | None = str(cap_rec["source"])
            else:
                expected_cap = None
                expected_src = None

            if (
                r.get("annual_capacity_raw") != expected_cap
                or r.get("capacity_source") != expected_src
            ):
                r["annual_capacity_raw"] = expected_cap
                r["capacity_source"] = expected_src
                changed = True

        if changed:
            updated_df = pl.DataFrame(rows, schema=CAPACITY_RAW_SCHEMA)
            try:
                self.paths.chemicals_parquet.parent.mkdir(parents=True, exist_ok=True)
                updated_df.write_parquet(self.paths.chemicals_parquet)
                logger.info("已按最新 CSV 产能底册自动回填并更新 RAW 底表")
            except Exception as exc:
                logger.debug(f"回填后持久化 RAW 失败: {exc}")
            return updated_df

        return df

    def _build_from_csv_candidates(self) -> pl.DataFrame:
        """从历史 CSV 候选项构建原始多品种 RAW 事实底表（严格不做任何计算）。"""
        soda_ash_caps = _load_soda_ash_capacity_by_year(self.raw_dir)
        caustic_soda_caps = _load_caustic_soda_capacity_by_year(self.raw_dir)
        pta_caps = _load_pta_capacity_by_year(self.raw_dir)
        methanol_caps = _load_methanol_capacity_by_year(self.raw_dir)
        plate_glass_caps = _load_plate_glass_capacity_by_year(self.raw_dir)
        synthetic_fiber_caps = _load_synthetic_fiber_capacity_by_year(self.raw_dir)
        urea_caps = _load_urea_capacity_by_year(self.raw_dir)
        pvc_caps = _load_pvc_capacity_by_year(self.raw_dir)
        now_iso = now_utc_iso()

        records: list[dict[str, Any]] = []

        for spec in NBS_PRODUCT_SPECS:
            csv_path = self.nbs_dir / spec["csv_filename"]
            if not csv_path.exists():
                alt_candidates = [
                    self.raw_dir / "chemicals" / spec["csv_filename"],
                    self.raw_dir / spec["csv_filename"],
                ]
                found_path = None
                for alt in alt_candidates:
                    if alt.exists():
                        found_path = alt
                        break
                if found_path is not None:
                    csv_path = found_path
                else:
                    logger.debug(f"NBS 产品事实 CSV 不存在，跳过: {csv_path}")
                    continue

            with csv_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    m_str = (r.get("report_month") or "").strip()
                    if not m_str:
                        continue
                    try:
                        yr, mo = parse_month_string(m_str)
                    except Exception:
                        continue

                    r_d = date(yr, mo, 1)

                    cap_raw: str | None = None
                    cap_src: str | None = None
                    if spec["capacity_type"] == "soda_ash":
                        cap_rec = soda_ash_caps.get(yr)
                        if cap_rec is not None:
                            cap_raw = str(cap_rec["capacity"])
                            cap_src = str(cap_rec["source"])
                    elif spec["capacity_type"] == "caustic_soda":
                        cap_rec = caustic_soda_caps.get(yr)
                        if cap_rec is not None:
                            cap_raw = str(cap_rec["capacity"])
                            cap_src = str(cap_rec["source"])
                    elif spec["capacity_type"] == "pta":
                        cap_rec = pta_caps.get(yr)
                        if cap_rec is not None:
                            cap_raw = str(cap_rec["capacity"])
                            cap_src = str(cap_rec["source"])
                    elif spec["capacity_type"] == "methanol":
                        cap_rec = methanol_caps.get(yr)
                        if cap_rec is not None:
                            cap_raw = str(cap_rec["capacity"])
                            cap_src = str(cap_rec["source"])
                    elif spec["capacity_type"] == "plate_glass":
                        cap_rec = plate_glass_caps.get(yr)
                        if cap_rec is not None:
                            cap_raw = str(cap_rec["capacity"])
                            cap_src = str(cap_rec["source"])
                    elif spec["capacity_type"] == "synthetic_fiber":
                        cap_rec = synthetic_fiber_caps.get(yr)
                        if cap_rec is not None:
                            cap_raw = str(cap_rec["capacity"])
                            cap_src = str(cap_rec["source"])
                    elif spec["capacity_type"] == "urea":
                        cap_rec = urea_caps.get(yr)
                        if cap_rec is not None:
                            cap_raw = str(cap_rec["capacity"])
                            cap_src = str(cap_rec["source"])
                    elif spec["capacity_type"] == "pvc":
                        cap_rec = pvc_caps.get(yr)
                        if cap_rec is not None:
                            cap_raw = str(cap_rec["capacity"])
                            cap_src = str(cap_rec["source"])

                    rel_date = _safe_date(r.get("release_date"))
                    if rel_date is None:
                        if mo == 12:
                            rel_date = date(yr + 1, 1, self.NBS_RELEASE_DAY)
                        elif mo in (1, 2):
                            rel_date = date(yr, 3, self.NBS_RELEASE_DAY)
                        else:
                            rel_date = date(yr, mo + 1, self.NBS_RELEASE_DAY)

                    records.append(
                        {
                            "product_name": spec["product_name"],
                            "symbol": spec["symbol"],
                            "report_month": m_str,
                            "trade_date": r_d,
                            "output_current_raw": r.get("output_current", "").strip() or None,
                            "output_cumulative_raw": r.get("output_cumulative", "").strip() or None,
                            "output_yoy_raw": r.get("output_yoy", "").strip() or None,
                            "output_cum_yoy_raw": r.get("output_cum_yoy", "").strip() or None,
                            "annual_capacity_raw": cap_raw,
                            "capacity_source": cap_src,
                            "unit": spec["unit"],
                            "source": "NBS_Official",
                            "release_date": rel_date,
                            "collected_at": now_iso,
                        }
                    )

        if not records:
            return pl.DataFrame(schema=CAPACITY_RAW_SCHEMA)
        return pl.DataFrame(records, schema=CAPACITY_RAW_SCHEMA).sort(
            ["product_name", "trade_date"]
        )

    def build_raw_utilization_result(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
        product_names: list[str] | tuple[str, ...] | None = None,
    ) -> IndustryFrameResult:
        """读取化工 RAW 底表，并在线探测增量更新，写回 data/raw/industry/chemicals/data.parquet。"""
        frame = self.build_raw_utilization()

        target_products = list(product_names) if product_names else ["纯碱"]
        all_new_records: list[dict[str, Any]] = []
        all_errors: list[str] = []
        all_fetched_periods: set[str] = set()
        covered_all: set[str] = set()
        updated = False

        for p_name in target_products:
            prod_frame = (
                frame.filter(pl.col("product_name") == p_name)
                if "product_name" in frame.columns
                else frame
            )
            valid_prod_frame = prod_frame.filter(
                pl.col("output_current_raw").is_not_null()
                | pl.col("output_cumulative_raw").is_not_null()
            )
            covered = (
                {
                    str(value)
                    for value in valid_prod_frame.get_column("report_month").to_list()
                    if value is not None
                }
                if "report_month" in valid_prod_frame.columns
                else set()
            )
            covered_all.update(covered)

            target_periods = _month_keys(
                start_date,
                end_date,
                self.NBS_RELEASE_DAY,
                latest_covered=max(covered) if covered else None,
            )
            to_fetch = target_periods if force else [p for p in target_periods if p not in covered]

            should_crawl = self._custom_crawler or self.enable_online
            if to_fetch and should_crawl:
                new_records, fetch_errors = self.crawler.fetch_range(to_fetch, product_name=p_name)
                all_errors.extend(fetch_errors)
                if new_records:
                    for rec in new_records:
                        if "product_name" not in rec:
                            rec["product_name"] = p_name
                    all_new_records.extend(new_records)
                    all_fetched_periods.update([r["report_month"] for r in new_records])

        if all_new_records:
            updated = True
            frame = self._merge_and_save_raw(frame, all_new_records)
            covered_all.update(all_fetched_periods)

        val_errors = validate_capacity_raw_frame(frame)
        all_errors.extend(val_errors)

        if frame.is_empty():
            status = "EMPTY"
        elif all_errors and not updated and not covered_all:
            status = "FAILED"
        elif all_errors:
            status = "PARTIAL"
        elif updated or frame.height > 0:
            status = "SUCCESS"
        else:
            status = "NO_CHANGE"

        cached = tuple(sorted(covered_all - all_fetched_periods))
        return IndustryFrameResult(
            frame=frame,
            status=status,
            fetched_periods=tuple(sorted(all_fetched_periods)),
            cached_periods=cached,
            errors=tuple(all_errors),
            updated=updated,
        )

    def _merge_and_save_raw(
        self,
        existing: pl.DataFrame,
        new_records: list[dict[str, Any]],
    ) -> pl.DataFrame:
        """将在线抓取的原始物理量（严格不做任何计算）合并入现有 RAW 表并保存为 Parquet。"""
        now_iso = now_utc_iso()

        new_rows: list[dict[str, Any]] = []
        for r in new_records:
            m_str = r["report_month"]
            yr, mo = parse_month_string(m_str)
            t_date = date(yr, mo, 1)

            p_name = str(r.get("product_name") or "纯碱")
            spec = next(
                (
                    s
                    for s in NBS_PRODUCT_SPECS
                    if s["product_name"] == p_name or s["symbol"] == r.get("symbol")
                ),
                None,
            )
            sym = str(r.get("symbol") or (spec["symbol"] if spec else "SA"))
            unit_val = str(r.get("unit") or (spec["unit"] if spec else "万吨"))

            cap_raw = r.get("annual_capacity_raw")
            cap_src = r.get("capacity_source")

            if cap_raw is None and spec and spec.get("capacity_type"):
                caps = _load_annual_capacity_for_spec(self.raw_dir, spec["capacity_type"])
                cap_record = caps.get(yr)
                if cap_record is not None:
                    cap_raw = str(cap_record["capacity"])
                    cap_src = str(cap_record["source"])

            rel_date = _safe_date(r.get("release_date"))
            if rel_date is None:
                if mo == 12:
                    rel_date = date(yr + 1, 1, self.NBS_RELEASE_DAY)
                elif mo in (1, 2):
                    rel_date = date(yr, 3, self.NBS_RELEASE_DAY)
                else:
                    rel_date = date(yr, mo + 1, self.NBS_RELEASE_DAY)

            new_rows.append(
                {
                    "product_name": p_name,
                    "symbol": sym,
                    "report_month": m_str,
                    "trade_date": t_date,
                    "output_current_raw": r.get("output_current_raw"),
                    "output_cumulative_raw": r.get("output_cumulative_raw"),
                    "output_yoy_raw": r.get("output_yoy_raw"),
                    "output_cum_yoy_raw": r.get("output_cum_yoy_raw"),
                    "annual_capacity_raw": cap_raw,
                    "capacity_source": cap_src,
                    "unit": unit_val,
                    "source": str(r.get("source") or "NBS_Official"),
                    "release_date": rel_date,
                    "collected_at": now_iso,
                }
            )

        new_df = pl.DataFrame(new_rows, schema=CAPACITY_RAW_SCHEMA)
        if existing.is_empty():
            merged = new_df
        else:
            aligned_existing = _align_to_raw_schema(existing)
            merged = (
                pl.concat([aligned_existing, new_df])
                .unique(subset=["product_name", "report_month"], keep="last")
                .sort(["product_name", "trade_date"])
            )

        self.paths.chemicals_dir.mkdir(parents=True, exist_ok=True)
        merged.write_parquet(self.paths.chemicals_parquet)
        logger.info(f"增量写回 RAW 底表: {self.paths.chemicals_parquet} ({len(merged)} 行)")
        return merged

    def build_10y_utilization(
        self,
        weekly_survey_df: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """从 RAW 构建 10 年产能利用率序列。"""
        return build_capacity_utilization_frame(
            self.build_raw_utilization(),
            weekly_survey_df=weekly_survey_df,
        )

    def sync_and_curate(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        force: bool = False,
        product_names: list[str] | tuple[str, ...] | None = None,
        curated_output_path: Path | str | None = None,
    ) -> tuple[IndustryFrameResult, pl.DataFrame]:
        """一体化执行在线增量采集、RAW data.parquet 写入与 Curated 黄金表物化。"""
        raw_result = self.build_raw_utilization_result(
            start_date=start_date,
            end_date=end_date,
            force=force,
            product_names=product_names,
        )
        curated_frame = self.build_10y_utilization()
        if curated_output_path is not None:
            c_path = Path(curated_output_path)
        else:
            c_path = (
                self.raw_dir.parents[1]
                / "curated"
                / "industry"
                / "chemical_capacity_utilization_10y.parquet"
            )
        c_path.parent.mkdir(parents=True, exist_ok=True)
        curated_frame.write_parquet(c_path)
        logger.info(f"成功物化 Curated 产能利用率黄金表至: {c_path} ({len(curated_frame)} 行)")
        return raw_result, curated_frame


def _align_to_raw_schema(df: pl.DataFrame) -> pl.DataFrame:
    """健壮对齐 DataFrame 到 CAPACITY_RAW_SCHEMA 列定义。"""
    if df.is_empty():
        return pl.DataFrame(schema=CAPACITY_RAW_SCHEMA)
    exprs = []
    cols = set(df.columns)
    for col_name, dtype in CAPACITY_RAW_SCHEMA.items():
        if col_name in cols:
            exprs.append(pl.col(col_name).cast(dtype))
        elif col_name == "product_name":
            exprs.append(pl.lit("纯碱").cast(dtype).alias(col_name))
        elif col_name == "symbol":
            exprs.append(pl.lit("SA").cast(dtype).alias(col_name))
        elif col_name == "unit":
            exprs.append(pl.lit("万吨").cast(dtype).alias(col_name))
        else:
            exprs.append(pl.lit(None, dtype=dtype).alias(col_name))
    return df.select(exprs)


def _month_keys(
    start_date: date | None,
    end_date: date | None,
    release_day: int = 18,
    latest_covered: str | None = None,
) -> list[str]:
    """生成包含边界月份的 YYYY-MM 列表。若均未提供，探测增量未入库月份。"""
    if start_date is None and end_date is None:
        current_month = date.today().replace(day=1)
        latest_month = current_month - timedelta(days=1)
        latest_str = latest_month.strftime("%Y-%m")
        if latest_covered:
            try:
                cov_yr, cov_mo = parse_month_string(latest_covered)
                next_dt = date(cov_yr + (cov_mo == 12), 1 if cov_mo == 12 else cov_mo + 1, 1)
                if next_dt <= latest_month.replace(day=1):
                    return _month_range(next_dt, latest_month.replace(day=1))
                return [latest_str]
            except Exception:
                pass
        if date.today().day < release_day:
            latest_month = latest_month.replace(day=1) - timedelta(days=1)
        return [latest_month.strftime("%Y-%m")]
    start = (start_date or date.today()).replace(day=1)
    end = (end_date or start_date or date.today()).replace(day=1)
    if end < start:
        return []
    return _month_range(start, end)


def _month_range(start: date, end: date) -> list[str]:
    result: list[str] = []
    cursor = start
    while cursor <= end:
        result.append(cursor.strftime("%Y-%m"))
        cursor = date(
            cursor.year + (cursor.month == 12),
            1 if cursor.month == 12 else cursor.month + 1,
            1,
        )
    return result


def _load_annual_capacity_for_spec(
    raw_dir: Path, capacity_type: str | None
) -> dict[int, dict[str, float | str]]:
    """加载指定品种的经审计年度产能字典 (年份 -> {capacity, source})。"""
    if not capacity_type:
        return {}
    if capacity_type == "soda_ash":
        return _load_soda_ash_capacity_by_year(raw_dir)
    if capacity_type == "caustic_soda":
        return _load_caustic_soda_capacity_by_year(raw_dir)
    if capacity_type == "pta":
        return _load_pta_capacity_by_year(raw_dir)
    if capacity_type == "methanol":
        return _load_methanol_capacity_by_year(raw_dir)
    if capacity_type == "plate_glass":
        return _load_plate_glass_capacity_by_year(raw_dir)
    if capacity_type == "synthetic_fiber":
        return _load_synthetic_fiber_capacity_by_year(raw_dir)
    if capacity_type == "urea":
        return _load_urea_capacity_by_year(raw_dir)
    if capacity_type == "pvc":
        return _load_pvc_capacity_by_year(raw_dir)
    return {}


def _load_soda_ash_capacity_by_year(raw_dir: Path) -> dict[int, dict[str, float | str]]:
    """优先从候选 CSV 读取年度产能；若无 CSV 则采用已审计的官方基准字典。"""
    for rel_path in CAPACITY_RAW_CANDIDATES:
        capacity_csv = raw_dir / rel_path
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: dict[int, dict[str, float | str]] = {}
            for row in reader:
                year = _safe_int(row.get("year"))
                capacity = _first_float(
                    row,
                    (
                        "annual_capacity_w_tons",
                        "soda_ash_capacity_w_tons",
                        "capacity_w_tons",
                        "effective_capacity_w_tons",
                    ),
                )
                if year is None or capacity is None:
                    continue
                records[year] = {
                    "capacity": capacity,
                    "source": str(row.get("source") or "capacity_raw").strip(),
                }
            if records:
                return records

    return {}


def _load_caustic_soda_capacity_by_year(raw_dir: Path) -> dict[int, dict[str, float | str]]:
    """优先从候选 CSV 读取烧碱年度产能；若无 CSV 则返回空字典。"""
    caustic_candidates = (
        "chemicals/capacity/caustic_soda_annual_capacity.csv",
        "chemicals/nbs/caustic_soda_annual_capacity.csv",
        "chemicals/caustic_soda_annual_capacity.csv",
        "caustic_soda_annual_capacity.csv",
    )
    for rel_path in caustic_candidates:
        capacity_csv = raw_dir / rel_path
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: dict[int, dict[str, float | str]] = {}
            for row in reader:
                year = _safe_int(row.get("year"))
                capacity = _first_float(
                    row,
                    (
                        "annual_capacity_w_tons",
                        "caustic_soda_capacity_w_tons",
                        "capacity_w_tons",
                        "effective_capacity_w_tons",
                    ),
                )
                if year is None or capacity is None:
                    continue
                records[year] = {
                    "capacity": capacity,
                    "source": str(row.get("source") or "CCIA").strip(),
                }
            if records:
                return records

    return {}


def _load_pta_capacity_by_year(raw_dir: Path) -> dict[int, dict[str, float | str]]:
    """优先从候选 CSV 读取 PTA 年度产能；若无 CSV 则返回空字典。"""
    pta_candidates = (
        "chemicals/capacity/pta_annual_capacity.csv",
        "chemicals/nbs/pta_annual_capacity.csv",
        "chemicals/pta_annual_capacity.csv",
        "pta_annual_capacity.csv",
    )
    for rel_path in pta_candidates:
        capacity_csv = raw_dir / rel_path
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: dict[int, dict[str, float | str]] = {}
            for row in reader:
                year = _safe_int(row.get("year"))
                capacity = _first_float(
                    row,
                    (
                        "annual_capacity_w_tons",
                        "pta_capacity_w_tons",
                        "capacity_w_tons",
                        "effective_capacity_w_tons",
                    ),
                )
                if year is None or capacity is None:
                    continue
                records[year] = {
                    "capacity": capacity,
                    "source": str(row.get("source") or "CCFA").strip(),
                }
            if records:
                return records

    return {}


def _load_methanol_capacity_by_year(raw_dir: Path) -> dict[int, dict[str, float | str]]:
    """优先从候选 CSV 读取甲醇年度产能；若无 CSV 则返回空字典。"""
    methanol_candidates = (
        "chemicals/capacity/methanol_annual_capacity.csv",
        "chemicals/nbs/methanol_annual_capacity.csv",
        "chemicals/methanol_annual_capacity.csv",
        "methanol_annual_capacity.csv",
    )
    for rel_path in methanol_candidates:
        capacity_csv = raw_dir / rel_path
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: dict[int, dict[str, float | str]] = {}
            for row in reader:
                year = _safe_int(row.get("year"))
                capacity = _first_float(
                    row,
                    (
                        "annual_capacity_w_tons",
                        "methanol_capacity_w_tons",
                        "capacity_w_tons",
                        "effective_capacity_w_tons",
                    ),
                )
                if year is None or capacity is None:
                    continue
                records[year] = {
                    "capacity": capacity,
                    "source": str(row.get("source") or "CNFA").strip(),
                }
            if records:
                return records

    return {}


def _load_plate_glass_capacity_by_year(raw_dir: Path) -> dict[int, dict[str, float | str]]:
    """优先从候选 CSV 读取平板玻璃年度有效产能；若无 CSV 则返回空字典。"""
    candidates = (
        "chemicals/capacity/plate_glass_annual_capacity.csv",
        "chemicals/nbs/plate_glass_annual_capacity.csv",
        "chemicals/plate_glass_annual_capacity.csv",
        "plate_glass_annual_capacity.csv",
    )
    for rel_path in candidates:
        capacity_csv = raw_dir / rel_path
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: dict[int, dict[str, float | str]] = {}
            for row in reader:
                year = _safe_int(row.get("year"))
                capacity = _first_float(
                    row,
                    (
                        "annual_capacity_w_weight_cases",
                        "annual_capacity_w_cases",
                        "annual_capacity_w_tons",
                        "plate_glass_capacity_w_cases",
                        "capacity_w_cases",
                        "effective_capacity_w_cases",
                    ),
                )
                if year is None or capacity is None:
                    continue
                records[year] = {
                    "capacity": capacity,
                    "source": str(row.get("source") or "CBMA").strip(),
                }
            if records:
                return records

    return {}


def _load_synthetic_fiber_capacity_by_year(raw_dir: Path) -> dict[int, dict[str, float | str]]:
    """优先从候选 CSV 读取合成纤维年度有效产能；若无 CSV 则返回空字典。"""
    candidates = (
        "chemicals/capacity/synthetic_fiber_annual_capacity.csv",
        "chemicals/nbs/synthetic_fiber_annual_capacity.csv",
        "chemicals/synthetic_fiber_annual_capacity.csv",
        "synthetic_fiber_annual_capacity.csv",
    )
    for rel_path in candidates:
        capacity_csv = raw_dir / rel_path
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: dict[int, dict[str, float | str]] = {}
            for row in reader:
                year = _safe_int(row.get("year"))
                capacity = _first_float(
                    row,
                    (
                        "annual_capacity_w_tons",
                        "synthetic_fiber_capacity_w_tons",
                        "capacity_w_tons",
                        "effective_capacity_w_tons",
                    ),
                )
                if year is None or capacity is None:
                    continue
                records[year] = {
                    "capacity": capacity,
                    "source": str(row.get("source") or "CCFA").strip(),
                }
            if records:
                return records

    return {}


def _load_urea_capacity_by_year(raw_dir: Path) -> dict[int, dict[str, float | str]]:
    """优先从候选 CSV 读取尿素年度有效产能；若无 CSV 则返回空字典。"""
    candidates = (
        "chemicals/capacity/urea_annual_capacity.csv",
        "chemicals/nbs/urea_annual_capacity.csv",
        "chemicals/urea_annual_capacity.csv",
        "urea_annual_capacity.csv",
    )
    for rel_path in candidates:
        capacity_csv = raw_dir / rel_path
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: dict[int, dict[str, float | str]] = {}
            for row in reader:
                year = _safe_int(row.get("year"))
                capacity = _first_float(
                    row,
                    (
                        "annual_capacity_w_tons",
                        "urea_capacity_w_tons",
                        "capacity_w_tons",
                        "effective_capacity_w_tons",
                    ),
                )
                if year is None or capacity is None:
                    continue
                records[year] = {
                    "capacity": capacity,
                    "source": str(row.get("source") or "CNFA").strip(),
                }
            if records:
                return records

    return {}


def _load_pvc_capacity_by_year(raw_dir: Path) -> dict[int, dict[str, float | str]]:
    """优先从候选 CSV 读取 PVC 年度有效产能；若无 CSV 则返回空字典。"""
    candidates = (
        "chemicals/capacity/pvc_annual_capacity.csv",
        "chemicals/nbs/pvc_annual_capacity.csv",
        "chemicals/pvc_annual_capacity.csv",
        "pvc_annual_capacity.csv",
    )
    for rel_path in candidates:
        capacity_csv = raw_dir / rel_path
        if not capacity_csv.exists():
            continue
        with capacity_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            records: dict[int, dict[str, float | str]] = {}
            for row in reader:
                year = _safe_int(row.get("year"))
                capacity = _first_float(
                    row,
                    (
                        "annual_capacity_w_tons",
                        "pvc_capacity_w_tons",
                        "capacity_w_tons",
                        "effective_capacity_w_tons",
                    ),
                )
                if year is None or capacity is None:
                    continue
                records[year] = {
                    "capacity": capacity,
                    "source": str(row.get("data_source") or row.get("source") or "CCIA").strip(),
                }
            if records:
                return records

    return {}


def _first_float(row: dict[str, str], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _safe_float(row.get(key))
        if value is not None:
            return value
    return None


def _safe_float(value: object) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"nan", "None"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _safe_int(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _safe_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


__all__ = [
    "CAPACITY_RAW_CANDIDATES",
    "CAPACITY_RAW_SCHEMA",
    "CAPACITY_UTILIZATION_SCHEMA",
    "NBS_PRODUCT_SPECS",
    "ChemicalCapacityUtilization10Y",
    "NbsChemicalsCrawler",
    "NbsSodaAshCrawler",
    "build_capacity_raw_frame",
    "build_capacity_utilization_frame",
]
