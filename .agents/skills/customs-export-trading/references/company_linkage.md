# 公司下沉操作手册（数据流、产物与维护）

> 本文件是 customs-export-trading skill 的操作手册，只保留**怎么跑、产什么、怎么维护**。
> 方法论权威（为什么下沉/股价验证/判读口径/三层信号/回测结论/排除清单）见
> [`docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md`](../../../../docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md)
> （唯一权威，改动口径需同步该文档并重跑回测）；行业研究方法论见 sibling skill
> [`customs-industry-prosperity`](../../customs-industry-prosperity/SKILL.md)。
> 2026-09 由 customs-industry-prosperity 迁入，2026-09 方法论沉淀至 docs/research
> （资产与脚本保持原位，不复制）。

## 1. 资产清单（config/data/customs/）

| 文件 | 内容 | 维护方 |
| :-- | :-- | :-- |
| `company_exposure_map.csv` | 109 产品 → 393 公司暴露度（0-1），`taxline_segment` 列绑定税号段（空=整产品） | 大模型/人工，fina_mainbz 校准 |
| `taxline_segments.csv` | 高分化产品税号段定义（14 段/5 产品：transformer 4 段、semiconductor_equipment 3 段、lithium_chemicals 3 段、silver 2 段、cathode_material 2 段） | 人工，需审计后新增 |
| `bz_item_alias_map.csv` | LLM 语义别名表：fina_mainbz `bz_item` → product_key（1395 条，2026-06-30 期） | LLM 批量生成 + 人工修订 |
| `hs_codes_catalog.csv` | 产品键 → hs 码全集（8 位优先，纯 6 位产品取其 8 位子码） | 既有 catalog |

加载器：`src/stock_data/fetcher/industry/customs/parsers/company_exposure.py`
（`load_company_exposure_map` / `load_taxline_segments` / `TaxlineSegmentMap.hs_codes_for`，
公司段引用非法会报错）。

## 2. 数据流与命令

```bash
# 暴露度校准（fina_mainbz type=P 主营构成 → exposure；dry-run 先看差异）
uv run python scripts/calibrate_company_exposure.py --period 2026-06-30 --apply

# 公司级出口景气观察表（段级聚合 + 3MMA yoy + 驱动/拐点 + 产品级对照）
uv run python scripts/build_customs_company_exposure.py

# 公司三层信号（出口前瞻 × 资金确认 × 财报真扩张）→ A/B/C/D/回避 评级
uv run python scripts/build_customs_company_signal.py

# 择时回测（分批建仓 / 景气松动分批减仓 → 胜率/持有收益）
uv run python scripts/backtest_customs_company_signal.py --quality-gate

# 多产品横向回测（信号普适性检验，10 产品 × 基础/质量两版）
uv run python scripts/backtest_customs_multi.py --detail
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
- 补全月序（2016-01~末月）重算 3MMA yoy，与
  `stock_analytics.pipelines.customs_prosperity.product_panel._derive` 同口径；
- 公司多段绑定 → 每 (company, product, segment) 一行；空段 → 产品级序列（对比基线）。

## 3. 抓机会手册（月度执行）

1. **8 月下旬**：刷黄金表 → 跑行业 4 个 build（见 customs-industry-prosperity SOP 1-4）
   → `build_customs_company_exposure.py` → `build_customs_company_signal.py`；
2. **选池**：`rating=="A强机会"`（三腿共振）优先；`B确认中` 做前瞻仓；
   `risk_flag=="顶背离⚠"` 一律回避（出口仍强但资金撤 = 利好兑现）；
3. **建仓**：产品出口 yoy 连续 2 月 >0 且量价齐升/量驱动 → 分 3 批建仓（月度 1/3）；
4. **监控**：月度看段级 yoy 二阶导——连续 2 月回落减半、转负清仓；
   同时盯 `f2_state`：主力/融资由正转负 = 资金背离预警（即便出口仍正）；
5. **组合纪律**：多产品分散（transformer/battery/semi/cathode/wind 信号强的池子），
   单产品不重仓；快周期商品（锂/铜/银）不用本信号；
6. **后视确认**：财报双正（f3=真扩张）验证"真扩张"，增收不增利（净利负）降级。

## 4. 别名表再生成流程（fina_mainbz 新报告期）

1. 从 `data/curated/tushare/market=CN/fina_mainbz`（type=P）提取每公司最新期 `bz_item` 去重清单；
2. LLM 批量归一化到 `hs_codes_catalog.csv` 的 product_key（alias/ambiguous/no_match/generic 四类，
   "电气设备系列"等语境模糊项硬标注产品并注明公司）；
3. 合并校验：product_key 必须为 catalog 合法键、条数全覆盖、冲突人工裁决；
4. 落 `bz_item_alias_map.csv`（显式可人工修订）→ 重跑 calibrate。
   临时脚本与 chunk 在 `scratch/`（gitignore），正式产物只提交 CSV。

## 5. 维护边界

- 段定义新增需人工审计（HS 码互斥、单位一致），不经 LLM 自动生成；
- exposure 优先 verified（fina_mainbz 校准），estimated 为人工估计需复核；
- `bz_item_alias_map.csv` 与 `company_exposure_map.csv` 由本链路唯一消费方
  （calibrate + company builder）引用，改动后重跑两个脚本验证；
- 公司段引用非法（段未定义）时 loader 直接报错，防止手误静默失效；
- 信号口径与回测结论改动（确认月数/质量门/三腿阈值）需同步
  `docs/research/customs_export_forward/METHODOLOGY_COMPANY_FINAL.md` 并重跑回测。
