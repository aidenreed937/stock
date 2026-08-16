# 六维市场温度计打分口径

## 时间窗口

- 主窗口：最近 20 个已落盘 A 股交易日，来自 `DataCatalog(data_source="tushare").latest_trade_dates("stock_daily_bar", n=20)`。
- 历史分位窗口：默认 5 年交易日或可用全历史；若 5 年窗口样本不足，必须说明。
- 主日期：`tushare.stock_daily_bar` 最新交易日；其他数据源按各自最新日期对齐并披露。

## metrics 源码导航

分析前先查 `src/stock/analytics/metrics` 的当前实现。此文件只提供导航和默认分析口径；若与源码不一致，以源码为准。

| 目的 | 源码位置 | 关注点 |
|---|---|---|
| 统一调度 | `src/stock/analytics/metrics/engine.py` | `MetricEngine.compute` 如何调度注册指标 |
| 上下文与日期 | `src/stock/analytics/metrics/context.py` | `MetricContext.start_date/end_date/target_date/cache` |
| 指标注册 | `src/stock/analytics/metrics/registry.py` | `MetricRegistry.specs/select/get` |
| 内置入口 | `src/stock/analytics/metrics/calculators/__init__.py` | `BUILTIN_METRIC_SPECS`, `BUILTIN_CALCULATORS` |
| 表现 | `src/stock/analytics/metrics/calculators/performance.py` | `return_1d/5d/20d/60d/252d` |
| 估值 | `src/stock/analytics/metrics/calculators/valuation.py` | `valuation_temperature`, PE/PB 分位, ERP, 股债收益比 |
| 资金 | `src/stock/analytics/metrics/calculators/flow.py` | 两融、主力资金、北向、成交额分位 |
| 情绪/流动性 | `src/stock/analytics/metrics/calculators/liquidity.py` | 换手率、成交额均量比、Z-score |
| 技术趋势 | `src/stock/analytics/metrics/calculators/trend.py` | MA 乖离、RSI、距252日高点 |
| 市场宽度 | `src/stock/analytics/metrics/calculators/breadth.py` | 上涨占比、均线上方占比、新高新低 |
| 波动风险 | `src/stock/analytics/metrics/calculators/volatility.py` | 已实现波动率、下行波动率、最大回撤 |
| 宏观扩展 | `src/stock/analytics/metrics/calculators/macro.py` | 当前是否已有宏观指标实现 |

推荐首轮定位命令：

```text
codegraph_explore: src/stock/analytics/metrics MetricEngine MetricContext BUILTIN_METRIC_SPECS BUILTIN_CALCULATORS calculators valuation flow liquidity trend breadth volatility performance macro
```

## 分数方向

所有维度都映射到 `0-100`，高分表示市场更热、更拥挤或更偏进攻。

- 估值：估值越高越热；ERP、股息率越低越热。
- 资金：融资占比、两融渗透率、成交额分位越高越热；主力净流入越高越进攻。
- 情绪：换手、成交额、上涨家数、站上短均线比例越高越热。
- 技术：20日收益、RSI、均线乖离、站上中短期均线比例越高越热。
- 基本面：盈利增速、ROE、正增长行业占比越高越支撑风险偏好。
- 宏观流动性：利率越低越宽松；M1/M2、社融越强越宽松；美元指数/VIX 越低越利好风险偏好。

## 推荐计算

### 估值面

主指标：

- `valuation_temperature`，优先取 `000985` 中证全指。
- 辅助展示 `000300`, `000905`, `000852` 的 `pe_percentile_5y`, `pb_percentile_5y`, `equity_bond_yield_ratio`, `equity_risk_premium`。

解释：

- `valuation_temperature >= 80`：估值偏热或接近拥挤。
- `60-80`：偏热但仍可能由低利率支撑。
- `< 40`：估值偏冷。

### 资金面

主指标：

- `margin_buy_share` 历史分位。
- `margin_penetration` 历史分位。
- `margin_balance_growth_20d` 历史分位。
- `main_money_net_inflow_share` 历史分位。
- `market_amount` 历史分位，作为资金活跃度补充。

可用 `moneyflow_hsgt.north_money` 做北向活跃度参考，但不要在未验证字段语义时称为“净流入”。

### 情绪面

主指标：

- 全市场成交额五年分位。
- 项目聚合口径 `market_turnover_rate`。
- `above_ma20_share * 100`。
- `advance_share * 100`。

注意：`daily_basic.turnover_rate` 简单平均和项目情绪模块的成交额/流通市值聚合口径可能不同。对用户输出优先使用项目现有口径，并说明差异。

### 技术面

主指标：

- 个股 `return_20d` 中位数和上涨占比。
- 个股 `rsi_14d` 中位数。
- 个股 `ma_bias_20d` 中位数。
- `above_ma20_share`, `above_ma60_share`。
- 主要指数 20 日收益：上证指数、沪深300、中证500、中证1000、创业板指。

判断：

- 站上20日线高、站上60日线低：短线修复强，中期趋势未全面确认。
- RSI 中位数 60-70：强势但未极端。
- RSI 中位数超过 70 且成交额分位高：追涨风险升高。

### 基本面

主指标来自理杏仁申万行业合并财报：

- `sw_2021_fs_non_financial`
- `sw_2021_fs_bank`
- `sw_2021_fs_security`
- `sw_2021_fs_insurance`

抽取字段：

- 收入 TTM 增速：`q.ps.toi.ttm_y2y`
- 利润 TTM 增速：`q.ps.np.ttm_y2y`
- ROE TTM：`q.m.roe.ttm`

展示最新报告期、行业数、中位数、正增长行业占比。季频数据只能作为基本面底座。

### 宏观流动性

主指标：

- `lixinger.national_debt.tcm_y10`：中国10年国债，低利率对应高流动性温度。
- `tushare.shibor.on`：短端资金价格，低利率对应高流动性温度。
- `tushare.cn_m.m2_yoy`、`m1_yoy - m2_yoy`。
- `tushare.sf_month.stk_endval` 同比。
- `yfinance.macro_indicators`: `DX-Y.NYB`, `^VIX`, `^TNX`, `GC=F` 作为外部背景。

## 输出模板

```markdown
口径：基于本地 Curated 黄金表，最近 20 个已落盘交易日为 `YYYY-MM-DD` 至 `YYYY-MM-DD`。资金流/宏观数据若有滞后，在此说明。

综合温度：`xx.x / 100`，一句话判断。

| 维度 | 温度 | 主要事实 | 判断 |
|---|---:|---|---|
| 估值面 | xx.x | ... | ... |
| 资金面 | xx.x | ... | ... |
| 情绪面 | xx.x | ... | ... |
| 技术面 | xx.x | ... | ... |
| 基本面 | xx.x | ... | ... |
| 宏观流动性 | xx.x | ... | ... |

结构判断：...

风险提示：...

数据限制：...
```

## 最小 Python 骨架

```python
from stock.analytics.engine import MarketScanEngine
from stock.analytics.metrics import MetricContext, MetricEngine
from stock.data.catalog import DataCatalog

cat_ts = DataCatalog(data_source="tushare")
latest = cat_ts.get_latest_trade_date("stock_daily_bar")
dates20 = list(reversed(cat_ts.latest_trade_dates("stock_daily_bar", n=20)))
start20 = dates20[0]

engine = MetricEngine()
ctx = MetricContext(catalog=cat_ts, start_date=start20, end_date=latest)
results = engine.compute(
    [
        "advance_share",
        "above_ma20_share",
        "above_ma60_share",
        "market_turnover_rate",
        "amount_ma_ratio_20d",
        "return_20d",
        "rsi_14d",
        "ma_bias_20d",
        "realized_volatility_20d",
    ],
    ctx,
)

scan = MarketScanEngine().compute(target_date=latest, index_symbol="000300")
```
