---
name: customs-industry-prosperity
description: 申万行业 × 海关出口数据前瞻景气研究方法技能。研究商品量价拐点（量最领先、价确认、金额合成）如何驱动申万二级/三级行业景气度变化，财报 TTM 仅作后视验证；产出行业出口量价观察表与月度前瞻观察报告。公司层交易信号（暴露度×税号段×三层信号×择时回测）见 customs-export-trading skill。当用户询问海关出口景气、申万行业量价拐点、出口驱动行业景气、L2/L3 行业出口前瞻、行业景气观察表、外需与行业财报关系、出口量价齐升/量驱动/价驱动/双弱分类，或要求按定稿方法论（非方向分等旧思路）生成行业景气观察时使用此技能。该方法论定稿见 docs/research/customs_export_forward/METHODOLOGY_FINAL.md，为唯一权威口径，明确排除 direction_score 方向分等已证伪信号。
---

# Customs Industry Prosperity (申万行业 × 海关出口量价景气研究)

**研究商品量价拐点（量最领先、价确认、金额合成），量价驱动申万 L2/L3 行业景气度变化，
财报 TTM 只作后视验证。** 方法论已定稿，不再探索，只按唯一权威
[`METHODOLOGY_FINAL.md`](../../../docs/research/customs_export_forward/METHODOLOGY_FINAL.md) 执行与扩展。

## 常用命令速查 (CLI Cheat Sheet)

```bash
# 月度 SOP 四步（金额面板 → 量价分解 → 商品拐点 → 观察表）一键执行
# 产物 data/analytics/industry/customs_*.parquet + Manifest，YAML 配置见
# config/analytics/customs_prosperity.yaml
uv run python -m stock_cli.customs_prosperity

# 可选参数：
uv run python -m stock_cli.customs_prosperity --config config/analytics/customs_prosperity.yaml
uv run python -m stock_cli.customs_prosperity --skip-product   # 仅金额/量价/观察表
uv run python -m stock_cli.customs_prosperity --skip-forward  # 仅三个面板（观察表依赖前两者产物）

# 三腿 AND 入场前置（L2，无前视窗口）——可选加载，非本 skill 主流程
uv run python .agents/skills/customs-industry-prosperity/scripts/three_leg_entry_and.py --level L2
```

> **公司层交易信号**（受益公司排序 / 三层信号评级 / 择时回测 / 抓机会手册）：
> 见独立 skill [`customs-export-trading`](../customs-export-trading/SKILL.md)
> （命令 1-5 在其 SKILL.md；数据资产共享 `config/data/customs/`，不复制口径）。

## 标准执行 SOP（月度，数据发布后约每月 8 月下旬）

1. **刷海关黄金表**：GACC/Comtrade 当月 raw 更新 → `customs_trade.parquet`
   （见 data-pipeline skill，不在此重复）；
2. **跑月度管线**（命令速查 1）：`uv run python -m stock_cli.customs_prosperity`
   ——内部按固定顺序执行金额 → 量价 → 商品拐点 → 观察表，并校验桥接审计
   （L3 归属一致、组合码跳过）后产出 Manifest；
3. **读观察表判景气**（L2 判景气，L3 看分化）：
   - 四象限：量价齐升 ✓ / 量驱动 / 价驱动 ⚠ / 双弱 ✗；
   - 二阶导：量 yoy 见顶回落 = 顶部前兆；量回落 × 财报仍加速 = 最危险组合；
   - 分位：36 月经验分位定位四阶段（启动/高潮/放缓/萎缩）；
   - 之后与财报 yoy 对照：前瞻窗口（出口正×财报负）与双正（兑现中）；
4. **更新月度观察报告** `docs/research/customs_export_forward/12_forward_watch_<yyyy_mm>.md`
   （四阶段定位表、量价驱动分层、拐点预警卡；格式与必含要素见
   [`references/methodology.md`](references/methodology.md)，样例
   [`12_forward_watch_2026_07.md`](../../../docs/research/customs_export_forward/12_forward_watch_2026_07.md)）；
5. **验证**：Manifest 桥接审计通过（L3 归属一致、组合码已跳过）再落报告；
6. **（可选）公司层交易信号**：行业观察判景气后如需下沉受益公司与择时，
   见独立 skill [`customs-export-trading`](../customs-export-trading/SKILL.md)
   （公司段级观察表 → 三层信号评级 → 分批建仓/景气松动减仓 → 回测）。

## 按需加载的参考（references/，遇相关任务再读）

- [`references/methodology.md`](references/methodology.md)——核心方法论、信号口径（四象限/拐点/一致率）、财报验证与排除清单、量化纪律、月度报告格式、关键实证锚点；
- [`references/data_basics.md`](references/data_basics.md)——数据底座黄金表与面板路径清单、财报/维度黄金表；
- [`references/maintenance.md`](references/maintenance.md)——维护边界（2 文件 / 645 码 / 73 断点）、已知数据质量限制、税则切换解冻流程、品目污染修复防复发、桥接强制规则与审计基线；
- [`references/global_resonance.md`](references/global_resonance.md)——全球资本开支共振辅助（通信设备光模块歧义结构定性，6 信号表 + 命令）；
- 公司层交易信号方法论权威：
  [`docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md`](../../../docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md)
  （2026-09 起定稿）；公司层操作手册（资产/命令/维护）见
  [`customs-export-trading/references/company_linkage.md`](../customs-export-trading/references/company_linkage.md)。
