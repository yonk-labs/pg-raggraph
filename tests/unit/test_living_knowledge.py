from datetime import datetime, timezone

from pg_raggraph import _as_aware_utc, _living_bucket
from pg_raggraph.config import PGRGConfig
from pg_raggraph.evolution import evolution_where_clauses


def test_living_bucket_day_hour_week_month():
    ts = datetime(2026, 5, 25, 14, 37, tzinfo=timezone.utc)

    day, day_start, day_end = _living_bucket(ts, "day")
    hour, hour_start, hour_end = _living_bucket(ts, "hour")
    week, week_start, week_end = _living_bucket(ts, "week")
    month, month_start, month_end = _living_bucket(ts, "month")

    assert day == "2026-05-25"
    assert day_start.isoformat() == "2026-05-25T00:00:00+00:00"
    assert day_end.isoformat() == "2026-05-26T00:00:00+00:00"
    assert hour == "2026-05-25T14"
    assert hour_start.isoformat() == "2026-05-25T14:00:00+00:00"
    assert hour_end.isoformat() == "2026-05-25T15:00:00+00:00"
    assert week == "2026-W22"
    assert week_start.isoformat() == "2026-05-25T00:00:00+00:00"
    assert week_end.isoformat() == "2026-06-01T00:00:00+00:00"
    assert month == "2026-05"
    assert month_start.isoformat() == "2026-05-01T00:00:00+00:00"
    assert month_end.isoformat() == "2026-06-01T00:00:00+00:00"


def test_living_timestamp_parses_z_suffix():
    assert _as_aware_utc("2026-05-25T12:00:00Z").tzinfo is not None


def test_living_current_filter_only_applies_to_latest_living_queries():
    cfg = PGRGConfig(living_knowledge=True)

    latest_clauses, latest_params = evolution_where_clauses(cfg)
    historical_clauses, historical_params = evolution_where_clauses(
        cfg,
        as_of=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )
    off_clauses, off_params = evolution_where_clauses(PGRGConfig())

    assert any("living_current" in clause for clause in latest_clauses)
    assert latest_params == {}
    assert not any("living_current" in clause for clause in historical_clauses)
    assert historical_params == {}
    assert off_clauses == []
    assert off_params == {}
