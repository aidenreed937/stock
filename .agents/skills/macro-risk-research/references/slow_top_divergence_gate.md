# 中期顶背离慢速减仓闸门（Slow Top-Divergence Gate）研究留档

> **文档定位**：本页记录 `macro_rotation_v5_rebalance_etf` 叠加「中期顶背离」慢速减仓闸门后的
> 实证评估，回答「`copper_gold_score` / `cb_price_score` 这两个最强最稳的慢变量因子该如何
> 运用」「能否在不牺牲收益的前提下压制回撤」。为一次性研究留档，不进入策略运行链路之外的承诺。
>
> **数字铁律**：全周期与样本外数字由 `macro_strategy_audit --walk-forward --assert-guardrails`
> 及 `scripts/macro_slow_gate_walkforward.py`（`MacroSlowTopDivergenceStrategy`）产出，可复算、可对账；
> 本页不另存快照。

---

## 一句话结论

- **`copper_gold_score` / `cb_price_score` 不适合塞进 `overheat_index`（§5.3 已证伪），但适合独立
  合成「中期顶背离」慢速减仓闸门**：当二者同时处于历史高分位（`dim_slow>=80`）时把权益封顶从
  70% 降至 30%、余量转固收。
- **全走行-Forward 样本外后定位明确：回撤抑制/防守增强层，非 alpha 增强**。OOS 拼接夏普
  0.88→0.93、最大回撤 -21.09%→-19.53%，收益不降反微升（CAGR +0.24pp）；核心价值在防守市主跌段
  （2021-03~2022-04：MDD -18.5%→-8.5%，+9.98pp）。
- **改进空间不在于增强，而在于「把回撤从小幅削到可感知」**：常态静默、只在真正的慢速顶背离
  高位区砍仓，牛市不乱动，代价极小。

---

## 落地状态（2026-09-03）

已落地为组合层策略 **`macro_slow_top_divergence_etf`**（类 `MacroSlowTopDivergenceStrategy`，
继承 `MacroRotationV5RebalanceStrategy`）：

- 行为：V5 权益状态机完全复用；仅「权益封顶」根据慢速顶背离在 `equity_cap=0.7` 与
  `gate_cap=0.30` 间动态切换（`dim_slow = mean(copper_gold_score, cb_price_score)`，
  `>= gate_threshold=80` 激活，`< gate_off_threshold=60` 解除）。
- **口径修正（相对初版原型）**：`copper/cb_score` 本身已是 0-100 滚动历史分位排名，故
  **直接做绝对高位判断、不做二次滚动分位**（对已分位值再分位会对恒定序列退化为「常数高分位」，
  牛市误伤）。初版滚动分位原型行为发散发，本次用绝对高位口径。
- **全周期**：CAGR 13.16%→13.11%、MaxDD -21.09%→-19.53%、Sharpe 0.79→0.82（th80/cap45 档）；
  更进取的 cap30 档全周期 Sharpe 0.85、MaxDD -19.53%。
- **滚动样本外（3Y IS→1Y OOS）**：拼接 OOS CAGR +13.39%、MaxDD **-20.07%**、Sharpe **0.85**
  （基底 v5_rebalance_etf CAGR +13.25% / MaxDD -21.30% / Sharpe 0.81）、WFE 2.07、有效切片 100%、
  评级「极强抗过拟合」，且 `--assert-guardrails` 回归断言通过。

---

## 1. 动机与背景

- **因子证据**（见 `docs/research/macro/factor_selection_methodology.md` §7）：`copper_gold_score`
  60D IC -0.33、`cb_price_score` -0.209，是 5 个「严格通过」单因子中 IC 最强、年度符号最稳的两个
  （copper 12 年 9 负 / cb 8 年 7 负），属「规律型」而非「时点型」因子。
- **为什么不能进 overheat**（§5.3 已证伪）：二者是慢变量（信号集中在 60D），混入服务 20D 短线
  防守的 overheat 会稀释其防守敏感度，全策略回测全面劣化（Sharpe -0.13~0.17、CAGR -1~2.6pp）。
- **独立用法**：把「慢速顶背离」作为单独的防御闸门，落点正好是它们最强的 60D 窗口。
- **循序渐进的教训**：初版「滚动分位」原型结果偏乐观（牛市也乱动），修正为「绝对高位」后行为
  克制、却在防守市更准——**对已分位因子必须用绝对高位，不能用二次相对分位**。

---

## 2. 收益/风险对比（全周期，含基底）

| 策略 | 全周期 CAGR | MaxDD | Sharpe |
| :--- | :---: | :---: | :---: |
| macro_rotation_v5_etf（纯权益）| ~14.8% | -33.8% | ~0.63 |
| macro_rotation_v5_rebalance_etf（基底 70/30）| 13.16% | -21.09% | 0.79 |
| **macro_slow_top_divergence_etf（th80/cap45）** | **13.11%** | **-19.53%** | **0.82** |
| macro_slow_top_divergence_etf（th80/cap30）| 13.33% | -19.53% | **0.85** |

- 相对于基底 rebalance，慢速闸门**几乎不牺牲收益**（CAGR 基本持平或微升），却把 MaxDD 再压 ~1.6pp、
  Sharpe 提升 0.03~0.06 —— 符合「防守增强、非 alpha」定位。

---

## 3. Walk-Forward 样本外关键证据（th80/cap30）

拼接 OOS 全区间：CAGR 14.26%→14.50%（+0.24pp）、MaxDD -21.09%→-19.53%（浅 1.56pp）、
Sharpe 0.88→0.93（+0.05）。

逐切片（3Y IS → 1Y OOS）中最关键段：

| OOS 区间 | 基底 DD | 闸门 DD | DDΔpp | 基底 CAGR | 闸门 CAGR | CAGRΔ |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| 2021-03~2022-04（存量防守主跌）| -18.49% | **-8.51%** | **+9.98** | 11.03% | **13.01%** | **+1.98** |

- 该段是闸门价值核心：copper/cb 处历史高位 + 随后真跌，闸门抓准。
- 其余 8 段基本静默（SRΔ≈0），说明闸门**在非高位区不乱动**（这是「绝对高位」口径的核心优势）。

---

## 4. 定位与使用原则（避免误用）

1. **是回撤抑制层，不是 alpha 增强**：OOS CAGR 只 4/9 切片战胜基底，进攻端无稳定超额；
   夏普提升主要来自防守市那段大回撤的削减。
2. **依赖「高位×随后熊市」组合**：若 copper/cb 高位但后市继续涨（牛市顶背离不兑现跌），闸门
   会承受阶段性踏空成本（如 2025-05~2026-06 牛市小幅拖累 CAGR）。
3. **适合叠加在 rebalance 之上作防御层**，不适合当独立、主进攻信号。

---

## 5. 局限披露

1. **样本外有效证据集中在单一防守段**（2021-22），9 个 OOS 切片中回撤压制主要由该段贡献，
   普适性有待更多防守段积累。
2. **参数（th80/cap30）为全样本 in-sample 选定**，虽经 walk-forward 验证同一固定规则在 OOS
   成立，但仍有 in-sample 调参残余风险；其余参数格（cap45/th80、cap30/th90）结论方向一致。
3. **铜/金、转债中位数断层**：2022 后恐慌日内部人连续增持取值为 0（结构条件变化），同源
   「结构过时」风险需关注 `copper_gold/cb_price` 的分数是否持续有效（IC 复审机制持续监控）。

---

## 6. 复现方法

1. `uv run python -m src.stock_cli.macro_risk --as-of <最新交易日>` 生成 `risk_factors.parquet`
   （含 `copper_gold_score` / `cb_price_score`）；
2. `uv run python scripts/macro_slow_gate_walkforward.py --gate-cap 0.30 --gate-threshold 80` 复算 OOS；
3. `uv run python -m stock_cli.macro_strategy_audit --walk-forward --assert-guardrails` 走正式审计；
4. 当前信号：`uv run python -m stock_cli.macro_strategy_live --strategy macro_slow_top_divergence_etf --dry-run`。

> 本文的复算逻辑已固化为策略类 `src/stock_strategy/pool/macro_slow_top_divergence.py`，
> 配置在 `config/strategy/macro_risk.yaml`，回测/审计经 `macro_strategy_audit` 产出，无需再手动复算。
