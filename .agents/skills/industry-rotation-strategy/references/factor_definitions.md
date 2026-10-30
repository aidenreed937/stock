# 申万二级行业量化因子定义与特征工程规范

---

## 一、 因子面板概览

- **物化数据文件**: [`data/curated/mart/industry_l2_panel_daily.parquet`](file:///Users/mac/workspace/personal/finance/stock/data/curated/mart/industry_l2_panel_daily.parquet)
- **覆盖范围**: 申万二级 120+ 细分行业日频面板，重点驱动 16 个全球共振核心方向池
- **数据源底座**: 申万二级日行情事实表 + 理杏仁二级行业财务黄金事实表 (`sw_2021_l2_fs_*`) + 垂直产业数据腿

---

## 二、 申万二级核心量化因子数学定义

### 1. 二级动量与趋势因子 (`return_60d`)
- **计算公式**:
  $$\text{return\_60d} = \left(\frac{P_t}{P_{t-60}} - 1.0\right) \times 100\%$$
- **业务含义**: 衡量二级细分行业在 1 个季度（约 60 交易日）内的绝对动量强弱，对齐产业景气扩散周期。实证表明在中观赛道层面，季度动量比日频或超短频具有更高的信噪比与趋势持续性。

### 2. 二级时序拥挤度因子 (`tcr_percentile`)
- **计算公式**:
  $$\text{TCR}_t = \frac{\text{二级行业日成交额}_t}{\text{全市场总成交额}_t}$$
  $$\text{tcr\_percentile}_t = \text{Percentile}_{5\text{Y}}(\text{TCR}_t)$$
- **学理与实证依据**:
  采用 5 年（约 1,250 交易日）滚动历史分位数，消除大盘整体成交量膨胀的体量通胀（无量纲化）。
  - **实证结论**: 拥挤度处于 $\ge 85\%$ 时，风险显著放大；以此作为一票否决门，在样本外将策略最大回撤从 **42.11% 直接压缩至 25.80%**。

### 3. 二级估值分位因子 (`pe_ttm_ew_percentile_5y`)
- **计算公式**:
  $$\text{pe5y} = \text{Percentile}_{5\text{Y}}(\text{PE\_TTM}_{\text{等权中位数}})$$
- **业务含义**: 衡量二级行业当前相对于自身过去 5 年的估值水平。策略将 `pe5y > 90.0%` 的极高估值泡沫标的剔除，避免在高位估值透支时接盘。

### 4. 财报滞后验证：量价齐升供需象限 (QLQ)
- **数据字段**:
  - 营收增速: `revenue_growth_ttm`（取自 `toi.ttm_y2y`）
  - 净利增速: `profit_growth_ttm`（取自 `np.ttm_y2y`）
- **象限分类**:
  - **量价齐升 (QLQ, 需求驱动)**: $\text{revenue} > 0 \land \text{profit} > 0$（供需最健康，享有策略动量加成）；
  - **供给收缩**: $\text{revenue} \le 0 \land \text{profit} > 0$（仅靠控本减产，非真实扩张）；
  - **增收不增利**: $\text{revenue} > 0 \land \text{profit} \le 0$（恶性价格战，毛利坍塌）；
  - **双负衰退**: $\text{revenue} \le 0 \land \text{profit} \le 0$（坚决剔除）。

### 5. 细分产业供需剪刀差与库存 DOI (产业数据腿)
针对已接入垂直产业数据的二级赛道（如半导体、化工）：
- **需求先行分 (`demand_score`)**: TSMC 订单、SIA 全球半导体销售额、海关出口数据；
- **供给扩张分 (`supply_score`)**: SEAJ 设备出货、化工产能装置开工率；
- **供需剪刀差 (`scissors_score`)**:
  $$\text{scissors\_score} = \text{demand\_score} - \text{supply\_score}$$
- **实证增益**: 在半导体行业叠加供需剪刀差与库存 DOI 防守后，样本外 Sharpe 从 0.45 飙升至 **1.19**，最大回撤压降至 **22.6%**。
