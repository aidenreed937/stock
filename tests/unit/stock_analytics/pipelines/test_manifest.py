"""管线 Manifest 公共字段测试。"""

import hashlib
from datetime import date
from pathlib import Path

from stock_analytics.pipelines.manifest import build_manifest_base, build_watermark_index


def test_build_manifest_base_contains_common_provenance_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("market_temperature:\n  schema_version: 1\n", encoding="utf-8")

    manifest = build_manifest_base(
        artifact_type="market_temperature",
        schema_version=1,
        title="测试市场温度计",
        run_id="run_test",
        as_of_date=date(2026, 8, 24),
        artifact_root=tmp_path / "artifacts",
        config_path=config_path,
        inputs={"datasets": {"tushare.stock_daily_bar": {"latest": "2026-08-23"}}},
        parents={"comparison": {"run_id": "run_previous"}},
    )

    assert manifest["manifest_schema_version"] == 1
    assert manifest["artifact_type"] == "market_temperature"
    assert manifest["run_status"] == "succeeded"
    assert manifest["as_of_date"] == "2026-08-24"
    assert manifest["inputs"]["datasets"]["tushare.stock_daily_bar"]["latest"] == "2026-08-23"
    assert manifest["parents"]["comparison"]["run_id"] == "run_previous"
    assert (
        manifest["provenance"]["config_sha256"]
        == hashlib.sha256(config_path.read_bytes()).hexdigest()
    )
    assert manifest["provenance"]["git_commit"]
    assert isinstance(manifest["provenance"]["git_dirty"], bool)


def test_build_watermark_index_keeps_status_and_latest_value() -> None:
    result = build_watermark_index(
        [
            {
                "category": "analysis_window",
                "data_source": "tushare",
                "dataset": "ignored",
            },
            {
                "category": "data_watermark",
                "data_source": "tushare",
                "dataset": "stock_daily_bar",
                "status": "lagging",
                "value_text": "2026-08-23",
                "sample_size": 20,
                "source": "DataCatalog",
                "note": "滞后一天",
            },
        ]
    )

    assert result == {
        "tushare.stock_daily_bar": {
            "data_source": "tushare",
            "dataset": "stock_daily_bar",
            "status": "lagging",
            "latest": "2026-08-23",
            "sample_size": 20,
            "source": "DataCatalog",
            "note": "滞后一天",
        }
    }
