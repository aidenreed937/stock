# 数据资产查询细节、时滞处理与避坑参考 (Data Query Caveats & References)

本文档整理了在对本地 Curated 黄金层数据资产执行微观资金流穿透、股债利差 (ERP) 时钟与多周期市场宽度等深度投研分析时的核心原则、规范、时滞处理与字段映射。

---

## 0. 量化投研与数据分析第一准则 (Ground Truth First & 防过拟合)

1. **本地真实数据第一（零臆造与缺失如实说明）**：
   * 所有市场点位、估值、收益率、两融规模等具体量化指标，**严禁凭大模型参数记忆给出**；
   * 必须通过代码实际读取本地 `data/curated/` 黄金表，以控制台真实计算输出作为第一证据；
   * **若本地数据库无对应标的或日期数据，必须如实说明“本地无数据”并指出缺口区间，严禁编造**；确需补充外部数据时，必须通过 GrokSearch 或权威金融渠道检索并显式标注数据源与时效。
2. **指标公式与策略逻辑严禁编造 (权威金融依据)**：
   * **严禁凭空臆造量化指标定义、数学公式或交易策略**；
   * 若对指标公式（如 ATR 真实波幅、ERP 股债利差、资金流分级阈值、行业动量评分等）或策略机制不确定，必须先检索外部权威金融学术文献、官方编制方案（中证指数/申万研究所）或券商金工研报，明确其数学定义与金融因果依据；
   * 交付代码或研报时，必须显式给出该指标的数学定义式与计算依据。
3. **三层信息分级透明化**：
   * **已验证事实 (Tier 1)**：本地代码计算得出的量化结果，必须附带表路径、计算公式与样本区间；
   * **机制推断 (Tier 2)**：基于金融工程/微观结构的因果机制，必须阐明逻辑链条与反例/局限；
   * **外部认知 (Tier 3)**：历史节点选择或宏观叙事背景，必须明确声明为“外部参考背景”。
4. **防过拟合自检清单 (Anti-Overfitting)**：
   * **警惕小样本拟合**：极值样本较少（$N \le 5$）时，严禁将历史具体数字当成机械套用的铁律；
   * **去绝对化**：优先使用“相对分位数 / 滚动 Z-Score”，避免因市场扩容或体量膨胀导致绝对金额失真；
   * **承认宏观范式漂移 (Regime Shift)**：遇到利率中枢下行（如中债 10Y 从 3.5% 降至 1.7%）等重大制度变迁时，主动提示历史统计中枢的局限性。
5. **严禁外部事件与叙事污染数据事实 (No Ungrounded Narrative Pollution)**：
   * 本地数据库仅落盘了量价行情、财务估值、宏观利率与微观资金流，**不存在任何政策新闻、会议通稿或官方公告日志表**；
   * 严禁将“政策刺激”、“救市政策”、“重磅会议”等大模型外部记忆中的宏观叙事直接写入数据结论或指标表格的定性中；
   * 若确需补充外部历史背景，必须显式隔离并标注为 **【Tier 3: 外部历史背景参考（本地无数据表支持）】**，绝不能将外部认知伪装成数据事实。

---

## 1. 目录隔离与在线安全加载范式

### ① 避免泛通配符混淆同名前缀数据集
* **典型案例**：`moneyflow`（个股资金流）与 `moneyflow_hsgt`（北向资金流），或 `margin` 与 `margin_detail`。
* **规范**：禁止使用 `moneyflow*` 或 `margin*` 这类模糊通配符，必须精确到具体数据集目录，或统一通过 `DataCatalog` 加载：
  ```python
  from stock_data.catalog import DataCatalog
  cat = DataCatalog(data_source="tushare")
  df_mf = cat.load_dataset("moneyflow")
  df_margin = cat.load_dataset("margin")
  ```

### ② 类型归一与容错机制（已内建）
* 系统已在 `StorageCompat.safe_normalize_frame` 与 `DataCatalog` 中内建自动预处理流水线：
  * **自动类型归一**：数值度量列（如 `rqyl`, `rzye`, `turnover_rate` 等）自动统一为 `Float64`；
  * **自动日期/时间对齐**：`trade_date` 统一转为 `pl.Date`，时间戳统一为 UTC 微秒精度；
  * **离线全库治理**：可通过 `make migrate-data APPLY=1` 随时对全库存量 Parquet 执行批量去重与 Schema 规范化（高危操作需人工授权）。

---

## 2. 数据集更新时钟与时滞矩阵 (Data Latency Matrix)

多表关联（Join）时需关注各数据集更新频率与入库时差，避免因 T 日收盘后尚未入库而读出空数据：

| 数据集名称 | 数据源 | 最新更新时点 | 典型时滞特性 | 关联查询最佳实践 |
| :--- | :--- | :--- | :--- | :--- |
| **`stock_daily_bar`** | TuShare | 当天 T 日 17:00 | **T+0 实时收盘** | 全市场日历基准，可用于获取最新交易日 |
| **`daily_basic`** | TuShare | 当天 T 日 17:30 | **T+0 实时收盘** | 与日 K 线同步 |
| **`moneyflow`** | TuShare | 当天 T 日 22:00 / T+1 | **T+0 晚间** | 收盘刚结束时可能尚未入库，应动态取 `cat.get_latest_trade_date("moneyflow")` |
| **`moneyflow_hsgt`** | TuShare | 当天 T 日 18:30 | **T+0 盘后** | 北向每日净买入资金流 |
| **`index_fundamental`** | 理杏仁 | 当天 T 日 20:00 | **T+0 晚间** | 申万行业与核心指数估值、股息率序列 |
| **`national_debt`** | 理杏仁 | 当天 T 日 18:00 | **T+0 盘后** | 1Y/2Y/5Y/10Y/30Y 中国官方国债收益率 |
| **`macro_indicators`** | FRED / YFinance | 美东时间盘后 / 月度公布 | **跨时区 / 低频** | 美债 `^TNX` 存在中美时差；月度指标（CPI/非农）需前向填充 (forward fill) |

---

## 3. 高级投研场景数据链路与字段映射

### ① 资金流向微观穿透 (`moneyflow`)
* **路径**：`data/curated/tushare/market=CN/moneyflow/`（覆盖 2013-01 至今 160+ 个月度分区）
* **微观单笔分级**：
  * **超大单（机构主力）**：`buy_elg_amount` / `sell_elg_amount`（单笔成交 $> 100$ 万元）
  * **大单（大户主力）**：`buy_lg_amount` / `sell_lg_amount`（单笔成交 $20 \sim 100$ 万元）
  * **中单（中户）**：`buy_md_amount` / `sell_md_amount`（单笔成交 $4 \sim 20$ 万元）
  * **小单（散户）**：`buy_sm_amount` / `sell_sm_amount`（单笔成交 $< 4$ 万元）
  * **主力净流入**：`net_mf_amount`（超大单净额 $+$ 大单净额）
* **单位口径**：Curated 层资金字段已统一归一为**元**。分析层不得再按 TuShare 源单位额外乘除倍率；仅在展示为亿元时除以 `1e8`。

### ② 股债利差 (ERP) 与宏观配置时钟
* **股票端收益率（$E/P$）**：
  * 路径：`data/curated/lixinger/market=CN/index_fundamental/`
  * 计算：$\text{Earnings Yield} = \frac{1}{\text{pe\_ttm.ew}} \times 100\%$
* **债券端无风险利率**：
  * **中国 10 年期国债收益率**：`data/curated/lixinger/market=CN/national_debt/data.parquet`（`tcm_y10`）
  * **全球/美债 10 年期基准**：`data/curated/yfinance/market=GLOBAL/macro_indicators/`（`^TNX`）
* **股债利差计算公式**：
  $$\text{ERP} = \left(\frac{1}{\text{PE}_{\text{TTM}}} \times 100\%\right) - \left(\text{tcm\_y10} \times 100\right)$$
