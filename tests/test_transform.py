"""Tests for the cleaning, validation and enrichment logic in transform.py."""
import json

import numpy as np
import pandas as pd
import pytest

import transform


def make_data(hours: int = 6, start: str = "2026-10-20 10:00") -> pd.DataFrame:
    """A small valid table, shaped like the output of transform.load_raw()."""
    index = pd.date_range(start, periods=hours, freq="h", tz="UTC", name="timestamp")
    return pd.DataFrame({
        "price_eur_mwh": 100.0,
        "solar_mwh": 1000.0,
        "wind_onshore_mwh": 2000.0,
        "wind_offshore_mwh": 500.0,
        "load_mwh": 50000.0,
    }, index=index)


# --- clean ---------------------------------------------------------------

def test_clean_drops_hours_with_missing_values():
    df = make_data(hours=4)
    df.iloc[3, df.columns.get_loc("solar_mwh")] = np.nan  # newest hour: no solar yet

    cleaned = transform.clean(df)

    assert len(cleaned) == 3
    assert not cleaned.isna().any().any()


# --- validate ------------------------------------------------------------

def test_validate_accepts_good_data():
    transform.validate(make_data())  # must not raise


@pytest.mark.parametrize("column, value, message", [
    ("price_eur_mwh", 4500.0, "Prices outside"),
    ("price_eur_mwh", -600.0, "Prices outside"),
    ("solar_mwh", -1.0, "Negative generation"),
    ("wind_offshore_mwh", -5.0, "Negative generation"),
    ("load_mwh", 0.0, "Load must be greater than zero"),
])
def test_validate_rejects_bad_values(column, value, message):
    df = make_data()
    df.iloc[2, df.columns.get_loc(column)] = value

    with pytest.raises(ValueError, match=message):
        transform.validate(df)


def test_validate_allows_negative_prices_within_limits():
    # Negative prices are real (too much solar/wind), so they must pass
    df = make_data()
    df["price_eur_mwh"] = -2.49
    transform.validate(df)


def test_validate_rejects_missing_hour():
    df = make_data(hours=6)
    df = df.drop(index=df.index[3])

    with pytest.raises(ValueError, match="1 missing hours"):
        transform.validate(df)


def test_validate_rejects_duplicate_hours():
    df = make_data(hours=3)
    df = pd.concat([df, df.iloc[[1]]]).sort_index()

    with pytest.raises(ValueError, match="Duplicate timestamps"):
        transform.validate(df)


def test_validate_rejects_empty_table():
    with pytest.raises(ValueError, match="No complete hours"):
        transform.validate(make_data().iloc[0:0])


# --- enrich --------------------------------------------------------------

def test_enrich_adds_renewable_total_and_share():
    df = transform.enrich(make_data(hours=1))

    # 1000 solar + 2000 onshore + 500 offshore = 3500; load is not included
    assert df["renewable_mwh"].iloc[0] == 3500.0
    assert df["renewable_share"].iloc[0] == pytest.approx(3500 / 50000)


def test_enrich_uses_german_local_time_across_clock_change():
    # 25 Oct 2026: clocks go back from 03:00 summer time to 02:00 winter time,
    # so the two UTC hours 00:00 and 01:00 are both "02:00" in Berlin
    df = transform.enrich(make_data(hours=4, start="2026-10-24 22:00"))

    assert list(df["hour"]) == [0, 1, 2, 2]
    assert list(df["weekday"]) == ["Sunday"] * 4
    assert str(df["date"].iloc[0]) == "2026-10-25"


# --- loading raw chunks --------------------------------------------------

def write_chunk(folder, name, rows):
    """Write a raw file in the same format as the SMARD API response."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps({"meta_data": {}, "series": rows}))


def test_load_series_removes_overlap_and_keeps_real_values(tmp_path):
    folder = tmp_path / "solar_mwh"
    t0, t1, t2 = 1792962000000, 1792965600000, 1792969200000  # three hours, in ms
    write_chunk(folder, "1.json", [[t0, 10.0], [t1, 20.0]])
    # A later chunk repeats t1, but without a value yet: the real 20.0 must win
    write_chunk(folder, "2.json", [[t1, None], [t2, 30.0]])

    series = transform.load_series(folder)

    assert series.name == "solar_mwh"
    assert series.index.is_unique
    assert list(series.values) == [10.0, 20.0, 30.0]


def test_load_raw_combines_series_into_columns(tmp_path):
    t0, t1 = 1792962000000, 1792965600000
    write_chunk(tmp_path / "price_eur_mwh", "1.json", [[t0, 80.0], [t1, 90.0]])
    write_chunk(tmp_path / "solar_mwh", "1.json", [[t0, 0.0], [t1, None]])

    df = transform.load_raw(tmp_path)

    assert list(df.columns) == ["price_eur_mwh", "solar_mwh"]
    assert len(df) == 2
    assert df["solar_mwh"].isna().sum() == 1  # clean() removes this hour later
