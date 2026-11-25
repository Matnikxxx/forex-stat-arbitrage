"""Tests for candle-feed freshness and coverage monitoring."""

from datetime import datetime, timedelta, timezone

import pytest

from src.market_data import Candle
from src.data_monitoring import assess_feed_health


NOW = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)


def candle(index, close=1.1):
    return Candle(
        "EUR/USD",
        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=15 * index),
        close,
        close + 0.001,
        close - 0.001,
        close,
        10.0,
    )


def test_recent_complete_feed_is_healthy():
    result = assess_feed_health([candle(2), candle(3)], "15m", NOW)
    assert result.status == "healthy"
    assert result.coverage == 1.0
    assert result.gap_count == 0


def test_feed_reports_pair_and_timeframe():
    result = assess_feed_health([candle(3)], "15m", NOW)
    assert result.pair == "EUR/USD"
    assert result.timeframe == "15m"


def test_feed_age_uses_candle_close_time():
    result = assess_feed_health([candle(3)], "15m", NOW)
    assert result.latest_closed_at == datetime(
        2026, 1, 1, 1, 0, tzinfo=timezone.utc
    )
    assert result.age_seconds == 0


def test_old_feed_is_stale():
    result = assess_feed_health(
        [candle(0)],
        "15m",
        NOW,
        max_age=timedelta(minutes=20),
    )
    assert result.status == "stale"
    assert "Latest candle is stale." in result.issues


def test_internal_gap_produces_warning():
    result = assess_feed_health([candle(1), candle(3)], "15m", NOW)
    assert result.status == "warning"
    assert result.gap_count == 1
    assert "Candle history contains gaps." in result.issues


def test_expected_count_reduces_coverage():
    result = assess_feed_health(
        [candle(2), candle(3)],
        "15m",
        NOW,
        expected_count=4,
    )
    assert result.status == "warning"
    assert result.coverage == 0.5
    assert result.missing_count == 2


def test_explicit_max_age_overrides_default():
    result = assess_feed_health(
        [candle(2)],
        "15m",
        NOW,
        max_age=timedelta(hours=1),
    )
    assert result.status == "healthy"
    assert result.max_age_seconds == 3600


def test_empty_feed_is_rejected():
    with pytest.raises(ValueError, match="At least one"):
        assess_feed_health([], "15m", NOW)


def test_naive_current_time_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        assess_feed_health([candle(3)], "15m", datetime(2026, 1, 1, 1))


def test_non_positive_max_age_is_rejected():
    with pytest.raises(ValueError, match="positive"):
        assess_feed_health(
            [candle(3)], "15m", NOW, max_age=timedelta(0)
        )


def test_future_or_forming_latest_candle_is_rejected():
    with pytest.raises(ValueError, match="not closed"):
        assess_feed_health([candle(4)], "15m", NOW)


def test_invalid_timeframe_is_rejected():
    with pytest.raises(ValueError, match="Unsupported"):
        assess_feed_health([candle(3)], "2h", NOW)


def test_feed_health_result_is_immutable():
    from dataclasses import FrozenInstanceError

    result = assess_feed_health([candle(3)], "15m", NOW)
    with pytest.raises(FrozenInstanceError):
        result.status = "stale"
