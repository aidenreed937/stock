# 26 发布时滞前视的影响与对齐后重估（2026-09）

> **性质**：修正一个此前未处理的回测缺陷——回测把 `report_month=M` 的出口 yoy 直接
> 对齐 `month=M` 的收益，而海关数据是次月 20 日才发布（在线查询），存在约 1 个月的
> **发布时滞前视**。本文记录对齐后的真实数字，并据此重估量拐门。
>
> **对齐方法**：新增 `release_date_for` / `effective_month`（`release_calendar.py`），
> 信号按 release_date 对齐到"发布后的下一个完整月"生效；回测脚本
> `backtest_customs_company_signal.py` / `backtest_customs_multi.py` 已改。

---

## 1. 结论速览

1. **前视贡献了约 70%~90% 的超额**：全池 base 平均超额从 +25.8pp 缩到 +7.9pp；
2. **"量拐门（quality）优于无门"被推翻**：对齐后 quality 与 base 打平（+7.9pp = +7.9pp），
   21 号文档"统一量拐门是最优门（+21.3pp）"的结论在消除前视后**不再成立**；
3. **普适性结论稳健**：全池 base 正超额占比 81%（对齐后）vs 80%（前视），信号本身
   仍普适，只是绝对收益缩水；
4. **竞争力过滤（quality_filter）仍有微弱正贡献**：对齐后 +8.6pp vs quality +7.9pp
   （+0.7pp），但远弱于前视口径的 +3.2pp。

## 2. 前视的根源

海关"在线查询数据"（`stats.customs.gov.cn`，GACC 数据源）发布时间为**次月 20 日**
（1-2 月合并 3 月 20 日，12 月次年 1 月 20 日），依据海关总署公告 2025 年第 240 号
《2026 年中国海关统计数据公布时间表》。故 `report_month=M` 的数据 M+1 月 20 日才可得，
最早 M+2 月才能完整交易；此前回测直接对齐 `month=M`，等于"用当月看不到的数据当月建仓"。

## 3. 对齐前后对比（数据事实）

### 3.1 全池三版（108 产品）

| 版本 | 前视平均超额 | 对齐后平均超额 | 前视正超额占比 | 对齐后正超额占比 |
| :-- | :-- | :-- | :-- | :-- |
| base | +25.8pp | +7.9pp | 80% | 81% |
| quality | +17.7pp | +7.9pp | 78% | 79% |
| quality_filter | +20.8pp | +8.6pp | 79% | 76% |

### 3.2 10 产品 quality 门

| 产品 | 前视 | 对齐后 |
| :-- | :-- | :-- |
| transformer | +45.1pp | +4.3pp |
| semiconductor_equipment | +153.8pp | +24.8pp |
| battery | +28.2pp | +3.7pp |
| cathode_material | +22.7pp | +0.0pp |
| silver | +49.3pp | −0.4pp |
| solar_cell | +54.2pp | +34.9pp |
| wind_turbine | +18.8pp | +11.8pp |
| 平均 | **+44.7pp** | **+8.8pp** |

## 4. 量拐门重估（对齐后）

对齐后 quality vs base **打平**（全池均 +7.9pp），且逐产品不再稳定占优：
transformer quality +4.3pp < base +9.5pp；battery quality +3.7pp < base +10.1pp；
copper quality +0.5pp < base +2.4pp。即：

- **量拐门（quality）的价值从"增强器"退化为"中性"**——它在前视口径下之所以显得
  "加分"，本质是"提前 1 个月抓住量拐"这一未来函数，而非量确认本身；
- **竞争力过滤（quality_filter）是唯一仍有正贡献的层**（对齐后 +0.7pp），但幅度微弱；
- **base（仅金额 yoy 择时）成为对齐后最简洁的等价选择**：与 quality 打平、正超额
  占比最高（81%）。

## 5. 对既有文档的修正

- METHODOLOGY §6 / 21 号文档 / SKILL 的"+21.3pp、4.50 盈亏比、统一量拐门最优门"等
  前视口径数字作废，以本文对齐后数字为准；
- "无未来函数"声明改为"已按 release_date 对齐消除发布时滞前视（2026-09 起）"。

## 6. 诚实边界

1. 对齐后的 +7.9pp 仍是"等权、月度、无成本"口径，未计手续费/滑点/市值加权；
2. 普适率（正超额占比）是稳健结论，但绝对超额对时滞敏感——拐点初期的 1~2 个月
   贡献了大部分收益，任何时点前视都会显著高估；
3. 快周期商品（铜/锂/银）对齐后银转负，维持排除结论不变。

---

## 附录：复现

```bash
# 全池对齐后回测（三版）
uv run python scripts/backtest_customs_multi.py \
  --products $(tail -n +2 config/data/customs/company_exposure_map.csv | cut -d, -f1 | sort -u | tr '\n' ' ') \
  --quality-filter --output data/analytics/industry/customs_signal_multi_fullpool_aligned.parquet
```
