"""快速提取最新 20D / 60D 周期特征截面与风险雷达状态。"""

import sys
import duckdb
import polars as pl
import pandas as pd

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
    print(f"\n[1. 双轨风控雷达最新状态]")
    print(f"  - 狂热指数 (Overheat): {latest.get('overheat_index', 0):.1f}")
    print(f"  - 恐慌指数 (Panic)   : {latest.get('panic_index', 0):.1f}")
    print(f"  - 两融杠杆分位       : {latest.get('dim_leverage', 0):.1f}")
    print(f"  - 换手拥挤分位       : {latest.get('dim_crowding', 0):.1f}")
    print(f"  - 主力资金分位       : {latest.get('dim_flow', 0):.1f}")
    print(f"  - 国家队ETF托底分位  : {latest.get('etf_flow_ratio_score', 0):.1f}")
    print(f"  - 大盘估值分位       : {latest.get('dim_valuation', 0):.1f}")

    # 指数近 60 日与近 20 日涨跌
    print(f"\n[2. 核心指数 20日 / 60日 区间涨跌幅与回撤]")
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
