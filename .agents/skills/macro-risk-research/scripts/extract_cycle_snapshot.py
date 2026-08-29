"""快速提取最新 20D / 60D 周期特征截面与风险雷达状态。"""

import duckdb
import pandas as pd
import polars as pl


def main():
    risk_df = pl.read_parquet("data/analytics/macro_risk/latest/risk_factors.parquet").with_columns(pl.col("trade_date").cast(pl.Date))
    con = duckdb.connect()
    index_df = pl.from_pandas(con.execute('''
        SELECT trade_date, symbol, close
        FROM "data/curated/lixinger/market=CN/index_daily_bar/**/*.parquet"
        WHERE symbol IN ('000985', '000300', '399006', '000922')
    ''').df()).with_columns(pl.col("trade_date").cast(pl.Date))

    latest_date = risk_df["trade_date"].max()
    print(f"=== 宏观风控与周期分析截面 (最新交易日: {latest_date}) ===")

    # 提取最近 60 交易日
    dates_60 = risk_df["trade_date"].sort().tail(60).to_list()
    risk_60 = risk_df.filter(pl.col("trade_date").is_in(dates_60)).sort("trade_date")
    index_60 = index_df.filter(pl.col("trade_date").is_in(dates_60)).sort(["symbol", "trade_date"])

    # 最新一行风控
    latest = risk_60.tail(1).to_dicts()[0]
    def _fmt(val):
        return f"{val:.1f}" if val is not None else "—"

    print("\n[1. 双轨风控雷达最新状态 (8 维全景画像)]")
    print(f"  - 狂热指数 (Overheat): {_fmt(latest.get('overheat_index'))}")
    print(f"  - 恐慌指数 (Panic)   : {_fmt(latest.get('panic_index'))}")
    # 3 大生存硬约束
    print(f"  - 两融杠杆分位       : {_fmt(latest.get('dim_leverage'))}")
    if latest.get("dim_leverage") is None:
        print("    ⚠ 提示: 最新交易日两融数据缺失 (dim_leverage 为 null)，杠杆维度硬约束排查不可用，请先补数")
    print(f"  - 换手拥挤分位       : {_fmt(latest.get('dim_crowding'))}")
    print(f"  - 主力资金分位       : {_fmt(latest.get('dim_flow'))}")
    # 2 大拐点快变量
    print(f"  - 期权情绪分位       : {_fmt(latest.get('dim_sentiment'))}")
    print(f"  - 市场广度分位       : {_fmt(latest.get('dim_breadth'))}")
    # 1 个长线慢变量
    print(f"  - 大盘估值分位       : {_fmt(latest.get('dim_valuation'))}")
    # 1 个微观基本面底
    print(f"  - 产业资本分位       : {_fmt(latest.get('dim_corporate'))}")
    # 1 个全谱系流动性
    print(f"  - 跨资产宏观分位     : {_fmt(latest.get('dim_cross_asset'))}")
    # 聪明钱独立维度（未加入双轨指数，供策略选用）
    print(f"  - 聪明钱组合分位     : {_fmt(latest.get('smart_money_score'))}")

    # 指数近 60 日与近 20 日涨跌
    print("\n[2. 核心指数 20日 / 60日 区间涨跌幅与回撤]")
    res = []
    for sym, name in [("000985", "中证全指"), ("000300", "沪深300"), ("399006", "创业板指"), ("000922", "中证红利")]:
        sub = index_60.filter(pl.col("symbol") == sym).sort("trade_date")
        if len(sub) >= 20:
            sub20 = sub.tail(20)
            ret20 = (sub20["close"][-1] / sub20["close"][0] - 1.0) * 100
        else:
            ret20 = 0.0
        ret60 = (sub["close"][-1] / sub["close"][0] - 1.0) * 100
        cum_max = sub["close"].cum_max()
        max_dd = ((sub["close"] / cum_max) - 1.0).min() * 100
        res.append({
            "指数": name,
            "代码": sym,
            "最新收盘": round(sub["close"][-1], 2),
            "近20日涨跌": f"{ret20:+.2f}%",
            "近60日涨跌": f"{ret60:+.2f}%",
            "60日最大回撤": f"{max_dd:.2f}%",
        })
    print(pd.DataFrame(res).to_string(index=False))

if __name__ == "__main__":
    main()
