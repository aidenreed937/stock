# 全球资本开支共振辅助（通信设备光模块拐点定性，非方向分）

当 L2/L3 出口量价出现"量停滞/回落 × 金额高增"的歧义结构时（如光模块量 yoy 个位数、
价 yoy 高增），用本地 6 信号全球共振表定性"暂歇"vs"反转"：

```bash
uv run python .agents/skills/customs-export-research/scripts/build_comm_global_resonance.py
# → data/analytics/industry/comm_global_resonance_panel.parquet
#   云 CapEx / SEMI 设备 / 台积电 / SIA / ASML 毛利率 / 渠道 DOI
```

- 判定规则（industry-trend-tracking 拐点规则）：拐点正确信号 = **全球资本开支见顶**，
  不来自 A 股内部；升级"反转预警"的三道闸（14 文档 §5）——① 云 CapEx 下季 yoy < +70%；② SEMI 设备 3MMA yoy < +20% 或单期回落 >10pp；③ 光模块量 yoy 重新转负并持续 2 个月；任一触发 → 通信设备处置转"减仓观察"；
- 与已排除的 `direction_score` 方向分的区别：本表输出**原始实物量信号状态**（扩张/收缩 ×
  加剧/缓解），不作合成打分、不作行业排序、不作策略门，仅作拐点警觉参考；
- 专题说明：[`14_comm_global_resonance.md`](../../../../docs/research/customs_export_forward/14_comm_global_resonance.md)。
