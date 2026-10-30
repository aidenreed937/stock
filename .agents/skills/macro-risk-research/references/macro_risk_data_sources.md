# 宏观风控管线数据源分级与完整性校验手册

> **文档定位**：回答「宏观因子从哪来、读黄金表还是 Mart、分析前怎么保证数据准确与完整」。
> 数据链路以工程代码为唯一信任源（`data_fetchers.py` fetcher、`features/builders/` 与
> `marts/` 构建器、`config/analytics/macro_risk.yaml` 因子配置）；本页只承载分级速查与
> 校验清单，不维护快照数字。
>
> **Ground Truth First**：宏观风控因子、分位数与双轨指数必须来自本地黄金产物
> `data/analytics/macro_risk/latest/risk_factors.parquet`；任何分析引用前，先按 §5 校验
> 数据准确与完整性，缺失必须披露，不得静默跳过。

---

## 1. 数据分层架构（串联 curated 与 Mart）

```
RAW 源 (tushare/lixinger/yfinance/fred)
   │  ① 回填/同步 + 清洗归一
   ▼
Curated 黄金表 (data/curated/…)          ← 事实唯一信任源
   │  ② 跨表聚合 / 领域计算（Mart 构建器）
   ▼
领域 Mart (FeatureStore)                  ← 派生特征缓存层
   │  ③ fetcher 消费
   ▼
宏观因子管线 (config/analytics/macro_risk.yaml + data_fetchers.py)
   │  ④ 滚动分位 → 维度均值 → 双轨指数
   ▼
risk_factors.parquet → assemble_macro_panel → 策略 on_bar
```

- **黄金表（curated）**：标准化黄金事实表（日期/主键/单位统一），是下游唯一事实消费层；
- **Mart（派生层）**：由黄金表构建的日频/月频宽表，缓存跨表聚合结果，供多个因子复用；
- **fetcher**：纯消费端，从黄金表或 Mart 取数，不自己造数。

---

## 2. 因子系列数据源分级表

| 因子系列 | 读取来源 | 类型 | 底层黄金表 / 说明 |
| :--- | :--- | :--- | :--- |
| 估值 erp / pb | 理杏仁 `index_fundamental` + 指标引擎 | **黄金表直读** | 中证全指 pb.mcw；ERP 由指标引擎计算 |
| 恐慌 VIX | yfinance | **黄金表直读** | 美股 VIX，时区平移对齐 |
| 可转债 | tushare `cb_daily` | **黄金表直读** | 转债价格中位数 |
| 跨资产宏观 | lixinger / fred / yfinance | **黄金表直读** | 国债收益率 / 铜金比 / 美债利差等 |
| 利率周期 ffr_chg_6m | fred | **黄金表直读** | `macro_indicators` 表 DFF 日频有效利率，相对六个日历月前最近观测的变化（pp；按 H.15 下一个联储工作日发布时间映射为北京时间可用日，再对齐 A 股交易日；加息为正/降息为负），独立观测因子不入维度/双轨指数；既有研究基于月频 FEDFUNDS，换源后待复验 |
| 两融杠杆 | `market_daily` Mart | **Mart** | stock_daily_bar + margin + daily_basic（融资穿透率/买入比，T+1 平移） |
| 市场广度 | `market_daily` Mart | **Mart** | stock_daily_bar（涨跌家数/60日新高占比） |
| 期权情绪 pcr | `market_daily` Mart | **Mart** | opt_daily（认沽认购比） |
| 换手拥挤 | `market_daily` Mart | **Mart** | stock_daily_bar + daily_basic（全市场换手率） |
| 主力资金 | `capital_game_daily` Mart | **Mart** | moneyflow + market_daily（主力/ETF/分歧度，T+1 平移） |
| 隐含波动率 iv | `settlement_iv_proxy_daily` Mart | **Mart** | opt_daily（主力合约 IV 截面聚合） |
| 聪明钱 | `smart_money_daily` Mart | **Mart** | insider_activity_daily + block_trade + top10_floatholders（三因子合成） |
| 产业资本 | `repurchase_daily` / `insider_activity_daily` / `unlock_pressure_daily` Mart | **Mart** | `dim_corporate` 等权汇总内部人净买入反向分位、内部人减持分位与限售解禁分位；回购反向分位是独立参考，不计入该维度。日报对综合分 65–79 标为“产业压力偏高”，≥80 标为“减持潮起”；解读时同时看分项，不能把 25–79 全部理解成压力常态 |

> 结论：**黄金表直读的少（估值/VIX/转债/跨资产/利率 5 类），Mart 消费的多（8 类）**——凡需
> 「全市场跨表聚合」或「领域合成」的因子，一律经 Mart 物化，避免各 fetcher 重复计算。

---

## 3. Mart 依赖关系（谁构建自谁）

| Mart | 构建器 | 依赖黄金表 / 上游 Mart |
| :--- | :--- | :--- |
| `market_daily` | `features/builders/market_daily.py` | stock_daily_bar, margin, daily_basic, moneyflow, limit_list_d, opt_daily |
| `capital_game_daily` | `marts/capital_game.py` | moneyflow + market_daily |
| `settlement_iv_proxy_daily` | `marts/option_volatility.py` | opt_daily |
| `smart_money_daily` | `marts/smart_money_build.py` | insider_activity_daily + block_trade + top10_floatholders |
| `repurchase_daily` | `marts/build_steps.py` | repurchase |
| `insider_activity_daily` | `marts/build_steps.py` | stk_holdertrade |
| `unlock_pressure_daily` | `marts/build_steps.py` | share_float |

Mart 构建入口：`make features-build TARGET=domain_marts`（`stock_analytics.marts.DomainMartBuilder`）。

---

## 4. 数据准确性校验（分析前必跑）

| 命令 | 作用 | 说明 |
| :--- | :--- | :--- |
| `make probe` | 数据源连通性探针 | 各源（tushare/lixinger/yfinance/fred）健康检测 |
| `make validate` | 离线质量校验 | QualityGate 物理断言：日期类型/主键唯一性/非有限数值/领域输入契约 |
| `make audit TYPE=reconciliation` | 对账审计 | RAW/Curated/隔离区与 Mart 的可解释对账 |
| `make master-audit` | 全库资产盘点 | 全源最新落盘时间、覆盖率、缺口诊断 |
| `make audit TYPE=all DATE=YYYY-MM-DD` | 指定日全面审计 | 分布审计、覆盖率归因 |

> 宏观风控分析前，最低要求：`make validate`（质量门禁）+ 确认目标日因子产物已生成且
> `manifest.json` 的 `run_status == "succeeded"`。
>
> 数据同步的目标日可能因显式 `DATE`、发布时间窗口或交易日历而未实际落盘；宏观分析应使用数据管道验收得到的 `effective_as_of`，具体规则见 [`data-pipeline/SKILL.md`](../data-pipeline/SKILL.md)。

---

## 5. 数据完整性校验与已知口径缺口（分析前必查）

### 5.1 完整性 checklist（按宏观因子逐项）

| 检查项 | 方法 | 处理 |
| :--- | :--- | :--- |
| 因子日期覆盖 | 读 `risk_factors.parquet` 的 `trade_date` 范围 vs 期望交易日历 | 缺口需补数或披露 |
| 最新日两融是否可用 | `dim_leverage` 最新一日非空（两融 T+1 早间发布，管线已平移） | 缺失需补数或显式披露，**不得静默跳过** |
| 估值冷启动 | `dim_valuation` 在 2015-01 ~ 2016-08 为 null（理杏仁 `index_fundamental` 最早 2011-08，`min_periods=1250`） | 该区间 overheat 按 4 维计，引用必须披露 |
| 关键列缺失 | `panic_index` / `overheat_index` 最新一日非空 | 缺失说明管线失败，需重跑 |
| Mart 新鲜度 | `market_daily` / `capital_game_daily` / `smart_money_daily` 等最新水位 | 落后则先 `make features-build TARGET=domain_marts` 重建 |
| 分位连续性 | 因子分位无跳变（滚动窗口计算正常） | 异常需查上游原始值 |

> ✅ **管线自动完整性检测（2026-08-30 起）**：每次生成产物时，管线自动检测
> `overheat_index / panic_index + 6 个构成维度` 在 as_of 日的缺失，结果写入
> `manifest.json` 的 `data_completeness` 字段（`total/available/missing_fields/complete`），
> 缺失时运行日志告警。引用产物前先看该字段：`complete: false` 需核验是「已知口径缺口」
> （如估值冷启动）还是「上游缺数异常」。

### 5.2 已知口径缺口（引用时必须披露）

1. **两融 T+1**：T 日收盘仅可用 T-1 日两融值（管线按交易日历平移对齐），最新交易日可能暂缺或滞后一日；
2. **估值冷启动**：2015-01 ~ 2016-08 无 `dim_valuation`，该区间 `overheat_index` 实为 4 维口径，不与后续 5 维口径直接横向比较；
3. **ETF 后复权**：策略回测用后复权（含分红），指数基准不含分红，两组超额含口径差；
4. **公募新发链路已下线（2026-10-29）**：因上游发行规模字段长期不稳定，生产管线已停止
   `fund_basic` 采集、`fund_issuance_monthly` Mart 构建、宏观报告展示和策略 IC 消费。
   `src/stock_analytics/marts/fund_issuance.py`、历史 Curated/Mart 文件和对应历史研究仅作追溯，
   不得作为当前读数或数据缺口引用；当前同步与 `domain_marts` 构建不会再访问该链路。

---

## 6. 一条因子从黄金表到策略的完整链路（示例：两融杠杆）

```
tushare margin / stock_daily_bar / daily_basic（黄金表）
  → MarketDailyBuilder 聚合 → market_daily Mart（融资穿透率 margin_penetration）
  → data_fetchers.fetch_leverage 读取 → T+1 平移
  → config/analytics/macro_risk.yaml margin_pen 因子（window=1250 滚动分位）
  → dim_leverage（维度均值）→ overheat_index / panic_index
  → risk_factors.parquet → assemble_macro_panel → 策略 on_bar
```

任一环节数据缺失都会向上传导：**黄金表缺 → Mart 缺 → 因子 null → 维度缺失 → 指数维度数下降**。
因此「分析前先校验黄金表与 Mart 完整性」是 Ground Truth First 的第一道闸门。
