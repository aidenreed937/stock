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
  * 当前估值计算优先使用市值加权字段 `pe_ttm.mcw`；仅在该字段不存在时才回退到 `pe_ttm.ew`。
  * raw 计算：$\text{Earnings Yield} = \frac{1}{\text{PE}}$，结果以小数保存；展示为百分比时再乘以 100。
* **债券端无风险利率**：
  * **中国 10 年期国债收益率**：`data/curated/lixinger/market=CN/national_debt/data.parquet`（`tcm_y10`）
  * **全球/美债 10 年期基准**：`data/curated/yfinance/market=GLOBAL/macro_indicators/`（`^TNX`）
* **股债利差计算公式**：
  $$\text{ERP}_{raw} = \frac{1}{\text{PE}_{\text{TTM}}} - \text{tcm\_y10}$$
  当前 `tcm_y10` 在 Curated 中按小数保存（如 1.7% 记为 0.017），因此 raw ERP 也为小数；展示为百分比时统一乘以 100。估值温度使用 ERP 的滚动历史分位，并对其执行反向温度映射。

---

## 4. 查询性能效率平衡与临时产物隔离规范

### ① 性能与内存效率平衡（四维投影裁剪）
* **全量加载反模式**：全市场 12 年个股日 K 线（`stock_daily_bar`）与每日估值（`daily_basic`）均达数千万行，**严禁无参数全量读取**；
* **必须采用四维裁剪**：
  ```python
  # 推荐：时间切片 + 标的过滤 + 列投影
  df = cat.load_dataset(
      "daily_basic",
      symbols=["600519.SH", "000001.SZ"],
      start_date=date(2026, 1, 1),
      end_date=date(2026, 8, 14),
      columns=["symbol", "trade_date", "pe_ttm", "pb"]
  )
  ```
* **按需使用 Polars 惰性表达式**：多表大批量聚合优先使用表达式下推，避免在 Python 原生循环中频繁转化 dict 或 list。

### ② 临时脚本与分析产物落盘隔离 (Scratch Isolation)
* **严禁污染工作区**：为临时测试、排查问题或为用户一次性提取数据所编写的 Python 脚本（如 `test_xxx.py`、`debug.py`）或输出的中间结果（`.csv`、`.parquet`），**绝对禁止直接保存在 `src/`、`data/` 或仓库根目录**；
* **规范存放路径**：统一存放在临时目录（如 `<appDataDir>/brain/<conversation-id>/scratch/` 或 `/tmp/`）；
* **用完即净**：分析完毕后及时清理临时产物，确保 `git status` 始终保持干净（Clean）。

---

## 5. 大表跨表聚合优化与计算引擎选型矩阵 (Rollup & Engine Selection)

### ① 聚合表优先策略（避免扫底层亿级明细）
当分析目标为宏观、大盘、行业或风格时，**优先消费系统已清洗入库的高层聚合表**，节省 $90\%+$ 的 I/O 与计算耗时：

| 分析目标 | ❌ 反模式（底层全量扫表重聚合） | ✅ 推荐最佳实践（消费现成聚合表） |
| :--- | :--- | :--- |
| **行业/大盘估值与股息率** | 扫描 5,000+ 个股 `daily_basic` 现场加权 | 直接读取 `index_fundamental` 或 `sw_2021_fundamental` |
| **行业日度行情与成交** | 扫描全部个股 `stock_daily_bar` 汇总 | 直接读取 `sw_daily` (申万一级/二级行情) |
| **全市场两融总规模** | 扫描数千只标的 `margin_detail` 求和 | 直接读取 `margin` (交易所日度汇总表) |
| **北向资金流动大盘时钟** | 扫描个股微观资金流汇总 | 直接读取 `moneyflow_hsgt` (北向每日净额) |
| **行业成份股持仓聚合** | 逐只股票查询分类标签 | 读取 `sw_2021_constituents` 图谱执行单次 `explode` Join |

### ② 计算引擎与工具选型指南
根据数据规模与计算拓扑选择最匹配的工具：

| 任务场景 | 推荐计算工具 / 引擎 | 核心理由与最佳实践 |
| :--- | :--- | :--- |
| **常规数据读取与单表过滤** | `DataCatalog.load_dataset()` | 内建类型容错、分区裁剪、自动主键去重 |
| **高维度多表关联 / 复杂 SQL 聚合** | **DuckDB 向量化 SQL** | 支持 Out-of-Core 内存自适应直接扫多目录 Parquet，比 Python 循环快数十倍 |
| **链式分析管道 / 惰性下推** | `polars.scan_parquet()` | 利用 LazyFrame 自动执行谓词下推与列投影，最后 `.collect()` |
| **临时排查与即席计算** | Scratch 目录下的独立单行脚本 | 脚本存入临时 scratch 目录，控制台打印即弃，保持代码库整洁 |
