---
name: customs-export-trading
description: 出口景气受益公司交易信号技能。把海关出口量价拐点下沉到受益公司（暴露度 × 税号段级序列），合成三层信号（出口前瞻 × 资金确认 × 财报真扩张）评级 A强机会/B确认中/C兑现中/D前瞻观察/回避-顶背离，按"分批建仓 → 景气松动分批减仓"规则择时，回测区间胜率与持有收益。行业层（L2/L3）区分度不足，交易信号落在公司层；产业趋势型产品普适（10 产品 9/10 平均超额为正），快周期商品（锂/铜/银）不可用。当用户询问出口受益公司、公司出口景气、受益公司排序、三层信号/评级、顶背离、出口择时回测、分批建仓、信号胜率、公司层交易信号、谁真正受益于出口高景气时使用此技能。数据资产与行业研究 skill（customs-industry-prosperity）共享，不复制口径。
---

# Customs Export Trading (出口景气 → 受益公司交易信号)

**研究链闭环：商品量价拐点（前瞻）→ 暴露度找公司 → 税号段级修正 → 三层信号评级 →
分批建仓/景气松动减仓 → 胜率验证。** 行业层（L2/L3）区分度不足（合并掩盖公司差异，
如 transformer 产品 +34% 内部 ultra 段 +111%），**交易信号落在公司层**。

方法论延续 [`customs-industry-prosperity`](../customs-industry-prosperity/SKILL.md) 的
METHODOLOGY_FINAL §2（3MMA yoy 四象限/拐点/二阶导）与 §6.5 桥接规则；本 skill 只做
公司下沉与交易化，不重述行业方法。

## 常用命令速查 (CLI Cheat Sheet)

```bash
# 1. 暴露度校准（fina_mainbz 主营构成 → exposure；先 dry-run 看差异）
uv run python scripts/calibrate_company_exposure.py --period 2026-06-30 --apply

# 2. 公司级出口景气观察表（段级聚合 + 3MMA yoy + 驱动/拐点 + 产品级对照）
uv run python scripts/build_customs_company_exposure.py

# 3. 公司三层信号（出口前瞻 × 资金确认 × 财报真扩张 → A/B/C/D/回避 评级）
uv run python scripts/build_customs_company_signal.py

# 4. 择时回测（分批建仓 3 批 / 见顶回落减半 / yoy≤0 清仓 → 胜率与持有收益）
uv run python scripts/backtest_customs_company_signal.py --quality-gate

# 5. 多产品横向回测（信号普适性检验：10 产品 × 基础/质量两版）
uv run python scripts/backtest_customs_multi.py --detail
```

## 数据资产（共享，不复制）

全部存在于 `config/data/customs/` 与 `src/stock_data/fetcher/industry/customs/parsers/company_exposure.py`：
`company_exposure_map.csv`（109 产品 → 393 公司暴露度 + taxline_segment 段绑定）、
`taxline_segments.csv`（14 段/5 产品）、`bz_item_alias_map.csv`（LLM 语义别名表 1395 条）、
`hs_codes_catalog.csv`。加载器唯一：`load_company_exposure_map` / `load_taxline_segments`
（公司段引用非法即报错）。

## 三层信号与评级

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

## 择时规则与回测

**交易规则**（命令 4，无未来函数）：产品出口 3MMA yoy 连续 2 月 >0 → 分 3 批建仓
（每月 1/3，可加 `--quality-gate` 要求量价齐升/量驱动）；满仓后 yoy 连续 2 月环比
下降（见顶回落）→ 减半；yoy≤0 → 清仓。

**transformer 回测（2016-2026，6 家等权 vs 沪深300）**：

| 版本 | 轮次 | 胜率 | 跑赢基准 | 平均轮收益 | 平均超额 | 持有 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 基础版 | 6 | 33% | 50% | +14.0% | +21.1pp | 12.5 月 |
| 质量过滤版 | 7 | **57%** | **86%** | +4.6% | +7.5pp | 5.9 月 |

**多产品普适性**（命令 5，10 产品 × 两版）：**9/10 平均超额为正**（仅 silver≈0）。
强信号：battery（+146%/+137pp 全胜）、semiconductor_equipment（+138%/+130pp）、
cathode_material（+15.7% 全胜）、transformer、aluminum_unwrought；wind_turbine/solar_cell
趋势钱（solar 盈亏比 8.7）；**快周期商品（铜/锂/银）不可用**——月度确认滞后于商品
脉冲，勿用本信号（详见 references/company_linkage.md §4c）。

## 抓机会手册（月度执行）

1. **8 月下旬**：刷黄金表 → 跑行业 4 个 build（见 customs-industry-prosperity）→
   命令 2 → 命令 3；
2. **选池**：`rating=="A强机会"` 优先；`B确认中` 前瞻仓；`顶背离⚠` 一律回避；
3. **建仓**：产品出口 yoy 连续 2 月 >0 且量价齐升/量驱动 → 分 3 批建仓（月度 1/3）；
4. **监控**：段级 yoy 二阶导连续 2 月回落减半、转负清仓；`f2_state` 由正转负 =
   资金背离预警（即便出口仍正）；
5. **组合纪律**：多产品分散（transformer/battery/semi/cathode/wind 强信号池），
   单产品不重仓；快周期商品（锂/铜/银）不用本信号；
6. **后视确认**：财报双正（f3=真扩张）验证真扩张，增收不增利（净利负）降级。

## 按需加载的参考

- **方法论权威（唯一口径）**：
  [`docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md`](../../../docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md)
  ——为什么下沉、股价验证（2020-2026 受益公司独立大盘）、判读口径、三层信号与评级、
  择时回测两版与多产品普适性表、排除清单；
- **操作手册**：
  [`references/company_linkage.md`](references/company_linkage.md)——资产清单与维护边界、
  命令与产物 schema、抓机会手册、别名表再生成流程（方法论细节指向权威文档，不重复）。
