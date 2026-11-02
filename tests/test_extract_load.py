"""Tests for extract.py and load.py that need no internet and no database."""
from datetime import date, datetime

import pandas as pd

import extract
import load
import transform


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    """Stands in for requests.Session, so no real API call is made."""

    def __init__(self, data):
        self.data = data
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)
        return FakeResponse(self.data)


def test_get_chunk_timestamps_returns_the_last_n_weeks(monkeypatch):
    monkeypatch.setattr(extract, "DELAY_BETWEEN_REQUESTS", 0)  # don't sleep in tests
    session = FakeSession({"timestamps": [100, 200, 300, 400, 500]})

    result = extract.get_chunk_timestamps(session, 4169, "DE-LU", weeks=2)

    assert result == [400, 500]
    assert session.urls == [f"{extract.BASE_URL}/4169/DE-LU/index_hour.json"]


def test_save_raw_uses_series_and_timestamp_in_path(tmp_path):
    path = extract.save_raw({"series": []}, tmp_path, "solar_mwh", 1234)

    assert path == tmp_path / "solar_mwh" / "1234.json"
    assert path.exists()


def test_to_rows_converts_to_plain_python_types():
    index = pd.date_range("2026-10-20 10:00", periods=2, freq="h", tz="UTC", name="timestamp")
    df = transform.enrich(pd.DataFrame({
        "price_eur_mwh": [100.5, -1.25],
        "solar_mwh": [1000.0, 0.0],
        "wind_onshore_mwh": [2000.0, 2100.0],
        "wind_offshore_mwh": [500.0, 450.0],
        "load_mwh": [50000.0, 48000.0],
    }, index=index))

    rows = load.to_rows(df)

    assert len(rows) == 2
    first = rows[0]
    assert len(first) == len(load.ALL_COLUMNS)
    assert isinstance(first[0], datetime) and first[0].tzinfo is not None
    assert first[1] == 100.5 and type(first[1]) is float
    assert first[-3] == date(2026, 10, 20)   # date in German time
    assert first[-2] == 12 and type(first[-2]) is int   # 10:00 UTC = 12:00 Berlin (summer)
    assert first[-1] == "Tuesday"
