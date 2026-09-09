# 18 景气周期分组速查表（108 产品 × 三轴，2026-09）

> 本文是 108 产品的**三轴分组完整清单**（速查），定义与机制见
> `METHODOLOGY_COMPANY_FINAL.md` §5.4/§6.2/§8；本文不重述推导，只落完整名单。
>
> **三轴**（正交，不互斥）：
> - **周期结构**（§6.2）：产品主段 3MMA yoy 波动 std（2021-08~2026-07 窗口），
>   std≥100pp = 高波动价格组（价格性周期），std<100pp = 低波动成长组（成长性周期）；
> - **内销主导**（§8.4）：叉车/挖掘机/起重机/装载机/锻压机床，股价由内销周期主导，
>   出口信号不适用；
> - **低毛利/价格战**（§5.4 产品级）：产品中位毛利率<15% 且中位 ROE<10% = 价格战/
>   产能过剩环节，静态组合用 `--product-gate` 剔除。

---

## 1. 分组汇总

| 轴 | 组 | 产品数 |
| :-- | :-- | :-- |
| 周期结构 | 高波动价格组 | 19 |
| | 低波动成长组 | 89 |
| 内销主导 | 内销机械 | 5 |
| 低毛利/价格战 | 低毛利产品 | 32 |

> 低毛利 32 与周期结构**正交重叠**：其中 7 个同时在高波动价格组（锌/铜/热轧/镀层钢/
> 烧碱/合金钢/纯碱），25 个在成长组（光伏/铜箔/正极/风电/多晶硅等价格战环节）。

## 2. 高波动价格组（19，std≥100pp，价格性周期）

- **大宗/化工 14**：尿素、热轧卷板、锌、钾肥、乙二醇、甲醇、锂盐、未锻轧精炼铜、
  复合肥、纯碱、烧碱、未锻轧铝、煤、合金钢；
- **新能源车 4**：纯电乘用车、混动乘用车、新能源商用车、燃料电池；
- **疫苗 1**：疫苗及免疫制品。

## 3. 内销主导（5，§8.4）

叉车、挖掘机、起重机、装载机、锻压机床。

## 4. 低毛利/价格战（32，产品中位毛利率<15% 且中位ROE<10%）

按中位毛利率升序（括号内：中位毛利率%/中位ROE%）：

焦炭(2/-13)、光伏电池组件(2/-20)、多晶硅(3/-3)、精炼铜丝(4/8)、聚酯短纤(5/1)、
锌(5/3)、锂电池铜箔(5/1)、聚酯长丝机织物(6/5)、未锻轧精炼铜(6/9)、锂电池铝箔(7/2)、
热轧卷板(7/5)、镀层钢板(8/3)、硝酸铵(9/0)、聚酯长丝(9/6)、三元正极材料(9/4)、
铝箔(9/3)、钛白粉(10/-1)、风电整机(10/5)、无缝钢管(10/7)、锦纶长丝(10/3)、
电解制氢设备(10/4)、纯碱(11/-1)、粘胶短纤(12/0)、船舶制造(13/6)、彩色电视机(13/7)、
汽车铝车轮(14/2)、平板显示模组(14/2)、成品油(15/7)、平板玻璃(15/4)、三元前驱体(15/8)、
烧碱(15/1)、合金钢(15/5)。

---

## 5. 完整 108 产品三轴表（价格组在前，成长组在后，按产品键排序）

| 产品 | 中文名 | 周期结构 | 内销 | 低毛利 |
| :-- | :-- | :-- | :-- | :-- |
| alloy_steel | 合金钢板材 | 价格组(103pp) |  | 低毛利(15%/5%) |
| aluminum_unwrought | 未锻轧铝 | 价格组(118pp) |  |  |
| bev | 纯电动乘用车 | 价格组(141pp) |  |  |
| caustic_soda | 烧碱 | 价格组(129pp) |  | 低毛利(15%/1%) |
| coal | 煤 | 价格组(113pp) |  |  |
| commercial_nev | 新能源商用车 | 价格组(104pp) |  |  |
| compound_fertilizer | 复合肥 | 价格组(158pp) |  |  |
| copper_unwrought | 未锻轧精炼铜 | 价格组(198pp) |  | 低毛利(6%/9%) |
| ethylene_glycol | 乙二醇 | 价格组(412pp) |  |  |
| fuel_cell | 燃料电池 | 价格组(110pp) |  |  |
| hev | 混合动力乘用车 | 价格组(242pp) |  |  |
| hot_rolled_steel | 热轧卷板 | 价格组(6257pp) |  | 低毛利(7%/5%) |
| lithium_chemicals | 锂盐 | 价格组(206pp) |  |  |
| methanol | 甲醇 | 价格组(402pp) |  |  |
| pharma_vaccines | 疫苗及免疫制品 | 价格组(4365pp) |  |  |
| potash_fertilizer | 钾肥 | 价格组(487pp) |  |  |
| soda_ash | 纯碱 | 价格组(154pp) |  | 低毛利(11%/-1%) |
| urea | 尿素 | 价格组(8959pp) |  |  |
| zinc | 锌 | 价格组(1058pp) |  | 低毛利(5%/3%) |
| air_conditioner | 家用空调 | 成长组(19pp) |  |  |
| aluminum_foil | 铝箔 | 成长组(34pp) |  | 低毛利(9%/3%) |
| aluminum_sheet | 铝板带 | 成长组(48pp) |  |  |
| ammonium_nitrate | 硝酸铵 | 成长组(72pp) |  | 低毛利(9%/0%) |
| anode_material | 石墨负极材料 | 成长组(34pp) |  |  |
| antibiotics | 抗菌素 | 成长组(9pp) |  |  |
| api_heparin | 原料药(肝素钠等) | 成长组(22pp) |  |  |
| api_paracetamol | 对乙酰氨基酚 | 成长组(28pp) |  |  |
| aquatic_products | 水产品 | 成长组(20pp) |  |  |
| audio_device | 耳机及声学设备 | 成长组(15pp) |  |  |
| auto_body | 汽车车身及附件 | 成长组(16pp) |  |  |
| auto_chassis | 汽车底盘系统 | 成长组(10pp) |  |  |
| auto_drive_motor | 汽车驱动电机 | 成长组(13pp) |  |  |
| auto_electronics | 汽车电子电气系统 | 成长组(11pp) |  |  |
| auto_glass | 汽车安全玻璃 | 成长组(14pp) |  |  |
| auto_parts | 汽车其他零部件 | 成长组(15pp) |  |  |
| auto_tire | 其他车辆轮胎 | 成长组(9pp) |  |  |
| auto_wheel | 汽车铝车轮/轮毂 | 成长组(10pp) |  | 低毛利(14%/2%) |
| battery | 锂电池与储能 | 成长组(35pp) |  |  |
| battery_aluminum_foil | 锂电池铝箔 | 成长组(21pp) |  | 低毛利(7%/2%) |
| battery_copper_foil | 锂电池铜箔 | 成长组(39pp) |  | 低毛利(5%/1%) |
| battery_electrolyte | 锂电池电解液 | 成长组(24pp) |  |  |
| battery_parts | 蓄电池零部件 | 成长组(37pp) |  |  |
| battery_separator | 锂电池隔膜 | 成长组(13pp) |  |  |
| cathode_material | 三元正极材料 | 成长组(92pp) |  | 低毛利(9%/4%) |
| cathode_precursor | 三元前驱体 | 成长组(47pp) |  | 低毛利(15%/8%) |
| ceramic_tile | 瓷砖 | 成长组(24pp) |  |  |
| coated_steel | 镀层钢板 | 成长组(56pp) |  | 低毛利(8%/3%) |
| coke | 焦炭及半焦炭 | 成长组(88pp) |  | 低毛利(2%/-13%) |
| copper_wire | 精炼铜丝 | 成长组(57pp) |  | 低毛利(4%/8%) |
| crane | 起重机 | 成长组(27pp) | 内销 |  |
| diagnostic_immunological | 免疫诊断制品 | 成长组(98pp) |  |  |
| electrolyte_salt | 六氟磷酸锂 | 成长组(65pp) |  |  |
| excavator | 挖掘机 | 成长组(46pp) | 内销 |  |
| flat_glass | 平板玻璃 | 成长组(73pp) |  | 低毛利(15%/4%) |
| flat_panel_module | 平板显示模组 | 成长组(10pp) |  | 低毛利(14%/2%) |
| forklift | 叉车 | 成长组(26pp) | 内销 |  |
| furniture | 木制家具 | 成长组(9pp) |  |  |
| glass_fiber | 玻璃纤维 | 成长组(27pp) |  |  |
| home_textile | 棉制卫生及厨房用纺织品 | 成长组(9pp) |  |  |
| hydrogen_electrolyzer | 电解制氢设备 | 成长组(45pp) |  | 低毛利(10%/4%) |
| inverter | 逆变器 | 成长组(17pp) |  |  |
| knit_apparel | 针织T恤 | 成长组(15pp) |  |  |
| laptop | 笔记本电脑 | 成长组(14pp) |  |  |
| machine_tool | 锻压机床 | 成长组(38pp) | 内销 |  |
| mdi | 聚合MDI | 成长组(31pp) |  |  |
| medical_device | 医疗设备 | 成长组(15pp) |  |  |
| motorcycle | 摩托车 | 成长组(16pp) |  |  |
| network_equipment | 通信网络设备 | 成长组(12pp) |  |  |
| nylon_filament | 锦纶长丝 | 成长组(32pp) |  | 低毛利(10%/3%) |
| optical_module | 光通信收发模块 | 成长组(18pp) |  |  |
| pcb | 印制电路板 | 成长组(19pp) |  |  |
| pesticide | 农药原药及制剂 | 成长组(47pp) |  |  |
| pharma_chemicals | 化学药制剂 | 成长组(9pp) |  |  |
| phev | 插电混动乘用车 | 成长组(65pp) |  |  |
| phosphate_fertilizer | 磷肥 | 成长组(56pp) |  |  |
| phosphoric_acid | 磷酸 | 成长组(74pp) |  |  |
| plant_extract | 植物提取物 | 成长组(30pp) |  |  |
| polyester_fabric | 聚酯长丝机织物 | 成长组(17pp) |  | 低毛利(6%/5%) |
| polyester_filament | 聚酯长丝 | 成长组(13pp) |  | 低毛利(9%/6%) |
| polyester_staple | 聚酯短纤 | 成长组(12pp) |  | 低毛利(5%/1%) |
| polysilicon | 多晶硅 | 成长组(94pp) |  | 低毛利(3%/-3%) |
| power_tools | 电动工具 | 成长组(19pp) |  |  |
| refined_products | 成品油 | 成长组(42pp) |  | 低毛利(15%/7%) |
| refrigerant | 制冷剂(三代氟化工) | 成长组(72pp) |  |  |
| refrigerator | 家用冰箱 | 成长组(22pp) |  |  |
| robot_vacuum | 扫地机器人及吸尘器 | 成长组(14pp) |  |  |
| seamless_steel_tube | 无缝钢管 | 成长组(60pp) |  | 低毛利(10%/7%) |
| seating | 可转换床座椅 | 成长组(17pp) |  |  |
| semiconductor_equipment | 半导体设备 | 成长组(22pp) |  |  |
| semiconductor_ic | 集成电路芯片 | 成长组(31pp) |  |  |
| server | 服务器及计算机处理单元 | 成长组(18pp) |  |  |
| shipbuilding | 船舶制造 | 成长组(74pp) |  | 低毛利(13%/6%) |
| silver | 白银 | 成长组(48pp) |  |  |
| small_appliance | 厨房电热器具 | 成长组(11pp) |  |  |
| smartphone | 手机 | 成长组(12pp) |  |  |
| solar_cell | 光伏电池及组件 | 成长组(30pp) |  | 低毛利(2%/-20%) |
| technical_ceramic | 卫生及技术陶瓷 | 成长组(26pp) |  |  |
| television | 彩色电视机 | 成长组(14pp) |  | 低毛利(13%/7%) |
| tio2 | 钛白粉 | 成长组(29pp) |  | 低毛利(10%/-1%) |
| transformer | 变压器 | 成长组(28pp) |  |  |
| viscose_staple | 粘胶短纤 | 成长组(21pp) |  | 低毛利(12%/-0%) |
| vitamins | 维生素 | 成长组(33pp) |  |  |
| washing_machine | 洗衣机 | 成长组(11pp) |  |  |
| wheel_loader | 装载机 | 成长组(20pp) | 内销 |  |
| wind_parts | 风电及发电设备零部件 | 成长组(22pp) |  |  |
| wind_turbine | 风力发电机组 | 成长组(55pp) |  | 低毛利(10%/5%) |
| wireless_earbud | 无线耳机 | 成长组(17pp) |  |  |
| woven_apparel | 男式棉制长裤 | 成长组(11pp) |  |  |

---

## 附录：复现

```bash
# 三轴分组重算（std 周期结构 + 内销机械 + 低毛利产品）
uv run python scratch/recompute_cycle_structure.py   # 周期结构 89/19
# 低毛利产品：fina_indicator 产品中位 grossprofit_margin<15% 且 roe<10%
# 完整三轴表由会话内脚本生成，输出见本文 §5。
```
