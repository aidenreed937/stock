import polars as pl

from stock_data.governance.quality.quarantine import QuarantineStore


def test_quarantine_store_writes_history_repair_file(tmp_path) -> None:
    target = QuarantineStore(tmp_path).write_file(
        pl.DataFrame({"symbol": ["000001"], "trade_date": ["1991-01-02"]}),
        endpoint="stock_daily_bar",
        reason="pre_listing_history",
        request_id="repair-1",
        data_source="lixinger",
    )

    assert target == tmp_path / "endpoint=stock_daily_bar" / "history_repair.parquet"
    output = pl.read_parquet(target)
    assert output["quarantine_reason"].to_list() == ["pre_listing_history"]
    assert output["request_id"].to_list() == ["repair-1"]
    assert output["data_source"].to_list() == ["lixinger"]
