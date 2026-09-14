# 公司下沉操作手册（数据流、产物与维护）

> 本文件是海关出口公司下沉层面的操作手册，只保留**怎么跑、产什么、怎么维护**。
> 方法论权威（为什么下沉/股价验证/判读口径/三层信号/回测结论/排除清单）见
> [`docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md`](../../../../docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md)
> （唯一权威，改动口径需同步该文档并重跑回测）；行业研究方法论见
> [`methodology.md`](methodology.md)。

## 1. 资产清单（config/data/customs/）

| 文件 | 内容 | 维护方 |
| :-- | :-- | :-- |
| `good_products.csv` | 产品主表（product_key 主键，**149 产品**，2026-10 税则补全 + aquatic_products 108 池恢复） | 既有 catalog（行业 skill 共享） |
| `good_h8_codes.csv` | 税号表（hs_code 主键 8 位，**1,044 个税号**；product_key 外键 + 覆盖列） | 既有 catalog（行业 skill 共享） |
| `categories.csv` | 分类枚举（18 个 category_key） | 既有 catalog（行业 skill 共享） |
| `taxline_segments.csv` | 高分化产品税号段定义——同一产品内段级区分（**31 段 / 12 产品**：auto_parts 4、transformer 4、semiconductor_equipment 3、lithium_chemicals 3、inverter 3、battery 3、power_cable 2、cathode_material 2、silver 2、solar_cell 2、uav_drone 2、electronic_cigarette 1） | 人工，需审计后新增（2026-09-13 恢复版段行待人工复核） |
| `company_segment_binding.csv` | **人工修正单表（2026-09-13 起，binding + override 二合一）**：**144 行，其中 59 行带 exposure**（override 行，evidence 列保留核验来源）；binding-only 行 exposure 为空；override 段必须 ⊆ 同(产品,公司) binding 段（loader 校验） | 人工逐家核验（34 号文档） |
| `gacc_query_codes.txt` | GACC 采集查询码清单（**1,039 个末级子税号**，由 catalog 派生） | 派生产物，不手改（归属 customs-export-research / data-pipeline） |

> 已移除（2026-09）：`company_exposure_map.csv`、`bz_item_alias_map.csv`（两张人工 CSV，
> 由动态 H8 链路的 `fina_mainbz` 直接映射 + `company_segment_binding.csv` 人工修正单表取代）。

加载器：`good_h8_codes.csv` / `good_products.csv` / `categories.csv` 经
`src/stock_data/fetcher/industry/customs/parsers/catalog.py`（`load_hs_catalog`）与
`src/stock_analytics/marts/customs_company_h8.py` 消费；`taxline_segments.csv` 经
`src/stock_data/fetcher/industry/customs/parsers/company_exposure.py`
（`load_taxline_segments` / `TaxlineSegmentMap.hs_codes_for`，段引用非法会报错）与
`src/stock_analytics/marts/customs_company_h8.py`（`_attach_segment`）消费；
`company_segment_binding.csv` 经 `src/stock_analytics/marts/customs_company_h8.py`
（`_load_segment_binding` / `_validate_override_segments`，override 段错位会报错）消费。

> **动态 H8 链路（2026-09，公司下沉主路径）**：
> `fina_mainbz(P)` 按报告期截断 + `jieba + rapidfuzz` 自动映射到 `good_h8_codes.csv` 产品，
> 叠加 `company_segment_binding.csv` 人工修正（绑定段过滤 + exposure override），
> 校验 H8/H6 父码、三级行业映射与重复编码，生成公司-H8 月度出口加权序列
> （`mapping_report_period < report_date` 无报告期前视；`report_date >= list_date` 上市日过滤）。
> - 代码：`src/stock_analytics/marts/customs_company_h8.py`（Mart 构建）+
>   `src/stock_cli/customs_company_h8.py`（CLI）+
>   `src/stock_analytics/pipelines/customs_company_h8/`（panel + signal + 门面）；
> - 测试：`tests/unit/stock_analytics/marts/test_customs_company_h8.py` +
>   `tests/unit/stock_analytics/pipelines/customs_company_h8/`；
> - 产物：`data/curated/mart/customs_company_product_mapping.parquet`
>   （公司-报告期-产品映射，`match_status=selected` 高置信）、
>   `data/curated/mart/customs_company_h8_exposure.parquet`（公司×月份×H8 暴露 Mart，
>   2026-10 储能系统匹配修复后重建 **348,713 行 / 1,045 家 / 104 产品**）；
> - 命令：`uv run python -m stock_cli.customs_company_h8 --as-of-period 2026-06-30 --with-signal`。

## 2. 数据流与命令

> **旧 CSV 链路已断链（2026-09，勿用）**：`calibrate_company_exposure.py` /
> `stock_cli.customs_company` / `backtest_customs_company_signal.py` /
> `backtest_customs_multi.py` 的默认路径仍指向已删除的 `company_exposure_map.csv` /
> `bz_item_alias_map.csv`，当前不可运行、待下线或改指 H8（择时回测口径仍复用，见待办）。
> **公司下沉主路径 = 动态 H8 链路**（命令见 §1），人工修正收敛为
> `company_segment_binding.csv` 单表（binding + override 一表两用，见 §1）。

```bash
# === 动态 H8 链路（主路径，当前可运行）===
# 公司观察表 + 三层信号（月度抓机会）一键执行（管线路径见
# src/stock_analytics/pipelines/customs_company_h8/）
uv run python -m stock_cli.customs_company_h8 --as-of-period 2026-06-30 --with-signal

# 动态 H8 链路股价验证（两轮，只读，产出 parquet）
uv run python scripts/analyze_h8_a_pool_price_strength.py
uv run python scripts/backtest_customs_company_h8_event.py

# === 旧链（2026-09 已断，仅口径保留，勿直接运行）===
# 下列命令默认路径仍指已删除的 company_exposure_map.csv / bz_item_alias_map.csv，
# 待改指 H8（见待办）。口径复现入口：
# uv run python scripts/calibrate_company_exposure.py --period 2026-06-30 --apply
# uv run python -m stock_cli.customs_company --skip-signal
# uv run python scripts/backtest_customs_company_signal.py [--quality-gate] [--quality-filter]
# uv run python scripts/backtest_customs_multi.py [--quality-filter] [--product-gate] --detail
```

`stock_cli.customs_company` 输出（**旧链，已断，仅口径保留**）：
- `data/analytics/industry/customs_company_exposure.parquet`——全序列（key × 月，3MMA yoy/驱动/拐点）；
- `data/analytics/industry/customs_company_exposure_latest.csv`——最新月公司快照：
  `company_name / stock_code / product_key / exposure / bind_segment / segment_name /
  value_yoy_3mma / volume_yoy_3mma / price_yoy_3mma / 驱动类型 / 拐点 / 二阶导 /
  product_value_yoy / segment_minus_product`；
- `customs_company_signal.parquet / _latest.csv`——三层信号（f1/f2/f3_state + rating/risk_flag）；
- `customs_company_manifest.json`——产物与数据水位。

`stock_cli.customs_company_h8`（动态 H8 链路）输出（`--with-signal` 追加面板与信号）：
- `data/curated/mart/customs_company_product_mapping.parquet / _latest.csv`——公司产品映射
  （match_status: selected/ambiguous/no_match/generic，含 product_exposure、match_score）；
- `data/curated/mart/customs_company_h8_exposure.parquet / _latest.csv`——公司×月份×H8 暴露
  （`company_h8_export_value_usd = export_value_usd × product_exposure`，含
  `company_h8_weight`、`company_h8_exposure_share`、`mapping_report_period`）；
- `data/analytics/industry/customs_company_h8_product_panel.parquet / _latest.csv`——
  公司×产品×月份面板（3MMA yoy/驱动/拐点/二阶导，复用 exposure_panel._derive 口径）；
- `data/analytics/industry/customs_company_h8_signal.parquet / _latest.csv`——三层信号
  （复用 signal.build_company_signal，字段契约与旧链路一致）；
- `data/analytics/industry/customs_company_h8_manifest.json`——产物与数据水位。

（2026-10 储能修复后重建：`customs_company_h8_exposure.parquet` **348,713 行 / 1,045 家 / 104 产品**；
面板/信号行数以最新 Manifest 为准。）

口径要点：
- 海关源统一 GACC 单源（`data/curated/industry/customs_trade_gacc.parquet`），
  聚合仅用黄金表 `trade_direction=export` + `hs_level=8` 行；
- 数量仅段内已知单位唯一时加总（否则置空，驱动不判）；金额全量；
- 补全月序（黄金表全序~末月）重算 3MMA yoy，与
  `stock_analytics.pipelines.customs_prosperity.product_panel._derive` 同口径；
- 公司多段绑定 → 每 (company, product, segment) 一行；空段 → 产品级序列（对比基线）；
- 人工修正单表语义：binding-only 行 exposure 空、override 行 exposure 非空（原
  company_product_override.csv 已并入）；override 段必须 ⊆ 同(产品,公司) binding 段，
  `_validate_override_segments` 校验段错位；绑定公司只保留绑定段 H8 码（段级暴露），
  未绑定公司保留全产品（产品级）；
- 未来公司前视：Mart 层 `report_date >= list_date` 双重点-in-time 过滤（暴露展开构建期用，
  `list_date` 从最终 mapping/exposure 列剥离），回测脚本另加防御性过滤，未来公司样本归 0。

## 3. 抓机会手册（月度执行）

1. **8 月下旬**：刷黄金表 → 跑行业管线（见 SKILL.md SOP）
   → `uv run python -m stock_cli.customs_company_h8 --as-of-period <报告期> --with-signal`
   （公司×产品面板 + 三层信号）；
2. **选池**：`rating=="A强机会"`（三腿共振）优先；`B确认中` 做前瞻仓；
   `risk_flag=="顶背离⚠"` 一律回避（出口仍强但资金撤 = 利好兑现）；
3. **建仓**：产品出口**金额** yoy 连续 2 月 >0 → 分 3 批建仓（月度 1/3，base 基线）；
   量拐门（量价齐升/量驱动）为可选中性层（对齐后 base=quality 打平，见 METHODOLOGY §6 / 26 号文档）；
4. **监控**：月度看段级 yoy 二阶导——连续 2 月回落减半、转负清仓；
   同时盯 `f2_state`：主力/融资由正转负 = 资金背离预警（即便出口仍正）；
5. **组合纪律**：多产品分散（transformer/battery/semi/cathode/wind 信号强的池子），
   单产品不重仓；快周期商品（锂/铜/银）不用本信号（GACC 口径回测轮次少、表现分化，
   维持排除，观察 2-3 个新景气轮后评估，见 METHODOLOGY_COMPANY_FINAL §8.1）；
6. **后视确认**：财报双正（f3=真扩张）验证"真扩张"，增收不增利（净利负）降级。

## 4. 别名表再生成流程（已移除，2026-09）

`bz_item_alias_map.csv` 与 `company_exposure_map.csv` 已移除，人工别名/暴露度表不再维护；
动态 H8 链路对 `fina_mainbz(P)` 的 `bz_item` 直接做 `jieba + rapidfuzz` 映射
（见 `src/stock_analytics/marts/customs_company_h8.py`）。旧链（calibrate + company builder）
残留代码待下线。

## 5. 维护边界

- 段定义新增需人工审计（HS 码互斥、单位一致），不经 LLM 自动生成；
- `company_segment_binding.csv` 人工修正规则：新增 override 行须人工核验主营占比
  （evidence 留来源）；override 段必须 ⊆ 同(产品,公司) binding 段（loader 校验报错，
  防段错位）；改动后重跑 H8 Mart 与
  `tests/unit/stock_analytics/marts/test_customs_company_h8.py`；
- 公司段引用非法（段未定义）时 loader 直接报错，防止手误静默失效；
- 映射匹配与校验（H8/H6 父码、三级行业映射、重复编码）调整需同步
  `src/stock_analytics/marts/customs_company_h8.py` 并重跑 H8 链路测试；
- 信号口径与回测结论改动（确认月数/质量门/三腿阈值）需同步
  `docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md` 并重跑回测。
