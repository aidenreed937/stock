# overheat 逃顶阈值鲁棒性（引用说明）

> 本页只维护**定性结论与决策边界**，具体数字与回测明细一律以工程产物为准（见文末引用路径），
> 不在本文档复制快照数据。

## 一句话结论

V5/V6 状态机的 `overheat_threshold` 是参数风险最集中的维度，鲁棒性**不对称**：
**向下（55~62）容错大、全面可用；向上（66+）悬崖陡峭**（ETF 口径回撤恶化至约 -54%、夏普崩塌）。
配置值 **65 处于安全区末端、悬崖边缘**，任何把阈值调高的改动都是红线。

## 决策边界（引用要点）

- **悬崖位置**：ETF 口径 66→68 之间回撤跳升约 8pp、夏普从 0.43 崩至 0.34；>66 不可取。
- **安全区**：55~62 全周期与滚动样本外（OOS）均不劣于 65；62 是经 OOS 验证的防守备选
  （OOS 回撤更浅、夏普更高，全周期收益反而更高）。
- **65 的适用前提**：牛市/结构牛行情持续性强（过热后"高位钝化继续涨"），晚防守吃满行情
  的收益大于回撤代价；一旦范式切换为慢熊或过热快速破位，应评估下移至 62。
- **2026-08 决策**：当前范式六（政策新质牛）结构牛持续性强，维持 `overheat_threshold: 65.0` 不变；
  本页作为未来范式切换时的重新评估依据。

## 机制要点（防误用）

- **2018 教训**：2018-01 overheat 峰值仅 62.8，配置 65 全年无 overheat 动作（2018 防御全靠
  panic 分支兜底）；阈值差 2~3 点 = 逃顶 vs 裸奔。
- **2015 机制**：低阈值提前数日切防守在快速崩塌中价值巨大；高阈值"少横跳"只是偶然红利，
  代价是漏掉后续所有过热事件。
- **ma_window 敏感性远小于 overheat**：调参风险集中在 overheat 单一维度。

## 引用产物路径

- 细网格全表（132 组合）：`data/analytics/macro_strategy/robustness/overheat_sweep.csv`
- 验证报告：`data/analytics/macro_strategy/robustness/overheat_sensitivity_report.md`
- OOS 明细（oh=60/62/65）：`data/analytics/macro_strategy/robustness/overheat_walkforward.json`
- 机制分析脚本（可复跑）：`data/analytics/macro_strategy/robustness/_overheat_mech.py`
- 旧版参数网格（注意：生成于乖离止盈提交前，数字已过期）：`data/analytics/macro_strategy/robustness/robustness_report.md`
