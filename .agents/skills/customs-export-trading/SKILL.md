---
name: customs-export-trading
description: 出口景气受益公司交易信号技能。把海关出口量价拐点下沉到受益公司（暴露度 × 税号段级序列），合成三层信号（出口前瞻 × 资金确认 × 财报真扩张）评级 A强机会/B确认中/C兑现中/D前瞻观察/回避-顶背离，按"分批建仓 → 景气松动分批减仓"规则择时，回测区间胜率与持有收益。交易信号落在公司层；快周期商品（锂/铜/银）维持排除。当用户询问出口受益公司、公司出口景气、受益公司排序、三层信号/评级、顶背离、出口择时回测、分批建仓、信号胜率、公司层交易信号、谁真正受益于出口高景气时使用此技能。数据资产与行业研究 skill（customs-industry-prosperity）共享，不复制口径。
---

# Customs Export Trading (出口景气 → 受益公司交易信号)

**研究链闭环：商品量价拐点（前瞻）→ 暴露度找公司 → 税号段级修正 → 三层信号评级 →
分批建仓/景气松动减仓 → 胜率验证。** 交易信号落在公司层。

方法论延续 [`customs-industry-prosperity`](../customs-industry-prosperity/SKILL.md) 的
METHODOLOGY_FINAL §2（3MMA yoy 四象限/拐点/二阶导）与 §6.5 桥接规则；本 skill 只做
公司下沉与交易化，不重述行业方法。

## 常用命令速查 (CLI Cheat Sheet)

```bash
# 1. 暴露度校准（fina_mainbz 主营构成 → exposure；先 dry-run 看差异）
uv run python scripts/calibrate_company_exposure.py --period 2026-06-30 --apply

# 2-3. 公司观察表 + 三层信号（月度抓机会）一键执行，YAML 见 config/analytics/customs_company.yaml
uv run python -m stock_cli.customs_company
#    可选：--skip-signal 仅公司观察表

# 4. 择时回测（base=纯金额 yoy 择时，默认；--quality-gate 加量拐门，规则见下）
uv run python scripts/backtest_customs_company_signal.py
uv run python scripts/backtest_customs_company_signal.py --quality-gate

# 5. 多产品横向回测（信号普适性检验；--quality-filter/--product-gate 语义见 METHODOLOGY §5.4）
uv run python scripts/backtest_customs_multi.py --detail
uv run python scripts/backtest_customs_multi.py --quality-filter --detail
uv run python scripts/backtest_customs_multi.py --quality-filter --product-gate --detail
```

## 三层信号与评级

> **层次区分（关键）**：**择时（建仓/离场）只看产品出口 yoy，见下节"择时规则"**；
> 三层信号评级是**选池（选哪家公司）**用的，不是择时时点。腿1 出口是前瞻（抓机会），
> 腿3 财报是**后视验证**（出口→订单→收入→利润的传导 + 财报披露周期，滞后是设计使然），
> 财报滞后**不影响产品择时时点**，只影响"选这家还是那家"。
> **财报可用出口量价提前预判**（滞后约 1 季度）：量价齐升 → 毛利扩张（财报改善）；
> 量增价跌 → 毛利被价格压（财报差）；双弱 → 财报恶化。

| 腿 | 信号 | 数据源 | 口径 |
| :-- | :-- | :-- | :-- |
| 腿1 出口前瞻 | 公司段级 3MMA yoy + 驱动 + 拐点 | 公司观察表（命令 2） | 强正（yoy≥30% 且量价齐升/量驱动）> 正 > 弱/负 |
| 腿2 资金确认 | 主力净流入 + 两融杠杆 | moneyflow + margin_detail | 近 20 日主力净流入强度、融资余额变化率（任一 >0 确认） |
| 腿3 财报真扩张 | 营收/净利 yoy | fina_indicator（最新报告期） | 双正=真扩张；营收正净利负=增收不增利 |

**评级操作含义**（命令 3 产出一行一评级）：
- **A强机会**：出口×资金×财报三腿共振 → 重点跟踪、回调即上车窗口；
- **B确认中**：出口+资金已动财报未出 → 前瞻仓位，财报确认后加仓；
- **C兑现中**：出口+财报双正资金未跟 → 警惕已透支（要查价格位置）；
- **D前瞻观察**：仅出口正 → 观察池；
- **回避·顶背离⚠**：出口见顶/回落 + 资金负 + 财报仍正 → 最危险，减仓回避
  （出口基本面仍强但聪明钱与杠杆在撤 = 利好兑现，如 2026-08 中国西电：ultra 段 +111%
  但主力 -5%、融资 -11%）。

## 择时规则（当前口径）

**base（纯金额 yoy 择时，最简基线版）**——`build_weight_plan(vals, quality_gate=False)`，
`backtest_customs_company_signal.py` 默认（不加 `--quality-gate`），只看**金额 yoy**一个量：

| 动作 | 触发条件 |
| :-- | :-- |
| 建仓 | 产品出口**金额** 3MMA yoy 连续 2 月 >0 → 分 3 批建仓（每月 1/3） |
| 减仓 | 满仓后金额 yoy 连续 2 月环比下降（见顶回落）→ 减半（可再加回） |
| 清仓 | 金额 yoy ≤0 |

**base 与 quality 的唯一区别 = 入场要不要量确认**：quality（`--quality-gate`）在 base
基础上，入场还要求驱动类型 ∈ {量价齐升, 量驱动}（量 yoy>0 的量拐门，`entry_ok` 判门）；
两者**离场完全一样**（都只看金额：见顶减半、yoy≤0 清仓）。（均已按 release_date 对齐
消除发布时滞前视。）

**对齐后回测结论（26 号文档，GACC 全池 108 产品）**：
- 量拐门（quality）与无门（base）**打平**（全池均 +7.9pp），量确认是中性门（既不增强
  也不拖累）；base 正超额占比最高（81% vs 79%），是**对齐后最简洁的等价选择**；
- "量只入门、不管出"（量≤0 不清仓，否则 whipsaw）的离场修正仍有效（机制不受前视影响）；
- 竞争力过滤（quality_filter）仍略优（+8.6pp vs +7.9pp），要叠加才用得上。

回测证据（transformer / 多产品 / 全池三版、竞争力过滤、产品门）与后续研究（产品级
细分质量门，缺分类轴）见 `METHODOLOGY_COMPANY_FINAL.md` §5.4/§6/§8 与 26 号文档。

## 抓机会手册（月度执行）

1. **8 月下旬**：刷黄金表 → 跑行业 4 个 build（见 customs-industry-prosperity）→
   命令 2 → 命令 3；
2. **选池**：`rating=="A强机会"` 优先；`B确认中` 前瞻仓；`顶背离⚠` 一律回避；
   入池前查价格位置（1 年/3 年涨幅 + 52 周高低点，长牛/低位/反弹/崩盘四形态分流，
   见 METHODOLOGY §5.1）；
3. **建仓**：产品出口**金额** yoy 连续 2 月 >0 → 分 3 批建仓（月度 1/3，base 基线）；
   量拐门（量 yoy>0）为可选中性层（对齐后 base=quality，不加不减，见上）；
   **每批建仓/加仓前重查资金与价格**：主力流出 + 融资堆积（杠杆堆积，见 §5.5）→
   降权/停止加仓（即便 `f2_state` 仍正）；价格涨高或长牛高位 → 停止加仓；
4. **监控**：段级 yoy 二阶导连续 2 月回落减半、转负清仓；`f2_state` 由正转负 =
   资金背离预警（即便出口仍正）；杠杆堆积 → 减仓/回避；
5. **组合纪律**：多产品分散（transformer/battery/semi/cathode/wind 强信号池），
   单产品不重仓；快周期商品（锂/铜/银）不用本信号；竞争力过滤（--quality-filter，
   同产品内净利率/毛利率相对中位数）作 quality 门之上的同产品选股精化层，不作全池强制门；
6. **后视确认**：财报双正（f3=真扩张）验证真扩张，增收不增利（净利负）降级。

## 按需加载的参考

- **方法论权威（唯一口径）**：
  [`docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md`](../../../docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md)
  ——为什么下沉、股价验证、判读口径、三层信号与评级、择时回测、竞争力分层、排除清单与后续研究；
- **操作手册**：
  [`references/company_linkage.md`](references/company_linkage.md)——资产清单与维护边界、
  命令与产物 schema、抓机会手册、别名表再生成流程（方法论细节指向权威文档，不重复）。
