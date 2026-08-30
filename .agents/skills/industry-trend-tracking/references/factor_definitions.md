# 产业趋势跟踪因子计算定义（申万二级方向池）

## 输入（阶段 1/3 产物）

- **二级行业基本面面板**：`data/curated/mart/industry_l2_panel_daily.parquet`
  （18 字段，2014-01 ~ 2026-08 全历史），由 `industry_l2_daily`（行情/估值/动量）+
  理杏仁 L2 财务黄金表 `sw_2021_l2_fs_*` 按 `reportDate` 发布日合并生成；
- **二级方向分**：`data/curated/mart/global_resonance_l2_map.parquet`
  （阶段 3，理杏仁码二级行业方向分，缺失时中性 50）。

Mart 构建入口：`src/stock_analytics/marts/industry_l2_panel.py`
（`build_industry_l2_panel_frame`，注册于 `build_steps.build_industry_l2_panel` 与
`DomainMartBuilder.build_industry_l2_panel` / `build_all`）。

二级方向池 6 行业（全球共振方向池）：
半导体 270100 / 通信设备 730200 / 计算机设备 710100 / 光伏设备 630500 / 电池 630700 / 汽车（乘用车 280500）。

---

## 面板字段（`industry_l2_panel_daily`，18 列）

| 字段 | 含义 | 计算 |
| :--- | :--- | :--- |
| `trade_date` / `industry_code` / `industry_name` / `parent_l1_code` / `parent_l1_name` | 交易日与申万二级行业标识 | 来自 `industry_l2_daily` |
| `close` / `amount_yi` | 收盘价 / 成交额（亿元） | 来自 `industry_l2_daily` |
| `return_20d` / `return_60d` | 20/60 日动量（%） | 来自 `industry_l2_daily` |
| `pe_ttm_ew_percentile_5y` / `pb_ew_percentile_5y` | 5Y 滚动估值分位 | 来自 `industry_l2_daily` |
| `revenue_growth_ttm` / `profit_growth_ttm` | 营收/净利 TTM 同比 | `q.ps.toi.ttm_y2y` / `q.ps.np.ttm_y2y` |
| `gross_margin_ttm` | 毛利率 TTM | `q.ps.gp_m.ttm`（非金融；银行/证券/保险为 null） |
| `supply_demand_score` | 量价齐升质量（0-100） | 量价齐升→双增速分位；供给收缩→20；双负→10 |
| `bargaining_score` | 议价权（0-100） | 量价齐升门内→(净利−营收)增速分位；门外→30 |
| `crowding_score` | 拥挤度（0-100） | 成交额截面分位 |
| `direction_score` | 全球方向（0-100） | `global_resonance_l2_map`，缺口→中性 50 |

**量价齐升判定（供需层，L2 财务黄金表）**：
```
量价齐升 = (toi.ttm_y2y > 0) 且 (np.ttm_y2y > 0)      # 营收 + 净利 TTM 同比双正
供给收缩 = (toi.ttm_y2y ≤ 0) 且 (np.ttm_y2y > 0)      # 假繁荣：压缩成本
双负     = (toi.ttm_y2y ≤ 0) 且 (np.ttm_y2y ≤ 0)
```
报告期滞后处理：报告期 `trade_date`（季度末）数据以 `reportDate`（发布日）为可用起点，
回测中按发布日生效，避免前视偏差。

---

## 策略口径（`IndustryL2DirectionStrategy`，注册于 `stock_strategy.pool`）

```
候选 = 方向池 6 行业
  → 估值防守：pe_ttm_ew_percentile_5y <= 90（缺失放行）
  → [可选] 量价齐升硬门：revenue_growth_ttm > 0 且 profit_growth_ttm > 0
  → [可选] 方向防守门：剔除 direction_score > 66 且非量价齐升
排序：return_60d（动量，[可选] 量价齐升加分 +10）
取 Top3 等权，季度调仓（63 交易日），T+1 执行
```

实证（2020-05 起，`scripts/industry_l2_direction_qlq.py`）：

| 策略 | 全周期 Sharpe | 样本外 |
| :--- | ---: | ---: |
| 动量 Top3 + 估值防守（baseline） | 0.72 | 0.22 |
| + 量价齐升硬门 | 0.45 | 0.24 |
| + 量价齐升加分（+10） | 0.69 | 0.16 |
| + 方向防守门 | 0.46 | 0.17 |

**结论**：量价齐升与方向层在 6 行业小池 Top3 框架下均不作选股门（弱于 baseline），
保留为持仓观察与拐点预警信号；其正贡献（需求驱动 > 供给收缩）在全行业截面框架成立。

---

## 权重信任源

`config/analytics/industry_trend_tracking.yaml`（三层共振权重，当前三层因子权重 0、
不作为 composite 加分——L2 主战场为动量 Top3 + 估值防守 + 门控）。
