# 指标层优化计划：行业指标入 MetricEngine 与衍生品 MetricDomain

> 对应 Gemini 评审建议 #2（行业指标入 MetricEngine）与 #3（期权/衍生品 MetricDomain）。
> 状态：已落地（本轮实现 + 单测 + 真实数据验证）。

## 背景

`stock_analytics/metrics/` 此前仅有 `EntityType.MARKET` 粒度指标（8 个 `MetricDomain`），
而行业结构（申万一级）与期权衍生品事实早已存在于 `marts/`（`industry_structure.py`、
`option_volatility.py`）和 `features/`（`market_daily_ops.py` 的 PCR），但**未接入统一
指标注册表**，无法被 `MetricEngine` 批量调度与 `MetricRegistry.select(domain=...)` 检索。

## 目标

1. **#2 行业指标入 MetricEngine**：将申万一级行业（SW2021/L1）日频截面指标注册为标准
   `MetricSpec`，`entity_type=EntityType.INDUSTRY`。
2. **#3 衍生品 MetricDomain**：新增 `MetricDomain.DERIVATIVES`，把全市场期权面板
   （`opt_daily` + `opt_basic`）的 PCR 与结算价 IV 代理注册为标准指标。

## 已实现

### 新增领域与实体粒度

- `MetricDomain.DERIVATIVES = "derivatives"`（`metrics/spec.py`）。
- `empty_metric_frame` 支持行业/标的字符串键列：`industry_code`、`industry_name`、
  `underlying_symbol`（`metrics/datasets/windows.py`），保证空帧 Schema 稳定。

### `calculators/industry.py`（4 个指标）

| metric_id | 名称 | domain | 说明 |
| :--- | :--- | :--- | :--- |
| `sw_industry_pct_change` | 申万一级行业日涨跌幅（%） | PERFORMANCE | `sw_daily.pct_change` |
| `sw_industry_amount_yi` | 申万一级行业成交额（亿元） | LIQUIDITY | `sw_daily.amount / 1e8` |
| `sw_industry_pe` | 申万一级行业市盈率 | VALUATION | `sw_daily.pe` |
| `sw_industry_pb` | 申万一级行业市净率 | VALUATION | `sw_daily.pb` |

- 统一经 `_industry_l1_frame` 过滤 `classification=="SW2021" & industry_level=="L1"`，
  输出列 `(trade_date, industry_code, industry_name, <metric_id>)`。
- 沿用 `features` 的 `_industry_daily_frame` 口径：以 `symbol` 为 `industry_code`、
  `name` 为 `industry_name`，与 `marts/industry_structure` 的 Mart 口径一致。

### `calculators/derivatives.py`（4 个指标）

| metric_id | 名称 | 依赖数据集 |
| :--- | :--- | :--- |
| `option_put_call_volume_ratio` | 全市场期权认沽/认购成交量比 | `opt_daily`, `opt_basic` |
| `option_put_call_oi_ratio` | 全市场期权认沽/认购持仓量比 | `opt_daily`, `opt_basic` |
| `option_settlement_iv_proxy_median` | 期权结算价隐含波动率代理（中位数） | `opt_daily`, `opt_basic`, `fund_daily`, `index_daily`, `shibor` |
| `option_settlement_iv_proxy_put_call_skew` | 期权结算价IV认沽认购偏度 | 同上 |

- **PCR**：按日聚合 `P`/`C` 成交量与持仓量，比值在分母为 0 时置空（与
  `market_daily_ops` 一致）。
- **IV 代理**：复用 `plugins/options.compute_fast_bs_iv`（Rust 插件或 Python 回退），
  标的收盘价由 `fund_daily`（ETF 期权）∪ `index_daily`（指数期权）提供，无风险利率取
  `shibor.3m`（百分数 → 小数），按日取 `_iv` 中位数与 `put_median - call_median` 偏度。
  口径与 `marts/option_volatility.settlement_iv_proxy` 一致（结算价 ≠ 买一卖一中间价，
  不冒充标准 VIX）。

### 取数层增强（`datasets/loaders.py`）

- 新增 `load_metric_dataset(..., reference=True)`：静态参照表（`opt_basic`）不随上下文
  日期窗口过滤，仅按需投影列。修复了真实数据联调中 `opt_basic` 被日期窗口过滤为空、
  PCR/IV 指标恒为空的问题。

### 注册

- `calculators/__init__.py`：`BUILTIN_METRIC_SPECS` / `BUILTIN_CALCULATORS` 并入
  `industry` 与 `derivatives` 模块。默认注册表现含 67 个指标。

## 测试与验证

- `tests/unit/stock_analytics/metrics/test_industry.py`（7 用例）：注册表、L1 过滤、
  `amount_yi` 换算、PE/PB、缺数据集空帧、缺源列降级、start_date 过滤。
- `tests/unit/stock_analytics/metrics/test_derivatives.py`（7 用例）：注册表、PCR 数值、
  分母为 0 置空、IV 中位数/偏度（用 `_black_scholes_price` 构造结算价反解回 0.2）、
  缺标的数据空帧、缺期权数据空帧、start_date 过滤。
- 真实 Curated 黄金表验证：
  - 行业：2026-08-14 ~ 2026-08-21，31 个一级行业 × 6 交易日，如 2026-08-21
    有色金属 +2.72%、成交额 1451 亿元、PE 22.13、PB 3.28；
  - 衍生品：2026-08-19 全市场 PCR 量比 0.921、持仓比 0.771，IV 代理中位数 34.36%、
    认沽认购偏度 +11.19%（认沽偏贵）。

## 后续方向（未实现，供下轮）

- 行业指标补充估值分位（`sw_industry_pe_percentile`）与动量因子（如 20 日/60 日收益），
  可复用 `historical_percentile`/`with_return_columns` 原语。
- 衍生品按标的粒度（`EntityType.INDEX`/`ETF`）展开，输出 `underlying_symbol` 列；
  远期可接入标准 VIX 编制方法（跨执行价方差积分）替换结算价代理。
- 新增 `DERIVATIVES` 领域后，可扩展 `MetricRegistry.select(domain=...)` 在 CLI/报告层的
  检索与渲染。
