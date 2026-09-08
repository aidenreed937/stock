---
name: customs-industry-prosperity
description: 申万行业 × 海关出口数据前瞻景气研究方法技能。研究商品量价拐点（量最领先、价确认、金额合成）如何驱动申万二级/三级行业景气度变化，财报 TTM 仅作后视验证；产出行业出口量价观察表与月度前瞻观察报告，并可下沉到受益公司（暴露度 × 税号段级出口景气）。当用户询问海关出口景气、申万行业量价拐点、出口驱动行业景气、L2/L3 行业出口前瞻、出口受益公司、公司出口景气、外需与行业财报关系、出口量价齐升/量驱动/价驱动/双弱分类，或要求按定稿方法论（非方向分等旧思路）生成行业/公司景气观察时使用此技能。该方法论定稿见 docs/research/customs_export_forward/METHODOLOGY_FINAL.md，为唯一权威口径，明确排除 direction_score 方向分等已证伪信号。
---

# Customs Industry Prosperity (申万行业 × 海关出口量价景气研究)

**研究商品量价拐点（量最领先、价确认、金额合成），量价驱动申万 L2/L3 行业景气度变化，
财报 TTM 只作后视验证。** 方法论已定稿，不再探索，只按唯一权威
[`METHODOLOGY_FINAL.md`](../../../docs/research/customs_export_forward/METHODOLOGY_FINAL.md) 执行与扩展。

## 常用命令速查 (CLI Cheat Sheet)

```bash
# 1. 金额面板（hs8 桥接 + 月序补全 + 3MMA yoy，含桥接校验）
uv run python .agents/skills/customs-industry-prosperity/scripts/build_customs_export_prosperity.py

# 2. 量价分解面板（单位归一 + 四象限驱动 + L2/L3）
uv run python .agents/skills/customs-industry-prosperity/scripts/build_customs_l2_volume_price.py

# 3. 商品级量价拐点面板（product 粒度三 yoy + 驱动 + 拐点/二阶导 + 行业映射）
uv run python .agents/skills/customs-industry-prosperity/scripts/build_customs_product_volume_price.py

# 4. L2/L3 观察表（金额/量/价/驱动/36 月分位/财报 yoy/一致率分级）
uv run python .agents/skills/customs-industry-prosperity/scripts/build_customs_forward_watch.py

# 5. 三腿 AND 入场前置（L2，无前视窗口）——可选加载，非本 skill 主流程
uv run python .agents/skills/customs-industry-prosperity/scripts/three_leg_entry_and.py --level L2

# 6. 公司级出口景气观察表（暴露度 × 税号段级序列 → 受益公司排序；见 company_linkage.md）
uv run python scripts/build_customs_company_exposure.py
```

## 标准执行 SOP（月度，数据发布后约每月 8 月下旬）

1. **刷海关黄金表**：GACC/Comtrade 当月 raw 更新 → `customs_trade.parquet`
   （见 data-pipeline skill，不在此重复）；
2. **跑 4 个 build 脚本**（命令速查 1-4），顺序固定：金额 → 量价 → 商品拐点 → 观察表；
3. **读观察表判景气**（L2 判景气，L3 看分化）：
   - 四象限：量价齐升 ✓ / 量驱动 / 价驱动 ⚠ / 双弱 ✗；
   - 二阶导：量 yoy 见顶回落 = 顶部前兆；量回落 × 财报仍加速 = 最危险组合；
   - 分位：36 月经验分位定位四阶段（启动/高潮/放缓/萎缩）；
   - 之后与财报 yoy 对照：前瞻窗口（出口正×财报负）与双正（兑现中）；
4. **更新月度观察报告** `docs/research/customs_export_forward/12_forward_watch_<yyyy_mm>.md`
   （四阶段定位表、量价驱动分层、拐点预警卡；格式与必含要素见
   [`references/methodology.md`](references/methodology.md)，样例
   [`12_forward_watch_2026_07.md`](../../../docs/research/customs_export_forward/12_forward_watch_2026_07.md)）；
5. **验证**：桥接审计断言通过（L3 归属一致、组合码已跳过）再落报告；
6. **（可选但推荐）公司下沉**：跑命令速查 6 → 读公司级出口景气观察表，
   按 `references/company_linkage.md` 判读受益公司（行业层区分度不足时，
   段级 yoy 是公司间差异信号，如 transformer 产品 +34% 内部 ultra 段 +111%）。

## 按需加载的参考（references/，遇相关任务再读）

- [`references/methodology.md`](references/methodology.md)——核心方法论、信号口径（四象限/拐点/一致率）、财报验证与排除清单、量化纪律、月度报告格式、关键实证锚点；
- [`references/data_basics.md`](references/data_basics.md)——数据底座黄金表与面板路径清单、财报/维度黄金表；
- [`references/maintenance.md`](references/maintenance.md)——维护边界（2 文件 / 645 码 / 73 断点）、已知数据质量限制、税则切换解冻流程、品目污染修复防复发、桥接强制规则与审计基线；
- [`references/global_resonance.md`](references/global_resonance.md)——全球资本开支共振辅助（通信设备光模块歧义结构定性，6 信号表 + 命令）；
- [`references/company_linkage.md`](references/company_linkage.md)——**出口商品→公司景气度下沉**：暴露度资产清单、税号段修正、LLM 别名表再生成、公司观察表判读口径（2026-09 新增）。
