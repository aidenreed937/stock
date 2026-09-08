# 出口商品 → 公司景气度下沉（Company Linkage）

> 2026-09 新增。行业层（L2/L3）区分度不足时，把商品量价拐点下沉到受益公司：
> **商品拐点（前瞻）→ 暴露度找公司 → 税号段级序列修正 → 公司出口景气排序 → 财报后视验证**。
> 口径延续 METHODOLOGY_FINAL §2（3MMA yoy 四象限/拐点/二阶导）与 §6.5 桥接规则。

## 1. 为什么下沉（实证锚点）

- transformer 产品 2026-07 产品级 3MMA yoy **+34.2%**，内部税号段分化 **+13%~+566%**；
- 段级落公司后：特变电工（ultra 段）**+111.5%**（产品级严重低估 3 倍）、明阳电气（small 段）
  **+19.2%**（产品级高估近 1 倍）——行业/产品层看不到的公司间差异，段级序列可见；
- 段驱动也分化：ultra 段量价齐升（量 +81%），small/mid 段价驱动——受益质量不同。

## 2. 资产清单（config/data/customs/）

| 文件 | 内容 | 维护方 |
| :-- | :-- | :-- |
| `company_exposure_map.csv` | 109 产品 → 393 公司暴露度（0-1），`taxline_segment` 列绑定税号段（空=整产品） | 大模型/人工，fina_mainbz 校准 |
| `taxline_segments.csv` | 高分化产品税号段定义（14 段/5 产品：transformer 4 段、semiconductor_equipment 3 段、lithium_chemicals 3 段、silver 2 段、cathode_material 2 段） | 人工，需审计后新增 |
| `bz_item_alias_map.csv` | LLM 语义别名表：fina_mainbz `bz_item` → product_key（1395 条，2026-06-30 期） | LLM 批量生成 + 人工修订 |
| `hs_codes_catalog.csv` | 产品键 → hs 码全集（8 位优先，纯 6 位产品取其 8 位子码） | 既有 catalog |

加载器：`src/stock_data/fetcher/industry/customs/parsers/company_exposure.py`
（`load_company_exposure_map` / `load_taxline_segments` / `TaxlineSegmentMap.hs_codes_for`，
公司段引用非法会报错）。

## 3. 数据流与命令

```bash
# 暴露度校准（fina_mainbz type=P 主营构成 → exposure；dry-run 先看差异）
uv run python scripts/calibrate_company_exposure.py --period 2026-06-30 --apply

# 公司级出口景气观察表（段级聚合 + 3MMA yoy + 驱动/拐点 + 产品级对照）
uv run python scripts/build_customs_company_exposure.py
```

`build_customs_company_exposure.py` 输出：
- `data/analytics/industry/customs_company_exposure.parquet`——全序列（key × 月，3MMA yoy/驱动/拐点）；
- `data/analytics/industry/customs_company_exposure_latest.csv`——最新月公司快照：
  `company_name / stock_code / product_key / exposure / bind_segment / segment_name /
  value_yoy_3mma / volume_yoy_3mma / price_yoy_3mma / 驱动类型 / 拐点 / 二阶导 /
  product_value_yoy / segment_minus_product`。

口径要点：
- 聚合仅用黄金表 `trade_direction=export` + `hs_level=8` 行；
- 数量仅段内已知单位唯一时加总（否则置空，驱动不判）；金额全量；
- 补全月序（2016-01~末月）重算 3MMA yoy，与 `build_customs_product_volume_price._derive` 同口径；
- 公司多段绑定 → 每 (company, product, segment) 一行；空段 → 产品级序列（对比基线）。

## 4. 判读口径（公司受益区分度）

1. **段级 yoy vs 产品级 yoy**（`segment_minus_product`）：>50pp 高估/低估，绑定该段的公司才是真实受益；
2. **驱动质量**：量价齐升 > 量驱动 > 价驱动 ⚠ > 双弱 ✗（ultra 段量价齐升 = 高景气质量）；
3. **拐点/二阶导**：见顶拐点 + 量增速回落 = 顶部前兆，公司层面同判；
4. **组合视角**：一家公司绑定多产品（如特变电工 transformer+polysilicon）时逐产品看，避免单一产品误判；
5. **财报验证**：用 fina_mainbz 主营占比（`calibrate_company_exposure.py` 产物）做暴露度确认，公司财报 yoy 仅后视。

## 5. 别名表再生成流程（fina_mainbz 新报告期）

1. 从 `data/curated/tushare/market=CN/fina_mainbz`（type=P）提取每公司最新期 `bz_item` 去重清单；
2. LLM 批量归一化到 `hs_codes_catalog.csv` 的 product_key（alias/ambiguous/no_match/generic 四类，
   "电气设备系列"等语境模糊项硬标注产品并注明公司）；
3. 合并校验：product_key 必须为 catalog 合法键、条数全覆盖、冲突人工裁决；
4. 落 `bz_item_alias_map.csv`（显式可人工修订）→ 重跑 calibrate。
   临时脚本与 chunk 在 `scratch/`（gitignore），正式产物只提交 CSV。

## 6. 维护边界

- 段定义新增需人工审计（HS 码互斥、单位一致），不经 LLM 自动生成；
- exposure 优先 verified（fina_mainbz 校准），estimated 为人工估计需复核；
- `bz_item_alias_map.csv` 与 `company_exposure_map.csv` 由本链路唯一消费方
  （calibrate + company builder）引用，改动后重跑两个脚本验证；
- 公司段引用非法（段未定义）时 loader 直接报错，防止手误静默失效。
