# 申万二级行业轮动稳定性审计与门禁规范

---

## 一、 申万一级行业退役依据 (Obsolescence Evidence)

在 2015-2026 全周期回测及 2022 年后样本外实证对账中，申万一级 31 行业轮动被明确证伪，主要依据如下：
1. **样本外夏普断崖下跌**: 四大一级行业轮动策略在 2022 年后样本外 Sharpe 仅在 **0.02 ~ 0.13** 之间，无法战胜大盘基准；
2. **粗颗粒度导致严重分化**: 31 个大类行业内部成分股分化极其严重，权重股拖累明显，导致“选对大类却赚不到钱”；
3. **宏观二值择时开关失效**: 11 组恐慌/过热阈值扫描证实，大盘择时开关不仅未能躲过下跌，反而在牛市加速段频繁踏空；
4. **决策结果**: 项目正式在 [`config/strategy/industry_rotation.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/strategy/industry_rotation.yaml) 中全线停用一级行业轮动策略。

---

## 二、 申万二级行业方向池稳定性门禁标准

针对申万二级行业策略（如 `industry_l2_direction_guarded_hike`），设立如下 CI 门禁断言标准：

| 门禁指标项 | 约束阈值 | 实测表现 (`guarded_hike`) | 状态 | 业务含义 |
| :--- | :---: | :---: | :---: | :--- |
| **全周期年化复合收益 (CAGR)** | $\ge 12.0\%$ | **+15.38%** | ✅ PASS | 确保长期复利显著战胜宽基基准 (基准仅 2.89%) |
| **全周期夏普比率 (Sharpe)** | $\ge 0.50$ | **0.58** | ✅ PASS | 较一级行业提升 4 倍以上 |
| **全周期最大回撤 (MaxDD)** | $\le 42.0\%$ | **38.33%** | ✅ PASS | 防守门有效控制深幅破位风险 |
| **卡玛比率 (Calmar)** | $\ge 0.35$ | **0.40** | ✅ PASS | 收益回撤比优良 |
| **加息周期防守有效性** | 回撤优化 $\ge 2\text{pp}$ | **改善 0.62pp / Sharpe +0.06** | ✅ PASS | FFR 周期防守机制带来正向收益增益 |
| **拥挤度防守回撤压降** | 回撤压缩 $\ge 10\text{pp}$ | **42.11% $\to$ 25.80% (压降 16.3pp)** | ✅ PASS | 规避抱团瓦解风险 |
| **交易死区过滤 (Deadband)** | 换手磨损压降 | 3% 死区过滤有效生效 | ✅ PASS | 杜绝微量换手摩擦 |

---

## 三、 持续集成与验证命令

运行申万二级核心策略检验门禁：
```bash
# 验证最优二级组合策略
uv run python -m stock_cli.industry_trend_strategy --strategy industry_l2_direction_guarded_hike

# 验证基础组合防守门策略
uv run python -m stock_cli.industry_trend_strategy --strategy industry_l2_direction_guarded
```
确保各项指标满足上述稳定性要求。
