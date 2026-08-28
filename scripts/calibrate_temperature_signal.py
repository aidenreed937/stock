"""温度信号校准回放脚本（A3：将 calibration 文档口径脚本化；A1：t+1 生效修正）。

用途: 复现 docs/research/temperature_signal_calibration.md 中的核心统计与回测，
     使该文档的措施口径可重跑、可校验。仅读取上游产物（history.parquet / 各 run 的
     facts.parquet / index_daily_bar），不修改任何产物；可选 --out 保存 JSON。

口径要点（与文档第 2 节一致）:
  - 样本: 988 交易日（2022-08-01..2026-08-26），以 history.parquet 有效 composite 为准；
  - 价格前向 fwdN = 中证全指 000985.CSI 未来 N 个交易日收益率（收盘对齐，名义收益，无成本）；
  - 温度惯性 tN = composite 未来 N 个交易日变化值；
  - 过去 3 日温度降幅 chg3d = composite - composite.shift(3)（冰点加速确认用过去值，防未来函数）；
  - 灯光合成: 风险灯 l_hot(comp>=65)/l_margin(两融>=95分位)/l_amount(成交>=90分位)/
    l_flowout(主力净流出<=-5%)；底部灯 l_width_weak(above_ma60<30%)/l_risk_high(risk=高)；
    net_risk = 风险灯数 - 底部灯数；
  - risk 升档事件: risk 序数(低0/低到中等1/中等2/中等偏高3/高4)较前日增大 且 目标>=中等(2)；
  - 回测 A1 修复: 信号 t 日收盘生成、t+1 日起生效（pos 滞后 1 日），无成本；
  - 多档仓位 beta = temp_beta(温度带) x risk_discount(net_risk)，
    temp_beta: comp<30->0.9 / <45->0.6 / <55->0.4 / <65->0.25 / >=65->0.1；
    risk_discount: net_risk<=0->1.0 / =1->0.8 / =2->0.5 / >=3->0.25；
  - 严格版: 滚动 walk-forward，每 252 日仅用当日之前 comp 分位数(p15/p40/p60/p85)重估，
    OOS 段 63 日/段逐段拼接。

输出: 控制台表格 + 可选 JSON（--out）。退出码 0 表示成功。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import polars as pl

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from stock_data.catalog import DataCatalog  # noqa: E402

MARKET_ROOT = _ROOT / "data/analytics/market_temperature"
INDEX_SYMBOL = "000985.CSI"
HISTORY_PATH = "index/history.parquet"

RISK_ORDER = {"低": 0, "低到中等": 1, "中等": 2, "中等偏高": 3, "高": 4}
FWD_WINDOWS = (1, 3, 5, 10, 20)


def _load_history() -> pl.DataFrame:
    df = pl.read_parquet(MARKET_ROOT / HISTORY_PATH)
    return (
        df.filter(pl.col("is_latest_for_date"))
        .filter(pl.col("composite_temperature").is_not_nan())
        .select(["as_of_date", "composite_temperature", "fast_temperature", "risk_level"])
        .unique(subset=["as_of_date"])
        .sort("as_of_date")
    )


def _load_facts_matrix() -> pl.DataFrame:
    """回放每个 as_of 最新 run 的 facts.parquet -> 需要的指标宽表。"""
    needed = [
        "above_ma60_share",
        "main_large_order_net_inflow_share",
        "margin_penetration_percentile_1250d",
        "market_amount_percentile_1250d",
    ]
    rows = []
    for asof_dir in sorted((MARKET_ROOT / "runs").glob("as_of=*")):
        runs = sorted(asof_dir.glob("run_*"))
        if not runs:
            continue
        facts_path = runs[-1] / "facts.parquet"
        if not facts_path.exists():
            continue
        try:
            facts = pl.read_parquet(facts_path).filter(pl.col("metric_id").is_in(needed))
        except Exception:
            continue
        if facts.is_empty():
            continue
        rec = {"as_of_date": facts["as_of_date"][0]}
        for metric in needed:
            hit = facts.filter(pl.col("metric_id") == metric)
            rec[metric] = hit["value_float"][0] if hit.height else None
        rows.append(rec)
    if not rows:
        return pl.DataFrame(schema={"as_of_date": pl.Date})
    return pl.DataFrame(rows).unique(subset=["as_of_date"]).sort("as_of_date")


def _load_index() -> pl.DataFrame:
    catalog = DataCatalog(data_source="tushare")
    idx = catalog.load_dataset("index_daily_bar", end_date=dt.date(2026, 8, 26))
    return (
        idx.filter(pl.col("symbol") == INDEX_SYMBOL)
        .select(["trade_date", "close"])
        .rename({"close": "idx_close"})
    )


def build_panel() -> pl.DataFrame:
    hist = _load_history()
    facts = _load_facts_matrix()
    index = _load_index()
    df = hist.join(facts, on="as_of_date", how="left").join(
        index, left_on="as_of_date", right_on="trade_date", how="left"
    )
    df = df.sort("as_of_date")
    df = df.with_columns(pl.col("idx_close").pct_change().alias("ret"))
    for hd in FWD_WINDOWS:
        df = df.with_columns(
            (pl.col("idx_close").shift(-hd) / pl.col("idx_close") - 1.0).alias(f"fwd{hd}")
        )
        df = df.with_columns(
            (pl.col("composite_temperature").shift(-hd) - pl.col("composite_temperature")).alias(
                f"t{hd}"
            )
        )
    # 过去 3 日温度降幅（冰点加速确认条件，防未来函数）
    df = df.with_columns(
        (pl.col("composite_temperature") - pl.col("composite_temperature").shift(3)).alias("chg3d")
    )
    # 连续高温计数
    comp = df["composite_temperature"].to_list()
    streak, cur = [], 0
    for c in comp:
        cur = cur + 1 if (c is not None and c > 60) else 0
        streak.append(cur)
    df = df.with_columns(pl.Series("hot_streak", streak))
    # risk 序数与升档事件
    df = df.with_columns(
        pl.col("risk_level").replace_strict(RISK_ORDER, default=None).alias("risk_num")
    )
    df = df.with_columns(
        (
            (pl.col("risk_num") > pl.col("risk_num").shift(1))
            & pl.col("risk_num").is_not_null()
            & pl.col("risk_num").shift(1).is_not_null()
            & (pl.col("risk_num") >= 2)
        ).alias("risk_up")
    )
    return df


def add_lights(df: pl.DataFrame) -> pl.DataFrame:
    """灯光合成：风险灯/底部灯/net_risk（幂等，可在多个实验中复用）。"""
    if "net_risk" in df.columns:
        return df
    lights = [
        pl.when(pl.col("composite_temperature") >= 65.0)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .alias("l_hot"),
        pl.when(pl.col("margin_penetration_percentile_1250d") >= 95.0)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .alias("l_margin"),
        pl.when(pl.col("market_amount_percentile_1250d") >= 90.0)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .alias("l_amount"),
        pl.when(pl.col("main_large_order_net_inflow_share") <= -0.05)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .alias("l_flowout"),
        pl.when(pl.col("above_ma60_share") < 0.30)
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .alias("l_width_weak"),
        pl.when(pl.col("risk_level") == "高")
        .then(pl.lit(1))
        .otherwise(pl.lit(0))
        .alias("l_risk_high"),
    ]
    df = df.with_columns(lights)
    df = df.with_columns(
        (pl.col("l_hot") + pl.col("l_margin") + pl.col("l_amount") + pl.col("l_flowout")).alias(
            "risk_lights"
        ),
        (pl.col("l_width_weak") + pl.col("l_risk_high")).alias("bottom_lights"),
        (
            pl.col("l_hot")
            + pl.col("l_margin")
            + pl.col("l_amount")
            + pl.col("l_flowout")
            - pl.col("l_width_weak")
            - pl.col("l_risk_high")
        ).alias("net_risk"),
    )
    return df


def _fmt(v: pl.Series) -> str:
    if v.len() == 0:
        return "  --  "
    return f"{v.mean() * 100:+.2f}%({int((v > 0).mean() * 100):>2})"


def _stat_rows(sub: pl.DataFrame, windows: tuple[int, ...] = FWD_WINDOWS) -> list[str]:
    return [f"fwd{hd} {_fmt(sub[f'fwd{hd}'].drop_nulls())}" for hd in windows]


def experiment1(df: pl.DataFrame) -> None:
    print("\n===== 实验 1：温度因子对价格前向收益的预测力 =====")
    cases = [
        ("高温 comp>60", pl.col("composite_temperature") > 60.0),
        ("冰点+加速", (pl.col("composite_temperature") <= 45.0) & (pl.col("chg3d") <= -3.0)),
        ("冰点极端 comp<30", pl.col("composite_temperature") < 30.0),
        ("risk 升档事件", pl.col("risk_up")),
        (
            "两融>=95 + 成交>=90",
            (pl.col("margin_penetration_percentile_1250d") >= 95.0)
            & (pl.col("market_amount_percentile_1250d") >= 90.0),
        ),
        ("宽度 <30%", pl.col("above_ma60_share") < 0.30),
        ("risk_level=高", pl.col("risk_level") == "高"),
    ]
    for label, cond in cases:
        sub = df.filter(cond)
        print(f"{label:<24} n={sub.height:<4} " + "  ".join(_stat_rows(sub)))


def experiment2(df: pl.DataFrame) -> None:
    print("\n===== 实验 2：净风险合成与分半 =====")
    df = add_lights(df)
    for k in (-1, 0, 1, 2):
        sub = df.filter(pl.col("net_risk") == k)
        print(f"net_risk={k:+d} n={sub.height:<4} " + "  ".join(_stat_rows(sub)))

    mid = df["as_of_date"].sort()[df.height // 2]
    for k in (0, -1):
        h1 = df.filter((pl.col("net_risk") == k) & (pl.col("as_of_date") <= mid))
        h2 = df.filter((pl.col("net_risk") == k) & (pl.col("as_of_date") > mid))
        line = (
            f"net_risk={k:+d} 前半 n={h1.height} {_fmt(h1['fwd20'].drop_nulls())}"
            f" | 后半 n={h2.height} {_fmt(h2['fwd20'].drop_nulls())}"
        )
        print(line)


def _temp_beta(c: float | None) -> float:
    if c is None:
        return 0.4
    if c < 30:
        return 0.9
    if c < 45:
        return 0.6
    if c < 55:
        return 0.4
    if c < 65:
        return 0.25
    return 0.1


def _risk_discount(r: int | None) -> float:
    if r is None or r <= 0:
        return 1.0
    if r == 1:
        return 0.8
    if r == 2:
        return 0.5
    return 0.25


def _eval_pos(pos: list[float], rets: list[float], label: str, start: int = 1) -> None:
    """评估仓位序列在 [start, n) 区间的收益（t+1 生效：pos[t-1] 决定 t 日持有）。"""
    n = len(pos)
    strat = [pos[i - 1] * rets[i] for i in range(start, n)]
    bench = rets[start:]
    ns = 1.0
    nb = 1.0
    for x in strat:
        ns *= 1 + x
    for x in bench:
        nb *= 1 + x
    peak, mdd = 0.0, 0.0
    nav = 1.0
    for x in strat:
        nav *= 1 + x
        peak = max(peak, nav)
        mdd = min(mdd, nav / peak - 1)
    period = len(strat)
    print(
        f"{label:<22} 累计 {ns * 100 - 100:+8.1f}%  年化 {(ns ** (252.0 / period) - 1) * 100:+6.1f}%  "
        f"回撤 {mdd * 100:6.1f}%  平均仓位 {sum(pos[start - 1 : n - 1]) / period * 100:5.1f}%"
    )


def experiment3(df: pl.DataFrame) -> None:
    """择时回测（A1：t+1 生效修正）。滚动前验/固定/0-1 三版 + 满仓基准。"""
    print("\n===== 实验 3：择时回测（信号 t+1 生效，无成本） =====")
    df = add_lights(df)
    comps = df["composite_temperature"].to_list()
    nrs = df["net_risk"].to_list()
    rets = df["ret"].fill_null(0.0).to_list()
    n = df.height

    # 0/1 开关：comp<30 且 net_risk<=0 才满仓
    pos_switch = [
        1.0 if (c is not None and c < 30 and (nr or 0) <= 0) else 0.0 for c, nr in zip(comps, nrs)
    ]

    # 固定阈值多档
    pos_fixed = [_temp_beta(c) * _risk_discount(nr) for c, nr in zip(comps, nrs)]

    # 滚动前验/后验：每 252 日重估 comp 分位数阈值，OOS 段 63 日
    pos_rolling = [0.4] * n
    refit_days, out_days = 252, 63
    t = refit_days
    while t < n:
        train = [c for c in comps[:t] if c is not None]
        q = sorted(train)
        p15 = q[int(len(q) * 0.15)]
        p40 = q[int(len(q) * 0.40)]
        p60 = q[int(len(q) * 0.60)]
        p85 = q[int(len(q) * 0.85)]
        end = min(t + out_days, n)
        for i in range(t, end):
            c = comps[i]
            if c is None or c < p15:
                b = 0.9
            elif c < p40:
                b = 0.6
            elif c < p60:
                b = 0.4
            elif c < p85:
                b = 0.25
            else:
                b = 0.1
            pos_rolling[i] = b * _risk_discount(nrs[i])
        t = end

    print("--- OOS 段（滚动版，纯样本外拼接） ---")
    # 滚动版只在 OOS 段评估：前 252 天定为前验（不统计），其后每段为样本外
    oos_pos = [0.0] * refit_days + pos_rolling[refit_days:]
    _eval_pos(oos_pos, rets, "滚动前验/后验(OOS)", start=refit_days + 1)
    _eval_pos([1.0] * n, rets, "满仓基准(OOS段)", start=refit_days + 1)
    _eval_pos(pos_fixed, rets, "固定阈值·多档位")
    _eval_pos(pos_switch, rets, "0/1 开关")
    _eval_pos([1.0] * n, rets, "满仓基准(全样本)")


def experiment87(df: pl.DataFrame) -> None:
    print("\n===== 8.7 连续高温 × 反弹 =====")
    df = add_lights(df)
    df = df.with_columns((pl.col("ret") > 0).fill_null(False).alias("up_day"))
    groups = [
        ("hot 全部", pl.col("hot_streak") >= 1),
        ("hot + 当日反弹", (pl.col("hot_streak") >= 1) & pl.col("up_day")),
        ("连续>=2 + 反弹", (pl.col("hot_streak") >= 2) & pl.col("up_day")),
        ("连续>=3 + 反弹", (pl.col("hot_streak") >= 3) & pl.col("up_day")),
        ("连续>=3 全部", pl.col("hot_streak") >= 3),
        ("非高温反弹", (pl.col("hot_streak") == 0) & pl.col("up_day")),
    ]
    for label, cond in groups:
        sub = df.filter(cond)
        print(f"{label:<16} n={sub.height:<4} " + "  ".join(_stat_rows(sub, (1, 5, 20))))


def experiment88(df: pl.DataFrame) -> None:
    print("\n===== 8.8 comp × risk 交叉（20 日） =====")
    df = add_lights(df)
    df = df.with_columns(
        pl.when(pl.col("risk_level").is_in(["低", "低到中等"]))
        .then(pl.lit("risk-L"))
        .when(pl.col("risk_level") == "中等")
        .then(pl.lit("risk-M"))
        .otherwise(pl.lit("risk-H"))
        .alias("rg")
    )
    comp_grp = (
        pl.when(pl.col("composite_temperature") < 30)
        .then(pl.lit("c<30"))
        .when(pl.col("composite_temperature") < 45)
        .then(pl.lit("c30-45"))
        .when(pl.col("composite_temperature") < 55)
        .then(pl.lit("c45-55"))
        .when(pl.col("composite_temperature") < 65)
        .then(pl.lit("c55-65"))
        .otherwise(pl.lit("c>=65"))
    )
    df = df.with_columns(comp_grp.alias("cg"))
    print("comp\\risk     risk-L            risk-M            risk-H")
    for cg in ["c<30", "c30-45", "c45-55", "c55-65", "c>=65"]:
        cells = []
        for rg in ("risk-L", "risk-M", "risk-H"):
            sub = df.filter((pl.col("cg") == cg) & (pl.col("rg") == rg))
            if sub.height == 0:
                cells.append("n=0")
            else:
                cells.append(f"{_fmt(sub['fwd20'].drop_nulls())}(n={sub.height})")
        print(f"{cg:<12} {'  '.join(c.ljust(16) for c in cells)}")


def experiment891(df: pl.DataFrame) -> None:
    print("\n===== 8.9.1 规则触发合理性（回放 decision_trace，历史生产规则） =====")
    by_date: dict[str, set] = {}
    versions: set[str] = set()
    for asof_dir in sorted((MARKET_ROOT / "runs").glob("as_of=*")):
        runs = sorted(asof_dir.glob("run_*"))
        if not runs:
            continue
        scores_path = runs[-1] / "scores.json"
        if not scores_path.exists():
            continue
        try:
            scores = json.loads(scores_path.read_text())
        except Exception:
            continue
        trace = (scores.get("systemic_risk") or {}).get("decision_trace") or {}
        if trace.get("rule_version"):
            versions.add(trace["rule_version"])
        triggered = by_date.setdefault(asof_dir.name.split("=")[1], set())
        for rule in trace.get("triggered_rules", []):
            triggered.add(rule.get("rule_id"))
    # 动态收集历史 trace 实际出现的 rule_id（兼容 v3/v4/v5，避免硬编码漂移）
    discovered: set[str] = set()
    for triggered in by_date.values():
        discovered |= triggered
    rule_ids = sorted(discovered)

    flags = {rid: [] for rid in rule_ids}
    for d in df["as_of_date"].to_list():
        triggered = by_date.get(d.isoformat(), set())
        for rid in rule_ids:
            flags[rid].append(1 if rid in triggered else 0)
    df = df.with_columns([pl.Series(rid, flags[rid]).alias(rid) for rid in rule_ids])
    print(f"历史 trace 中的 rules_version: {sorted(versions)}")
    print(f"发现的 rule_id 数: {len(rule_ids)}")
    for rid in rule_ids:
        n = int(df[rid].sum())
        if n == 0:
            print(f"{rid:<42} 0  (从未触发)")
            continue
        sub = df.filter(pl.col(rid) == 1)
        print(f"{rid:<42} n={n:<4} " + "  ".join(_stat_rows(sub, (5, 10, 20))))


def experiment_v4_offline() -> None:
    """Step 2/3 健康度：用当前 SystemicRiskConfig(v4) 离线重算历史 risk_level 分布。

    历史 scores.json 里的 systemic_risk 是各历史 run 生产期规则（v3）产出的；
    本段用代码当前配置重算 988 天，输出新规则下的档位分布，验证死规则修复
    与 sentiment 降级的实际效果（不写产物，只读 scores.json）。
    """
    print("\n===== Step2/3 离线验证：v4 规则重算历史 risk_level 分布 =====")
    try:
        from stock_analytics.pipelines.market_temperature.scoring_risk import _systemic_risk
    except ImportError:
        print("import scoring_risk 失败，跳过（需在项目根运行）")
        return
    from stock_core.config.analytics_market_temperature import SystemicRiskConfig

    cfg = SystemicRiskConfig()
    new_counts = dict.fromkeys(["低到中等", "中等", "中等偏高", "高"], 0)
    rule_counts: dict[str, int] = {}
    old_counts = dict.fromkeys(["低到中等", "中等", "中等偏高", "高"], 0)
    n_days = 0
    for asof_dir in sorted((MARKET_ROOT / "runs").glob("as_of=*")):
        runs = sorted(asof_dir.glob("run_*"))
        if not runs:
            continue
        scores_path = runs[-1] / "scores.json"
        if not scores_path.exists():
            continue
        try:
            scores = json.loads(scores_path.read_text())
        except Exception:
            continue
        composite = (
            (scores.get("composite") or {}).get("temperature")
            if isinstance(scores.get("composite"), dict)
            else None
        )
        dims = scores.get("dimensions") or []
        fast_slow = scores.get("fast_slow") or {}
        if composite is None or not isinstance(dims, list) or not dims:
            continue
        old = (scores.get("systemic_risk") or {}).get("level")
        if old in old_counts:
            old_counts[old] += 1
        new = _systemic_risk(composite, dims, fast_slow=fast_slow, config=cfg)
        new_counts[new["level"]] = new_counts.get(new["level"], 0) + 1
        for rule in new["decision_trace"]["triggered_rules"]:
            rule_counts[rule["rule_id"]] = rule_counts.get(rule["rule_id"], 0) + 1
        n_days += 1

    print(f"重算天数: {n_days}")
    print(f"{'level':<10}{'旧(history)':>14}{'新(v4 重算)':>14}")
    for lv in ["低到中等", "中等", "中等偏高", "高"]:
        print(f"{lv:<10}{old_counts[lv]:>14}{new_counts[lv]:>14}")
    print("v4 规则触发频率（Top 8）:")
    for rid, n in sorted(rule_counts.items(), key=lambda x: -x[1])[:8]:
        print(f"  {rid:<44} {n}")


def run() -> int:
    df = build_panel()
    print(f"面板: {df.height} 天, {df['as_of_date'].min()} .. {df['as_of_date'].max()}")
    experiment1(df)
    experiment2(df)
    experiment3(df)
    experiment87(df)
    experiment88(df)
    experiment891(df)
    experiment_v4_offline()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", help="(预留) 注入预装配面板，未实现", default=None)
    args = parser.parse_args()
    _ = args
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
