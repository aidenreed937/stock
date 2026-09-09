---
name: customs-export-trading
description: 出口景气受益公司交易信号技能。把海关出口量价拐点下沉到受益公司（暴露度 × 税号段级序列），合成三层信号（出口前瞻 × 资金确认 × 财报真扩张）评级 A强机会/B确认中/C兑现中/D前瞻观察/回避-顶背离，按"分批建仓 → 景气松动分批减仓"规则择时，回测区间胜率与持有收益。行业层（L2/L3）区分度不足，交易信号落在公司层；产业趋势型产品普适（GACC 口径 108 产品 80% 正超额，样本缩短），快周期商品（锂/铜/银）维持排除待验证。当用户询问出口受益公司、公司出口景气、受益公司排序、三层信号/评级、顶背离、出口择时回测、分批建仓、信号胜率、公司层交易信号、谁真正受益于出口高景气时使用此技能。数据资产与行业研究 skill（customs-industry-prosperity）共享，不复制口径。
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

# 2-3. 公司观察表 + 三层信号（月度抓机会）一键执行
#    产物 data/analytics/industry/customs_company_*.parquet/csv + Manifest，
#    YAML 配置见 config/analytics/customs_company.yaml
uv run python -m stock_cli.customs_company
#    可选：--skip-signal 仅公司观察表

# 4. 择时回测（分批建仓 3 批 / 见顶回落减半 / yoy≤0 清仓 → 胜率与持有收益）
uv run python scripts/backtest_customs_company_signal.py --quality-gate

# 5. 多产品横向回测（信号普适性检验：10 产品 × 基础/质量两版；
#    加 --quality-filter 追加竞争力过滤版：同产品内剔除亏损型/低竞争力，§5.4）
#    --product-gate 追加产品级低毛利排除（静态组合下行保护用，择时默认关）
uv run python scripts/backtest_customs_multi.py --detail
uv run python scripts/backtest_customs_multi.py --quality-filter --detail
uv run python scripts/backtest_customs_multi.py --quality-filter --product-gate --detail
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
下降（见顶回落）→ 减半；yoy≤0 → 清仓。入场加"量价同正（量拐）或加速（二阶导）"
质量确认优于纯金额转正（正交验证见 19 号文档：胜率 59%→63~70%、超额 +29.6→+33~36pp）；
`--quality-gate` 的量为"只入门、不管出"（量≤0 不清仓，见 21 号文档，否则 whipsaw）；
离场规则（见顶减半 + 可再加回）也已回测验证最优（见 20 号文档，直接清仓/锁仓均更差）。

**transformer 回测（GACC 口径 2019-2026，6 家等权 vs 沪深300）**：

| 版本 | 轮次 | 胜率 | 跑赢基准 | 平均轮收益 | 平均超额 | 持有 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 基础版 | 4 | 50% | 50% | +30.7% | +32.4pp | 12.8 月 |
| 质量过滤版 | 3 | **67%** | **67%** | +51.9% | +45.1pp | 14.7 月 |

**多产品普适性**（命令 5，10 产品 × 两版）：**10/10 平均超额为正**（GACC 口径，
样本缩短后快周期商品转正但轮次少）。强信号：battery（+49pp 全胜）、
semiconductor_equipment（+154pp 全胜）、cathode_material（+23pp 全胜）、solar_cell
（盈亏比 10-31）；transformer 质量版短轮弱化（超额≈0），基础版靠 2022-08 大轮撑
均值；**快周期商品（铜/锂/银）维持排除**——GACC 口径轮次仅 2-7 个、表现分化
（铜仍弱、锂/银转正但样本不足），月度确认滞后于商品脉冲的机制风险仍在，观察
2-3 个新景气轮后再评估（详见 references/company_linkage.md §4c）。

**全产品池普适性**（命令 5 `--quality-filter`，108 产品 × 三版，见
`17_fullpool_universal_validation.md`）：base 版 **80% 产品平均超额为正**（86/108）、
成长组有效池 81%（+28.9pp）——信号本身可扩展到全池；竞争力过滤（§5.4 修订：同产品内
净利率×毛利率均低于同产品中位数剔除）在 quality 门上是**弱正向选股精化**（平均 +3.2pp、
中位 ≈0、51% 产品更优），且不再整池误杀（清空仅 1 产品 coke，旧绝对口径清空 16 产品）。
故竞争力过滤定位为 **quality 门之上的"同产品选股精化层"（本质下行保护）**，不作全池
强制前置。产品级低毛利排除（`--product-gate`，中位毛利率<15% 且 ROE<10%）只用于静态
组合下行保护（强信号池 21 家累计 +550%，见 16 号文档），择时回测默认关闭——择时已由
yoy≤0 清仓做下行保护，产品级排除会误伤低毛利产品的上行赢家。

## 抓机会手册（月度执行）

1. **8 月下旬**：刷黄金表 → 跑行业 4 个 build（见 customs-industry-prosperity）→
   命令 2 → 命令 3；
2. **选池**：`rating=="A强机会"` 优先；`B确认中` 前瞻仓；`顶背离⚠` 一律回避；
3. **建仓**：产品出口 yoy 连续 2 月 >0 且量价齐升/量驱动 → 分 3 批建仓（月度 1/3）；
4. **监控**：段级 yoy 二阶导连续 2 月回落减半、转负清仓；`f2_state` 由正转负 =
   资金背离预警（即便出口仍正）；
5. **组合纪律**：多产品分散（transformer/battery/semi/cathode/wind 强信号池），
   单产品不重仓；快周期商品（锂/铜/银）不用本信号；竞争力过滤（--quality-filter，
   同产品内净利率/毛利率相对中位数）作 quality 门之上的同产品选股精化层，不作全池强制门；
6. **后视确认**：财报双正（f3=真扩张）验证真扩张，增收不增利（净利负）降级。

## 按需加载的参考

- **方法论权威（唯一口径）**：
  [`docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md`](../../../docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md)
  ——为什么下沉、股价验证（2020-2026 受益公司独立大盘）、判读口径、三层信号与评级、
  择时回测两版与多产品普适性表、排除清单；
- **操作手册**：
  [`references/company_linkage.md`](references/company_linkage.md)——资产清单与维护边界、
  命令与产物 schema、抓机会手册、别名表再生成流程（方法论细节指向权威文档，不重复）。
