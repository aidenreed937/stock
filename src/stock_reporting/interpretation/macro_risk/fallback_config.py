"""宏观风控研报评级与定性话术默认备用配置。"""

from __future__ import annotations

from typing import Any

FALLBACK_CONFIG: dict[str, Any] = {
    "dimensions": {
        "leverage": {
            "name": "两融杠杆",
            "category": "生存与毁灭级风险 (硬约束 / 强平与失速)",
            "missing": {"grade": "数据暂缺", "icon": "⚪", "comment": "历史数据不足"},
            "tiers": [
                {
                    "min": 85.0,
                    "grade": "极度高危",
                    "icon": "🔴",
                    "comment": "存量杠杆触顶，严防连环多杀多强平",
                },
                {
                    "min": 65.0,
                    "grade": "偏高警惕",
                    "icon": "🟡",
                    "comment": "杠杆资金积聚，容错空间收窄",
                },
                {
                    "max": 30.0,
                    "grade": "杠杆健康",
                    "icon": "🟢",
                    "comment": "场内杠杆处于低位，无踩踏风险",
                },
                {
                    "default": True,
                    "grade": "规模适中",
                    "icon": "⚪",
                    "comment": "杠杆水平处于正常区间",
                },
            ],
        },
        "crowding": {
            "name": "换手拥挤",
            "category": "生存与毁灭级风险 (硬约束 / 强平与失速)",
            "missing": {"grade": "数据暂缺", "icon": "⚪", "comment": "历史数据不足"},
            "tiers": [
                {
                    "min": 85.0,
                    "grade": "严重过热",
                    "icon": "🔴",
                    "comment": "换手极度亢奋，短线买力濒临透支",
                },
                {
                    "min": 65.0,
                    "grade": "偏热过载",
                    "icon": "🟡",
                    "comment": "交易活跃度高，面临动量失速",
                },
                {
                    "max": 20.0,
                    "grade": "地量冰点",
                    "icon": "🟢",
                    "comment": "交投极度低迷，常对应坚实地量底",
                },
                {
                    "default": True,
                    "grade": "换手适中",
                    "icon": "⚪",
                    "comment": "交投活跃度处于正常区间",
                },
            ],
        },
        "flow": {
            "name": "主力资金",
            "category": "生存与毁灭级风险 (硬约束 / 强平与失速)",
            "missing": {"grade": "数据暂缺", "icon": "⚪", "comment": "历史数据不足"},
            "special_cases": [
                {
                    "condition": "divergence_and_flow",
                    "div_score_min": 85.0,
                    "val_min": 65.0,
                    "grade": "主力派发",
                    "icon": "🔴",
                    "comment": "主力坚决流出且散户激进接盘，筹码严重背离",
                },
            ],
            "tiers": [
                {
                    "min": 80.0,
                    "grade": "坚决出逃",
                    "icon": "🔴",
                    "comment": "主力资金单向大幅净流出，防范真摔",
                },
                {"min": 60.0, "grade": "流出承压", "icon": "🟡", "comment": "主力资金持续净流出"},
                {"max": 30.0, "grade": "流入活跃", "icon": "🟢", "comment": "主力资金积极回流加仓"},
                {
                    "default": True,
                    "grade": "流向平衡",
                    "icon": "⚪",
                    "comment": "主力资金流向未见明显倾斜",
                },
            ],
        },
        "fear": {
            "name": "期权情绪",
            "category": "拐点与博弈级信号 (快变量 / 情绪与超跌)",
            "missing": {"grade": "数据暂缺", "icon": "⚪", "comment": "历史数据不足"},
            "tiers": [
                {
                    "min": 80.0,
                    "grade": "极度恐慌",
                    "icon": "🟢",
                    "comment": "期权抢买Put避险，反向做多胜率极高",
                },
                {
                    "min": 60.0,
                    "grade": "恐慌升温",
                    "icon": "🟡",
                    "comment": "避险情绪上升，波动率放大",
                },
                {
                    "max": 20.0,
                    "grade": "极度自满",
                    "icon": "🔴",
                    "comment": "波动率降至冰点，警惕突发利空杀伤",
                },
                {
                    "default": True,
                    "grade": "情绪平稳",
                    "icon": "⚪",
                    "comment": "期权定价与避险情绪处于正常区间",
                },
            ],
        },
        "breadth": {
            "name": "市场广度",
            "category": "拐点与博弈级信号 (快变量 / 情绪与超跌)",
            "missing": {"grade": "数据暂缺", "icon": "⚪", "comment": "历史数据不足"},
            "tiers": [
                {
                    "min": 85.0,
                    "grade": "全面普跌",
                    "icon": "🟡",
                    "comment": "个股大面积破位，短期情绪宣泄充分",
                },
                {
                    "max": 20.0,
                    "grade": "全线普涨",
                    "icon": "⚪",
                    "comment": "赚钱效应扩散，涨多后警惕分化",
                },
                {
                    "default": True,
                    "grade": "结构均衡",
                    "icon": "⚪",
                    "comment": "涨跌家数与新高新低未现极端背离",
                },
            ],
        },
        "valuation": {
            "name": "大盘估值",
            "category": "长线估值与安全边际 (慢变量 / 空间)",
            "missing": {"grade": "数据暂缺", "icon": "⚪", "comment": "历史数据不足"},
            "tiers": [
                {
                    "min": 80.0,
                    "grade": "估值昂贵",
                    "icon": "🔴",
                    "comment": "ERP与PB处于高位，中长线期望空间压缩",
                },
                {
                    "min": 60.0,
                    "grade": "估值偏高",
                    "icon": "🟡",
                    "comment": "安全边际收窄，需业绩消化",
                },
                {
                    "max": 20.0,
                    "grade": "极度低估",
                    "icon": "🟢",
                    "comment": "安全边际极高，长线配置价值突出",
                },
                {
                    "default": True,
                    "grade": "估值合理",
                    "icon": "⚪",
                    "comment": "处于历史中位数水平",
                },
            ],
        },
    }
}
