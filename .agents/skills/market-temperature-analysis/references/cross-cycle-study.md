# 跨周期研究方法

## 适用场景

当用户要求分析一段时间内的市场结构变化、资金运动、重要信号日、行业轮动可靠性，或要求把多个交易日的市场报告联合起来看时，使用本方法。

## 执行顺序

1. 确认目标区间是交易日口径，不使用自然日补齐。
2. 确认三类产物都存在：
   - `data/analytics/market_temperature`
   - `data/analytics/industry_structure`
   - `data/analytics/investor_brief`
3. 先运行一致性校验：

```bash
make report-consistency START=YYYY-MM-DD END=YYYY-MM-DD
```

4. 再生成跨周期复盘产物：

```bash
make market-cycle-review START=YYYY-MM-DD END=YYYY-MM-DD
```

5. 解读时分三层：
   - 市场环境：综合温度、系统风险、六维分数变化。
   - 结构确认：20日上涨行业数、60日上涨行业数、结构健康度。
   - 行业方向：候选行业、拥挤风险、落后方向、TCR迁移和 `trend_diagnostics`。
   - 驱动拆解：优先读取每个日期 `scores.json` 的 `drivers`、资金 20 日累计占比、两融 60 日变化和情绪 `activity`/`slow` 子组。

## 核心判断

- 综合温度解决“风险环境是否允许参与”。
- 行业结构解决“资金和价格往哪里运动”。
- 投资者简报解决“普通投资者如何读成操作约束”。
- 20日扩散强而60日扩散弱时，只能称为短线修复，不能称为中期趋势确认。
- 资金温度没有同步上升时，价格上涨要表述为“价格先行、资金待确认”。
- `main_money_net_inflow_share` 是单日脉冲，`main_money_net_inflow_share_20d_cum` 才能用于
  窗口趋势；两者的 `metric_date` 可能晚于行情基准日，必须分别披露。
- 外盘 `short_term_shock` 只表示隔夜冲击观察；若 `transmission_status` 为
  `pending_next_ashare_session`，不能写成 A 股风险已经确认。

## 输出约束

- 只使用本地产物事实，不使用新闻、政策、模型记忆补叙事。
- 低频基本面和宏观月频只能解释底座，不解释区间内每个交易日波动。
- 跨周期结论必须说明起止日期、交易日数和一致性校验状态。
- 若某日的 `drivers.status` 为 `insufficient` 或情绪主温度发生子组降级，应把它作为数据可比性
  限制写入结论，而不是强行排出完整的驱动排名。
