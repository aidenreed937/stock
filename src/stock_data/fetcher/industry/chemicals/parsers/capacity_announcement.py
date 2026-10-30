"""纯碱重大产能公告文本结构化解析器。

从巨潮资讯公告标题与正文中，通过模式匹配与规则抽取结构化产能事件属性
（项目ID、装置名称、工艺路线、产能规模、工程状态与关键投产/试车日期）。
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


class CapacityAnnouncementParser:
    """纯碱重大产能公告结构化解析器。"""

    # 常见纯碱上市公司代码与主体映射
    COMPANY_MAP: dict[str, dict[str, str]] = {
        "000683": {
            "name": "远兴能源 (博源银根矿业)",
            "province": "内蒙古",
            "default_tech": "natural_alkali",
        },
        "600328": {
            "name": "中盐化工",
            "province": "内蒙古 / 青海",
            "default_tech": "solvay_and_hou",
        },
        "000822": {"name": "山东海化", "province": "山东", "default_tech": "solvay_process"},
        "600409": {"name": "三友化工", "province": "河北", "default_tech": "solvay_process"},
        "000707": {"name": "双环科技", "province": "湖北", "default_tech": "hou_process"},
    }

    def parse_announcement(
        self, item: dict[str, Any], content_text: str = ""
    ) -> dict[str, Any] | None:
        """解析单条公告为结构化产能事件字典。若无关则返回 None。"""
        raw_title = str(item.get("announcementTitle") or "").strip()
        title = re.sub(r"<[^>]+>", "", raw_title).strip()
        sec_code = str(item.get("secCode") or "").strip()
        timestamp_ms = item.get("announcementTime")
        if timestamp_ms:
            ann_date = datetime.fromtimestamp(timestamp_ms / 1000.0).date()
        else:
            ann_date = date.today()

        ann_date_str = ann_date.isoformat()

        # 过滤无关公告（如董事会决议、季度财报、日常关联交易等，除非标题含重大产能关键词）
        target_keywords = [
            "天然碱",
            "试车",
            "投料",
            "投产",
            "达产",
            "二期",
            "纯碱项目",
            "技改",
            "扩建",
            "淘汰",
        ]
        if not any(kw in title for kw in target_keywords):
            return None

        # 排除纯财务公告/担保公告/质押公告/临时设备故障检修/采矿权评估
        exclude_keywords = [
            "担保",
            "质押",
            "套期保值",
            "回购",
            "定期报告",
            "审计报告",
            "年度报告",
            "半年度报告",
            "评估报告",
            "收购",
            "股权",
            "故障",
            "降负荷",
            "恢复正常运行",
        ]
        if any(ek in title for ek in exclude_keywords):
            return None

        combined_text = f"{title}\n{content_text}"

        # 仅关注纯碱核心产能，排除金属钠、特种树脂等无关扩产
        if sec_code == "600328" and not ("天然碱" in combined_text or "纯碱" in combined_text):
            return None

        # 1. 远兴能源阿拉善项目专项精准解析
        if sec_code == "000683":
            company = "远兴能源 (博源银根矿业)"
            province = "内蒙古"
            technology = "natural_alkali"

            if "二期" in combined_text:
                project_id = "YX_ALSH_PHASE2"
                plant_name = "阿拉善天然碱项目二期工程"
                capacity = 280.0
            elif any(w in combined_text for w in ["第一条", "1线", "第1条"]):
                project_id = "YX_ALSH_PHASE1_L1"
                plant_name = "阿拉善天然碱项目一期1线"
                capacity = 150.0
            elif any(w in combined_text for w in ["第二条", "2线", "第2条"]):
                project_id = "YX_ALSH_PHASE1_L2"
                plant_name = "阿拉善天然碱项目一期2线"
                capacity = 150.0
            elif any(w in combined_text for w in ["第三条", "3线", "第3条"]):
                project_id = "YX_ALSH_PHASE1_L3"
                plant_name = "阿拉善天然碱项目一期3线"
                capacity = 100.0
            elif any(w in combined_text for w in ["第四条", "4线", "第4条"]):
                project_id = "YX_ALSH_PHASE1_L4"
                plant_name = "阿拉善天然碱项目一期4线"
                capacity = 100.0
            elif "碳回收" in combined_text:
                # 碳回收综合利用非纯碱主体扩产
                return None
            else:
                return None
        elif sec_code == "600328":
            company = "中盐化工"
            province = "内蒙古"
            if "天然碱" in combined_text:
                technology = "natural_alkali"
                project_id = "ZYHG_ALSH_NATURAL"
                plant_name = "中盐内蒙古天然碱综合开发项目"
                capacity = 500.0
            else:
                return None
        else:
            # 其他公司通用解析
            comp_info = self.COMPANY_MAP.get(
                sec_code,
                {
                    "name": str(item.get("secName") or "未知公司"),
                    "province": "全国",
                    "default_tech": "hou_process",
                },
            )
            company = comp_info["name"]
            province = comp_info["province"]
            technology = comp_info["default_tech"]
            plant_name = (
                title.replace("关于", "").replace("的公告", "").replace("进展公告", "").strip()
            )
            cap_match = re.search(r"(\d+(?:\.\d+)?)\s*万吨", combined_text)
            capacity = float(cap_match.group(1)) if cap_match else 100.0
            project_id = f"{sec_code}_CAP_{ann_date.strftime('%Y%m')}"

            if "联碱" in combined_text:
                technology = "hou_process"
            elif "氨碱" in combined_text:
                technology = "solvay_process"

        # 3. 判定状态与日期
        status = "under_construction"
        actual_start: str | None = None
        full_capacity_date: str | None = None
        expected_start: str | None = None

        if any(
            w in combined_text for w in ["投料试车", "试车成功", "正式投产", "试生产", "顺利投料"]
        ):
            status = "operating"
            actual_start = ann_date_str
            # 若提及达产或满负荷
            if any(w in combined_text for w in ["达产", "满产", "达标"]):
                full_capacity_date = ann_date_str
        elif any(w in combined_text for w in ["达产", "全面达产"]):
            status = "operating"
            full_capacity_date = ann_date_str
            actual_start = actual_start or ann_date_str
        elif any(w in combined_text for w in ["淘汰", "关停", "退出"]):
            status = "shutdown"
            actual_start = ann_date_str
            capacity = -abs(capacity)
        elif any(w in combined_text for w in ["启动建设", "开工", "建设进展", "推进"]):
            status = "under_construction"
            # 尝试查找预计时间 (例如 2025年12月 或 2026年)
            exp_match = re.search(r"(202[4-9])\s*年\s*(\d{1,2})?\s*月?", combined_text)
            if exp_match:
                yr = int(exp_match.group(1))
                mo = int(exp_match.group(2)) if exp_match.group(2) else 6
                expected_start = f"{yr:04d}-{mo:02d}-30"

        return {
            "project_id": project_id,
            "company": company,
            "plant_name": plant_name,
            "province": province,
            "technology": technology,
            "capacity_w_tons": capacity,
            "status": status,
            "announcement_date": ann_date_str,
            "expected_start": expected_start,
            "actual_start": actual_start,
            "full_capacity_date": full_capacity_date,
            "source": f"巨潮资讯/{title}",
            "confidence": "B",
        }
