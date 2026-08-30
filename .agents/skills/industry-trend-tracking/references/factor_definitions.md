# 产业趋势跟踪因子计算定义

输入：`data/curated/mart/industry_panel_daily.parquet`（49 字段 Mart）。
方向层输入：`data/curated/mart/global_resonance_map.parquet`（数据缺口，缺失时中性 50）。
输出：`data/analytics/industry_trend/latest/industry_trend_panel.parquet`。

权重信任源：`config/analytics/industry_trend_tracking.yaml`。

---

## 面板字段

| 字段 | 含义 | 0-100 方向 | 计算 |
| :--- | :--- | :--- | :--- |
| `direction_score` | 全球资本开支方向 | 越高越景气 | 全球共振映射（缺口→中性 50） |
| `supply_demand_score` | 量价齐升质量 | 越高越好 | 量价齐升→双增速分位；供给收缩→20；双负→10 |
| `bargaining_score` | 议价权（毛利率扩张） | 越高越好 | 量价齐升门内→(净利−营收增速)分位；门外→30 |
| `prosperity_score` | 现实景气 | 越高越好 | (业绩预告向好占比分位 + 快报利润增速中位数分位) / 2 |
| `crowding_score` | 拥挤度 | 越高越危险 | 成交额占比 5Y 滚动分位（缺失用成交额截面分位） |
| `composite_trend_score` | 复合趋势得分 | 越高越好 | 三层共振 + 现实景气 − 拥挤度的加权合成 |
| `trend_momentum` | 环比趋势确认 | 越高越好 | `composite_trend_score − shift(63)` |

---

## 复合趋势得分合成

```
composite_trend_score = (
      w_direction × direction_score
    + w_supply_demand × supply_demand_score
    + w_bargaining × bargaining_score
    + w_prosperity × prosperity_score
    + w_crowding × (100 − crowding_score)
) / Σw
```

**默认权重**（精确对齐已验证 milestone，样本外 Sharpe ≈ 0.39）：

| 因子 | 默认权重 | 说明 |
| :--- | :--- | :--- |
| `direction` | 0.0 | 全球方向，数据缺口未激活 |
| `supply_demand` | 0.0 | 量价齐升，待验证激活 |
| `bargaining` | 0.0 | 议价权，待验证激活 |
| `prosperity` | 2/3 | 现实景气（业绩预告/快报），主驱动 |
| `crowding` | 1/3 | 拥挤度防守（减分项） |

默认权重下：`composite_trend_score = (2 × prosperity_score + (100 − crowding_score)) / 3`
= 已验证的「现实景气 + 拥挤度防守」复合分。

---

## 环比趋势确认（关键机制）

```
trend_momentum = composite_trend_score(t) − composite_trend_score(t − 63)
```

季度调仓按 `trend_momentum` 排序追「景气方向」而非「景气高低」。已验证：把样本外 Sharpe
从 0.22（追绝对水平）提升到 0.39（追环比改善）。

---

## 现实景气来源（样本外走强）

| 字段 | 来源 | 样本外 IC |
| :--- | :--- | :--- |
| `forecast_positive_share` | 业绩预告向好占比 | +1.68% → +3.63% |
| `express_profit_growth_median` | 快报利润增速中位数 | +1.40% → +2.94% |
| `report_rc_revision_ratio` | 分析师一致预期修正（反例） | +6.98% → +2.01% |

注意：分析师预期样本外衰减，不作主信号。
