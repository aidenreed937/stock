# 聪明钱组合因子 (smart_money) 完整口径与使用手册

> **文档定位**：本文档是 `smart_money` 因子的**唯一权威口径说明**，集中维护「子信号合成 → 管线二次分位 → 策略消费 → 阈值语义」全链路，避免口径散落在 Mart / 管线 / 策略 / 复算脚本多个文件。具体数值一律以工程实现与最新产物为准，本文档不另存快照数字。

## 1. 因子定位

聪明钱（Smart Money）组合信号，刻画「知情 + 逆势接货型资金」的净买入强度，用于恐慌左侧确认**真黄金坑 vs 假黄金坑**：恐慌区若聪明钱高分位逆势接货，支持左侧分批布局；若低分位未接货，判定假黄金坑不建仓。

## 2. 三个子信号（Mart 合成层）

三个子信号**各自 0-100 滚动分位，等权合成**（`src/stock_analytics/marts/smart_money.py`）：

| 子信号 | 底层事实表 | 计算口径 | 分位窗口 (min) |
| :--- | :--- | :--- | :--- |
| `insider_score` 产业资本增持 | `insider_activity_daily` | 董监高净增持 `insider_net_buy_amount` 20 日滚动和 | 1250 日 (500) |
| `block_score` 大宗折价接盘 | `block_trade_daily` | `金额 × max(0, −折价率中位)`（金额×折价深度） | 250 日 (60) |
| `nat_score` 国家队股东锚点 | `top10_floatholders` | 汇金/证金/社保/梧桐树 `hold_change` 净增持（ann_date asof backward） | 500 日 (20) |

- 合成：`smart_money_score = mean(insider_score, block_score, nat_score)`，产物 Mart `smart_money_daily` 的列名为 `smart_money_score`，是 **0-100 组合分**（非均匀分布）。
- PIT：增持/大宗/股东数据均按公告日（`announcement_date` / `ann_date`）对齐，公告日才可用。

## 3. 管线二次分位与命名（关键口径）

宏观因子管线（`config/analytics/macro_risk.yaml`）把 Mart 组合分再经 **250 日滚动分位**，产物列名经 `score_column` 显式命名为 **`smart_money_pct`**：

- `smart_money_score`（Mart 组合分）：0-100，非均匀，三子分位等权合成。
- `smart_money_pct`（管线产物，分位排名）：0-100，均匀，组合分在近 250 日的历史排名。
- `dim_smart_money`（管线维度）：单因子维度，数值恒等于 `smart_money_pct`，无策略消费。

> ⚠️ 命名陷阱（已通过改名根除）：历史上 Mart 组合分与管线分位排名曾共用 `smart_money_score` 同名，导致二次分位化语义被遮蔽。现 Mart 列保留 `smart_money_score`，管线产物列改名 `smart_money_pct`，二者口径不同、勿混淆。

## 4. 策略消费矩阵

策略通过 `assemble_macro_panel` 的 `extra_cols` 白名单拿到 `smart_money_pct`，**不读 `dim_smart_money`**：

| 策略 | 阈值 (config) | 用法 |
| :--- | :--- | :--- |
| `macro_rotation_v5` / `v6` | `smart_filter_threshold: 40` | 恐慌左侧（Panic 65~75）`smart_money_pct < 40` → 假黄金坑，不建仓 |
| `macro_meta_router` | `smart_support_threshold: 80` | 恐慌区 `smart_money_pct >= 80`（或回购/产业资本 >= 80）→ 托底共振，左侧防踩踏 |
| `macro_all_weather` | `smart_support_threshold: 80` | 同上，托底共振触发权益反弹 |

## 5. 阈值语义

阈值针对的是**分位排名** `smart_money_pct`（0-100 均匀分位）：

- `< 40` = 聪明钱强度处于近 250 日**后 40%** → 未逆势接货（假黄金坑）。
- `>= 80` = 处于近 250 日**前 20%** → 强托底共振。

## 6. 复算脚本情景定义

`scripts/compute_cycle_winrate_matrix.py` 的胜率情景直接引用 `smart_money_pct`：

- 聪明钱逆势接货：`smart_money_pct >= 80`；
- 真黄金坑：`panic_index > 65 and smart_money_pct >= 80`。

## 7. 证伪边界

- `etf_flow_ratio`（ETF 份额托底代理）已证伪（与国家队真实增持无关、无前瞻收益、V5 托底分支净值贡献为负），**不作为国家队识别与交易信号**；本因子 `smart_money` 是替代口径。
- `smart_money` 刻意**不加入 `overheat_index` / `panic_index`** 双轨指数，保持双轨指数成分纯净。
- 实证产物：`data/analytics/macro_strategy/smart_money_composite.md`。

- **门控降噪平滑已证伪（2026-10-27，全周期回测）**：`smart_money_pct` 日频跳变确实剧烈
  （60 日内穿越 40 阈值 18 次、日间标准差 27pp、最大单日跳变 94pp），但把门控换成滚动均值反而更差：

  | 变体 | v5_etf CAGR | v5_etf MaxDD | v5_rebalance_etf 净值 | v5_hike_gate_etf MaxDD |
  | :--- | :---: | :---: | :---: | :---: |
  | 原始日频（现行） | 15.35% | -36.95% | 3.853 | -18.84% |
  | 3D 均值 | 14.49% | -39.07% | 3.621 | -21.17% |
  | 5D 均值 | 13.86% | -38.76% | 3.461 | -21.03% |

  机制：平滑同时滞后了「未逆势接货」的判定，使策略在下跌途中更早建仓 → 收益下降、回撤加深。
  故门控保留原始日频分位，噪声登记为已知特性；若要再试，应先验证状态化解法（如滞回带 进场 35 / 出场 50），
  并跑 `macro_strategy_report` + `macro_strategy_audit --assert-guardrails` 复核。

## 8. 工程入口速查

| 环节 | 入口 |
| :--- | :--- |
| Mart 合成 | `src/stock_analytics/marts/smart_money.py`（`build_smart_money_frame`）、`smart_money_build.py`（`build_smart_money`） |
| 因子提取 | `src/stock_analytics/pipelines/macro_risk/data_fetchers.py` `@register_fetcher("smart_money")` |
| 二次分位 + 命名 | `src/stock_analytics/pipelines/macro_risk/pipeline.py`（`score_column`）+ `config/analytics/macro_risk.yaml` |
| 面板透传 | `src/stock_strategy/macro/assembly.py` `extra_cols` |
| 策略消费 | `src/stock_strategy/pool/macro_rotation_v5.py` / `v6` / `macro_meta_router.py` / `macro_all_weather.py` |
| 报告解读 | `src/stock_reporting/interpretation/macro_risk/logic.py` |
