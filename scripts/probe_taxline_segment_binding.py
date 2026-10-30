"""探针：5 个段产品的 bz_item → 段 可绑捕获率（规则/关键词匹配，非手动非 LLM）。

复用 H8 链的匹配口径，把目标从「产品」下沉到「段」：每段建语料
（segment_name + description + 该段 H8 码的 hs_name），对已匹配到产品的
bz_item 做第二层打分。输出每产品的 bz_item/公司可绑、含糊、回退三档占比，
用于判断段级绑定值不值得接进 H8 链（捕获率低 → 只能手动/LLM）。

用法:
    uv run python scripts/probe_taxline_segment_binding.py
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import polars as pl
from rapidfuzz import fuzz

SEGMENTS_PATH = Path("config/data/customs/taxline_segments.csv")
CATALOG_PATH = Path("config/data/customs/good_h8_codes.csv")
MAPPING_PATH = Path("data/curated/mart/customs_company_product_mapping.parquet")

_SEGMENTED_PRODUCTS = (
    "transformer",
    "semiconductor_equipment",
    "lithium_chemicals",
    "silver",
    "cathode_material",
)
_STOP_TOKENS = frozenset({"产品", "业务", "系列", "项目", "收入", "其他", "相关"})
_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")
_BIND_SCORE = 88.0
_AMBIGUOUS_SCORE = 65.0
_BIND_MARGIN = 6.0


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[_/|;,，。；、()（）\[\]【】+\-]+", " ", text)
    return " ".join(text.split())


def _tokens(value: object) -> tuple[str, ...]:
    normalized = _norm(value)
    tokens = [t for t in _TOKEN_RE.findall(normalized) if t not in _STOP_TOKENS]
    return tuple(dict.fromkeys(tokens))


def _score(item: str, seg_name: str, corpus: str) -> float:
    """与 customs_company_h8._score_item 同口径，目标换成段语料。"""
    item_norm = _norm(item)
    name_norm = _norm(seg_name)
    corpus_norm = _norm(corpus)
    if item_norm == name_norm:
        return 100.0
    item_tokens = " ".join(_tokens(item))
    corpus_tokens = " ".join(_tokens(corpus))
    token_score = fuzz.token_set_ratio(item_tokens, corpus_tokens) if item_tokens else 0.0
    char_score = fuzz.ratio(item_norm, name_norm) if name_norm else 0.0
    partial_score = fuzz.partial_ratio(item_norm, corpus_norm) if corpus_norm else 0.0
    score = max(char_score * 0.75 + partial_score * 0.25, token_score * 0.6 + partial_score * 0.2)
    if item_norm in name_norm or name_norm in item_norm:
        score = max(score, 92.0)
    else:
        score = min(score, 86.0)
    if len(item_norm.replace(" ", "")) < 3:
        score = min(score, 72.0)
    return round(score, 4)


def _load_segments() -> pl.DataFrame:
    frame = pl.read_csv(SEGMENTS_PATH).with_columns(pl.all().cast(pl.String))
    hs_name = {
        str(r["hs_code"]): str(r.get("hs_name") or "").strip()
        for r in pl.read_csv(CATALOG_PATH, infer_schema_length=0).iter_rows(named=True)
    }

    def corpus(row: dict[str, object]) -> str:
        names = [str(hs_name.get(code, "") or "") for code in str(row["hs_codes"]).split(";")]
        return " ".join([str(row["segment_name"]), str(row["description"]), " ".join(names)])

    return frame.with_columns(
        pl.struct(["segment_name", "hs_codes", "description"])
        .map_elements(corpus, return_dtype=pl.String)
        .alias("corpus")
    )


def main() -> int:
    segments = _load_segments()
    mapping = pl.read_parquet(MAPPING_PATH).filter(
        (pl.col("match_status") == "selected")
        & pl.col("product_key").is_in(_SEGMENTED_PRODUCTS)
        & pl.col("product_key").is_not_null()
    )
    items = (
        mapping.group_by(["product_key", "bz_item"])
        .agg(pl.col("symbol").n_unique().alias("n_company"))
        .sort(["product_key", "n_company"], descending=[False, True])
    )

    print(
        f"=== 段产品 bz_item → 段 捕获率（bind≥{_BIND_SCORE} & margin≥{_BIND_MARGIN}；"
        f"ambiguous≥{_AMBIGUOUS_SCORE}；其余回退产品级）===\n"
    )
    total_companies = 0
    bind_companies = 0
    for product in _SEGMENTED_PRODUCTS:
        segs = segments.filter(pl.col("product_key") == product)
        sub = items.filter(pl.col("product_key") == product)
        if segs.is_empty() or sub.is_empty():
            continue
        bind_rows: list[dict[str, object]] = []
        ambiguous_rows: list[dict[str, object]] = []
        for row in sub.iter_rows(named=True):
            item = str(row["bz_item"])
            ranked = sorted(
                (
                    (_score(item, str(s["segment_name"]), str(s["corpus"])), s)
                    for s in segs.iter_rows(named=True)
                ),
                key=lambda pair: (-pair[0], pair[1]["segment_key"]),
            )
            top_score, top_seg = ranked[0]
            second = ranked[1][0] if len(ranked) > 1 else 0.0
            margin = top_score - second
            if top_score >= _BIND_SCORE and margin >= _BIND_MARGIN:
                bind_rows.append(
                    {
                        "item": item,
                        "n": row["n_company"],
                        "seg": top_seg["segment_name"],
                        "score": top_score,
                    }
                )
            elif top_score >= _AMBIGUOUS_SCORE:
                ambiguous_rows.append(
                    {
                        "item": item,
                        "n": row["n_company"],
                        "seg": top_seg["segment_name"],
                        "score": top_score,
                    }
                )

        n_company = int(sub["n_company"].sum())
        n_bind = sum(r["n"] for r in bind_rows)
        n_amb = sum(r["n"] for r in ambiguous_rows)
        total_companies += n_company
        bind_companies += n_bind
        print(f"[{product}] bz_item {sub.height} 种 / 公司 {n_company} 家")
        print(
            f"  可绑段(公司) {n_bind} ({n_bind / n_company:.0%})；"
            f"含糊 {n_amb} ({n_amb / n_company:.0%})；回退 {n_company - n_bind - n_amb}"
        )
        for r in sorted(bind_rows, key=lambda x: -x["n"]):
            print(f"    → {r['seg']}: 「{r['item']}」({r['n']}家, {r['score']:.0f})")
        if ambiguous_rows:
            amb_top = sorted(ambiguous_rows, key=lambda x: -x["n"])[:3]
            print("    含糊示例: " + "; ".join(f"「{r['item']}」→{r['seg']}" for r in amb_top))
        print()

    if total_companies:
        print(
            f"=== 汇总：{total_companies} 家段产品公司，可绑 {bind_companies} "
            f"({bind_companies / total_companies:.0%}) ==="
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
