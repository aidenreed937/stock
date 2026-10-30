"""纯碱产能种子库增量对齐与更新器。

负责将巨潮资讯抽取出的最新结构化产能事件与本地
config/industry/chemicals/soda_ash/capacity_projects.yaml 种子库进行幂等合并与安全回写。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("config/industry/chemicals/soda_ash/capacity_projects.yaml")


class CapacityProjectUpdater:
    """产能种子库增量更新器。"""

    def __init__(self, config_path: Path | str = DEFAULT_CONFIG_PATH) -> None:
        self.config_path = Path(config_path)

    def load_existing_data(self) -> dict[str, Any]:
        """读取现有 YAML 配置文件。"""
        if not self.config_path.exists():
            return {
                "metadata": {
                    "product_name": "纯碱",
                    "symbol": "SA",
                    "unit": "万吨/年",
                    "version": "1.0.0",
                },
                "projects": [],
            }
        content = self.config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content) or {}
        if "projects" not in data:
            data["projects"] = []
        return data

    def merge_events(
        self,
        new_events: list[dict[str, Any]],
        dry_run: bool = True,
    ) -> tuple[dict[str, Any], list[str]]:
        """将新抽取的产能事件合并到现有项目中。

        返回 (更新后的完整字典, 变更日志列表)。
        """
        data = self.load_existing_data()
        projects: list[dict[str, Any]] = list(data.get("projects", []))
        change_log: list[str] = []

        # 建立现有 project_id 索引
        project_idx_map = {
            p["project_id"]: idx for idx, p in enumerate(projects) if "project_id" in p
        }

        for event in new_events:
            pid = event.get("project_id")
            if not pid:
                continue

            if pid in project_idx_map:
                # 针对已存在项目的状态/时间推进合并
                idx = project_idx_map[pid]
                old = projects[idx]
                updated = False

                # 1. 状态由建设中转为已投产/已达产
                if (
                    old.get("status") in ["under_construction", "planned"]
                    and event.get("status") == "operating"
                ):
                    change_log.append(
                        f"[{pid}] 状态由 {old.get('status')} 推进为 operating (来源: {event.get('source')})"
                    )
                    old["status"] = "operating"
                    updated = True

                # 2. 补充实际投料时间
                if event.get("actual_start") and not old.get("actual_start"):
                    change_log.append(f"[{pid}] 补充实际投料时间: {event.get('actual_start')}")
                    old["actual_start"] = event.get("actual_start")
                    updated = True

                # 3. 补充满产达产时间
                if event.get("full_capacity_date") and not old.get("full_capacity_date"):
                    change_log.append(f"[{pid}] 补充达产时间: {event.get('full_capacity_date')}")
                    old["full_capacity_date"] = event.get("full_capacity_date")
                    updated = True

                # 4. 更新预计投产时间 (若在建且有更新预期)
                if old.get("status") == "under_construction" and event.get("expected_start"):
                    if old.get("expected_start") != event.get("expected_start"):
                        change_log.append(
                            f"[{pid}] 修正预计投产时间: {old.get('expected_start')} -> {event.get('expected_start')}"
                        )
                        old["expected_start"] = event.get("expected_start")
                        updated = True

                if updated and old.get("confidence") != "A":
                    old["confidence"] = "B"
            else:
                # 全新项目追加
                projects.append(event)
                project_idx_map[pid] = len(projects) - 1
                change_log.append(
                    f"[新增项目 {pid}] {event.get('company')} {event.get('plant_name')}, "
                    f"产能: {event.get('capacity_w_tons')}万吨/年, 状态: {event.get('status')}"
                )

        data["projects"] = projects

        if not dry_run and change_log:
            self.save_data(data)
            logger.info("已将 %d 处产能变更写入 %s", len(change_log), self.config_path)

        return data, change_log

    def save_data(self, data: dict[str, Any]) -> None:
        """安全格式化回写 YAML 文件。"""
        # 手工格式化保留优雅注释与缩进
        lines = [
            "# 纯碱重大产能事件种子库 (Capacity Project Database)",
            "# 数据源：上市公司公告 (深交所/巨潮 000683 远兴能源、600328 中盐化工等) + 行业协会披露",
            "# 用途：跟踪行业供给端物理有效产能释放日历与冲击规模",
            "",
            "metadata:",
            f'  product_name: "{data["metadata"].get("product_name", "纯碱")}"',
            f'  symbol: "{data["metadata"].get("symbol", "SA")}"',
            f'  unit: "{data["metadata"].get("unit", "万吨/年")}"',
            f'  version: "{data["metadata"].get("version", "1.0.0")}"',
            "",
            "projects:",
        ]

        for p in data.get("projects", []):
            lines.append(f'  - project_id: "{p.get("project_id", "")}"')
            lines.append(f'    company: "{p.get("company", "")}"')
            lines.append(f'    plant_name: "{p.get("plant_name", "")}"')
            lines.append(f'    province: "{p.get("province", "")}"')
            lines.append(f'    technology: "{p.get("technology", "hou_process")}"')
            lines.append(f"    capacity_w_tons: {float(p.get('capacity_w_tons', 0.0))}")
            lines.append(f'    status: "{p.get("status", "under_construction")}"')
            lines.append(f'    announcement_date: "{p.get("announcement_date", "")}"')

            exp_s = f'"{p.get("expected_start")}"' if p.get("expected_start") else "null"
            act_s = f'"{p.get("actual_start")}"' if p.get("actual_start") else "null"
            full_s = f'"{p.get("full_capacity_date")}"' if p.get("full_capacity_date") else "null"

            lines.append(f"    expected_start: {exp_s}")
            lines.append(f"    actual_start: {act_s}")
            lines.append(f"    full_capacity_date: {full_s}")
            lines.append(f'    source: "{p.get("source", "")}"')
            lines.append(f'    confidence: "{p.get("confidence", "B")}"')
            lines.append("")

        self.config_path.write_text("\n".join(lines), encoding="utf-8")
