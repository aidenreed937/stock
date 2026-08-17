# 常用量化金融核心指标权威定义字典 (Common Financial Indicators)

本字典汇编量化投研中高频指标的**标准数学公式、分母选型、经济学含义与权威依据**，严禁凭空臆造。

---

## 1. 估值与资产定价类 (Valuation & Asset Pricing)

### ① 股债风险溢价 / 股债利差 (Equity Risk Premium, ERP)
* **权威依据**：美联储模型 (Fed Model) & 中金/华泰金工标准定义。
* **数学公式**：
  $$\text{ERP} = \left(\frac{1}{\text{PE}_{\text{TTM}}} \times 100\%\right) - Y_{10\text{Y}}$$
  * $\frac{1}{\text{PE}_{\text{TTM}}}$：股票资产的盈利收益率（Earnings Yield %，可取指数等权或加权 PE）；
  * $Y_{10\text{Y}}$：中国 10 年期中债官方到期收益率（`tcm_y10`，%）。
* **经济含义**：衡量股票资产相比于无风险国债的超额风险补偿。ERP 处于 10 年 90% 分位以上代表权益资产具备极高性价比。

### ② 巴菲特比值 (Buffett Indicator)
* **权威依据**：沃伦·巴菲特（Warren Buffett）1999/2001 年论述，衡量股票总市值与经济总产出比值。
* **数学公式**：
  $$\text{Buffett Ratio} = \frac{\sum \text{A股全市场总市值}}{\text{中国滚动 4 季度 TTM GDP}} \times 100\%$$
* **经济含义**：
  * $< 65\%$：显著低估区间；
  * $70\% \sim 80\%$：合理中枢平衡区；
  * $> 90\%$：资产价格过度膨胀/高估预警。

---

## 2. 交易微观结构与流动性类 (Market Microstructure)

### ① 大盘拥挤度 (A-Shares Market Congestion)
* **权威依据**：券商微观结构恶化模型（乐咕乐咕/华创证券）。
* **数学公式**：
  $$\text{Congestion} = \frac{\sum_{i=1}^{\lceil 0.05 \times N \rceil} \text{Amount}_{(i)}}{\sum_{i=1}^{N} \text{Amount}_i} \times 100\%$$
  * 分子：全市场按单日成交额降序排列前 5% 的个股成交额之和；
  * 分母：全市场所有 A 股当日成交总额。
* **阈值基准**：
  * $< 40\%$：微观结构健康分散；
  * $40\% \sim 50\%$：局部过热；
  * $> 50\%$：微观结构恶化预警（极易诱发大小盘剧烈切换或牛转熊）。

### ② 流量杠杆率 vs 存量杠杆率 (Margin Trading Leverage)
* **流量杠杆率 (Trading Leverage %)**：
  $$\text{Leverage}_{\text{Flow}} = \frac{\sum \text{rzmre}}{\sum \text{amount}} \times 100\%$$
  * 衡量每日全市场总成交中融资加杠杆买入的活跃度占比。
* **存量杠杆率 (Stock Penetration %)**：
  $$\text{Leverage}_{\text{Stock}} = \frac{\sum \text{rzrqye}}{\sum \text{circ\_mv}} \times 100\%$$
  * 衡量两融总余额占全市场实际可交易流通市值的渗透率。

### ③ 机构主力净流入额 (Main Force Net Inflow)
* **权威依据**：Level-2 单笔订单切片微观资金流标准（上交所/深交所/TuShare）。
* **数学公式**：
  $$\text{Net Main Inflow} = (\text{buy\_elg\_amount} + \text{buy\_lg\_amount}) - (\text{sell\_elg\_amount} + \text{sell\_lg\_amount})$$
  * **超大单 (`elg`)**：单笔成交金额 $> 100$ 万元；
  * **大单 (`lg`)**：单笔成交金额 $20 \sim 100$ 万元。
* **无量纲化**：通常除以个股当日总成交额转换为 **主力净买入占比 (Net Inflow Ratio %)**。

---

## 3. 波动与技术类 (Volatility & Technicals)

### ① 真实波幅与 ATR (Average True Range)
* **权威依据**：J. Welles Wilder (1978)。
* **数学公式**：
  $$\text{TR}_t = \max\left(\text{high}_t - \text{low}_t, |\text{high}_t - \text{close}_{t-1}|, |\text{low}_t - \text{close}_{t-1}|\right)$$
  $$\text{ATR}_{t}(N) = \frac{(N-1)\text{ATR}_{t-1} + \text{TR}_t}{N}$$
* **无量纲化（相对 ATR %）**：$\text{NATR} = \frac{\text{ATR}_t}{\text{close}_t} \times 100\%$。

---

## 4. 市场宽度与景气动量类 (Market Breadth & Momentum)

### ① 市场均线站上比例 (Market Breadth MA Ratio)
* **权威依据**：Ned Davis 市场宽度模型。
* **数学公式**：
  $$\text{Breadth}_{\text{MA}(K)} = \frac{\sum_{i=1}^{N} \mathbb{I}\left(\text{close}_{i, t} > \text{MA}_{i, t}(K)\right)}{N} \times 100\%$$
  * $K \in \{20, 60, 250\}$ 对应短期、中期、长期均线；
  * $N$：全市场有效交易股票总数。
* **含义**：
  * $> 80\%$：全市场普涨过热，需防范脉冲式回踩；
  * $< 20\%$：全市场普跌冰点，处于超跌企稳区间。

### ② 分析师一致预期盈利上修比例 (Earnings Revision Ratio)
* **权威依据**：摩根士丹利 (Morgan Stanley) / 华泰金工卖方预期模型。
* **数学公式**：
  $$\text{Revision Ratio} = \frac{N_{\text{up}} - N_{\text{down}}}{N_{\text{total}}} \times 100\%$$
  * $N_{\text{up}}$：过去 30/90 天卖方机构调高净利润预测的次数；
  * $N_{\text{down}}$：过去 30/90 天卖方机构调低净利润预测的次数；
  * $N_{\text{total}}$：该行业/个股同期的总预测覆盖次数。
* **含义**：衡量行业景气度的前瞻边际变化，是 PB-ROE 四象限分类的核心 Y 轴因子。
