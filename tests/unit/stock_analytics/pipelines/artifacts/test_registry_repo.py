from pathlib import Path

import pytest

from stock_analytics.pipelines.artifacts.registry_repo import ArtifactRegistryRepository
from stock_core.storage.sqlite_engine import SQLiteEngine


def test_artifact_registry_record_and_get(tmp_path: Path) -> None:
    db_file = tmp_path / "test_artifact_state.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = ArtifactRegistryRepository(engine)

    # 构造假产物文件
    run_dir = tmp_path / "runs" / "as_of=2026-08-28" / "run_test_001"
    run_dir.mkdir(parents=True)
    (run_dir / "report.md").write_text("# 市场温度研报\n温度: 78.5", encoding="utf-8")
    (run_dir / "manifest.json").write_text('{"dummy": true}', encoding="utf-8")

    manifest = {
        "run_id": "run_test_001",
        "artifact_type": "market_temperature",
        "as_of_date": "2026-08-28",
        "run_class": "official",
        "run_status": "succeeded",
        "generated_at": "2026-08-28T15:30:00",
        "duration_ms": 1250,
        "provenance": {"git_commit": "abc1234"},
        "summary": {
            "market_temperature_score": 78.5,
            "panic_index": 45.2,
            "overheat_index": 82.1,
            "advance_count": 3200,
        },
        "watermarks": {
            "tushare.daily_bars": {
                "data_source": "tushare",
                "dataset": "daily_bars",
                "upstream_watermark": "2026-08-28",
                "synced_at": "2026-08-28T15:05:00",
            }
        },
    }

    # 1. 记录运行
    run_id = repo.record_run(manifest=manifest, run_dir=run_dir, is_latest=True)
    assert run_id == "run_test_001"

    # 2. 查询运行详情
    detail = repo.get_run("run_test_001")
    assert detail is not None
    assert detail["pipeline_name"] == "market_temperature"
    assert detail["as_of_date"] == "2026-08-28"
    assert detail["is_latest"] == 1
    assert detail["is_pinned"] == 0

    # 验证指标提取
    assert detail["metrics"]["market_temperature_score"] == pytest.approx(78.5)
    assert detail["metrics"]["panic_index"] == pytest.approx(45.2)

    # 验证上游水位
    assert len(detail["watermarks"]) == 1
    assert detail["watermarks"][0]["dataset_name"] == "daily_bars"

    # 验证文件清单
    assert len(detail["files"]) == 2
    f_types = [f["file_type"] for f in detail["files"]]
    assert "REPORT_MD" in f_types
    assert "MANIFEST_JSON" in f_types


def test_artifact_registry_find_stale_and_diff(tmp_path: Path) -> None:
    db_file = tmp_path / "test_diff.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = ArtifactRegistryRepository(engine)

    run_dir_1 = tmp_path / "run_1"
    run_dir_1.mkdir()
    run_dir_2 = tmp_path / "run_2"
    run_dir_2.mkdir()

    manifest_1 = {
        "run_id": "run_v1",
        "artifact_type": "macro_risk",
        "as_of_date": "2026-08-28",
        "summary": {"panic_index": 45.0, "risk_score": 60.0},
        "watermarks": {
            "tushare.daily_bars": {
                "data_source": "tushare",
                "dataset": "daily_bars",
                "upstream_watermark": "2026-08-28",
                "synced_at": "2026-08-28T15:00:00",
            }
        },
    }
    manifest_2 = {
        "run_id": "run_v2",
        "artifact_type": "macro_risk",
        "as_of_date": "2026-08-28",
        "summary": {"panic_index": 55.0, "risk_score": 75.0, "extra_metric": 10.0},
        "watermarks": {
            "tushare.daily_bars": {
                "data_source": "tushare",
                "dataset": "daily_bars",
                "upstream_watermark": "2026-08-28",
                "synced_at": "2026-08-28T16:00:00",
            }
        },
    }

    repo.record_run(manifest=manifest_1, run_dir=run_dir_1)
    repo.record_run(manifest=manifest_2, run_dir=run_dir_2)

    # 1. 测试 Diff
    diff_res = repo.diff_runs("run_v1", "run_v2")
    assert diff_res["run_id_a"] == "run_v1"
    diff_map = {m["metric_key"]: m["delta"] for m in diff_res["metrics"]}
    assert diff_map["panic_index"] == pytest.approx(10.0)  # 55 - 45
    assert diff_map["risk_score"] == pytest.approx(15.0)  # 75 - 60

    # 2. 测试反查失效产物
    # 假设 15:30 发现 15:00 同步的数据有错误，反查 15:30 之前生成的产物
    stale = repo.find_stale_runs("daily_bars", "2026-08-28", cutoff_synced_at="2026-08-28T15:30:00")
    assert len(stale) == 1
    assert stale[0]["run_id"] == "run_v1"


def test_artifact_registry_pinning_and_pruning(tmp_path: Path) -> None:
    db_file = tmp_path / "test_prune.db"
    engine = SQLiteEngine(db_path=db_file, auto_migrate=True)
    repo = ArtifactRegistryRepository(engine)

    run_dir = tmp_path / "run_exp"
    run_dir.mkdir()

    manifest = {
        "run_id": "run_exp_old",
        "artifact_type": "market_temperature",
        "as_of_date": "2026-07-01",
        "run_class": "experiment",
        "generated_at": "2026-07-01T10:00:00",
    }
    repo.record_run(manifest=manifest, run_dir=run_dir, is_latest=False)

    # 初始状态：未锁定，且生成于 30 天前，应出现在清理候选列表中
    candidates = repo.collect_pruning_candidates(older_than_days=10)
    assert len(candidates) == 1
    assert candidates[0]["run_id"] == "run_exp_old"

    # 执行锁定保护
    repo.set_pinned("run_exp_old", True)
    candidates_pinned = repo.collect_pruning_candidates(older_than_days=10)
    assert len(candidates_pinned) == 0  # 锁定后不再被当作清理候选

    # 解除锁定
    repo.set_pinned("run_exp_old", False)
    candidates_unpinned = repo.collect_pruning_candidates(older_than_days=10)
    assert len(candidates_unpinned) == 1
