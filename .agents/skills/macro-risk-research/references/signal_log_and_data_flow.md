# 宏观策略调仓动作日志与数据链路手册

> **文档定位**：回答「策略怎么调的、调了什么、接的什么数据」三类运维/审计问题。
> 调仓逻辑与数据链路以工程代码为唯一信任源（`src/stock_strategy/pool/` 策略类、
> `config/analytics/macro_risk.yaml` 因子配置、`data_fetchers.py` 提取器）；本页只承载
> 「日志在哪、怎么查、链路是什么」的速查说明，不维护快照数字。
>
> 以 `macro_rotation_v5_rebalance_etf`（权益封顶 70% + 国债固收）为示例策略。

---

## 1. 调仓动作日志

### 1.1 存储位置与表结构

实盘推演（`macro_strategy_live`）的调仓动作持久化在 **`data/state/quant_state.db`**（SQLite），两张表：

| 表 | 用途 | 关键列 |
| :--- | :--- | :--- |
| `signal_history` | 每次盘尾推演的策略信号快照 | `strategy_key` / `trade_date` / `panic_index` / `overheat_index` / `instructions_json` / `has_rebalance` |
| `trade_orders` | 订单执行记录 | `symbol` / `direction` / `target_weight` / `filled_price` / `reason` / `status` |

`signal_history.instructions_json` 为 JSON 数组，每条含 `symbol / direction / target_weight / reason`。

### 1.2 查询方法

```bash
uv run python -c "
import sqlite3, json
conn = sqlite3.connect('data/state/quant_state.db')
cur = conn.cursor()
cur.execute('SELECT strategy_key, trade_date, panic_index, overheat_index, instructions_json FROM signal_history ORDER BY generated_at DESC LIMIT 10')
for skey, tdate, panic, overheat, instr in cur.fetchall():
    print(f'=== {skey} @ {tdate}  Panic={panic:.1f} Overheat={overheat:.1f} ===')
    for i in json.loads(instr):
        print(f\"  {i['symbol']} {i['direction']} target_w={i['target_weight']} {i['reason'][:50]}\")
conn.close()
"
```

### 1.3 实盘日志 vs 回测信号（重要区分）

- **实盘 `signal_history`**：只在执行 `macro_strategy_live` 推演时写入，且**无调仓动作时记录为 `HOLD`**（维持当前持仓）。示例（2026-08-30，Overheat 69.2 防守态）：

  ```
  510880.SH HOLD target_w=0.35   红利（泡沫膨胀切防守）
  159915.SZ HOLD target_w=0.0    创业板（已清仓）
  511010.SH HOLD target_w=0.65   国债
  ```

- **完整调仓动作序列**（BUY/SELL/CLOSE）看回测：`uv run python -m stock_cli.macro_strategy --strategy <键>` 输出的「最近信号」，或重跑 `MacroRiskRunner.run` 取全量信号。

### 1.4 v5_rebalance_etf 最近调仓记录（回测，2026-07 ~ 08）

| 日期 | 调仓动作 | 触发逻辑 |
| :--- | :--- | :--- |
| 07-07 | 创业板 BUY→0.70，红利 CLOSE | 极度冰点全仓反击 (Panic=77.2) |
| 07-09 | 创业板 CLOSE，国债 BUY→1.00 | 泡沫破裂逃顶 (Overheat=67.5, 破MA20) |
| 07-13 | 创业板 BUY→0.70，国债 SELL→0.30 | 极度冰点全仓反击 (Panic=78.0) |
| 07-21 | 创业板 CLOSE，国债 BUY→1.00 | 泡沫破裂逃顶 (Overheat=65.7, 破MA20) |
| 07-24 | 创业板 BUY→0.70 | 极度冰点全仓反击 (Panic=75.4) |
| 07-28 | 红利 BUY→0.14，创业板 SELL→0.35，国债 BUY→0.51 | 恐慌左侧分批 (Panic=69.9, SmartMoney=44.6) |
| 08-03 | 红利/创业板 CLOSE，国债 BUY→1.00 | 泡沫破裂逃顶 (Overheat=66.3) |
| 08-05 | 红利 BUY→0.35，国债 SELL→0.65 | 泡沫膨胀切防守 (Overheat=75.3) |
| 08-19 | 红利 SELL→0.14，创业板 BUY→0.35 | 恐慌左侧分批 (Panic=73.9, SmartMoney=81.1) |
| 08-27 | 红利 BUY→0.35，创业板 CLOSE，国债 BUY→0.65 | 泡沫膨胀切防守 (Overheat=68.9) |

全周期统计（2015-01 ~ 2026-08）：549 信号 / 199 个调仓事件日，CLOSE 110 / BUY 272 / SELL 167；
各年调仓事件数：2015 年 35（股灾年）、2018 年 32（慢熊年）、2024 年仅 3（存量底震荡）、2026 年 28。

### 1.5 实证案例：2026-07 暴跌段的「逃顶预判」与「接飞刀」（调仓复盘）

背景：2026-06-22 ~ 08-10，中证全指 6624 → 5672 → 6010，创业板 4359 → 3429 → 3537，为「急跌 - 中继反弹 - 再跌 - 企稳」的剧烈震荡段。

| 日期 | 指数点位（全指/创业板）| 策略动作 | 事后结果 |
| :--- | :--- | :--- | :--- |
| 07-07 | 6246 / 3912 | 满仓创业板 (Panic=77.2) | 左侧抄底，次日续跌 |
| **07-09** | 6304 / 4018（反弹+2.4%）| **逃顶清仓 (Overheat=67.5 且破 MA20)** | **预判成真：躲过随后 -10% / -14.7% 主跌段** |
| 07-13 | 6002 / 3724 | 满仓创业板 (Panic=78.0) | ⚠️ 抄底后 07-17 再跌 -7.9%（接飞刀） |
| 07-21 | 5834 / 3686 | 逃顶清仓 (Overheat=65.7) | 躲过 07-22 起的续跌 |
| 07-24 | 5687 / 3481 | 满仓创业板 (Panic=75.4) | ⚠️ 抄底后 07-28 再跌 -4.4%（接飞刀） |
| 07-28 | 5649 / 3327 | 分批建仓 (Panic=69.9) | 中继，08-03 前仍承压 |
| 08-03 | 5653 / 3303 | 逃顶清仓 (Overheat=66.3) | 躲过最后一段下探 |
| 08-05 | 5882 / 3535 | 切防守红利 (Overheat=75.3) | ✅ 右侧反弹跟上 |

**07-09 逃顶的机制**（本轮最漂亮的一笔）：07-07~08 暴跌后 07-09 反弹 +2.4%，但价格仍低于
MA20（乖离 -1.60%）且 Overheat=67.5 仍 > 65——「泡沫破裂后的逃命波」特征。策略判定趋势已破、
反弹不可持续，在反弹日果断清仓转固收，随后一周全指 -10%、创业板 -14.7%，完全躲过。

**两面性结论**（与全周期研究一致）：
- **逃顶侧（Overheat > 65 且破 MA20）是「预判」**：07-09 / 07-21 / 08-03 三次逃顶全部躲过后续下跌，
  是本策略最稳定的 alpha 来源；
- **抄底侧（Panic > 75 满仓）是「接飞刀」**：07-13 / 07-24 两次抄底均被继续下跌套住（-7.9% / -4.4%），
  这是左侧抄底博 V 反的固有成本，属已接受的取舍而非缺陷（详见 `v5_etf_fixed_income_rebalance.md`）。

---

## 2. 调仓逻辑（v5_rebalance_etf 状态机）

先运行内部 V5 状态机（5 分支，优先级从高到低），再把权益腿目标 × 70% 封顶、余量配国债：

| 优先级 | 条件 | 权益腿目标 | 缩放后目标权重 |
| :---: | :--- | :--- | :--- |
| 0 | 乖离 Bias20 > 15% 且非恐慌区 | 清仓 0% | 固收 100% |
| 1 | Overheat > 65 且跌破 MA20 | 清仓 0% | 固收 100% |
| 2 | Overheat > 65 且 MA20 完好 | 红利 50% | 红利 35% + 固收 65% |
| 3 | Panic > 75 | 创业板 100% | 创业板 70% + 固收 30% |
| 4 | Panic 65~75 且 聪明钱 ≥ 40 | 红利 20% + 创业板 50% | 红利 14% + 创业板 35% + 固收 51% |

- **执行语义**：T 日收盘生成信号 → T+1 日生效（严格 T+1），盘尾 14:50 报单；
- **目标权重语义**：`MacroRiskRunner` 按「每日再平衡到目标权重」复利（权益永不超 70%，比季度再平衡更保守）；
- **聪明钱过滤**：恐慌左侧若 `smart_money_pct < 40`（内部人/机构未逆势接货）判定假黄金坑，不建仓。

---

## 3. 数据链路（接的什么数据）

```
原始数据源 → 领域 Mart → 宏观因子管线(config/analytics/macro_risk.yaml + data_fetchers.py)
         → risk_factors.parquet → assemble_macro_panel 装配 → 策略 on_bar
```

| 因子系列 | 数据源 | 上游输入 |
| :--- | :--- | :--- |
| 估值 erp / pb | 理杏仁 | `index_fundamental`（中证全指 pb.mcw）+ 指标引擎 ERP |
| 两融杠杆 | tushare | `market_daily` Mart（融资穿透率 / 融资买入比），T+1 平移 |
| 主力资金 | tushare | `capital_game_daily` Mart（主力净流入 / ETF净流入 / 筹码分歧），T+1 平移 |
| 市场广度 | tushare | `market_daily` Mart（涨跌家数比 / 60日新高占比） |
| 期权情绪 pcr / iv | tushare | `market_daily`（认沽认购比）+ `settlement_iv_proxy_daily` Mart |
| 恐慌 VIX | yfinance | 美股 VIX（时区平移对齐） |
| 换手拥挤 | tushare | `market_daily` Mart（全市场换手率） |
| 产业资本 | tushare | 回购 / 大宗 / 高管增减持 |
| 可转债 | tushare | `cb_daily` |
| 跨资产宏观 | lixinger / fred / yfinance | 国债收益率 / 铜金比 / 美债利差等 |
| 利率周期 ffr_chg_6m | fred | `macro_indicators`（DFF 六个月变化 pp；独立观测，不入维度） |
| 聪明钱 | tushare | `smart_money_daily` Mart（产业增持 + 大宗折价 + 国家队锚点） |

**价格数据**：基准 `000985.CSI` 中证全指（理杏仁 `index_daily_bar`）算 MA20 / 乖离；
三个 ETF（510880 红利 / 159915 创业板 / 511010 国债）用 tushare `fund_daily` + `fund_adj` 后复权算回测净值。

**产物链路**：因子原始值 → 滚动分位（`macro_risk.yaml` 的 window/min_periods）→ 维度均值 → 双轨指数
（`overheat_index` 5 维 / `panic_index` 3 维）→ `data/analytics/macro_risk/latest/risk_factors.parquet`
→ `assemble_macro_panel` 左连接基准日线 + forward fill → 逐日喂给 `MacroRiskRunner`。

> 因子方向（raw/rev）、窗口与维度构成以 `config/analytics/macro_risk.yaml` 为唯一信任源；
> 两融 T+1 平移、ETF 后复权等口径见相应因子提取器与装配代码。
