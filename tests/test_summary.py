"""Tests for the daily summary. A fake client replaces the LLM: no API key, no cost."""
import json
from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import summary
import transform


def make_days(days: int = 9, extra_hours: int = 0) -> pd.DataFrame:
    """Enriched data starting at midnight German time on 13 Oct 2026."""
    hours = days * 24 + extra_hours
    index = pd.date_range("2026-10-12 22:00", periods=hours, freq="h", tz="UTC", name="timestamp")
    return transform.enrich(pd.DataFrame({
        "price_eur_mwh": 100.0,
        "solar_mwh": 1000.0,
        "wind_onshore_mwh": 3000.0,
        "wind_offshore_mwh": 1000.0,
        "load_mwh": 10000.0,
    }, index=index))


class FakeClient:
    """Stands in for anthropic.Anthropic and records the request."""

    def __init__(self, text="Prices were moderate.", stop_reason="end_turn"):
        self.request = None
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)],
            stop_reason=stop_reason,
            usage=SimpleNamespace(input_tokens=500, output_tokens=80),
        )
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))
        self._response = response

    def _create(self, **kwargs):
        self.request = kwargs
        return self._response


def test_latest_complete_day_skips_todays_partial_day():
    df = make_days(days=9, extra_hours=15)   # 9 full days + 15 hours of day 10

    assert summary.latest_complete_day(df) == date(2026, 10, 21)


def test_daily_stats_calculates_the_numbers():
    df = make_days()
    day = date(2026, 10, 21)
    # Make the day interesting: one cheap negative hour at 13:00, one peak at 19:00
    rows = df.index[df["date"] == day]
    df.loc[rows[13], "price_eur_mwh"] = -5.0
    df.loc[rows[19], "price_eur_mwh"] = 300.0

    stats = summary.daily_stats(df, day)

    assert stats["date"] == "2026-10-21"
    assert stats["weekday"] == "Wednesday"
    assert stats["cheapest_hour"] == {"time": "13:00", "price_eur_mwh": -5.0}
    assert stats["most_expensive_hour"] == {"time": "19:00", "price_eur_mwh": 300.0}
    assert stats["hours_with_negative_price"] == 1
    assert stats["average_price_eur_mwh"] == pytest.approx((22 * 100 - 5 + 300) / 24, abs=0.01)
    # (1000 + 3000 + 1000) / 10000 = 50 %, solar 10 %, wind 40 %
    assert stats["solar_and_wind_share_of_consumption_pct"] == 50.0
    assert stats["solar_share_pct"] == 10.0
    assert stats["wind_share_pct"] == 40.0
    assert stats["previous_7_days"]["average_price_eur_mwh"] == 100.0


def test_daily_stats_without_history_has_no_comparison():
    df = make_days(days=1)

    stats = summary.daily_stats(df, date(2026, 10, 13))

    assert "previous_7_days" not in stats


def test_daily_stats_is_json_serializable():
    # The numbers are sent to the LLM as JSON, so numpy types must not leak in
    stats = summary.daily_stats(make_days(), date(2026, 10, 21))
    json.dumps(stats)
    assert not any(isinstance(v, np.generic) for v in stats.values())


def test_generate_summary_sends_numbers_and_returns_text():
    client = FakeClient(text="  Prices averaged 100 €/MWh.  ")
    stats = {"date": "2026-10-21", "average_price_eur_mwh": 100.0}

    text = summary.generate_summary(stats, client)

    assert text == "Prices averaged 100 €/MWh."
    assert client.request["model"] == summary.MODEL
    assert client.request["system"] == summary.SYSTEM_PROMPT
    assert '"average_price_eur_mwh": 100.0' in client.request["messages"][0]["content"]


def test_generate_summary_raises_on_refusal():
    client = FakeClient(text="", stop_reason="refusal")

    with pytest.raises(RuntimeError, match="declined"):
        summary.generate_summary({"date": "2026-10-21"}, client)
