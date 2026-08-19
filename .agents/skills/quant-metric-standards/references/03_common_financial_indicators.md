# 常用量化金融核心指标权威定义字典 (Common Financial Indicators)

本字典严格按照 **【宏观总量与大类资产类】**、**【中观行业与风格赛道类】**、**【微观个股与量价资金类】** 三层架构，汇编量化投研中高频核心指标的标准数学公式、分母选型、计算注意事项与权威依据，严禁凭空臆造。

---

## 1. 宏观总量与大类资产类 (Macro & Asset Allocation)

### ① 股债风险溢价 / 股债利差 (Equity Risk Premium, ERP)
* **权威依据**：美联储模型 (Fed Model) & 券商金工（中金/华泰）标准定义。
* **数学公式**：
  $$\text{ERP} = \left(\frac{1}{\text{PE}_{\text{TTM}}} \times 100\%\right) - Y_{10\text{Y}}$$
  * $\frac{1}{\text{PE}_{\text{TTM}}}$：股票资产的盈利收益率（Earnings Yield %）；
    * **计算关键约束**：指数或全市场 PE 必须采用**总市值加权 PE（即 $\frac{\sum \text{Total MV}}{\sum \text{Net Profit}}$）**或**盈利收益率中位数**，**严禁采用简单算术平均 PE**（避免成分股亏损或小市值极端负值扭曲大盘中枢）。
  * $Y_{10\text{Y}}$：中国 10 年期中债官方到期收益率（`tcm_y10`，小数制；如 2.5% 记为 0.025）。
* **经济含义**：衡量股票大盘资产相较无风险国债的超额风险补偿。ERP 处于 10 年 90% 分位以上代表大盘具备极高配置性价比。

### ② 巴菲特比值 (Buffett Indicator)
* **权威依据**：沃伦·巴菲特（Warren Buffett）1999/2001 年论述，衡量股票总市值与经济总产出比值。
* **数学公式**：
  $$\text{Buffett Ratio} = \frac{\sum \text{A股全市场总市值}}{\text{中国滚动 4 季度 TTM GDP}} \times 100\%$$
* **经济含义**：
  * $< 65\%$：宏观估值偏低区间；
  * $70\% \sim 80\%$：长期中枢平衡区；
  * $> 90\%$：资产价格相对实体经济总产出过热预警。

---

## 2. 中观行业与风格赛道类 (Meso & Sector Rotation)

### ① 申万行业 PB-ROE 与预期回报
* **权威依据**：Gordon 股利增长模型。
* **核心指标**：行业 PB 5Y 滚动历史分位数（X 轴） vs 行业 ROE / 预期上修比例（Y 轴）。
* **含义**：划分高景气低估值（黄金配置区）、高景气高估值（赛道拥挤区）、低景气低估值（周期筑底区）与低景气高估值（价值陷阱区）。

### ② 分析师一致预期盈利上修比例 (Earnings Revision Ratio)
* **权威依据**：摩根士丹利 (Morgan Stanley) / 华泰金工卖方预期模型。
* **数学公式**：
  $$\text{Revision Ratio} = \frac{N_{\text{up}} - N_{\text{down}}}{N_{\text{total}}} \times 100\%$$
  * $N_{\text{up}}$：过去 30/90 天卖方机构调高该行业净利润预测的次数；
  * $N_{\text{down}}$：过去 30/90 天卖方机构调低该行业净利润预测的次数；
  * $N_{\text{total}}$：该行业同期全部可比预测覆盖次数，包含预测不变项（需满足 $N_{\text{total}} \ge 5$ 以免小样本失真）。
* **含义**：衡量中观行业景气度的前瞻边际变化。

本项目市场温度使用同一 `symbol + org_name + quarter` 的窗口内最新预测与窗口前最新预测进行配对；不变项保留在分母。原始净修正率为 `-100%~100%`，市场温度再用 `50 + Revision Ratio / 2` 映射为 `0~100`。

### ③ 全市场均线站上比例 / 市场宽度 (Market Breadth MA Ratio)
* **权威依据**：Ned Davis 市场宽度模型。
* **数学公式**：
  $$\text{Breadth}_{\text{MA}(K)} = \frac{\sum_{i=1}^{N} \mathbb{I}\left(\text{close}_{i, t} > \text{MA}_{i, t}(K)\right)}{N} \times 100\%$$
  * $K \in \{20, 60, 250\}$ 对应短期、中期、长期均线；$N$ 为全市场有效交易股票总数。
* **含义**：$>80\%$ 提示全市场多数个股处于上升趋势（短期过热），$<20\%$ 提示多数个股跌破均线（超跌企稳）。

---

## 3. 微观个股、量价与交易结构类 (Micro & Execution)

### ① 大盘拥挤度 (A-Shares Market Congestion)
* **权威依据**：微观结构恶化模型（乐咕乐咕/华创证券）。
* **数学公式**：
  $$\text{Congestion} = \frac{\sum_{i=1}^{\lceil 0.05 \times N \rceil} \text{Amount}_{(i)}}{\sum_{i=1}^{N} \text{Amount}_i} \times 100\%$$
  * 分子：全市场按单日成交额降序排列前 5% 个股成交额之和；分母：全市场总成交额。
* **阈值基准**：$<40\%$ 健康分散；$40\%\sim 50\%$ 局部过热；$>50\%$ 筹码集中与微观结构恶化高危预警。

### ② 两融杠杆率（流量活跃度 vs 存量渗透率）
* **流量杠杆率 (Trading Leverage %)**：$\frac{\sum \text{rzmre}}{\sum \text{amount}} \times 100\%$（衡量每日成交中融资买入的杠杆交易烈度）；
* **存量杠杆率 (Stock Penetration %)**：$\frac{\sum \text{rzrqye}}{\sum \text{circ\_mv}} \times 100\%$（衡量两融总余额占全市场实际可交易流通市值的渗透率）。

### ③ Level-2 机构主力资金净流入 (Main Force Net Inflow)
* **权威依据**：交易所 Level-2 单笔订单切片微观资金流标准。
* **数学公式**：
  $$\text{Net Main Inflow} = (\text{buy\_elg\_amount} + \text{buy\_lg\_amount}) - (\text{sell\_elg\_amount} + \text{sell\_lg\_amount})$$
  * **超大单 (`elg`)**：单笔成交金额 $> 100$ 万元；**大单 (`lg`)**：单笔成交金额 $20 \sim 100$ 万元。
* **无量纲化**：除以标的当日总成交额转换为 **主力净买入占比 (Net Inflow Ratio %)**。

### ④ 相对真实波幅 (Normalized Average True Range, NATR)
* **权威依据**：J. Welles Wilder (1978)。
* **数学公式**：
  $$\text{TR}_t = \max\left(\text{high}_t - \text{low}_t, |\text{high}_t - \text{close}_{t-1}|, |\text{low}_t - \text{close}_{t-1}|\right)$$
  $$\text{NATR}_t = \frac{\text{ATR}_t(14)}{\text{close}_t} \times 100\%$$
* **含义**：消除股票价格绝对值影响，衡量单只标的微观日内波动幅度。
