"""巨潮资讯纯碱产能采集、解析与更新器单元测试。"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from stock_data.fetcher.industry.chemicals.capacity_updater import CapacityProjectUpdater
from stock_data.fetcher.industry.chemicals.collectors.cninfo_announcement import (
    CninfoAnnouncementCollector,
)
from stock_data.fetcher.industry.chemicals.parsers.capacity_announcement import (
    CapacityAnnouncementParser,
)


def test_collector_fetch_with_mock(tmp_path: Path) -> None:
    """测试采集器在 Mock 外部网络请求下的行为与快照保存。"""
    collector = CninfoAnnouncementCollector(raw_dir=tmp_path / "announcements", raw_root=tmp_path)

    mock_resp_data = {
        "announcements": [
            {
                "announcementId": "ann_001",
                "secCode": "000683",
                "secName": "远兴能源",
                "announcementTitle": "关于阿拉善天然碱项目一期第一条生产线投料试车的公告",
                "announcementTime": 1687881600000,  # 2023-06-28
                "adjunctUrl": "finalpage/2023-06-28/ann_001.PDF",
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = json.dumps(mock_resp_data).encode("utf-8")
    mock_resp.text = json.dumps(mock_resp_data)

    with patch("curl_cffi.requests.post", return_value=mock_resp):
        items = collector.fetch_announcements_for_stock(
            sec_code="000683",
            column="szse",
            keywords="天然碱 投料",
            start_date="2023-01-01",
            end_date="2023-07-01",
        )

        assert len(items) == 1
        assert items[0]["announcementTitle"] == "关于阿拉善天然碱项目一期第一条生产线投料试车的公告"
        assert "_raw_content_sha256" in items[0]
        assert "_raw_snapshot_path" in items[0]


def test_parser_soda_ash_announcements() -> None:
    """测试结构化解析器对不同类型产能公告的规则匹配。"""
    parser = CapacityAnnouncementParser()

    # 1. 远兴能源一期1线投料公告
    item_l1 = {
        "secCode": "000683",
        "secName": "远兴能源",
        "announcementTitle": "关于阿拉善天然碱项目一期第一条生产线投料试车的公告",
        "announcementTime": 1687881600000,
    }
    evt_l1 = parser.parse_announcement(item_l1)
    assert evt_l1 is not None
    assert evt_l1["project_id"] == "YX_ALSH_PHASE1_L1"
    assert evt_l1["technology"] == "natural_alkali"
    assert evt_l1["capacity_w_tons"] == 150.0
    assert evt_l1["status"] == "operating"
    assert evt_l1["actual_start"] == "2023-06-28"

    # 2. 远兴能源一期4线投料公告
    item_l4 = {
        "secCode": "000683",
        "secName": "远兴能源",
        "announcementTitle": "关于阿拉善天然碱项目一期第四条生产线顺利投料试车的公告",
        "announcementTime": 1717027200000,  # 2024-05-30
    }
    evt_l4 = parser.parse_announcement(item_l4)
    assert evt_l4 is not None
    assert evt_l4["project_id"] == "YX_ALSH_PHASE1_L4"
    assert evt_l4["capacity_w_tons"] == 100.0
    assert evt_l4["status"] == "operating"
    assert evt_l4["actual_start"] == "2024-05-30"

    # 3. 远兴能源二期建设进展公告
    item_p2 = {
        "secCode": "000683",
        "secName": "远兴能源",
        "announcementTitle": "关于阿拉善天然碱项目二期工程建设进展的公告",
        "announcementTime": 1718928000000,
    }
    evt_p2 = parser.parse_announcement(item_p2, content_text="计划于2025年12月建成试车")
    assert evt_p2 is not None
    assert evt_p2["project_id"] == "YX_ALSH_PHASE2"
    assert evt_p2["status"] == "under_construction"
    assert evt_p2["capacity_w_tons"] == 280.0
    assert evt_p2["expected_start"] == "2025-12-30"

    # 4. 过滤无关公告
    item_irrelevant = {
        "secCode": "000683",
        "secName": "远兴能源",
        "announcementTitle": "关于为控股子公司提供担保的进展公告",
        "announcementTime": 1718928000000,
    }
    evt_irrelevant = parser.parse_announcement(item_irrelevant)
    assert evt_irrelevant is None


def test_capacity_project_updater(tmp_path: Path) -> None:
    """测试产能种子库增量对齐合并与幂等性。"""
    config_file = tmp_path / "test_capacity.yaml"
    initial_data = {
        "metadata": {
            "product_name": "纯碱",
            "symbol": "SA",
            "unit": "万吨/年",
            "version": "1.0.0",
        },
        "projects": [
            {
                "project_id": "YX_ALSH_PHASE2",
                "company": "远兴能源",
                "plant_name": "阿拉善天然碱项目二期工程",
                "technology": "natural_alkali",
                "capacity_w_tons": 280.0,
                "status": "under_construction",
                "announcement_date": "2023-12-12",
                "expected_start": "2026-06-30",
                "actual_start": None,
                "full_capacity_date": None,
                "source": "巨潮资讯",
                "confidence": "A",
            }
        ],
    }
    config_file.write_text(yaml.dump(initial_data, allow_unicode=True), encoding="utf-8")

    updater = CapacityProjectUpdater(config_path=config_file)

    # 模拟从新公告中抽取出二期投料成功的事件
    new_event = {
        "project_id": "YX_ALSH_PHASE2",
        "company": "远兴能源",
        "plant_name": "阿拉善天然碱项目二期工程",
        "technology": "natural_alkali",
        "capacity_w_tons": 280.0,
        "status": "operating",
        "announcement_date": "2025-12-20",
        "actual_start": "2025-12-20",
        "full_capacity_date": None,
        "source": "巨潮资讯/二期投料试车公告",
        "confidence": "B",
    }

    # 1. 试运行模式 (不修改文件)
    _data_dry, log_dry = updater.merge_events([new_event], dry_run=True)
    assert len(log_dry) > 0
    # 文件内容未改变
    saved_text = config_file.read_text(encoding="utf-8")
    assert "actual_start: null" in saved_text or "actual_start: null" in saved_text.lower()

    # 2. 正式应用模式 (写入文件)
    _data_applied, log_applied = updater.merge_events([new_event], dry_run=False)
    assert len(log_applied) > 0

    # 重新加载验证
    reloaded = updater.load_existing_data()
    p2 = reloaded["projects"][0]
    assert p2["status"] == "operating"
    assert p2["actual_start"] == "2025-12-20"

    # 3. 幂等性验证 (再次合并相同事件无新增变更)
    _, log_idempotent = updater.merge_events([new_event], dry_run=False)
    assert len(log_idempotent) == 0
