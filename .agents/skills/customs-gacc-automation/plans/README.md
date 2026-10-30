# GACC 历史海关数据半年度批量回填计划 (2018 - 2026)

本目录为中国海关总署 (GACC) 在线查询平台商品出口数据回填规划中心。

- **规划时间跨度**：2018 年 1 月 ～ 2026 年 12 月（共 9 年，18 个半年度批次）。
- **切片策略**：**默认严格按半年（H1: 1~6月，H2: 7~12月）切片**，严防 1000+ 核心税号单次查询行数超出海关接口硬上限而发生静默截断。
- **查询配置**：出口 (`iEType=0`) / 美元 (`currencyType=usd`) / 分月展示 (`monthFlag=1`) / 输出字段选“商品 (CODE_TS)” / 1041 个核心税号。
- **入库保障**：写入 Curated 黄金表 `data/curated/industry/customs_trade_gacc.parquet` 时基于 5 维复合主键执行 Upsert，重复回填自动去重与覆盖，保证零重复。

---

## 1. 2018 - 2026 半年度批次排期与状态追踪表

| 批次编号 | 年份 | 半年区间 | 期间范围 | 状态 | 采集命令 | 说明 |
| :--- | :--- | :--- | :--- | :---: | :--- | :--- |
| **2018H1** | 2018 | 上半年 | 2018-01 ~ 2018-06 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2018 --half H1` | 历史基准数据 |
| **2018H2** | 2018 | 下半年 | 2018-07 ~ 2018-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2018 --half H2` | 历史基准数据 |
| **2019H1** | 2019 | 上半年 | 2019-01 ~ 2019-06 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2019 --half H1` | 历史基准数据 |
| **2019H2** | 2019 | 下半年 | 2019-07 ~ 2019-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2019 --half H2` | 历史基准数据 |
| **2020H1** | 2020 | 上半年 | 2020-01 ~ 2020-06 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2020 --half H1` | 疫情初期异动期 |
| **2020H2** | 2020 | 下半年 | 2020-07 ~ 2020-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2020 --half H2` | 外需爆发扩张期 |
| **2021H1** | 2021 | 上半年 | 2021-01 ~ 2021-06 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2021 --half H1` | 全球高景气共振期 |
| **2021H2** | 2021 | 下半年 | 2021-07 ~ 2021-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2021 --half H2` | 供应链红利兑现期 |
| **2022H1** | 2022 | 上半年 | 2022-01 ~ 2022-06 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2022 --half H1` | 俄乌冲击与能源链异动 |
| **2022H2** | 2022 | 下半年 | 2022-07 ~ 2022-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2022 --half H2` | 海外去库存期 |
| **2023H1** | 2023 | 上半年 | 2023-01 ~ 2023-06 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2023 --half H1` | 出口筑底期 |
| **2023H2** | 2023 | 下半年 | 2023-07 ~ 2023-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2023 --half H2` | 出口温和复苏期 |
| **2024H1** | 2024 | 上半年 | 2024-01 ~ 2024-06 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2024 --half H1` | 电网设备/船舶景气爆发 |
| **2024H2** | 2024 | 下半年 | 2024-07 ~ 2024-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2024 --half H2` | 抢出口与分化期 |
| **2025H1** | 2025 | 上半年 | 2025-01 ~ 2025-06 | **已完成** | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2025 --half H1` | **已完成采集 (5,221 行)** |
| **2025H2** | 2025 | 下半年 | 2025-07 ~ 2025-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2025 --half H2` | 扩充税号待回填 |
| **2026H1** | 2026 | 上半年 | 2026-01 ~ 2026-06 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2026 --half H1` | 扩充税号待回填 |
| **2026H2** | 2026 | 下半年 | 2026-07 ~ 2026-12 | `待采集` | `uv run python scripts/cdp/gacc_cdp_automation.py --year 2026 --half H2` | 最新月份待同步 (截至当前已发月份) |

---

## 2. 批量回填标准作业指南 (Batch SOP)

由于海关总署平台设有滑块验证码防爬风控机制，每个半年度批次需要人工在 Chrome 浏览器中向右滑动一次拼图（耗时约 2 秒）。其余步骤（选型、注入编码、等数据、查总条数、自动导出、重命名、入库）全自动完成。

### 推进方式一：使用排期调度脚本（推荐）

```bash
# 1. 查看排期总览与当前回填进度
uv run python scripts/gacc_batch_scheduler.py --status

# 2. 自动启动下一个待采集的批次
uv run python scripts/gacc_batch_scheduler.py --next

# 3. 指定特定批次执行
uv run python scripts/gacc_batch_scheduler.py --batch 2024H2
```

### 推进方式二：直接执行命令单步回填

在 Chrome 调试实例保持运行的前提下，依次复制表格中的命令执行：

```bash
# 示例：回填 2024 年下半年
uv run python scripts/cdp/gacc_cdp_automation.py --year 2024 --half H2
```

每次执行的节奏：
1. 终端启动并自动点好选项；
2. 弹出滑块提示时，在浏览器中滑动拼图（2 秒）；
3. 终端自动打印返回条数，全自动下载并入库；
4. 耗时约 10~15 秒完成一个半年度批次。

---

## 3. 计划元数据文件

机器可读的结构化批次排期位于同目录下的 YAML 文件：
[`backfill_plan_2018_2026.yaml`](backfill_plan_2018_2026.yaml)。
包含每个批次的起始年月、参数、执行命令及入库目标路径。
