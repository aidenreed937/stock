import polars as pl

from stock_data.fetcher.tushare.slicer import batch_slice_and_merge


def test_batch_slice_and_merge_single_worker() -> None:
    def dummy_fetch(ts_code: str) -> pl.DataFrame:
        codes = ts_code.split(",")
        return pl.DataFrame({"ts_code": codes, "value": [1.0] * len(codes)})

    symbols = [f"{i:06d}.SZ" for i in range(1, 15)]
    df = batch_slice_and_merge(dummy_fetch, symbols, batch_size=5, max_workers=1)
    assert len(df) == 14
    assert df["ts_code"].to_list() == symbols


def test_batch_slice_and_merge_parallel_workers() -> None:
    def dummy_fetch(ts_code: str) -> pl.DataFrame:
        codes = ts_code.split(",")
        return pl.DataFrame({"ts_code": codes, "value": [2.0] * len(codes)})

    symbols = [f"{i:06d}.SH" for i in range(1, 11)]
    df = batch_slice_and_merge(dummy_fetch, symbols, batch_size=3, max_workers=2)
    assert len(df) == 10


def test_batch_slice_and_merge_empty() -> None:
    assert batch_slice_and_merge(lambda **kwargs: pl.DataFrame(), []).is_empty()
