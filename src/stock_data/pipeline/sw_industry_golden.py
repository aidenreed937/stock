"""TuShare 与理杏仁申万 2021 行业跨源黄金表构建。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from stock_data.catalog.compat import load_dataset_compat
from stock_data.core.derived_datasets import resolve_derived_dataset
from stock_data.pipeline.cleaner.date_utils import parse_mixed_date

if TYPE_CHECKING:
    from stock_core.contracts import MarketDataCatalog
    from stock_data.core.runtime import DataRuntimeContext
    from stock_data.storage.duckdb_store import DuckDBMarketStore

SW_INDUSTRY_CLASSIFICATION = "SW2021"
SW_INDUSTRY_DIMENSION_GOLDEN_DATASET = "sw_2021_industry_dimension_golden"
SW_INDUSTRY_MEMBER_GOLDEN_DATASET = "sw_2021_industry_member_golden"
SW_INDUSTRY_GOLDEN_SOURCE_ENDPOINT = (
    "derived:tushare.index_classify+index_member+lixinger.sw_2021_constituents"
)

_DIMENSION_SPEC = resolve_derived_dataset("derived", SW_INDUSTRY_DIMENSION_GOLDEN_DATASET)
_MEMBER_SPEC = resolve_derived_dataset("derived", SW_INDUSTRY_MEMBER_GOLDEN_DATASET)
if _DIMENSION_SPEC is None or _MEMBER_SPEC is None:
    raise RuntimeError("申万跨源黄金表契约未注册")

DIMENSION_PRIMARY_KEYS: tuple[str, ...] = _DIMENSION_SPEC.primary_keys
MEMBER_PRIMARY_KEYS: tuple[str, ...] = _MEMBER_SPEC.primary_keys

_DIMENSION_COLUMNS = (
    "classification",
    "industry_code",
    "index_code",
    "industry_name",
    "level",
    "parent_code",
    "src",
    "tushare_present",
    "lixinger_present",
    "mapping_status",
    "tushare_request_id",
    "lixinger_request_id",
)
_MEMBER_COLUMNS = (
    "classification",
    "symbol",
    "stock_code",
    "industry_code",
    "index_code",
    "industry_name",
    "level",
    "parent_code",
    "valid_from",
    "valid_to",
    "snapshot_date",
    "src",
    "canonical_source",
    "source_status",
    "is_canonical",
    "conflict_flag",
    "tushare_present",
    "lixinger_present",
    "tushare_request_id",
    "lixinger_request_id",
)
_LINEAGE_COLUMNS = (
    "data_source",
    "source_endpoint",
    "request_id",
    "updated_at",
    "market",
    "exchange",
    "currency",
    "adjustment",
    "schema_version",
    "source_scope",
    "field_provenance",
)


@dataclass(frozen=True, slots=True)
class SWIndustryGoldenFrames:
    """一次申万跨源黄金表构建得到的两张表。"""

    dimension: pl.DataFrame
    members: pl.DataFrame
    snapshot_date: date | None
    request_id: str
    dimension_path: Path | None = None
    member_path: Path | None = None


def empty_sw_industry_dimension() -> pl.DataFrame:
    """返回稳定业务 Schema 的空行业维度表。"""
    return pl.DataFrame(
        schema={
            "classification": pl.String,
            "industry_code": pl.String,
            "index_code": pl.String,
            "industry_name": pl.String,
            "level": pl.String,
            "parent_code": pl.String,
            "src": pl.String,
            "tushare_present": pl.Boolean,
            "lixinger_present": pl.Boolean,
            "mapping_status": pl.String,
            "tushare_request_id": pl.String,
            "lixinger_request_id": pl.String,
        }
    )


def empty_sw_industry_members() -> pl.DataFrame:
    """返回稳定业务 Schema 的空成员黄金表。"""
    return pl.DataFrame(
        schema={
            "classification": pl.String,
            "symbol": pl.String,
            "stock_code": pl.String,
            "industry_code": pl.String,
            "index_code": pl.String,
            "industry_name": pl.String,
            "level": pl.String,
            "parent_code": pl.String,
            "valid_from": pl.Date,
            "valid_to": pl.Date,
            "snapshot_date": pl.Date,
            "src": pl.String,
            "canonical_source": pl.String,
            "source_status": pl.String,
            "is_canonical": pl.Boolean,
            "conflict_flag": pl.Boolean,
            "tushare_present": pl.Boolean,
            "lixinger_present": pl.Boolean,
            "tushare_request_id": pl.String,
            "lixinger_request_id": pl.String,
        }
    )


def build_sw_2021_industry_dimension(
    index_classify: pl.DataFrame,
    lixinger_constituents: pl.DataFrame,
    *,
    tushare_request_id: str | None = None,
    lixinger_request_id: str | None = None,
) -> pl.DataFrame:
    """以 TuShare 行业字典为身份基准，登记理杏仁代码覆盖情况。"""
    tushare = _prepare_index_classify(index_classify)
    lixinger_codes = (
        _prepare_lixinger_constituents(lixinger_constituents).select("industry_code").unique()
    )
    lixinger_code_set = set(lixinger_codes.get_column("industry_code").to_list())

    rows: list[dict[str, Any]] = []
    tushare_codes: set[str] = set()
    dimension_keys: set[tuple[str, str]] = set()
    for row in tushare.to_dicts():
        code = row["industry_code"]
        level = row["level"]
        key = (code, level)
        if key in dimension_keys:
            continue
        dimension_keys.add(key)
        tushare_codes.add(code)
        rows.append(
            {
                "classification": SW_INDUSTRY_CLASSIFICATION,
                "industry_code": code,
                "index_code": row["index_code"],
                "industry_name": row["industry_name"],
                "level": level,
                "parent_code": row["parent_code"] or _infer_parent_code(code, level),
                "src": "TUSHARE+LIXINGER" if code in lixinger_code_set else "TUSHARE",
                "tushare_present": True,
                "lixinger_present": code in lixinger_code_set,
                "mapping_status": ("both_present" if code in lixinger_code_set else "tushare_only"),
                "tushare_request_id": tushare_request_id,
                "lixinger_request_id": lixinger_request_id,
            }
        )

    for code in sorted(lixinger_code_set - tushare_codes):
        level = _infer_level(code)
        rows.append(
            {
                "classification": SW_INDUSTRY_CLASSIFICATION,
                "industry_code": code,
                "index_code": None,
                "industry_name": None,
                "level": level,
                "parent_code": _infer_parent_code(code, level),
                "src": "LIXINGER",
                "tushare_present": False,
                "lixinger_present": True,
                "mapping_status": "lixinger_only",
                "tushare_request_id": tushare_request_id,
                "lixinger_request_id": lixinger_request_id,
            }
        )

    if not rows:
        return empty_sw_industry_dimension()
    return (
        pl.DataFrame(
            rows, schema={column: _dimension_dtype(column) for column in _DIMENSION_COLUMNS}
        )
        .unique(subset=list(DIMENSION_PRIMARY_KEYS), keep="first")
        .sort(["level", "industry_code"])
    )


def build_sw_2021_industry_member_golden(
    index_classify: pl.DataFrame,
    index_member: pl.DataFrame,
    lixinger_constituents: pl.DataFrame,
    *,
    snapshot_date: date | None = None,
    dimension: pl.DataFrame | None = None,
    tushare_request_id: str | None = None,
    lixinger_request_id: str | None = None,
) -> pl.DataFrame:
    """构建带历史有效期、来源优先级与冲突标记的成员黄金表。"""
    classify = _prepare_index_classify(index_classify)
    members = _prepare_index_member(index_member)
    lixinger = _prepare_lixinger_constituents(lixinger_constituents)
    if dimension is None:
        dimension = build_sw_2021_industry_dimension(
            index_classify,
            lixinger_constituents,
            tushare_request_id=tushare_request_id,
            lixinger_request_id=lixinger_request_id,
        )
    dimension_lookup = {(row["industry_code"], row["level"]): row for row in dimension.to_dicts()}
    dimension_by_code = {row["industry_code"]: row for row in dimension.to_dicts()}

    joined = members.join(
        classify.select(
            "index_code",
            "industry_code",
            "industry_name",
            "level",
            "parent_code",
        ),
        on="index_code",
        how="inner",
    )
    if joined.is_empty() and lixinger.is_empty():
        return empty_sw_industry_members()

    ts_rows = joined.to_dicts()
    current_tushare: dict[tuple[str, str], set[str]] = {}
    for row in ts_rows:
        if _is_current_member(row, snapshot_date):
            current_tushare.setdefault((row["symbol"], row["level"]), set()).add(
                row["industry_code"]
            )
    current_lixinger: dict[tuple[str, str], set[str]] = {}
    for row in lixinger.to_dicts():
        current_lixinger.setdefault((row["symbol"], row["level"]), set()).add(row["industry_code"])

    rows: list[dict[str, Any]] = []
    for row in ts_rows:
        code = row["industry_code"]
        level = row["level"]
        is_current = _is_current_member(row, snapshot_date)
        ts_codes = current_tushare.get((row["symbol"], level), set())
        lx_codes = current_lixinger.get((row["symbol"], level), set())
        conflict = bool(is_current and lx_codes and lx_codes != {code})
        if not is_current:
            status = "tushare_historical"
        elif conflict:
            status = "conflict_tushare_preferred"
        elif code in lx_codes:
            status = "both_consistent"
        else:
            status = "tushare_only"
        rows.append(
            _member_row(
                classification=SW_INDUSTRY_CLASSIFICATION,
                symbol=row["symbol"],
                industry_code=code,
                index_code=row["index_code"],
                industry_name=row["industry_name"],
                level=level,
                parent_code=row["parent_code"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                snapshot_date=None,
                src="TUSHARE",
                canonical_source="TUSHARE",
                source_status=status,
                is_canonical=True,
                conflict_flag=conflict,
                tushare_present=True,
                lixinger_present=bool(lx_codes),
                tushare_request_id=tushare_request_id,
                lixinger_request_id=lixinger_request_id,
            )
        )

    for row in lixinger.to_dicts():
        code = row["industry_code"]
        level = row["level"]
        dimension_row = dimension_lookup.get((code, level)) or dimension_by_code.get(code, {})
        ts_codes = current_tushare.get((row["symbol"], level), set())
        conflict = bool(ts_codes and ts_codes != {code})
        same_tushare = code in ts_codes
        status = (
            "both_consistent"
            if same_tushare and not conflict
            else "conflict_tushare_preferred"
            if conflict
            else "lixinger_supplement"
        )
        rows.append(
            _member_row(
                classification=SW_INDUSTRY_CLASSIFICATION,
                symbol=row["symbol"],
                industry_code=code,
                index_code=dimension_row.get("index_code"),
                industry_name=dimension_row.get("industry_name"),
                level=level,
                parent_code=dimension_row.get("parent_code") or _infer_parent_code(code, level),
                valid_from=None,
                valid_to=None,
                snapshot_date=snapshot_date,
                src="LIXINGER",
                canonical_source="TUSHARE" if ts_codes else "LIXINGER",
                source_status=status,
                is_canonical=not ts_codes,
                conflict_flag=conflict,
                tushare_present=bool(ts_codes),
                lixinger_present=True,
                tushare_request_id=tushare_request_id,
                lixinger_request_id=lixinger_request_id,
            )
        )

    return (
        pl.DataFrame(rows, schema={column: _member_dtype(column) for column in _MEMBER_COLUMNS})
        .unique(subset=list(MEMBER_PRIMARY_KEYS), keep="last")
        .sort(["src", "level", "symbol", "industry_code"])
    )


def build_sw_2021_industry_golden(
    index_classify: pl.DataFrame,
    index_member: pl.DataFrame,
    lixinger_constituents: pl.DataFrame,
    *,
    snapshot_date: date | None = None,
    request_id: str = "",
    tushare_request_id: str | None = None,
    lixinger_request_id: str | None = None,
) -> SWIndustryGoldenFrames:
    """构建不含物理写入的两张跨源黄金表。"""
    dimension = build_sw_2021_industry_dimension(
        index_classify,
        lixinger_constituents,
        tushare_request_id=tushare_request_id,
        lixinger_request_id=lixinger_request_id,
    )
    members = build_sw_2021_industry_member_golden(
        index_classify,
        index_member,
        lixinger_constituents,
        snapshot_date=snapshot_date,
        dimension=dimension,
        tushare_request_id=tushare_request_id,
        lixinger_request_id=lixinger_request_id,
    )
    return SWIndustryGoldenFrames(
        dimension=dimension,
        members=members,
        snapshot_date=snapshot_date,
        request_id=request_id,
    )


def materialize_sw_2021_industry_golden(
    catalog_tushare: MarketDataCatalog | None = None,
    catalog_lixinger: MarketDataCatalog | None = None,
    store: DuckDBMarketStore | None = None,
    *,
    storage_dir: Path | str | None = None,
    runtime: DataRuntimeContext | None = None,
    dry_run: bool = False,
) -> SWIndustryGoldenFrames:
    """从本地 TuShare/LiXinger Curated 输入构建并可选原子写入黄金表。"""
    active_runtime, curated_root = _resolve_runtime(runtime, storage_dir)
    if catalog_tushare is None:
        from stock_data.catalog import DataCatalog

        catalog_tushare = DataCatalog("tushare", curated_root, runtime=active_runtime)
    if catalog_lixinger is None:
        from stock_data.catalog import DataCatalog

        catalog_lixinger = DataCatalog("lixinger", curated_root, runtime=active_runtime)

    index_classify = _load_dataset(
        catalog_tushare,
        "index_classify",
        columns=(
            "index_code",
            "industry_name",
            "level",
            "industry_code",
            "parent_code",
            "src",
            "request_id",
        ),
    )
    index_member = _load_dataset(
        catalog_tushare,
        "index_member",
        columns=("index_code", "con_code", "in_date", "out_date", "request_id"),
    )
    lixinger_constituents = _load_dataset(
        catalog_lixinger,
        "sw_2021_constituents",
        columns=("industryCode", "symbol", "updated_at", "request_id"),
    )
    snapshot = _resolve_snapshot_date(lixinger_constituents)
    request_id = _lineage_request_id(index_classify, index_member, lixinger_constituents, snapshot)
    result = build_sw_2021_industry_golden(
        index_classify,
        index_member,
        lixinger_constituents,
        snapshot_date=snapshot,
        request_id=request_id,
        tushare_request_id=_source_request_id(index_classify, index_member),
        lixinger_request_id=_source_request_id(lixinger_constituents),
    )
    dimension = _with_lineage(result.dimension, request_id, "industry dimension by industry_code")
    members = _with_lineage(result.members, request_id, "member evidence by source and validity")
    if not dry_run:
        if store is not None and getattr(store, "data_source", "derived") != "derived":
            raise ValueError("申万跨源黄金表只允许写入 derived Curated 存储")
        if store is None:
            from stock_data.storage import DuckDBMarketStore

            store = DuckDBMarketStore(
                storage_dir=curated_root,
                data_source="derived",
                runtime=active_runtime,
            )
        if dimension.is_empty() or members.is_empty():
            raise ValueError("申万跨源黄金表构建结果为空，保留旧表")
        target_date = snapshot or _latest_input_date(index_classify, index_member) or date.today()
        dimension_path = _replace_materialized_file(
            store, SW_INDUSTRY_DIMENSION_GOLDEN_DATASET, dimension, target_date
        )
        member_path = _replace_materialized_file(
            store, SW_INDUSTRY_MEMBER_GOLDEN_DATASET, members, target_date
        )
        return SWIndustryGoldenFrames(
            dimension=dimension,
            members=members,
            snapshot_date=snapshot,
            request_id=request_id,
            dimension_path=dimension_path,
            member_path=member_path,
        )
    return SWIndustryGoldenFrames(
        dimension=dimension,
        members=members,
        snapshot_date=snapshot,
        request_id=request_id,
    )


def _load_dataset(
    catalog: MarketDataCatalog,
    dataset: str,
    *,
    columns: tuple[str, ...],
) -> pl.DataFrame:
    try:
        return load_dataset_compat(catalog, dataset, columns=columns, dedup=False)
    except Exception:
        return pl.DataFrame()


def _resolve_runtime(
    runtime: DataRuntimeContext | None,
    storage_dir: Path | str | None,
) -> tuple[DataRuntimeContext, Path]:
    if runtime is None:
        from stock_data.core.runtime import DataRuntimeContext

        runtime = DataRuntimeContext.from_settings()
    return runtime, Path(storage_dir) if storage_dir is not None else runtime.curated_root


def _prepare_index_classify(frame: pl.DataFrame) -> pl.DataFrame:
    required = {"index_code", "industry_code", "level"}
    if frame.is_empty() or not required.issubset(frame.columns):
        return pl.DataFrame(
            schema={
                "index_code": pl.String,
                "industry_code": pl.String,
                "industry_name": pl.String,
                "level": pl.String,
                "parent_code": pl.String,
            }
        )
    selected = frame
    if "src" in selected.columns:
        selected = selected.filter(
            pl.col("src").cast(pl.String, strict=False) == SW_INDUSTRY_CLASSIFICATION
        )
    if selected.is_empty():
        return pl.DataFrame(
            schema={
                "index_code": pl.String,
                "industry_code": pl.String,
                "industry_name": pl.String,
                "level": pl.String,
                "parent_code": pl.String,
            }
        )
    expressions = [
        pl.col("index_code").cast(pl.String, strict=False).str.strip_chars().alias("index_code"),
        pl.col("industry_code")
        .cast(pl.String, strict=False)
        .str.strip_chars()
        .alias("industry_code"),
        pl.col("level").cast(pl.String, strict=False).str.strip_chars().alias("level"),
    ]
    expressions.extend(
        [
            _string_or_null(selected, "industry_name"),
            _string_or_null(selected, "parent_code"),
        ]
    )
    return (
        selected.select(expressions)
        .filter(pl.col("index_code").is_not_null() & pl.col("industry_code").is_not_null())
        .unique(subset=["index_code"], keep="first")
    )


def _prepare_index_member(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or not {"index_code", "con_code"}.issubset(frame.columns):
        return pl.DataFrame(
            schema={
                "index_code": pl.String,
                "symbol": pl.String,
                "valid_from": pl.Date,
                "valid_to": pl.Date,
            }
        )
    expressions = [
        pl.col("index_code").cast(pl.String, strict=False).str.strip_chars().alias("index_code"),
        pl.col("con_code")
        .map_elements(_normalize_stock_code, return_dtype=pl.String)
        .alias("symbol"),
        _date_expr(frame, "in_date", "valid_from"),
        _date_expr(frame, "out_date", "valid_to"),
    ]
    return (
        frame.select(expressions)
        .filter(pl.col("index_code").is_not_null() & pl.col("symbol").is_not_null())
        .unique(subset=["index_code", "symbol", "valid_from", "valid_to"], keep="last")
    )


def _prepare_lixinger_constituents(frame: pl.DataFrame) -> pl.DataFrame:
    if frame.is_empty() or not {"industryCode", "symbol"}.issubset(frame.columns):
        return pl.DataFrame(
            schema={
                "industry_code": pl.String,
                "symbol": pl.String,
                "level": pl.String,
            }
        )
    return (
        frame.select(
            pl.col("industryCode")
            .cast(pl.String, strict=False)
            .str.strip_chars()
            .alias("industry_code"),
            pl.col("symbol")
            .map_elements(_normalize_stock_code, return_dtype=pl.String)
            .alias("symbol"),
        )
        .with_columns(
            pl.col("industry_code")
            .map_elements(_infer_level, return_dtype=pl.String)
            .alias("level")
        )
        .filter(pl.col("industry_code").is_not_null() & pl.col("symbol").is_not_null())
        .unique(subset=["industry_code", "symbol"], keep="last")
    )


def _resolve_snapshot_date(frame: pl.DataFrame) -> date | None:
    if frame.is_empty() or "updated_at" not in frame.columns:
        return None
    values = [parse_date_value(value) for value in frame.get_column("updated_at").to_list()]
    parsed = [value for value in values if value is not None]
    return max(parsed) if parsed else None


def _latest_input_date(*frames: pl.DataFrame) -> date | None:
    values: list[date] = []
    for frame in frames:
        for column in ("updated_at", "in_date", "out_date"):
            if column in frame.columns:
                values.extend(
                    value
                    for value in (
                        parse_date_value(item) for item in frame.get_column(column).to_list()
                    )
                    if value is not None
                )
    return max(values) if values else None


def _is_current_member(row: dict[str, Any], snapshot_date: date | None) -> bool:
    if snapshot_date is None:
        return row.get("valid_to") is None
    valid_from = row.get("valid_from")
    valid_to = row.get("valid_to")
    return (valid_from is None or valid_from <= snapshot_date) and (
        valid_to is None or valid_to > snapshot_date
    )


def _member_row(**kwargs: Any) -> dict[str, Any]:
    return {column: kwargs.get(column) for column in _MEMBER_COLUMNS}


def _infer_level(code: object) -> str:
    text = str(code or "").strip()
    if len(text) != 6 or not text.isdigit():
        return "UNKNOWN"
    if text.endswith("0000"):
        return "L1"
    if text.endswith("00"):
        return "L2"
    return "L3"


def _infer_parent_code(code: object, level: object) -> str | None:
    text = str(code or "").strip()
    if str(level) == "L1":
        return None
    if len(text) != 6 or not text.isdigit():
        return None
    if str(level) == "L2":
        return f"{text[:2]}0000"
    if str(level) == "L3":
        return f"{text[:4]}00"
    return None


def _normalize_stock_code(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip().split(".", 1)[0]
    if not text or not text.isdigit():
        return None
    return text.zfill(6)[:6]


def parse_date_value(value: object) -> date | None:
    """解析日期、日期时间或紧凑日期文本。"""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = str(value).strip().replace("-", "")
    if len(text) >= 8 and text[:8].isdigit():
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None
    return None


def _date_expr(frame: pl.DataFrame, column: str, alias: str) -> pl.Expr:
    if column not in frame.columns:
        return pl.lit(None, dtype=pl.Date).alias(alias)
    return parse_mixed_date(column).alias(alias)


def _string_or_null(frame: pl.DataFrame, column: str) -> pl.Expr:
    if column not in frame.columns:
        return pl.lit(None, dtype=pl.String).alias(column)
    return pl.col(column).cast(pl.String, strict=False).str.strip_chars().alias(column)


def _dimension_dtype(column: str) -> Any:
    return {
        "classification": pl.String,
        "industry_code": pl.String,
        "index_code": pl.String,
        "industry_name": pl.String,
        "level": pl.String,
        "parent_code": pl.String,
        "src": pl.String,
        "tushare_present": pl.Boolean,
        "lixinger_present": pl.Boolean,
        "mapping_status": pl.String,
        "tushare_request_id": pl.String,
        "lixinger_request_id": pl.String,
    }[column]


def _member_dtype(column: str) -> Any:
    if column in {"valid_from", "valid_to", "snapshot_date"}:
        return pl.Date
    if column in {"is_canonical", "conflict_flag", "tushare_present", "lixinger_present"}:
        return pl.Boolean
    return pl.String


def _with_lineage(frame: pl.DataFrame, request_id: str, source_scope: str) -> pl.DataFrame:
    provenance = json.dumps(
        {
            "dimension": "tushare.index_classify keyed by industry_code",
            "historical_members": "tushare.index_member JOIN index_classify on index_code",
            "current_snapshot": "lixinger.sw_2021_constituents",
            "canonical_rule": "TUSHARE history/current first; LIXINGER supplements only missing stock-level assignments",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    metadata = [
        pl.lit("derived").alias("data_source"),
        pl.lit(SW_INDUSTRY_GOLDEN_SOURCE_ENDPOINT).alias("source_endpoint"),
        pl.lit(request_id).alias("request_id"),
        pl.lit(datetime.now(UTC)).cast(pl.Datetime("us", "UTC")).alias("updated_at"),
        pl.lit("CN").alias("market"),
        pl.lit("CN").alias("exchange"),
        pl.lit("CNY").alias("currency"),
        pl.lit("raw").alias("adjustment"),
        pl.lit("v2").alias("schema_version"),
        pl.lit(source_scope).alias("source_scope"),
        pl.lit(provenance).alias("field_provenance"),
    ]
    return frame.with_columns(metadata).select([*frame.columns, *_LINEAGE_COLUMNS])


def _lineage_request_id(*frames: Any) -> str:
    snapshot = frames[-1]
    source_frames = frames[:-1]
    source_ids: list[str] = []
    for frame in source_frames:
        if isinstance(frame, pl.DataFrame) and "request_id" in frame.columns:
            source_ids.extend(
                str(value) for value in frame.get_column("request_id").drop_nulls().unique()
            )
    payload = {
        "classification": SW_INDUSTRY_CLASSIFICATION,
        "source_request_ids": sorted(set(source_ids)),
        "source_rows": [frame.height for frame in source_frames if isinstance(frame, pl.DataFrame)],
        "snapshot_date": str(snapshot),
    }
    return sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def _source_request_id(*frames: pl.DataFrame) -> str | None:
    values: set[str] = set()
    for frame in frames:
        if "request_id" not in frame.columns:
            continue
        values.update(
            str(value)
            for value in frame.get_column("request_id").drop_nulls().unique().to_list()
            if str(value)
        )
    if not values:
        return None
    return json.dumps(sorted(values), ensure_ascii=False, separators=(",", ":"))


def _replace_materialized_file(
    store: DuckDBMarketStore,
    dataset: str,
    frame: pl.DataFrame,
    target_date: date,
) -> Path:
    import uuid

    target = store.get_parquet_path(dataset, target_date, market="CN")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp.parquet")
    try:
        frame.write_parquet(temporary, compression="zstd")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def load_sw_2021_industry_members(
    catalog: MarketDataCatalog,
    *,
    as_of_date: date | None = None,
    level: str | None = None,
    src: str | None = None,
    canonical_only: bool = True,
    current_only: bool = False,
    columns: tuple[str, ...] | None = None,
) -> pl.DataFrame:
    """读取成员黄金表并按时点、层级、来源过滤。"""
    catalog = _resolve_golden_catalog(catalog, SW_INDUSTRY_MEMBER_GOLDEN_DATASET)
    requested = columns
    base_columns = columns or (
        "classification",
        "symbol",
        "stock_code",
        "industry_code",
        "index_code",
        "industry_name",
        "level",
        "parent_code",
        "valid_from",
        "valid_to",
        "snapshot_date",
        "src",
        "canonical_source",
        "source_status",
        "is_canonical",
        "conflict_flag",
        "tushare_present",
        "lixinger_present",
    )
    load_columns = tuple(
        dict.fromkeys(
            (*base_columns,)
            + (
                "classification",
                "valid_from",
                "valid_to",
                "snapshot_date",
                "src",
                "level",
                "is_canonical",
            )
        )
    )
    frame = _load_dataset(
        catalog,
        SW_INDUSTRY_MEMBER_GOLDEN_DATASET,
        columns=load_columns,
    )
    if frame.is_empty():
        frame = _load_lixinger_fallback(catalog)
    if frame.is_empty():
        return frame
    if "classification" in frame.columns:
        frame = frame.filter(pl.col("classification") == SW_INDUSTRY_CLASSIFICATION)
    if canonical_only and "is_canonical" in frame.columns:
        frame = frame.filter(pl.col("is_canonical"))
    if src is not None and "src" in frame.columns:
        frame = frame.filter(pl.col("src") == src)
    if level is not None and "level" in frame.columns:
        frame = frame.filter(pl.col("level") == level)
    if as_of_date is not None:
        if {"valid_from", "valid_to"}.issubset(frame.columns):
            frame = frame.filter(
                (pl.col("valid_from").is_null() | (pl.col("valid_from") <= as_of_date))
                & (pl.col("valid_to").is_null() | (pl.col("valid_to") > as_of_date))
            )
        if "snapshot_date" in frame.columns and "src" in frame.columns:
            frame = frame.filter(
                (pl.col("src") != "LIXINGER")
                | (pl.col("snapshot_date").is_not_null() & (pl.col("snapshot_date") <= as_of_date))
            )
    elif current_only:
        snapshot_values = frame.filter(pl.col("src") == "LIXINGER").get_column("snapshot_date")
        snapshot_values = (
            snapshot_values.drop_nulls() if not snapshot_values.is_empty() else snapshot_values
        )
        latest_snapshot = snapshot_values.max() if not snapshot_values.is_empty() else None
        if latest_snapshot is not None:
            frame = frame.filter(
                (
                    (pl.col("src") != "LIXINGER")
                    & ((pl.col("valid_from").is_null()) | (pl.col("valid_from") <= latest_snapshot))
                    & ((pl.col("valid_to").is_null()) | (pl.col("valid_to") > latest_snapshot))
                )
                | ((pl.col("src") == "LIXINGER") & (pl.col("snapshot_date") == latest_snapshot))
            )
        else:
            today = date.today()
            frame = frame.filter(
                (pl.col("valid_from").is_null() | (pl.col("valid_from") <= today))
                & (pl.col("valid_to").is_null() | (pl.col("valid_to") > today))
            )
    if requested is not None and not frame.is_empty():
        return frame.select([column for column in requested if column in frame.columns])
    return frame


def load_sw_2021_industry_dimension(
    catalog: MarketDataCatalog,
    *,
    level: str | None = None,
    src: str | None = None,
    columns: tuple[str, ...] | None = None,
) -> pl.DataFrame:
    """读取申万 2021 行业维度黄金表。"""
    catalog = _resolve_golden_catalog(catalog, SW_INDUSTRY_DIMENSION_GOLDEN_DATASET)
    requested = columns
    base_columns = columns or (
        "classification",
        "industry_code",
        "index_code",
        "industry_name",
        "level",
        "parent_code",
        "src",
        "tushare_present",
        "lixinger_present",
        "mapping_status",
    )
    load_columns = tuple(dict.fromkeys((*base_columns, "classification", "level", "src")))
    frame = _load_dataset(
        catalog,
        SW_INDUSTRY_DIMENSION_GOLDEN_DATASET,
        columns=load_columns,
    )
    if frame.is_empty():
        return frame
    if "classification" in frame.columns:
        frame = frame.filter(pl.col("classification") == SW_INDUSTRY_CLASSIFICATION)
    if level is not None and "level" in frame.columns:
        frame = frame.filter(pl.col("level") == level)
    if src is not None and "src" in frame.columns:
        frame = frame.filter(pl.col("src") == src)
    if requested is not None and not frame.is_empty():
        return frame.select([column for column in requested if column in frame.columns])
    return frame


def load_sw_2021_industry_symbols(
    catalog: MarketDataCatalog,
    industry_code: str,
    *,
    level: str | None = None,
) -> list[str]:
    """返回当前黄金层中指定行业的六位股票代码。"""
    frame = load_sw_2021_industry_members(
        catalog,
        level=level,
        current_only=True,
        canonical_only=True,
        columns=("symbol", "industry_code", "level"),
    )
    if frame.is_empty() or not {"symbol", "industry_code"}.issubset(frame.columns):
        return []
    return (
        frame.filter(pl.col("industry_code") == industry_code)
        .get_column("symbol")
        .cast(pl.String)
        .unique()
        .sort()
        .to_list()
    )


def _load_lixinger_fallback(catalog: MarketDataCatalog) -> pl.DataFrame:
    """黄金表尚未生成时，为旧调用保留理杏仁成员读取兼容。"""
    raw = _load_dataset(
        catalog,
        "sw_2021_constituents",
        columns=("industryCode", "symbol", "updated_at"),
    )
    prepared = _prepare_lixinger_constituents(raw)
    if prepared.is_empty():
        return prepared
    snapshot = _resolve_snapshot_date(raw)
    return prepared.with_columns(
        [
            pl.lit(SW_INDUSTRY_CLASSIFICATION).alias("classification"),
            pl.lit("LIXINGER").alias("src"),
            pl.lit("LIXINGER").alias("canonical_source"),
            pl.lit("legacy_lixinger_fallback").alias("source_status"),
            pl.lit(True).alias("is_canonical"),
            pl.lit(False).alias("conflict_flag"),
            pl.lit(False).alias("tushare_present"),
            pl.lit(True).alias("lixinger_present"),
            pl.lit(None, dtype=pl.String).alias("stock_code"),
            pl.lit(None, dtype=pl.String).alias("index_code"),
            pl.lit(None, dtype=pl.String).alias("industry_name"),
            pl.lit(None, dtype=pl.String).alias("parent_code"),
            pl.lit(None, dtype=pl.Date).alias("valid_from"),
            pl.lit(None, dtype=pl.Date).alias("valid_to"),
            pl.lit(snapshot, dtype=pl.Date).alias("snapshot_date"),
        ]
    ).with_columns(pl.col("symbol").alias("stock_code"))


def _resolve_golden_catalog(catalog: MarketDataCatalog, dataset: str) -> MarketDataCatalog:
    """从共享 Curated 根目录切换到 derived Catalog；测试内存目录保持原样。"""
    if getattr(catalog, "data_source", "") == "derived":
        return catalog
    storage_dir = getattr(catalog, "storage_dir", None)
    if storage_dir is None:
        return catalog
    root = Path(storage_dir)
    if root.name in {"tushare", "lixinger", "derived"}:
        root = root.parent
    try:
        from stock_data.catalog import DataCatalog

        golden = DataCatalog(data_source="derived", storage_dir=root)
        if dataset in golden.list_datasets():
            return golden
    except Exception:
        pass
    return catalog


__all__ = [
    "MEMBER_PRIMARY_KEYS",
    "SW_INDUSTRY_CLASSIFICATION",
    "SW_INDUSTRY_DIMENSION_GOLDEN_DATASET",
    "SW_INDUSTRY_GOLDEN_SOURCE_ENDPOINT",
    "SW_INDUSTRY_MEMBER_GOLDEN_DATASET",
    "SWIndustryGoldenFrames",
    "build_sw_2021_industry_dimension",
    "build_sw_2021_industry_golden",
    "build_sw_2021_industry_member_golden",
    "empty_sw_industry_dimension",
    "empty_sw_industry_members",
    "load_sw_2021_industry_dimension",
    "load_sw_2021_industry_members",
    "load_sw_2021_industry_symbols",
    "materialize_sw_2021_industry_golden",
]
