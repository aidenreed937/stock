# 申万行业轮动四大策略池设计与 14:50 盘尾实盘推演

---

## 一、 统一回测与交易执行语义

所有行业策略严格遵循以下回测与实盘执行语义：
1. **T+1 调仓执行**：信号于当日收盘（或 14:50 盘尾预判）生成，次日开盘按目标权重生效并计算当日增益；
2. **真实摩擦成本扣除**：
   - 佣金率 (`commission_rate`): 万一 (0.0001)
   - 滑点率 (`slippage_rate`): 万五 (0.0005)
3. **3% 死区过滤 (`rebalance_deadband: 0.03`)**：
   - 当组合总调仓换手权重 $< 3\%$ 时，忽略调仓，杜绝无效微量换手磨损。

---

## 二、 四大行业轮动策略详细设计

### 1. 纯高景气动量轮动 (`IndustryMomentumRotationStrategy`)
- **配置标识**: `industry_momentum`
- **逻辑**: 每 20 个交易日调仓，按 `ind_momentum` 降序排列，打满得分最高的 Top 3 行业，等权持有各 33.33%。
- **特性**: 强多头主升浪进攻利器（11 年全周期 CAGR +5.53%）。

### 2. 反拥挤逆向低估值 (`IndustryCrowdingReversalStrategy`)
- **配置标识**: `industry_reversal`
- **逻辑**:
  1. 拥挤度硬过滤：`ind_crowding > 85.0` 坚决剔除；
  2. 低估值筛选：在估值处于安全边际（`ind_valuation >= 80.0`，即 PE/PB 分位 $\le 20\%$）的行业中筛选；
  3. 买入动量初起 Top 3 行业。
- **特性**: 防踩踏能力优异，滚动 3 年正收益胜率高达 **64.1%**。

### 3. 供需景气剪刀差 (`IndustrySupplyDemandScissorsStrategy`)
- **配置标识**: `industry_scissors`
- **逻辑**:
  1. 剪刀差门槛过滤：`ind_scissors >= 60.0`（毛利率扩张排名前 40%）；
  2. 综合打分：$0.40 \times \text{ind\_scissors} + 0.35 \times \text{ind\_momentum} + 0.25 \times \text{ind\_smart\_flow}$ 排序取 Top 3。
- **特性**: 重仓具备真实产业链定价权与抗通胀优势的核心赛道。

### 4. 宏观相态元自适应路由器 (`IndustryMetaRouterStrategy`)
- **配置标识**: `industry_meta_router`
- **逻辑**:
  - 监听宏观风险雷达：
    - 若 `panic_index > 75.0` 或基准破位 MA20：100% 切换至银行 (`801780.SI`)、煤炭 (`801950.SI`)、公用事业 (`801160.SI`)、食品饮料 (`801120.SI`) 红利防御；
    - 若宏观处于多头主升区间：切换至电子 (`801080.SI`)、电力设备 (`801730.SI`)、计算机 (`801750.SI`)、通信 (`801770.SI`) 等成长动量赛道。
- **特性**: 全天候跨周期自适应，全周期最大回撤仅 49.55%，危机回撤 42.6%。

---

## 三、 申万 31 行业对应场内 ETF 映射字典

在 [`config/strategy/industry_rotation.yaml`](file:///Users/mac/workspace/personal/finance/stock/config/strategy/industry_rotation.yaml) 中集中维护了 31 行业流动性最高的场内 ETF：

```yaml
industry_etf_map:
  "801010.SI": { symbol: "159825.SZ", name: "农业ETF" }
  "801030.SI": { symbol: "516020.SH", name: "化工ETF" }
  "801040.SI": { symbol: "515210.SH", name: "钢铁ETF" }
  "801050.SI": { symbol: "512400.SH", name: "有色金属ETF" }
  "801080.SI": { symbol: "512480.SH", name: "半导体芯片ETF" }
  "801110.SI": { symbol: "159996.SZ", name: "家电ETF" }
  "801120.SI": { symbol: "515170.SH", name: "食品饮料ETF" }
  "801150.SI": { symbol: "512010.SH", name: "医药ETF" }
  "801160.SI": { symbol: "561560.SH", name: "电力ETF" }
  "801170.SI": { symbol: "159666.SZ", name: "运输ETF" }
  "801180.SI": { symbol: "512200.SH", name: "房地产ETF" }
  "801730.SI": { symbol: "516160.SH", name: "新能源ETF" }
  "801740.SI": { symbol: "512660.SH", name: "军工ETF" }
  "801750.SI": { symbol: "512720.SH", name: "计算机ETF" }
  "801760.SI": { symbol: "512980.SH", name: "传媒ETF" }
  "801770.SI": { symbol: "515880.SH", name: "通信ETF" }
  "801780.SI": { symbol: "512800.SH", name: "银行ETF" }
  "801790.SI": { symbol: "512880.SH", name: "证券ETF" }
  "801880.SI": { symbol: "516110.SH", name: "汽车ETF" }
  "801890.SI": { symbol: "516960.SH", name: "机械装备ETF" }
  "801950.SI": { symbol: "515220.SH", name: "煤炭ETF" }
  "801960.SI": { symbol: "561360.SH", name: "石油石化ETF" }
```
