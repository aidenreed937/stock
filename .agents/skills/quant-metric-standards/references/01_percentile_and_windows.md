# 历史分位数与时间窗口计算规范 (Percentile & Windowing Standards)

在量化金融中，指标的绝对数值往往随着宏观周期、通胀水平和市场结构演变而漂移，**历史分位数（Percentile Rank）与标准化 Z-Score 是消除静态绝对值偏误、衡量当前估值/情绪相对极端程度的最核心工具**。

---

## 1. 时间窗口选型标准契约 (Windowing Matrix)

根据金融指标的**自相关性周期、发布频率与宏观敏感度**，严格遵守以下时间窗口选型规范：

| 适用时间窗口 | 对应交易日数 | 适用指标类别 | 典型金融场景 | 选型理由与注意事项 |
| :--- | :--- | :--- | :--- | :--- |
| **5 年滚动窗口 (5Y Rolling)** | 通用约 1,215；本项目 **1,250** 交易日 | • 个股/行业估值 (PE/PB)<br>• 行业轮动动量<br>• 短中期情绪/换手率 | 中期估值与行业景气度比较 | 交易日数是工程近似，必须以实际实现和质量报告为准。 |
| **10 年滚动窗口 (10Y Rolling)** | 通用约 2,430；本项目 **2,500** 交易日 | • 大盘宽基估值 (沪深300/中证500)<br>• 股债利差 (ERP)<br>• 长期资产收益率 | 跨越完整牛熊周期的战略配置 | 交易日数是工程近似，必须以实际实现和质量报告为准。 |
| **全样本历史窗口 (Full History)** | $\ge 2,500$ 交易日 | • 大盘拥挤度<br>• 巴菲特比值 (总市值/GDP)<br>• 宏观利率极值 | 极端危机/历史泡沫极值定位 | 用于定位当前市场状态在 A 股有史以来的历史极端分位（如 2015 顶点、2018 底部）。 |
| **短期微观窗口 (20D / 60D)** | 20 / 60 交易日 | • 资金流偏度<br>• 滚动成交活跃度<br>• ATR 真实波幅 | 短线战术择时与流动性挤压 | 衡量月度与季度维度的边际异动与突破。 |

---

## 2. 历史分位数计算标准公式与代码实现

### ① 百分位排名标准算法 (Percentile Rank)
在样本容量为 $N$ 的历史时序序列 $X = \{x_1, x_2, \dots, x_N\}$ 中，当前时点值 $x_t$ 的历史分位数计算式为：

$$\text{Percentile}(x_t) = \frac{\text{Rank}_{\min}(x_t) - 1}{N - 1} \times 100\% \quad (N > 1)$$

* **定义说明**：$N$ 为有效非空样本数；$\text{Rank}_{\min}(x_t)$ 为样本升序排序后的最小名次（最小值排名为 1，最大值排名为 $N$，重复值共享最小名次）；
* **边界特征**：历史最低值对应 $0.00\%$，历史最高值对应 $100.00\%$，历史中位数对应 $50.00\%$。
* **实现约束**：$N \le 1$ 时返回缺失；滚动窗口至少保留窗口长度 80% 的有效样本，当前值为空时返回缺失。

### ② 真实可执行代码实现 (Polars & DuckDB)

#### Polars 实现全历史截面分位数：
```python
import polars as pl

def calc_history_percentile(df: pl.DataFrame, col_name: str) -> pl.DataFrame:
    """计算指标在给定历史样本序列中的百分位排名 (0%~100%)."""
    return df.with_columns(
        (
            (pl.col(col_name).rank(method="min") - 1)
            / (pl.col(col_name).count() - 1)
            * 100
        ).alias(f"{col_name}_percentile")
    )
```

#### DuckDB 实现滚动 10 年（本项目 2,500 日）分位数：
```sql
SELECT
    trade_date,
    symbol,
    pe_ttm,
    PERCENT_RANK() OVER (
        PARTITION BY symbol
        ORDER BY pe_ttm
        ROWS BETWEEN 2499 PRECEDING AND CURRENT ROW
    ) * 100.0 AS pe_10y_percentile
FROM stock_daily_basic;
```

市场温度计的估值主分不是单独的 PE 或 PB 分位，而是以下四项等权组合：

`valuation_temperature = (pe_percentile_10y + pb_percentile_10y + (100 - equity_risk_premium_percentile_10y) + (100 - dividend_yield_percentile_10y)) / 4`

同一基准日切换 5Y/10Y 窗口会改变历史参照样本，因此分数变化不必然表示底层估值数据发生变化。

---

## 3. 滚动 Z-Score (标准化偏离度)

当指标分布近似对称，或需要衡量当前值距离历史均值的标准差偏离倍数时，使用滚动 Z-Score：

$$Z_t = \frac{x_t - \mu_{W}(x)}{\sigma_{W}(x)}$$

* $\mu_{W}(x)$：过去 $W$ 个交易日的移动平均值（Rolling Mean）；
* $\sigma_{W}(x)$：过去 $W$ 个交易日的移动标准差（Rolling Std，$\sigma > 0$）。

### 分布判别基准
* **$|Z| \le 1.0$**：历史正常波动区间（占约 $68.2\%$ 样本）；
* **$1.0 < |Z| \le 2.0$**：温和过热/低估（占约 $27.2\%$ 样本）；
* **$|Z| > 2.0$**：统计学显著极值区（占 $<4.6\%$ 样本，具有均值回归倾向）；
* **$|Z| > 3.0$**：极端黑天鹅/严重脱离常态分布区（占 $<0.3\%$ 样本）。
