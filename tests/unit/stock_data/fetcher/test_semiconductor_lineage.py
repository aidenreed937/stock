"""半导体源端快照 lineage 工具测试。"""

from __future__ import annotations

import gzip
from pathlib import Path
from unittest.mock import MagicMock

from stock_data.fetcher.industry.semiconductor.lineage import (
    raw_content_sha256,
    raw_snapshot_content_bytes,
    raw_snapshot_path_value,
    response_content_bytes,
)


def test_raw_content_sha256_is_stable() -> None:
    assert raw_content_sha256(b"semi-source") == (
        "6ffd45598409cdcf3a78aee68b44a11aeaf6289efcc59c06f3a4b7c19b24e597"
    )


def test_response_content_bytes_falls_back_to_text() -> None:
    resp = MagicMock()
    resp.content = b""
    resp.text = "source html"

    assert response_content_bytes(resp) == b"source html"


def test_raw_snapshot_content_bytes_reads_gzip_and_relative_path(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    snapshot = raw_root / "semiconductor" / "semi" / "article.html.gz"
    snapshot.parent.mkdir(parents=True)
    with gzip.open(snapshot, "wb") as fh:
        fh.write(b"<html>source</html>")

    assert raw_snapshot_content_bytes(snapshot) == b"<html>source</html>"
    assert raw_snapshot_path_value(snapshot, raw_root) == "semiconductor/semi/article.html.gz"
