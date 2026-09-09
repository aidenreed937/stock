# 24 出口产品量价结构分类（全池 108 产品，2020-2026）

> **性质**：把默认 10 产品的量价分化外推到全池 108 产品，做**描述性**量价结构分类。
> 本文一个重要产出是**证伪了"量价结构 → 量拐门适用性"的因果**（见 §4），这一点强化了
> 21 号文档 §6 的既有结论。区分**数据事实**（序列/驱动占比/回测）与**机制推断**（归类）。
>
> **数据口径**：GACC 黄金表各产品主段金额 3MMA yoy，2019-2026；驱动占比 = 各驱动类型
> 出现月数 / 有效月数；std_yoy 为金额 yoy 标准差（pp）。回测 `backtest_customs_multi.py`。

---

## 1. 重要更正（相对本文初版）

初版曾论断"量拐门最优适用区 = 量价同动成长"，**该论断被全池数据推翻**（见 §4）：

- battery 量价齐升占比 **62%**（全池最"量价同动"），量拐门 delta **−20.8pp（受害）**；
- transformer 量价齐升占比 **4%**（价驱动 55%），量拐门 delta **+12.7pp（受益）**。

故本文四型只做**量价运行形态的描述性分类**，不再声称能预测量拐门收益。

## 2. 量价结构四型（描述性定义）

| 类型 | 量价关系特征 | 判定口径 |
| :-- | :-- | :-- |
| A 量价同动 | 量价齐升占比高 | qq≥35% 且 qq≥价驱动占比 |
| B 量驱动/价驱动主导 | 量价齐升占比低，量或价单腿主导 | 成长组中非 A |
| C 内销/政策 | 内销机械（出口非主导） | 18 号文档四轴标签 |
| D 价格脉冲 | 金额 yoy 波动极大（价主导/低基数） | std_yoy≥100pp |

## 3. 全池归类（108 产品）

### 分型统计

| 类型 | 产品数 | 代表 |
| :-- | :-- | :-- |
| A 量价同动 | 16 | battery、copper_wire、battery_copper_foil、cathode_material、semiconductor_ic |
| B 量驱动/价驱动主导 | 66 | transformer、solar_cell、semi、server、optical_module、wind_turbine |
| C 内销/政策 | 5 | forklift、excavator、crane、wheel_loader、machine_tool |
| D 价格脉冲 | 21 | copper、silver、lithium、zinc、urea、铝/钢/煤、bev/hev/phev |

### 完整名单（108 产品）

**A 量价同动（16）**：battery、copper_wire、battery_copper_foil、battery_electrolyte、
aluminum_sheet、auto_chassis、cathode_material、refrigerant、aluminum_foil、semiconductor_ic、
vitamins、auto_glass、auto_parts、commercial_nev、nylon_filament、tio2。

**C 内销/政策（5）**：forklift、wheel_loader、excavator、crane、machine_tool。

**D 价格脉冲（21）**：silver、bev、aluminum_unwrought、caustic_soda、zinc、
copper_unwrought、diagnostic_immunological、hev、lithium_chemicals、methanol、
ethylene_glycol、urea、coal、pharma_vaccines、fuel_cell、compound_fertilizer、
alloy_steel、hot_rolled_steel、phev、soda_ash、potash_fertilizer。

**B 量驱动/价驱动主导（66）**：其余全部产品，含 inverter、pcb、auto_electronics、
knit_apparel、seamless_steel_tube、shipbuilding、auto_wheel、battery_aluminum_foil、
phosphoric_acid、wind_parts、api_paracetamol、auto_tire、battery_separator、
electrolyte_salt、phosphate_fertilizer、television、anode_material、auto_body、
wind_turbine、cathode_precursor、coke、flat_panel_module、polyester_staple、flat_glass、
washing_machine、auto_drive_motor、ceramic_tile、hydrogen_electrolyzer、polyester_fabric、
motorcycle、plant_extract、refrigerator、semiconductor_equipment、battery_parts、furniture、
mdi、pesticide、server、technical_ceramic、woven_apparel、glass_fiber、power_tools、
robot_vacuum、small_appliance、api_heparin、wireless_earbud、pharma_chemicals、
refined_products、smartphone、optical_module、viscose_staple、air_conditioner、coated_steel、
antibiotics、home_textile、ammonium_nitrate、network_equipment、audio_device、laptop、
polyester_filament、seating、solar_cell、aquatic_products、medical_device、polysilicon、
transformer。

## 4. 核心证伪发现：量价结构不预测量拐门收益

这是本文最重要的事实发现，再次印证 21 号文档 §6（`mode=价驱动` 分类轴不可用）：

| 产品 | 量价齐升占比 | 量拐门 delta（21 号 §5） | 判断 |
| :-- | :-- | :-- | :-- |
| battery | 62% | −20.8pp | 最"量价同动"，却受害 |
| transformer | 4% | +12.7pp | 最"价驱动"，却受益 |

**机制解释**（21 号文档 §5 的原结论仍然成立）：量拐门受害与否取决于"价驱动阶段是
真涨前奏（量滞后）还是伪景气（量没动）"，而这个区分**无法从驱动类型占比/量价齐升
占比这类结构指标读出**——battery 的价驱动是"真涨前奏"，transformer 的价驱动是"伪景气"，
两者结构占比完全不同，但决定 delta 的是价驱动阶段的**性质**，不是占比。

**结论**：量拐门适用性的分类轴（候选：价 yoy 领先量 yoy 的相关性 / 价 yoy 波动）仍未
找到，维持 METHODOLOGY §8 第 5 条的后续研究定位。本文四型仅作产品特征的描述性分类，
不作选门依据。

## 5. 产品特性根源：段级异质性（同质 vs 异质）

§4 证伪了"量价结构 → 量拐门收益"，本节给出**产品特性层面的根因**：量拐门受害/受益，
取决于产品内部有无强段分化（段级异质性），这决定"价驱动"是"真实需求拉动的前奏"还是
"段结构升级的假象"。

### 5.1 battery（同质 → 真涨前奏 → 受害）

电芯相对同质（无 ultra/main/mid/small 这类单价差十几倍的段）。2020 年初价驱动阶段：

| 指标 | 数值 | 含义 |
| :-- | :-- | :-- |
| 量 yoy | −11%~−18% | 浅跌（产能爬坡滞后） |
| 价 yoy | +22%~+35% | 温和涨（需求拉动） |

量浅跌、价温和涨 = 需求起来、价先反应、量 5 个月后转正（2020-08）。量拐门等量转正，
白等 5 个月、错过 +78% 涨幅 → 受害。

### 5.2 transformer（异质 → 段结构升级假象 → 受益）

transformer 有 4 个税号段（ultra 特高压 / main / mid / small），单价差 17 倍以上。
2022-06 段级量价：

| 段 | 量 yoy | 价 yoy | 性质 |
| :-- | :-- | :-- | :-- |
| ultra（特高压） | −98% | +1753%（17.5 倍） | 结构升级（低端→高端） |
| mid（中压，量主力） | +110% | −0.5% | 健康量驱动（真实需求） |
| main | −32% | +82% | 温和 |
| **产品级聚合** | **−56%** | **+125%** | 被 ultra 段扭曲 |

产品级"价驱动"是 ultra 段的极端价涨（量崩 98%、价涨 17 倍）主导，真实需求在 mid 段
（量 +110%）。产品级聚合把"mid 段真实量驱动"与"ultra 段结构升级假象"搅在一起，ultra
极端价涨淹没 mid 的量，使产品级看起来是"量崩 + 价涨"的伪景气。量拐门等产品级量转正，
恰好躲过 ultra 段结构升级的假象 → 受益。

### 5.3 意义与边界

- 这坐实了 skill 核心命题的微观机制："行业层区分度不足、交易信号落公司层/段级；transformer
  产品 +34% 内部 ultra 段 +111%"——**高分化产品的产品级量价会被段结构扭曲，须下沉段级
  才能看清真实量驱动**；
- 但"同质/异质"只干净解释 battery、transformer 两个极端案例；中间态（server/refrigerant/
  machine_tool）价驱动阶段的量价深度混杂，不能靠"有无段定义"二分——分类轴仍待研究
  （METHODOLOGY §8 第 5 条）。

## 6. D 型（价格脉冲）内部的边界问题

D 型按 std_yoy≥100pp 切分，但混入了两类不同成因：

1. **真·商品价格脉冲**：铜/银/锂/锌/尿素/甲醇/乙二醇/钢材/煤/化肥等——价主导、
   量价脱钩，月度确认滞后于商品脉冲（对应快周期排除）；
2. **低基数/疫情脉冲**：bev/hev/phev（新能源车 2019 低基数爆发）、pharma_vaccines
   （疫苗）、diagnostic_immunological（诊断）——std 高来自基数效应，非商品价格脉冲。

故 D 型内部并不均质：前一类维持快周期排除；后一类（新能源车/医药）的周期结构判断
需单独评估，不能与铜/锂/银同等对待。

## 7. 诚实局限

1. 驱动占比是**全程统计**，掩盖了"同一产品不同阶段的驱动切换"（如 transformer 价驱动
   伪景气期 vs 量驱动真景气期），这也是它无法预测量拐门 delta 的直接原因；
2. std_yoy 阈值 100pp 会把低基数爆发（新能源车/医药）误入价格组，见 §5；
3. 四型是描述性归纳，任何"某型更适用量拐门"的因果推断都需先过 §4 的证伪检验。

---

## 附录：复现

```bash
# 全池三版回测（108 产品）
uv run python scripts/backtest_customs_multi.py \
  --products $(tail -n +2 config/data/customs/company_exposure_map.csv | cut -d, -f1 | sort -u | tr '\n' ' ') \
  --quality-filter
```
