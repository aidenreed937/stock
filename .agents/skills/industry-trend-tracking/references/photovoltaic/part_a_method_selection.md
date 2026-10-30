# 光伏（630500）交易方法选择 —— Part A：机制/结构层面的确定与取舍

> 研究基准：2026-09，继承 `established_laws.md`（光伏 630500 全链条实证总纲）的 Part A 界定。
> 本文回答一个具体问题：**把光伏当「重资产、有一定成长、低壁垒易扩产拉长周期」的周期股，该选什么交易方法？**
> 结论先行：光伏**不能照搬半导体方法论**（fwd60 择时全失效、无双向剪刀差进攻腿），
> 可移植的只有"反例"，能确定的是**一套「产能周期状态机 + 组合防守门」的结构性方法**。
> 分级沿用 `established_laws.md`：〔A〕机制/结构确定 ·〔B〕单次循环内成立未证重复 ·〔C〕证伪。
> 每一条结论标注落点文档与可复现脚本；结论均为 Ground Truth First（本地 Curated/Mart 实证）。

---

## Part A —— 先定"哪些机制在结构层面必然成立"，由机制反推方法选择

> **思路**：方法不能凭空选。先锁定不依赖单轮行情的结构性机制（必然成立），
> 每一条机制都直接对方法做一次"取舍裁定"——保留下、砍掉什么由机制决定，而非由拟合决定。

### A1. 产能周期是光伏价值的核心定价对象（机制确定 → 方法定位为"周期状态机"）

资金交易的不是当期盈利，而是「单瓦盈利的边际方向 = 产能周期位置的反身性预期」。
逻辑链必然成立（低壁垒扩产行业的普遍机制）：低估扩张 → 投产过剩 → 单瓦盈利预期恶化 → 下跌；
出清 → 供给收缩 → 预期修复 → 上涨。

**方法取舍**：光伏天然是**周期股择时问题**，不是"成长延续"持有问题。方法框架 = 状态机（识别相位），
不是趋势追涨。

- **证据等级**：〔A〕机制/结构确定（逻辑必然性）。
- **出处**：`established_laws.md:A1`；`01_signal_horizon.md`（资金定价对象 = 产能周期反身预期）。
- **脚本**：`scripts/industry_solar_cycle_position.py` → `data/analytics/industry_strategy/industry_solar_cycle_position.md`。

### A1-c. 进攻与防守同源于同一产能周期状态机，互为镜像（方法单选，不叠双轨）

对照半导体方法论的关键偏差点：**半导体是"剪刀差双轨"（防守门 + 进攻脚正交可叠）；
光伏的进攻（上行相位满仓）与防守（过剩/下行相位降仓）共用同一套状态识别开关、共享同一风险源，
在单一标的是互为镜像，不是能叠加的独立 alpha。**

**方法取舍**：
- ✂️ 砍掉"防守腿 + 进攻腿叠加增厚"的设计——在光伏单标的内部是伪正交，只会做冗余降仓。
- ✅ 保留"上行相位满仓吃（进攻）、非上行相位降仓（防守）"的**单一状态机**。
- ➡️ 真正可能正交增厚的方向不在标的内，而是**引入另一个独立供需面的行业**做跨行业低相关相位对冲
  （`A1-c` 推论的跨行业状态套利，**未验证**——列为后续候选，不作当前方法承诺）。

- **证据等级**：〔A〕结构/逻辑确定（同源状态机，互为镜像）；〔B〕跨行业状态套利未验证。
- **出处**：`established_laws.md:A1-c`。

### A2. 低壁垒 → 供给弹性大 → 可交易尺度必须放长（方法裁定：砍 fwd60，走季度 fwd2q/4q）

对照半导体：高壁垒、扩产慢（2-3 年），利用率是**正向延续腿**、数据为高频连续流，fwd60 可跟踪；
光伏低壁垒、扩产快（12-18 个月），利用率是**反向过剩前兆腿**、反身传导链 1-2 年，
fwd60 是噪音（OOS IC 全负），只 fwd2q/fwd4q 才拉开区分度。这是供给弹性结构决定的，不是数据偶然。

| 行业 | 腿 | fwd60 Spearman IC | 裁决 |
| :-- | :-- | :-- | :-- |
| 半导体 | demand 腿（实物流量） | +0.116 / ICIR 0.35 | fwd60 可跟踪 ✅ |
| 光伏 | 需求腿（装机） | +0.106（全）/ **OOS -0.166** | fwd60 失效 ❌ |
| 光伏 | 供给腿·硅料利用率 | **-0.157**（OOS -0.247） | 反向腿，fwd60 失效 ❌ |
| 光伏 | 供给腿·硅片利用率 | **-0.307**（OOS -0.283） | 反向腿，fwd60 失效 ❌ |

**方法取舍**：光伏供需腿在 fwd60 上 IC 全负/样本外失效，直接否定半导体式 fwd60 择时腿的可移植性。
方法决策尺度必须是**季度（fwd2q/4q）**，任何 fwd60 级别的决策都是噪音。

- **证据等级**：〔A〕结构/机制确定（供给弹性决定信号尺度）；〔C〕fwd60 择时腿已证伪。
- **出处**：`established_laws.md:A2`；`01_signal_horizon.md`。
- **脚本**：`scripts/industry_solar_supply_legs_backtest.py` → `data/analytics/industry_strategy/industry_solar_supply_legs_backtest.md`。

### A3. 财报层是滞后验证，不是前瞻（方法裁定：财报只做"减仓防守补丁 + 事后确认"，不当前瞻引擎）

净利 TTM 拐头滞后真实底部约 2 季度（`2024-04-30` 触发减仓门时 630500 已跌掉约 **87% 回撤**）；
财报 capex 先导经检验为**数据截断假象**（"首次触发=数据起点即触发"），可证部分滞后于产业层
（244 天 vs 124 天）。**财报永远追不上产能周期，只能做"确认恶化后的尾部防守"。**

**方法取舍**：
- 💰 净利 TTM 同比：可作**减仓防守门**（同比 ≤0 降仓至 ~0.3），但**不作前瞻择时/增强**。
- 🧱 财报 capex（在建工程/资本开支）：**不建前瞻腿**（已证伪），只作滞后防守确认。
- ⛔ 不可把财报层当"回正收益的引擎"——它只能减亏（`09`:样本外最好 -0.89%）。

- **证据等级**：〔A〕机制确定（财报必然滞后产能周期）；〔C〕capex 先导已证伪。
- **出处**：`established_laws.md:A3`；`05_profit_turn{,_ext}.md`、`06_defense_gates.md`、`08_capex_leading.md`。
- **脚本**：`scripts/industry_solar_profit_turn.py`、`scripts/industry_solar_profit_turn_ext.py`（→ `data/analytics/industry_strategy/industry_solar_profit_turn{,_ext}.md`）、`scripts/industry_solar_fin_defense_gate.py`、`scripts/industry_solar_capex_leading.py`（→ `data/analytics/industry_strategy/industry_solar_capex_leading.md`）。

### A4. 需求分位"贴顶"在高位是反向/反噬，但作为独立择时纪律不成立（方法裁定：不加贴顶门）

贴顶反身机制真实（需求分位冲高后 fwd60 反转），但贴顶区占比高 + 恰逢景气主升也触发，
作为完整择时纪律不成立（全 CAGR 9.16→1.96 劣化）。

**方法取舍**：✂️ 砍掉"贴顶防守门/择时门"——季度/拐点防守层复用贴顶实证**劣化**防守
（三源 5.82/-12.84/46.84 全面劣于 cycle+fin 两源 13.06/-6.47/30.56），不新增危险区分度
（alert fwd4q 28.0% vs ~alert 32.2% 无差异）。

- **证据等级**：〔A〕贴顶反身机制成立；〔C〕作为择时纪律 / 防守门增强不成立。
- **出处**：`established_laws.md:A4`、`12_warning_card.md`。
- **脚本**：`scripts/industry_solar_cap_defense.py`、`scripts/industry_solar_combo_defense.py`、`scripts/industry_solar_warning_card.py`。

---

## Part A 收束：三条机制 → 方法选择矩阵

> 由 A1（状态机）、A2（季度尺度）、A3（财报滞后）、A4（贴顶劣化）四点机制裁定，
> 自然收敛到唯一可行方法形态：

| 机制裁定 | 保留下 | 砍掉 |
| :-- | :-- | :-- |
| A1 产能周期定价 | 周期状态机识别相位 | "双轨进攻+防守叠加"（单标的内伪正交） |
| A2 信号尺度放长 | 季度 fwd2q/4q | fwd60 择时腿（半导体式不可移植） |
| A3 财报滞后 | 净利 TTM 减仓防守门 + 事后确认 | capex 前瞻腿 / 财报当正收益引擎 |
| A4 贴顶反噬 | （不保留） | 贴顶防守门/择时纪律 |

---

## 最终方法形态（B 级证据支撑，须诚实标注局限）

**选定形态（`09_final_closed_loop.md` 定稿）：**
1. **单行业最好形态** = `动量 Top3 选中才持有 + 产能周期状态门`：样本外 **-0.89%**（最接近转正）、
   全周期 8.23% 反超纯买入、MaxDD 16.0%。
2. **最优季度防守门** = `产业层产能周期状态 + 财报 TTM 两源门`：外 -6.47%、外 MaxDD 30.56，
   为所有防守方案最优（`11_warning_card.md` 定稿）。
3. **唯一前瞻危险源** = 产能周期状态门（扩产潮 cap_yoy≥30% + 24 个月余波是 630500 最强状态开关）：
   过剩 vs 上行 fwd4q **-31.5%/胜率 3% vs +82.9%/83%**，且阈值稳健排除调参凑结论（`12`）。
4. 组合防守回撤最稳：`OR 三门（动量+产能+财报）`外 MaxDD 15.99%（但全周期 3.76%，降仓代价大）。

**方法铁律：**
- **杜绝前视**：全部信号 release_date/披露日生效、无前视、T+1 出仓、扣摩擦。
- **成份股聚合口径**：净利 TTM 用 L2 财务黄金表成分股聚合（非单一龙头），避免基数坍塌伪信号——
  2025Q4 起同比"转正"为**基数坍塌伪信号**（绝对额仍深亏），越过披露日会错误放行，实现时需对
  near-zero 基数做强约束（`06_defense_gates.md` 边界 ③）。
- **样本外是硬门槛**：一切改进用 2022-01-01 后样本外检验，不拿全样本刷参数（src 沿用）。

**局限（必须披露，不得隐去）：**
- 全部 B 级时序区分度来自**单次产能循环实现**（2019-2021 涨 + 2022-2024 跌先后分离），
  IS/OOS 跨相位**无法同截面验证**——`「过剩 vs 上行」尚不足以宣称为可重复规律`（`12`）。
- **样本外仍为负收益**（最好 -0.89%）：当前形态本质是"**减亏工具**"，不是正收益来源。
- **当可重复信号使用前必须等 2026+「底部右侧 → 新一轮上行」的二轮数据二次确认**
  （`established_laws.md` 关键未证实项 / `10` 未决项）。

---

## 相关文件与复现

- 总纲：`established_laws.md`（Part A 机制，[A] / [B] / [C] 分级）
- **操作逻辑定稿**：`core_proposition.md`（核心命题：结构化配合而非单一信号）
- 主框架对照（半导体可移植性/反例警示）：`.agents/skills/industry-trend-tracking/references/framework.md`、
  `references/semiconductor/semiconductor_trading_methodology.md`
- 光伏专题实证：`docs/research/photovoltaic/00_study_overview.md`（目录+文档地图）+ 01~12 分文档
- 待办/未决（二轮确认项）：`docs/research/photovoltaic/10_conclusion_roadmap.md`
- 价格补丁定义（三源防守第三源）：`price_patch_definition.md`

全量复现命令：
```bash
uv run python scripts/industry_solar_supply_legs_backtest.py   # A2 fwd60 腿证伪
uv run python scripts/industry_solar_cycle_position.py         # A1/A2 产能周期状态门
uv run python scripts/industry_solar_profit_turn_ext.py        # A3 财报净利 TTM 拐头右确
uv run python scripts/industry_solar_fin_defense_gate.py       # A3 财报减仓防守门
uv run python scripts/industry_solar_combo_defense.py          # A4 财报+贴顶组合（OR/AND）
uv run python scripts/industry_solar_warning_card.py           # 最优两源门（cycle+fin）
uv run python scripts/industry_solar_final_closed_loop.py      # 定稿闭环（动量+组合防守门）
uv run python scripts/industry_solar_cycle_robustness.py       # B 级阈值稳健 + IS/OOS 局限
uv run python scripts/industry_solar_capex_leading.py          # A3 财报 capex 先导证伪
```
分析产物：`data/analytics/industry_strategy/industry_solar_*.md`。
