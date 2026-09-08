# 13 技能链路审计：问题清单与修复方案（2026-09 审计）

> 审计对象：`customs-industry-prosperity` 技能全链路——SKILL.md、METHODOLOGY_FINAL.md、
> 4 个 build 脚本、`hs_codes_catalog.csv`、5 个 parquet 产物、月度报告
> `12_forward_watch_2026_07.md` 与 02/04 证据文档。
>
> 审计方式：读全脚本与文档 → 实跑 4 个 build 脚本（临时目录，不覆盖现产物，结果与
> 现产物逐列一致）→ 产物交叉对账（金额/量价/商品/观察表/财报/维度表）→ 定位差异根因。
>
> **修复状态（2026-09 同日）：P0-1 ~ P5-1 全部已修复并重跑验证**，详见 §5 修复记录；
> §1-§3 保留原始审计发现，§3 为修复方案原稿。
>
> 结论：**4 脚本全部可复现（96012 / 14117 / 13918 行，数值列与现产物一致）**；发现
> **1 个 P0 数据正确性 Bug（GACC 段商品错映射）**、4 个面板口径不一致、2 处文档数字
> 过时、1 个仓库级问题（桥接唯一源未入库）。修复建议见 §3，按 P0→P1 顺序执行。

---

## 1. 问题清单（按严重度分级）

### P0-1 GACC 段 87046000（新能源载货车）错映射到 850913.SI（商用载客车）★数据正确性

| 项 | 内容 |
| :--- | :--- |
| 现象 | curated 中 `850912.SI`（商用载货车）2025-01 起金额为 0；观察表 L3 该行金额 yoy NaN。`850913.SI`（商用载客车）2025+ 被高估约 **12.3 亿美元**（2025-01~2026-07） |
| 根因 | `parse_gacc_csv` 的 `gacc_code_map` 命中分支用 `_catalog_info_for_product_key(product_key)` 反查 catalog，该函数返回 **catalog 中 product_key 匹配的"第一行"**（`src/stock_data/fetcher/industry/customs/parsers/catalog.py:110-118`，dict 插入序 87024000 在 87046000 之前）→ `commercial_nev` 的所有 GACC 行（含 87046000 载货车）一律归入 850913.SI |
| 证据 | `_catalog_info_for_product_key('commercial_nev')` 返回 `87024000 → 850913.SI`；curated 中 GACC `87046000 → 850913.SI`、UN 段 `87046000 → 850912.SI`；coal 因 catalog 只有 6 位行（不命中 gacc_code_map 8 位索引）走 8 位→6 位前缀回退而幸免 |
| 影响 | 仅 `commercial_nev` 一个产品受影响（8 位行间 L3 不同的唯一产品）；L2 商用车不受影响（两 L3 同属 801096.SI）；L3 载客车/载货车分化被扭曲，L3 观察表载货车行 NaN |
| 修复 | 见 §3.1（解析层优先按 8 位码精确匹配，不再按 product_key 反查任意行） |

### P1-1 金额面板 L2 未内置跳过组合码（801033.SI;801034.SI）

| 项 | 内容 |
| :--- | :--- |
| 现象 | `customs_export_prosperity_panel.parquet` L2 层含组合码组 `801033.SI;801034.SI`（127 行），仅观察表（`build_customs_forward_watch.py:102`）与 three_leg（`SKIP_L2`）消费时过滤 |
| 违反 | METHODOLOGY §6.5 强制规则 4"组合码行在行业聚合中**必须跳过**"；金额面板是共享中间产物，应内置跳过并披露，而非依赖各消费端各自过滤 |
| 修复 | `build_customs_export_prosperity.py` L2 聚合前 filter `;` 行 + 打印披露（与量价/商品脚本一致） |

### P1-2 量价面板 L3 缺钛白粉 850326.SI（组合码过滤过宽）

| 项 | 内容 |
| :--- | :--- |
| 现象 | 量价面板 L3 仅 72 行业（缺 `850326.SI` 钛白粉）；金额面板 L3 73 行业（含钛白粉）→ 观察表 L3 钛白粉金额有、量价 NaN |
| 根因 | `build_customs_l2_volume_price.py:47` 的 `SKIP_L2` 过滤作用在**行级**（`target_l2_codes` 含组合码的 tio2 整产品行被剔除），连带删除了 tio2 的 L3（850326.SI 是单一明确 L3） |
| 修复 | 过滤应在 **L2 聚合组内**执行（L2 跳过组合码组、L3 保留 850326.SI），或在 L3 层不过滤；同时商品面板 `_bridge_validate` 剔除组合码行导致 tio2 285 行出口数据在产品面板丢失（产品面板 107 vs catalog 109，缺 tio2 与 comm_equipment_mixed） |

### P2-1 一致率分级数字三处不一致（文档 vs 文档 vs 脚本）

| 处 | 数字 |
| :--- | :--- |
| METHODOLOGY §2.4 | A6 / **B19** / **C15** = 40 |
| 02 文档 §1（分级结论表） | A6 / B19 / C15 |
| 02 文档 §2（全表 40 行实际） | A6 / **B22** / **C12** |
| `build_customs_forward_watch.py` CONSISTENCY 字典 | 39 个（A6/B22/**C11**，**缺厨卫电器 801114.SI 0.38 C 级**） |
| 观察表实际 | 42 行 = 43 唯一 L2 − 1 组合码；有 grade 39 行 + 3 行无 grade（生物制品/化学制品/光学光电子） |

说明：02 文档 §1 与 METHODOLOGY 的 19/15 是过时口径（9-14 主表合并后应为 22/12）；脚本字典
39 个与观察表 join 后可观测行业一致，但缺 801114.SI（catalog 无产品映射到厨卫电器 → 金额面板
无该行业 → 观察表无该行，属映射缺口而非脚本 bug，但需披露）。

### P3-1 月度报告 12_forward_watch_2026_07.md 未随 HS2027 修复更新

| 项 | 内容 |
| :--- | :--- |
| 现象 | 报告（12:46 生成，基于 12:39 旧观察表）中炼化 **-83.0%**、乘用车 +117.1%/分位 47.2；最新观察表（17:34）炼化 **+47.9%**、乘用车 +88.3%/91.7。报告版本说明仍写"炼化及贸易止于 2024-12 → -83.0%"（修复前旧数据） |
| 根因 | 报告早于 2026-09-07 下午的 HS2027 对齐重导（METHODOLOGY §7.5 已记录修复），未重跑 |
| 修复 | 按最新产物重跑观察表后更新报告；报告头部版本说明注明"HS2027 对齐后口径" |

### P3-2 报告仍引用已排除的方向分（global_resonance_l2_map）

| 项 | 内容 |
| :--- | :--- |
| 现象 | 报告数据底座列出 `global_resonance_l2_map.parquet`（最新 2026-08-28），正文多处引用方向分数字（8.3 / 16.7 / 2.8） |
| 违反 | METHODOLOGY §5 明确排除 direction_score（不建、不消费）；报告虽注明"方向分无预测力"，但数据底座列已排除信号易误导 |
| 修复 | 报告数据底座移除方向分或标注"已排除，仅历史背景" |

### P4-1 桥接唯一源 hs_codes_catalog.csv 未被 git 跟踪 ★仓库级

| 项 | 内容 |
| :--- | :--- |
| 现象 | `git ls-files config/data/customs/` 为空、`git status` 不显示该文件；`git check-ignore -v` 命中 `.gitignore:41` 的 `data/` 规则（`config/data/` 目录被误匹配） |
| 影响 | 映射唯一信任源不在版本控制中，新环境无法复现任何海关景气链路；所有"只改 catalog + 重刷 curated"的 SOP 都依赖本地未提交文件 |
| 修复 | `.gitignore` 的 `data/` 改为 `/data/`（仅锚定仓库根），或增加 `!config/data/` 例外 |

### P4-2 catalog 行数文档过时（253 → 256）

| 处 | 内容 |
| :--- | :--- |
| SKILL.md 数据底座 / METHODOLOGY §6.5 | 写"253 行 / 109 产品"，实际 **256 行**（2026-09-07 HS2027 修复新增 27101913/14/24 三行）/ 109 产品 |
| 修复 | 两处文档更新为 256 行，注明 +3 系 HS2027 新码 |

### P4-3 旧产物 customs_forward_watch_202607.parquet 残留

| 项 | 内容 |
| :--- | :--- |
| 现象 | 旧观察表（含已排除列 direction_score / demand_score / scissors_score）与新版 `customs_forward_watch_l2/l3.parquet` 并存；SKILL 数据底座只列 l2/l3 |
| 修复 | 删除旧文件或加 `_deprecated` 后缀；SKILL 数据底座注明"旧 202607 命名已废弃" |

### P5-1 其他小问题

| 项 | 内容 |
| :--- | :--- |
| 观察表 L3 商用载货车 NaN | P0-1 的可见后果，随 P0-1 修复消失 |
| `_load_financial` 财报 `end_date=date(2026,12,31)` 硬编码 | 2027 年后运行会取不到最新财报期（reportDate 过滤上限过时），应改为动态当前期或数据源最新期 |
| `gacc_active` 仅 22 行标记 | 语义 OK（空值默认启用），但字段利用不完整，可后续补全 |
| 商品面板缺 comm_equipment_mixed | 属"6 位载体行"设计（catalog 中仅作 h6 聚合载体，无 8 位出口数据），正常 |

---

## 2. 审计复核基线（本次实测通过项，供回归）

| 检查项 | 结果 |
| :--- | :--- |
| 4 脚本顺序运行 | 全部成功，输出与现产物数值列一致（金额 96012 / 量价 14117 / 商品 13918 行） |
| curated 组合码 | 786 行 / 2 产品（hs6_320611、tio2）/ 唯一 L2 `801033.SI;801034.SI`，与 METHODOLOGY §6.5 一致 |
| L3 空映射 | 0 行（catalog 与 curated 均无空 L3） |
| 观察表覆盖 | L2 42 行（43−1 组合码）✓；L3 73 行 ✓；L2 财报列 42/42 非空 ✓ |
| 商品面板桥接断言 | L3 归属断言通过（109 行可校验，0 不一致） |
| 报告 §2.1 抽查 10 行 | 与最新观察表一致（航海装备/半导体/贵金属/其他电源/化学原料/元件/电池/工业金属/电网/摩托车） |

---

## 3. 修复方案（按优先级执行）

### 3.1 P0-1：GACC 解析按 8 位码精确匹配，废弃 product_key 反查任意行（★先修）

**改 `src/stock_data/fetcher/industry/customs/parsers/gacc.py` 的 `parse_gacc_csv` 分支**：

```python
if gacc_code_map is None:
    catalog_info = _catalog_info_for_code(hs_code, catalog_map)
else:
    # P0-1 修复：优先 8 位码精确匹配（保留行级 L3 差异），
    # 不再用 product_key 反查"任意第一行"（commercial_nev 87046000 曾错归载客车）。
    catalog_info = _catalog_info_for_code(hs_code, catalog_map)
    if not catalog_info:
        gacc_info = gacc_code_map.get(hs_code)
        if gacc_info is not None and is_queryable_gacc_code(gacc_info):
            catalog_info = _catalog_info_for_product_key(gacc_info.get("product_key", ""), catalog_map)
        else:
            catalog_info = _catalog_info_for_code(hs_code, catalog_map)
```

或更简：`catalog_map`（`load_hs_catalog`）已含全部 8 位行与其 6 位父行，直接
`_catalog_info_for_code` 即可，`gacc_code_map` 仅用于查询清单而非映射。修复后：

1. **重导 GACC 2025/2026 raw**（`gacc-import`，raw 文件在 `data/raw/industry/customs/gacc/export/`，无需重新下载）；
2. **重建黄金表** `customs_trade.parquet`；
3. **重跑 4 个 build 脚本**（顺序：金额 → 量价 → 商品 → 观察表）；
4. 验证：`850912.SI` 2025+ 金额恢复（预计 ~12.3 亿美元 2025-01~2026-07）、`850913.SI` 相应回落、L3 观察表载货车行 yoy 不再 NaN、L2 商用车不变。

### 3.2 P1-1：金额面板 L2 内置跳过组合码

`build_customs_export_prosperity.py` L2 聚合前：

```python
l2_src = monthly.filter(
    pl.col("export_value_usd").is_not_null(),
    pl.col("l2_code").str.contains(";").not_(),   # 新增：组合码行跳过
)
# 并打印披露：跳过组合码行数与涉及产品
```

### 3.3 P1-2：量价面板 L3 保留钛白粉 + 商品面板保留 tio2

- `build_customs_l2_volume_price.py`：将 `SKIP_L2` 过滤从行级移到 **L2 聚合分组**（L2 跳过
  组合码组、L3 不过滤），L3 层恢复 850326.SI；
- `build_customs_product_volume_price.py`：`_bridge_validate` 只跳过"L2 组合码**作为聚合键**"
  的场景；商品面板是产品级面板，tio2（L3=850326.SI 明确）应保留段数据，仅在披露中标注其
  L2 为组合码。

### 3.4 P2-1：一致率数字统一

- 02 文档 §1 与 METHODOLOGY §2.4 更新为 A6 / B22 / C12 = 40（以 02 全表为准）；
- 脚本字典补 `801114.SI: (0.38, "C")` 并在文档披露：厨卫电器一致率 0.38 但 catalog 无产品
  映射，观察表不出现该行业；
- 观察表输出文件头（或 SKILL）注明"有 grade 39 行 + 3 行无 grade（生物制品/化学制品/光学
  光电子，未纳入 02 矩阵）"。

### 3.5 P3-1 / P3-2：报告更新

- 重跑后更新 `12_forward_watch_2026_07.md`：炼化 +47.9%（36m 分位 100）、乘用车 +88.3%/
  91.7 等；版本说明改为"HS2027 对齐后口径（2026-09-07）"；
- 数据底座移除方向分或标注"已排除，仅历史背景"。

### 3.6 P4-1：.gitignore 锚定根目录

`.gitignore` 第 41 行 `data/` → `/data/`（仅忽略仓库根 data/，放行 `config/data/`）。

### 3.7 P4-2 / P4-3：文档与产物清理

- SKILL.md / METHODOLOGY §6.5：`253 行` → `256 行`（+3 系 HS2027 新码）；
- 删除或 `_deprecated` 旧 `customs_forward_watch_202607.parquet`；
- `build_customs_forward_watch.py:69` 的 `end_date` 改为动态（如 `date.today()` 或数据源最新期）。

---

## 4. 验证方式（修复后）

1. 重跑 4 脚本（顺序固定），断言输出行数与桥接审计通过；
2. 专项断言：
   - `850912.SI` 2025-01 起金额 > 0，`850913.SI` 回落（合计不变）；
   - 金额面板 L2 无 `;` 组；量价/观察表 L3 含 850326.SI 且量价非空；
   - 观察表 L2 42 行、L3 73 行、grade 40/42（含厨卫电器披露）；
3. `git check-ignore config/data/customs/hs_codes_catalog.csv` 不再命中；
4. `make test TEST_PATH=tests/unit/stock_cli/test_customs_cli.py`（GACC 解析改动影响面）。

---

## 5. 修复记录（2026-09 同日执行）

| 项 | 修复动作 | 验证 |
| :--- | :--- | :--- |
| P0-1 | `parsers/gacc.py`：GACC 解析优先 8 位码精确匹配 `_catalog_info_for_code`，product_key 反查仅作兜底；全源重放 GACC 段（4 manifests + 6 无 manifest CSV）+ 保留非 GACC 段重建黄金表（158151 行不变、无主键重复） | 87046000 2025+ 由 0 恢复 1230.9M；L3 观察表载货车 +99.1%、载客车回落；L2 商用车不变 |
| P1-1 | `build_customs_export_prosperity.py`：L2 聚合前 filter 组合码并披露 | 金额面板 L2 43→42 行业、行数 96012→95885，无 `;` 组残留 |
| P1-2 | `build_customs_l2_volume_price.py`：SKIP_L2 移至 L2 聚合层（L3 保留 850326.SI）；`build_customs_product_volume_price.py`：商品级保留组合码行（tio2 恢复） | 量价面板 L3 72→73（钛白粉量价齐升 +36.1%/+20.0%/+13.4%）；商品面板 107→108 产品 |
| P2-1 | 脚本 CONSISTENCY 补 `801114.SI (0.38, C)`；02 文档 §1 与 METHODOLOGY §2.4 更正为 A6/B22/C12 | 字典与 02 全表一致（40 行业）；观察表 grade 39 + 3 无级披露 |
| P3-1/2 | `12_forward_watch_2026_07.md`：炼化 -83.0%→+47.9%（移出双弱）、乘用车 +117.1%→+88.3%、四阶段表/决策卡/复现段更新；移除方向分引用 | 报告数字与最新观察表逐行一致 |
| P4-1 | `.gitignore` 第 41 行 `data/` → `/data/` | `git check-ignore` 不再命中 catalog；catalog 进入 untracked 可入库 |
| P4-2 | SKILL + METHODOLOGY 行数 253 → 256（+3 系 HS2027 新码） | 与 catalog 实际行数一致 |
| P4-3 | 删除旧产物 `customs_forward_watch_202607.parquet`（含已排除列） | 无任何脚本/文档再引用；仅 l2/l3 命名保留 |
| P5-1 | `build_customs_forward_watch.py` 财报 end_date 硬编码 → `date.today()` | 2027+ 运行可取最新财报期 |

> 遗留提示：① GACC 无 manifest 的 2026-export.csv / 2026-export-20260907.csv 等 6 个
> CSV 游离于 manifests 体系外——`replay_industry_raw.py` 只读 manifests 会丢 70 行水产品
> 数据（本次全源重放已覆盖，但未来重导请走 `gacc-import` 注册 manifest 后再 replay）；
> ② 本月报告文件名为 2026_07，若 8 月数据已发布可更新报告基准月。

---

## 6. 通信行业全球共振辅助（2026-09 新增，非审计项）

通信行业出口量价歧义结构（光模块量停滞 × 价高增）的拐点定性不足，新增本地 6 信号
全球资本开支共振小面板辅助判断"暂歇 vs 反转"，与已排除的 direction_score 方向分严格
区分（原始实物量信号状态，不作合成打分/策略门）：

- 脚本：`scripts/build_comm_global_resonance.py`
- 产物：`data/analytics/industry/comm_global_resonance_panel.parquet`
- 专题：`14_comm_global_resonance.md`（含月度跟踪三道闸升级阈值）
- 2026-07 当前判定：6 信号全部扩张、拐点预警无——光模块量能回落 = 涨价换量的暂歇，
  非趋势反转（云 CapEx +87% 加速、SEMI 设备 +35.4% 五连升、台积电 +44.7%）。
