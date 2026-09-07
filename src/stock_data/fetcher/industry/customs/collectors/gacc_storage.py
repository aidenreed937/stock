"""中国海关 GACC RAW CSV 与查询 manifest 存储。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from stock_data.fetcher.industry.customs.lineage import sha256_file
from stock_data.fetcher.industry.customs.models import (
    DEFAULT_INDUSTRY_OUTPUT_FIELDS,
    CustomsTradeRecord,
    GaccQueryParams,
    GaccSnapshotManifest,
)
from stock_data.fetcher.industry.customs.parsers.gacc import parse_gacc_csv


class GaccRawStore:
    """保存、校验并枚举 GACC 人工导出的原始文件。"""

    def __init__(self, raw_dir: Path | str = "data/raw/industry/customs/gacc") -> None:
        self.raw_dir = Path(raw_dir)
        self.manifest_dir = self.raw_dir / "manifests"

    def snapshot_path(self, params: GaccQueryParams) -> Path:
        """返回带方向和查询指纹的 CSV 路径。"""
        fingerprint = params.fingerprint()[:12]
        return self.raw_dir / params.flow_type / f"{params.period}_{fingerprint}.csv"

    def manifest_path(self, params: GaccQueryParams) -> Path:
        """返回对应 manifest 路径。"""
        fingerprint = params.fingerprint()[:12]
        return self.manifest_dir / f"{params.flow_type}_{params.period}_{fingerprint}.json"

    def find_cached(self, params: GaccQueryParams) -> GaccSnapshotManifest | None:
        """仅在文件存在且 SHA256 与 manifest 一致时返回缓存。"""
        manifest_path = self.manifest_path(params)
        snapshot_path = self.snapshot_path(params)
        if not manifest_path.exists() or not snapshot_path.exists():
            return None
        try:
            manifest = GaccSnapshotManifest.from_dict(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            if manifest.status != "success" or manifest.query_fingerprint != params.fingerprint():
                return None
            manifest_snapshot = Path(manifest.raw_snapshot_path)
            if not manifest_snapshot.is_absolute():
                manifest_snapshot = self.raw_dir / manifest_snapshot
            if manifest_snapshot.resolve() != snapshot_path.resolve():
                return None
            if manifest.raw_content_sha256 != sha256_file(manifest_snapshot):
                return None
            return manifest
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def save_download(
        self,
        params: GaccQueryParams,
        content: bytes | Path,
        *,
        source_url: str,
        downloaded_at: str | None = None,
    ) -> GaccSnapshotManifest:
        """保存人工导出的 CSV，并同步写入 manifest。"""
        raw_content = content.read_bytes() if isinstance(content, Path) else content
        if not raw_content:
            raise ValueError("GACC 下载内容为空，拒绝写入 RAW")

        snapshot_path = self.snapshot_path(params)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_bytes(raw_content)
        content_hash = hashlib.sha256(raw_content).hexdigest()
        row_count = max(raw_content.count(b"\n") - 1, 0)
        manifest = GaccSnapshotManifest(
            query=params,
            source_url=source_url,
            raw_snapshot_path=str(snapshot_path.relative_to(self.raw_dir)),
            raw_content_sha256=content_hash,
            downloaded_at=downloaded_at or datetime.now(UTC).isoformat(),
            row_count=row_count,
        )
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path(params).write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return manifest

    def iter_manifests(self) -> Iterator[GaccSnapshotManifest]:
        """按文件名稳定枚举有效 manifest。"""
        if not self.manifest_dir.exists():
            return
        for path in sorted(self.manifest_dir.glob("*.json")):
            try:
                manifest = GaccSnapshotManifest.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            snapshot_path = Path(manifest.raw_snapshot_path)
            if not snapshot_path.is_absolute():
                snapshot_path = self.raw_dir / snapshot_path
            if manifest.status != "success" or not snapshot_path.exists():
                continue
            if manifest.raw_content_sha256 != sha256_file(snapshot_path):
                continue
            yield manifest


def parse_gacc_manifest(
    manifest: GaccSnapshotManifest,
    raw_store: GaccRawStore,
    catalog_map: dict[str, dict[str, str]],
    gacc_code_map: dict[str, dict[str, str]] | None = None,
) -> list[CustomsTradeRecord]:
    """解析单个已校验 manifest，确认缓存确实包含 GACC 目录商品。"""
    path = Path(manifest.raw_snapshot_path)
    if not path.is_absolute():
        path = raw_store.raw_dir / path
    return parse_gacc_csv(
        path,
        params=manifest.query,
        catalog_map=catalog_map,
        gacc_code_map=gacc_code_map,
        manifest=manifest,
        source_url=manifest.source_url,
    )


def _merge_records(
    records_by_key: dict[tuple[str, str, str, str, str], CustomsTradeRecord],
    records: list[CustomsTradeRecord],
) -> None:
    """按产品、税号、月份、方向和币制幂等合并 RAW 解析结果。"""
    for record in records:
        key = (
            record.product_key,
            record.hs_code,
            record.report_month,
            record.trade_direction,
            record.trade_value_currency,
        )
        records_by_key[key] = record


def load_gacc_raw_records(
    raw_store: GaccRawStore,
    catalog_map: dict[str, dict[str, str]],
    source_url: str | None = None,
    gacc_code_map: dict[str, dict[str, str]] | None = None,
) -> list[CustomsTradeRecord]:
    """从新规范目录中的有效 manifest 快照加载并幂等合并记录。"""
    del source_url
    records_by_key: dict[tuple[str, str, str, str, str], CustomsTradeRecord] = {}

    for manifest in raw_store.iter_manifests():
        if manifest.query.output_fields != DEFAULT_INDUSTRY_OUTPUT_FIELDS:
            continue
        _merge_records(
            records_by_key,
            parse_gacc_manifest(
                manifest,
                raw_store,
                catalog_map,
                gacc_code_map,
            ),
        )

    records = list(records_by_key.values())
    records.sort(
        key=lambda record: (
            record.product_key,
            record.hs_code,
            record.trade_direction,
            record.trade_date,
        )
    )
    return records


__all__ = ["GaccRawStore", "load_gacc_raw_records", "parse_gacc_manifest", "sha256_file"]
