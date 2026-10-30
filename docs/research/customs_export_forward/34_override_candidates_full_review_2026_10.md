# 34. override 候选全量核验报告（2026-10）

来源：`scratch/override_candidates.csv`（3,157 条，基于主营关键词扫描的全市场候选）。
目标：按“真口径”（电芯/正极/整机等）逐家核验主营构成，产出确认/否决裁决；仅将人工核验通过的公司写入 override/binding。

## 1. 全量裁决统计

| 类别 | 数量 | 说明 |
| :--- | :---: | :--- |
| 候选总数 | 3,157 | 关键词扫描出的 公司×产品 |
| 自动判定“确认” | 752 | 规则命中，**待人工抽查，未自动写库** |
| 自动判定“否决” | 2,405 | 主营无真口径命中（“银”泛词、银行/券商、材料/隔膜/BMS 等） |

确认按产品：battery 51、semiconductor_equipment 462、auto_parts 108、power_cable 58、
solar_cell 22、cathode_material 17、lithium_chemicals 7、silver 8、transformer 8、
uav_drone 5、electronic_cigarette 2、inverter 4。

## 2. 为什么 752 条不自动写库（抽样证据）

自动规则仍存在系统性误绑，逐产品抽查示例：

- **semiconductor_equipment（462）**：“零部件/备件/设备”泛词误伤：爱玛科技（电动自行车）、山河智能（工程机械）、三达膜（膜材料）、信隆健康（自行车配件）等；
- **battery（51）**：亿华通（燃料电池）、金时科技（包装印刷）、国晟科技（光伏 EPC）；
- **solar_cell（22）**：TCL中环（硅片）、星帅尔（压缩机）、星光股份（照明）；
- **lithium_chemicals（7）**：东晶电子（石英晶体）、南华生物（生物）；
- **inverter（4）**：瑞凌股份/佳士科技（电焊机，焊接逆变器≠电源逆变器）；
- **power_cable（58）**：信通电子（智能巡检）、凯旺科技（连接器）、矩子科技（视觉检测）；
- **cathode_material（17）**：西陇科学（化学试剂）、ST司特（磷化工）；
- 另有大量无公司名/异常代码（如 A17281.SH）无法落地。

结论：**自动判定仅作候选线索，不能直接写入公司暴露表**；批量写入会污染公司级出口信号（违反 Ground Truth First）。

## 3. 已写入（人工逐家核验批次）

- `company_segment_binding.csv`：**人工修正合并表**（2026-09-13 起，原 binding + override 二合一）——撰写时快照 148 行 / 42 行带 exposure（override 行，evidence 列保留各批核验来源）；**2026-10 最终重建后实测 144 行 / 59 行带 exposure**（当前口径以 customs-export-research 操作手册 §1 为准）；原五批家数不变；
- 每行 `evidence` 注明主营占比来源与“待财报校准”。

## 4. 产物文件

| 文件 | 内容 |
| :--- | :--- |
| `scratch/override_confirmed.csv` | 752 条自动确认（待人工抽查） |
| `scratch/override_rejected.csv` | 2,405 条否决 + 原因 |
| `scratch/auto_verify_overrides.py` | 全量核验规则脚本（可复现） |
| `scratch/override_candidates.csv` | 3,157 条原始候选 |

## 5. 后续建议

1. 从 752 条里按产品人工抽查（优先 silver/cathode_lfp/ecig/uav 等小集合，误绑率低）；
2. 修规则：semiconductor 必须含“半导体/集成电路/晶圆+设备”且排除“零部件”泛词单独命中；
3. battery 需排除 燃料电池/印刷/EPC；solar_cell 需排除 硅片/压缩机；inverter 需排除 电焊机；
4. 已写入的 37 家建议在财报披露后按实际主营占比校准 exposure。
