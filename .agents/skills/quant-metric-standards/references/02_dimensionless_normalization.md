# 量化指标无量纲化与去体量通胀原则 (Dimensionless Normalization)

在跨周期（10年+）量化投研中，直接使用**绝对金额、绝对股数或静态点位**进行历史比较是严重的**量化反模式**。市场扩容（上市公司从 2000 家增至 5500+ 家）、M2/GDP 体量膨胀以及名义价格演变，会导致绝对数值完全失真。

---

## 1. 为什么指标解读必须无量纲化？

### ① 核心原因
1. **消除体量通胀 (Scale Invariant)**：
   2014 年全市场成交 5,000 亿是“天量爆发”，2026 年全市场成交 5,000 亿则是“极致地量冰点”。若直接比绝对金额，会导致严重的牛熊错判。
2. **跨资产/跨行业可比 (Cross-Asset Comparability)**：
   银行板块万亿市值与计算机板块千亿市值无法直接对比资金绝对流入额，必须转换为相对其自由流通市值的比率（无量纲）。
3. **消除单位依赖 (Unit Independence)**：
   无论上游返回元、千元、万元还是亿美元，无量纲化后的比率、分位数和比值在数学上严格等价。

---

## 2. 哪些指标解读必须无量纲化？（对照速查表）

| 指标类别 | ❌ 严禁直接比较的绝对量 (有量纲) | ✅ 必须转换的无量纲化量化指标 | 标准化转化公式 |
| :--- | :--- | :--- | :--- |
| **成交活跃度** | 全市场总成交金额 (万亿元) | **全市场自由流通换手率 (Turnover %)** | $\frac{\sum \text{amount}}{\sum \text{free\_float\_mv}} \times 100\%$ |
| **资金流向** | 主力资金净流入额 (亿元) | **主力净流入占成交比 / 流通市值比** | $\frac{\text{net\_mf\_amount}}{\text{total\_amount}} \times 100\%$ |
| **融资融券** | 两融总余额 (万亿元) | **存量渗透率 (两融余额/流通市值 %)** | $\frac{\sum \text{rzrqye}}{\sum \text{circ\_mv}} \times 100\%$ |
| **两融交易** | 单日融资买入额 (亿元) | **流量杠杆率 (融资买入/总成交 %)** | $\frac{\sum \text{rzmre}}{\sum \text{amount}} \times 100\%$ |
| **市场集中度** | 头部前 5% 个股成交总额 (万亿元) | **大盘拥挤度 (前5%成交占比 %)** | $\frac{\sum_{\text{top } 5\%} \text{amount}}{\sum \text{amount}} \times 100\%$ |
| **宏观整体估值** | 全市场总市值 (万亿元) | **巴菲特比值 (总市值 / GDP %)** | $\frac{\sum \text{total\_mv}}{\text{GDP (TTM)}} \times 100\%$ |
| **股债相对性价比** | 股票 PE 倍数 vs 国债收益率 % | **股债风险溢价 ERP (%)** | $\left(\frac{1}{\text{PE}_{\text{TTM}}} \times 100\%\right) - \text{Bond Yield}$ |
| **期权/衍生品** | PCR 认沽认购成交张数 | **PCR 比率 (Put-Call Ratio)** | $\frac{\text{Put Volume}}{\text{Call Volume}}$ |

---

## 3. 常见无量纲化数学方法

### ① 比率化归一 (Ratio Normalization)
将绝对金额映射为相对于基准分母的占比（无量纲百分比）：
$$\text{Ratio} = \frac{A (\text{元})}{B (\text{元})} \in [0, 1] \text{ 或 } [0, 100\%]$$

### ② Min-Max 极差标准化 (Min-Max Scaling)
将指标映射到固定的 $[0, 1]$ 或 $[0, 100]$ 连续区间：
$$X_{\text{scaled}} = \frac{X - X_{\min}}{X_{\max} - X_{\min}} \times 100$$
* **注意**：必须在过去固定时间窗口（如 5Y/10Y 滚动窗口）内取 $\min/\max$，防止因未来数据导致前瞻偏差（Lookahead Bias）。

### ③ 分位数映射 (Percentile Transform)
将任意非正态、长尾或尖峰分布的指标单调变换为 $[0\%, 100\%]$ 的均匀分布：
$$\text{Score} = \text{Percentile}(x) \in [0\%, 100\%]$$
* **优势**：对离群极值（Outliers）极具鲁棒性，是温度计与雷达图评级的首选。
