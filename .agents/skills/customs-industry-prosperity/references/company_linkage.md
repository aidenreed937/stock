# 出口商品 → 公司景气度下沉（Company Linkage）

> 2026-09 新增。行业层（L2/L3）区分度不足时，把商品量价拐点下沉到受益公司：
> **商品拐点（前瞻）→ 暴露度找公司 → 税号段级序列修正 → 公司出口景气排序 → 财报后视验证**。
> 口径延续 METHODOLOGY_FINAL §2（3MMA yoy 四象限/拐点/二阶导）与 §6.5 桥接规则。

## 1. 为什么下沉（实证锚点）

- transformer 产品 2026-07 产品级 3MMA yoy **+34.2%**，内部税号段分化 **+13%~+566%**；
- 段级落公司后：特变电工（ultra 段）**+111.5%**（产品级严重低估 3 倍）、明阳电气（small 段）
  **+19.2%**（产品级高估近 1 倍）——行业/产品层看不到的公司间差异，段级序列可见；
- 段驱动也分化：ultra 段量价齐升（量 +81%），small/mid 段价驱动——受益质量不同。

## 1b. 股价验证（2026-09 实证：出口景气 → 受益公司独立大盘）

- **区间收益（2020-01 ~ 2026-09，前复权）**：思源 +983%、华明 +393%、特变 +332%、
  中国西电 +262%、金盘 +197%（2021-03 上市）；沪深300 仅 +12%——**5/6 家超额
  +164~+864pp**；明阳电气 +10%（2023-06 上市，几乎无超额）；
- **超额启动时点与出口景气对照**（vs 沪深300，2020 起点）：
  2021-12 思源 +415pp / 特变 +84pp / 华明 −34pp；2023-12（出口 3MMA yoy +104%
  量价双升）起全面爆发：特变 +93pp / 思源 +445pp / 金盘 +134pp / 华明 +120pp；
  2025-12 特变 +219pp / 思源 +1683pp / 金盘 +435pp / 华明 +303pp / 西电 +82pp；
- **公司分化与段级景气一一对应**：中国西电 2024 年超额转正（−4pp → +65pp →
  +200pp@2026-08）对应 ultra 段 2026-07 +111.5% 量价齐升（2024 特高压招标大年）；
  明阳电气（绑 small/mid 弱段，段 yoy 仅 +13~19% 价驱动）**无超额**——反向印证
  弱段公司不独立大盘；
- 口径注意：思源 2021 已 +415pp（电网板块 beta），出口量价双升（2023 起）后
  超额持续放大——出口景气是"确认/放大"而非唯一驱动，组合判读需结合板块行情。

## 2. 资产清单（config/data/customs/）

| 文件 | 内容 | 维护方 |
| :-- | :-- | :-- |
| `company_exposure_map.csv` | 109 产品 → 393 公司暴露度（0-1），`taxline_segment` 列绑定税号段（空=整产品） | 大模型/人工，fina_mainbz 校准 |
| `taxline_segments.csv` | 高分化产品税号段定义（14 段/5 产品：transformer 4 段、semiconductor_equipment 3 段、lithium_chemicals 3 段、silver 2 段、cathode_material 2 段） | 人工，需审计后新增 |
| `bz_item_alias_map.csv` | LLM 语义别名表：fina_mainbz `bz_item` → product_key（1395 条，2026-06-30 期） | LLM 批量生成 + 人工修订 |
| `hs_codes_catalog.csv` | 产品键 → hs 码全集（8 位优先，纯 6 位产品取其 8 位子码） | 既有 catalog |

加载器：`src/stock_data/fetcher/industry/customs/parsers/company_exposure.py`
（`load_company_exposure_map` / `load_taxline_segments` / `TaxlineSegmentMap.hs_codes_for`，
公司段引用非法会报错）。

## 3. 数据流与命令

```bash
# 暴露度校准（fina_mainbz type=P 主营构成 → exposure；dry-run 先看差异）
uv run python scripts/calibrate_company_exposure.py --period 2026-06-30 --apply

# 公司级出口景气观察表（段级聚合 + 3MMA yoy + 驱动/拐点 + 产品级对照）
uv run python scripts/build_customs_company_exposure.py

# 公司三层信号（出口前瞻 × 资金确认 × 财报真扩张）→ A/B/C/D/回避 评级
uv run python scripts/build_customs_company_signal.py

# 择时回测（分批建仓 / 景气松动分批减仓 → 胜率/持有收益）
uv run python scripts/backtest_customs_company_signal.py --quality-gate

# 多产品横向回测（信号普适性检验，10 产品 × 基础/质量两版）
uv run python scripts/backtest_customs_multi.py --detail
```

`build_customs_company_exposure.py` 输出：
- `data/analytics/industry/customs_company_exposure.parquet`——全序列（key × 月，3MMA yoy/驱动/拐点）；
- `data/analytics/industry/customs_company_exposure_latest.csv`——最新月公司快照：
  `company_name / stock_code / product_key / exposure / bind_segment / segment_name /
  value_yoy_3mma / volume_yoy_3mma / price_yoy_3mma / 驱动类型 / 拐点 / 二阶导 /
  product_value_yoy / segment_minus_product`。

口径要点：
- 聚合仅用黄金表 `trade_direction=export` + `hs_level=8` 行；
- 数量仅段内已知单位唯一时加总（否则置空，驱动不判）；金额全量；
- 补全月序（2016-01~末月）重算 3MMA yoy，与 `build_customs_product_volume_price._derive` 同口径；
- 公司多段绑定 → 每 (company, product, segment) 一行；空段 → 产品级序列（对比基线）。

## 4. 判读口径（公司受益区分度）

1. **段级 yoy vs 产品级 yoy**（`segment_minus_product`）：>50pp 高估/低估，绑定该段的公司才是真实受益；
2. **驱动质量**：量价齐升 > 量驱动 > 价驱动 ⚠ > 双弱 ✗（ultra 段量价齐升 = 高景气质量）；
3. **拐点/二阶导**：见顶拐点 + 量增速回落 = 顶部前兆，公司层面同判；
4. **组合视角**：一家公司绑定多产品（如特变电工 transformer+polysilicon）时逐产品看，避免单一产品误判；
5. **财报验证**：用 fina_mainbz 主营占比（`calibrate_company_exposure.py` 产物）做暴露度确认，公司财报 yoy 仅后视。

## 4b. 三层信号与择时交易（2026-09 新增）

**产品**：`build_customs_company_signal.py` → `customs_company_signal_latest.csv`（402 行/341 家），
把公司观察表与三腿信号合并：`f1_state`（出口段级）/ `f2_state`（资金）/ `f3_state`（财报）+
`rating`（A强机会/B确认中/C兑现中/D前瞻观察/观望/回避）+ `risk_flag`（顶背离⚠）。

| 腿 | 信号 | 数据源 | 口径 |
| :-- | :-- | :-- | :-- |
| 腿1 出口前瞻 | 公司段级 3MMA yoy + 驱动 + 拐点 | 公司观察表 | 强正（yoy≥30% 且量价齐升/量驱动）> 正 > 弱/负 |
| 腿2 资金确认 | 主力净流入 + 两融杠杆 | moneyflow + margin_detail | 近 20 日主力净流入强度、融资余额变化率（任一 >0 确认） |
| 腿3 财报真扩张 | 营收/净利 yoy | fina_indicator（最新报告期） | 双正=真扩张；营收正净利负=增收不增利 |

评级操作含义：**A** 三腿共振（重点跟踪）/ **B** 出口+资金已动财报未出（前瞻仓位）/
**C** 出口+财报双正资金未跟（警惕透支）/ **D** 仅出口正（观察池）/
**回避·顶背离⚠**（出口见顶/回落 + 资金负 + 财报仍正 = 最危险，减仓回避）。

## 4c. 回测验证：分批建仓 / 景气松动分批减仓（2026-09 实证）

**交易规则**（`backtest_customs_company_signal.py`，无未来函数）：
- 建仓：产品出口 3MMA yoy 连续 2 月 >0（可加 `--quality-gate` 要求量价齐升/量驱动）→
  分 3 批建仓（每月 1/3）；
- 减仓：满仓后 yoy 连续 2 月环比下降（见顶回落）→ 减半；yoy≤0 → 清仓。

**transformer 回测（2016-2026，6 家受益公司等权 vs 沪深300）**：

| 版本 | 轮次 | 胜率 | 跑赢基准 | 平均轮收益 | 平均超额 | 持有 |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 基础版 | 6 | 33% | 50% | +14.0% | +21.1pp | 12.5 月 |
| 质量过滤版 | 7 | **57%** | **86%** | +4.6% | +7.5pp | 5.9 月 |

基础版 2022-08 大轮 +124.6%（超额 +125pp，42 个月）撑高均值；质量版过滤 2017/2022
价驱动伪景气轮（2017-2018 亏损 -30% 轮消失），胜率显著提升。

**多产品普适性**（`backtest_customs_multi.py`，10 产品 × 两版，2016-2026）：

| 产品 | 最佳版 | 胜率 | 平均超额 | 结论 |
| :-- | :-- | :-- | :-- | :-- |
| battery / semiconductor_equipment | base | 100% | +137~176pp | 长景气轮全胜（样本少） |
| cathode_material | base | 100% | +19.9pp | 强信号 |
| transformer / aluminum_unwrought | quality | 57~60% | +6~8pp | 质量过滤有效 |
| wind_turbine / solar_cell | base | 40~62% | +13~35pp | 趋势钱（solar 盈亏比 8.7） |
| copper / lithium / silver | — | 30~75% | +0~7pp | **信号不适用**：快周期商品节奏不匹配 / 公司池错配 |

结论：**9/10 产品平均超额为正**（仅 silver≈0）——出口景气信号在产业趋势型产品上普适；
质量过滤提升 7/10 产品胜率；铜/锂/银等快周期商品不可用（月度确认滞后于商品脉冲）。

## 4d. 抓机会手册（月度执行）

1. **8 月下旬**：刷黄金表 → 跑 4 个 build（skill SOP 1-4）→ `build_customs_company_exposure.py`
   → `build_customs_company_signal.py`；
2. **选池**：`rating=="A强机会"`（三腿共振）优先；`B确认中` 做前瞻仓；
   `risk_flag=="顶背离⚠"` 一律回避（出口仍强但资金撤 = 利好兑现）；
3. **建仓**：产品出口 yoy 连续 2 月 >0 且量价齐升/量驱动 → 分 3 批建仓（月度 1/3）；
4. **监控**：月度看段级 yoy 二阶导——连续 2 月回落减半、转负清仓；
   同时盯 `f2_state`：主力/融资由正转负 = 资金背离预警（即便出口仍正）；
5. **组合纪律**：多产品分散（transformer/battery/semi/cathode/wind 信号强的池子），
   单产品不重仓；快周期商品（锂/铜/银）不用本信号；
6. **后视确认**：财报双正（f3=真扩张）验证"真扩张"，增收不增利（净利负）降级。

## 5. 别名表再生成流程（fina_mainbz 新报告期）

1. 从 `data/curated/tushare/market=CN/fina_mainbz`（type=P）提取每公司最新期 `bz_item` 去重清单；
2. LLM 批量归一化到 `hs_codes_catalog.csv` 的 product_key（alias/ambiguous/no_match/generic 四类，
   "电气设备系列"等语境模糊项硬标注产品并注明公司）；
3. 合并校验：product_key 必须为 catalog 合法键、条数全覆盖、冲突人工裁决；
4. 落 `bz_item_alias_map.csv`（显式可人工修订）→ 重跑 calibrate。
   临时脚本与 chunk 在 `scratch/`（gitignore），正式产物只提交 CSV。

## 6. 维护边界

- 段定义新增需人工审计（HS 码互斥、单位一致），不经 LLM 自动生成；
- exposure 优先 verified（fina_mainbz 校准），estimated 为人工估计需复核；
- `bz_item_alias_map.csv` 与 `company_exposure_map.csv` 由本链路唯一消费方
  （calibrate + company builder）引用，改动后重跑两个脚本验证；
- 公司段引用非法（段未定义）时 loader 直接报错，防止手误静默失效。
