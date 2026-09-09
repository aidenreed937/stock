# 25 段级择时验证（段级信号 vs 产品级信号，5 产品）

> **假设**（源自 24 号 §5）：高分化产品的产品级量价会被段结构扭曲（transformer 的
> ultra 段价涨 17 倍、量崩 98% 扭曲产品级信号），下沉到"量主力段"信号择时应优于产品级。
> 本文用 5 个有段定义产品的真实数据验证该假设。
>
> **口径**：质量门（量拐）择时，同一受益公司池等权 vs 沪深300；产品级信号取自
> `customs_product_volume_price.parquet` 主段，段级信号取自
> `customs_company_exposure.parquet` 的税号段 key。区分**数据事实**与**机制推断**。

---

## 1. 结论速览

1. **transformer 坐实机制**：mid 段信号 +67.4pp 显著优于产品级 +45.1pp，而 ultra 段
   （扭曲源）仅 +7.2pp——产品级信号确实被段结构扭曲，下沉量主力段能改善；
2. **但不普适**：5 产品里仅 transformer、cathode 的某段优于产品级，lithium 段级全不如
   产品级，silver 无差异；
3. **两个硬障碍**：① 公司段绑定与段金额占比严重错配（lithium hydroxide 占 90% 金额
   却无公司主绑）；② 无法先验识别"量主力段"（transformer 事后才知道 mid 最优）。

## 2. 信号粒度对比（数据事实）

同一公司池等权，用不同信号触发量拐门择时：

| 产品 | 信号 | 轮次 | 胜率 | 平均超额 |
| :-- | :-- | :-- | :-- | :-- |
| transformer | 产品级 | 3 | 2/3 | +45.1pp |
| | mid | 3 | 3/3 | **+67.4pp** |
| | main | 3 | 3/3 | +11.8pp |
| | small | 2 | 1/2 | +26.3pp |
| | ultra | 4 | 3/4 | +7.2pp |
| semiconductor_equipment | 产品级 | 2 | 2/2 | +23.8pp |
| | parts | 2 | 2/2 | +153.8pp |
| | fab_device | 4 | 2/4 | +28.7pp |
| | fab_wafer | 4 | 1/4 | −13.5pp |
| lithium_chemicals | 产品级 | 2 | 1/2 | +26.9pp |
| | carbonate | 2 | 1/2 | +19.4pp |
| | hydroxide | 3 | 3/3 | +18.3pp |
| | other | 2 | 1/2 | +21.8pp |
| silver | 产品级 | 3 | 2/3 | +49.3pp |
| | unwrought | 3 | 2/3 | +49.3pp |
| | wrought | 4 | 1/4 | +10.1pp |
| cathode_material | 产品级 | 3 | 3/3 | +22.7pp |
| | lfp | 3 | 2/3 | +56.6pp |
| | ncm | 3 | 3/3 | +15.5pp |

## 3. transformer：机制坐实

mid 段（量主力，2022-06 量 +110%）信号 +67.4pp、3/3 全胜，产品级 +45.1pp，ultra 段
（扭曲源，量崩 98%、价涨 17 倍）+7.2pp。梯度清晰：**量主力段 > 产品级 > 扭曲段**——
证明产品级信号被 ultra 段拖累，下沉到 mid 段能绕开。

## 4. 不普适的两个硬障碍

### 4.1 公司段绑定与段金额占比错配（lithium 典型）

税号段金额占比（`customs_company_exposure` 各 key 金额）揭示错配：

| 产品 | 金额最大段 | 占比 | 该段有无公司主绑 |
| :-- | :-- | :-- | :-- |
| lithium_chemicals | hydroxide | **90%** | 仅 3/5 家绑，无一家主绑 |
| | carbonate | 10% | 5/5 家全绑 |
| cathode_material | ncm | 96% | 4/4 家绑 |
| | lfp | 4% | 仅 1 家绑 |
| silver | unwrought | 100% | 3/3 家绑 |
| semiconductor_equipment | parts | 56% | 无公司绑（parts 段序列无对应公司） |

lithium 的 hydroxide 占 90% 金额，但公司主要绑 carbonate（10%）——段级信号与公司业务
错配，导致段级择时全部劣于产品级。这暴露的是**数据资产的段绑定质量问题**，不是
"段级择时"方法本身无效。

### 4.2 无法先验识别"量主力段"

transformer 事后知道 mid 最优，但事前面对 4 个段（mid/main/small/ultra）无从判断该选谁。
semi 的 parts 段 +153.8pp 最优，但 parts 段**没有公司绑定**（纯序列无对应持仓），无法落地。
cathode 的 lfp 段 +56.6pp 仅 1 家公司，样本无统计意义。

## 5. 先验识别量主力段的特征（§4.2 的推进）

§4.2 提出"无法先验识别量主力段"，本节给出**方向性特征**（可事前计算，无需回测）：

1. **量 yoy>0 占比**（量扩张的持续性）：真实需求段量长期为正（transformer_mid 74%、
   cathode_lfp 84%），扭曲段量频繁为负（ultra 36%、semi_fab_wafer 35%）；
2. **价 yoy 波动 std**（价的稳定性）：真实需求段价波动低（semi_parts 0.2、cathode 0.5~0.6），
   扭曲段价波动高（transformer_main 65.7、ultra 25.6、lithium_other 33.4）。

机制自洽：量 yoy>0 占比高 = 量最领先（真实需求），价波动低 = 价确认而非价驱动——
正是 METHODOLOGY §8 第 5 条候选"价 yoy 波动"的落地，并补充了"量 yoy>0 占比"量维度。

**相关性（14 段）**：量 yoy>0 占比 vs 超额 +0.38（弱正）；价 yoy 波动 vs 超额 −0.29（弱负）。
方向正确但偏弱，不是干净分类轴——反例 cathode_ncm（量 75% + 价 0.6 均健康）段级超额
仅 +15.5pp，说明还有第三因素（段绑定质量、样本数、公司池）未捕捉。

## 6. 结论

- **段级择时不是通用解法**：只在"段分化典型 + 段绑定均衡"的产品（transformer）有效；
- **先验识别量主力段的方向已找到**：量 yoy>0 占比 + 价 yoy 波动（§5），但相关性偏弱，
  需组合或强化，尚非干净分类轴（METHODOLOGY §8 第 5 条仍未闭合）；
- **可落地的一步**：对高分化产品，选"量 yoy>0 占比最高、价 yoy 波动最低"的段做主段
  信号择时——transformer 已验证（mid 段 +67.4pp vs 产品级 +45.1pp），但需人工确认。

## 7. 诚实局限

1. 段级信号来自 `customs_company_exposure.parquet`，其段绑定（taxline_segment）是
   LLM+人工维护，错配（§4.1）会直接污染段级择时结论；
2. cathode lfp、silver wrought 等段只有 0~1 家公司，段级"组合"退化为个股，超额无统计意义；
3. 段金额占比是全程聚合，掩盖了段占比的时变（如 transformer ultra 段 2022 年占比飙升）；
4. 未做段级择时的公司按段独立建仓/离场（仅做了"同一池换信号"的粒度对比），更完整的
   段级架构需重跑。

---

## 附录：复现

```bash
uv run python - <<'PY'
# 见 session 内验证脚本：对 5 产品，产品级/各段级信号分别跑 build_weight_plan(quality_gate=True)
# + split_trades，同一公司池等权，对比平均超额
PY
```
