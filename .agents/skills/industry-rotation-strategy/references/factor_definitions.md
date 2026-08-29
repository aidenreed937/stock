# 申万 31 行业 5 大中观量化因子定义与特征工程规范

---

## 一、 因子面板概览

- **物化文件**: [`data/analytics/industry_structure/latest/industry_factor_panel.parquet`](file:///Users/mac/workspace/personal/finance/stock/data/analytics/industry_structure/latest/industry_factor_panel.parquet)
- **规格**: 86,171 行 $\times$ 2,833 交易日 $\times$ 31 申万一级行业
- **无量纲化标准**: 横截面百分位计算至 $[0.0, 100.0]$，保证 100% 零空值。

---

## 二、 5 大中观因子数学定义与第一性原理

### 1. 景气动量因子 (`ind_momentum`)
- **计算公式**:
  $$\text{ind\_momentum} = 0.35 \times \text{Rank}(\text{Ret}_{20d}) + 0.35 \times \text{Rank}(\text{Ret}_{60d}) + 0.30 \times \text{Rank}(\text{MA\_bias}_{20d})$$
- **学理依据**: Moskowitz & Grinblatt (1999) 行业动量效应。高景气行业呈现 1~3 个月的信息扩散与机构共识推升惯性。

### 2. 供需剪刀差因子 (`ind_scissors`)
- **计算公式**:
  $$\text{scissors\_raw} = \text{ProfitGrowth}_{\text{TTM}} - \text{RevenueGrowth}_{\text{TTM}}$$
  $$\text{ind\_scissors} = \text{Rank}(\text{scissors\_raw})$$
- **学理依据**: 衡量毛利率逆势扩张与产业链真实定价权。在去库存或通胀期，具备剪刀差的行业抗通胀转嫁能力最强。

### 3. 拥挤过热因子 (`ind_crowding`)
- **计算公式**:
  $$\text{TCR} = \frac{\text{行业日成交额}}{\text{全市场总成交额}}$$
  $$\text{ind\_crowding} = \text{Percentile}_{5Y}(\text{TCR})$$
- **学理依据**: 资金博弈极值与防踩踏硬约束。TCR 突破 85%~90% 表明流动性虹吸过度，潜在增量资金枯竭，进入高危筑顶期。

### 4. 估值赔率因子 (`ind_valuation`)
- **计算公式**:
  $$\text{val\_raw} = 100.0 - \frac{1}{2}(\text{PE}_{\text{Pct5Y}} + \text{PB}_{\text{Pct5Y}})$$
  $$\text{ind\_valuation} = \text{Rank}(\text{val\_raw})$$
- **学理依据**: 反转估值分位。数值越高代表处于历史极端低估底，安全边际充足，向下空间有限且向上赔率极大。

### 5. 聪明资金流因子 (`ind_smart_flow`)
- **三维融合公式**:
  $$\text{ind\_smart\_flow} = 0.60 \times \text{Rank}(\text{Flow}_{20d}) + 0.25 \times \text{Rank}(\text{NB\_Chg}_{20d}) + 0.15 \times \text{Rank}(\text{InsiderNet}_{60d})$$
- **自适应降级机制**:
  - 当北向资金与产业资本均具备时：`0.60 * flow + 0.25 * nb + 0.15 * insider`；
  - 当仅有产业资本时：`0.75 * flow + 0.25 * insider`；
  - 当仅有北向资金时：`0.65 * flow + 0.35 * nb`；
  - 均缺失时：`flow`。
- **学理依据**: Kyle (1985) 知情交易学理。融合内资主力机构、外资陆股通与实体上市公司实控人三维资金共振。

---

## 三、 复合中观得分合成

在 [`config/analytics/industry_factors.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/analytics/industry_factors.yaml) 中定义了复合行业打分权重：

$$\text{composite\_score} = 0.30 \times \text{ind\_momentum} + 0.25 \times \text{ind\_scissors} + 0.15 \times (100 - \text{ind\_crowding}) + 0.15 \times \text{ind\_valuation} + 0.15 \times \text{ind\_smart\_flow}$$
