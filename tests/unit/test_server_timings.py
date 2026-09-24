"""Request timings: the sample, the buffered sink, the daily rollup and the retention prune."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from server.app import create_app
from server.config import Config
from server.db import Database
from server.pages import PageCatalog
from server.timings import (
    OK,
    Sample,
    TimingSink,
    percentile,
)
from tests.app_state import app_state


class Clock:
    """A clock a test winds by hand, standing in for `timings.utc_now`."""

    def __init__(self, at: datetime):
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def day(self, day: str, hour: int = 12) -> None:
        self.at = datetime.strptime(day, "%Y-%m-%d").replace(hour=hour, tzinfo=UTC)


@pytest.fixture
def db() -> Database:
    database = Database(":memory:")
    database.migrate()
    return database


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 9, 1, 12, 0, tzinfo=UTC))


@pytest.fixture
def sink(db, clock) -> TimingSink:
    return TimingSink(db, now=clock, flush_seconds=None, retention_days=30)


def sample(route="/generate", status=200, ms=100.0, outcome=OK) -> Sample:
    one = Sample(method="POST", request_id="r", route=route, outcome=outcome)
    one.status = status
    one.total_ms = ms
    return one


def record_day(sink: TimingSink, clock: Clock, day: str, count: int = 10) -> None:
    """A day of samples, written without sweeping, so a test arranges what it means to.

    A flush sweeps the first time it runs on a new day, so arranging two days through
    it would roll up and prune before the test had asked for anything.
    """
    clock.day(day)
    for index in range(count):
        sink.record(sample(ms=float(index + 1)))
    sink._swept = day
    sink.flush()


def rows(db: Database, sql: str) -> list[tuple]:
    with db.transaction() as conn:
        return [tuple(row) for row in conn.execute(sql)]


# -- The sample ---------------------------------------------------------------------------


def test_a_phase_records_the_time_inside_it():
    one = sample()
    with one.phase("build"):
        pass
    assert "build" in one.phases
    assert one.phases["build"] >= 0


def test_entering_a_phase_twice_adds_to_it():
    one = sample()
    for _ in range(2):
        with one.phase("queue"):
            pass
    assert len(one.phases) == 1


def test_a_phase_is_recorded_even_when_its_block_raises():
    one = sample()
    with pytest.raises(ValueError), one.phase("build"):
        raise ValueError("no")
    assert "build" in one.phases


@pytest.mark.parametrize(
    ("status", "ms", "notable"),
    [(200, 10.0, False), (404, 10.0, True), (500, 10.0, True), (200, 5000.0, True)],
)
def test_only_a_failure_or_a_slow_request_is_notable(status, ms, notable):
    assert sample(status=status, ms=ms).notable is notable


# -- Percentiles --------------------------------------------------------------------------


def test_the_percentile_is_a_value_that_was_observed():
    ordered = [float(n) for n in range(1, 101)]
    assert percentile(ordered, 0.50) == 50
    assert percentile(ordered, 0.90) == 90
    assert percentile(ordered, 0.99) == 99


def test_the_percentile_of_one_sample_is_that_sample():
    assert percentile([7.0], 0.99) == 7


# -- Buffering ----------------------------------------------------------------------------


def test_recording_writes_nothing_until_the_flush(sink, db):
    sink.record(sample())
    assert rows(db, "SELECT count(*) FROM timings") == [(0,)]
    sink.flush()
    assert rows(db, "SELECT count(*) FROM timings") == [(1,)]


def test_a_flush_with_nothing_buffered_writes_nothing(sink, db):
    sink.flush()
    assert rows(db, "SELECT count(*) FROM timings") == [(0,)]


def test_a_sample_keeps_its_route_outcome_and_phases(sink, db):
    one = sample(route="/h/{seed_id}/patch.ips", ms=42.5)
    with one.phase("finish"):
        pass
    sink.record(one)
    sink.flush()
    (row,) = rows(
        db, "SELECT request_id, route, method, status, total_ms, outcome FROM timings"
    )
    assert row == ("r", "/h/{seed_id}/patch.ips", "POST", 200, 42.5, OK)
    (detail,) = rows(db, "SELECT detail FROM timings")
    assert '"finish"' in detail[0]


# -- The rollup ---------------------------------------------------------------------------


def test_the_rollup_covers_only_days_that_are_over(sink, db, clock):
    record_day(sink, clock, "2026-09-01")
    record_day(sink, clock, "2026-09-02")
    assert sink.rollup() == ["2026-09-01"]
    assert rows(db, "SELECT day FROM timing_day") == [("2026-09-01",)]


def test_a_days_samples_stay_after_it_is_rolled_up(sink, db, clock):
    record_day(sink, clock, "2026-09-01")
    clock.day("2026-09-02")
    sink.rollup()
    assert rows(db, "SELECT count(*) FROM timings") == [(10,)]


def test_the_rollup_summarizes_what_the_day_held(sink, db, clock):
    record_day(sink, clock, "2026-09-01", count=100)
    clock.day("2026-09-02")
    sink.rollup()
    (row,) = rows(
        db, "SELECT count, errors, p50_ms, p90_ms, p99_ms, max_ms FROM timing_day"
    )
    assert row == (100, 0, 50.0, 90.0, 99.0, 100.0)


def test_rolling_up_again_changes_nothing(sink, db, clock):
    record_day(sink, clock, "2026-09-01")
    clock.day("2026-09-02")
    sink.rollup()
    before = rows(db, "SELECT * FROM timing_day")
    assert sink.rollup() == []
    assert rows(db, "SELECT * FROM timing_day") == before


def test_the_rollup_catches_up_on_the_days_an_outage_missed(sink, db, clock):
    for day in ("2026-09-01", "2026-09-02", "2026-09-03"):
        clock.day(day)
        sink.record(sample())
        # buffered straight into the database, so no sweep runs in between
        sink.flush()
    clock.day("2026-09-10")
    with db.transaction() as conn:
        conn.execute("DELETE FROM timing_day")
    assert sink.rollup() == ["2026-09-01", "2026-09-02", "2026-09-03"]


def test_a_day_is_rolled_up_before_the_prune_can_reach_it(sink, db, clock):
    """The order inside a flush, which is what keeps the two windows from racing."""
    record_day(sink, clock, "2026-08-01")
    clock.day("2026-09-30")
    sink.flush()
    assert rows(db, "SELECT count(*) FROM timings") == [(0,)]
    assert rows(db, "SELECT day, count FROM timing_day") == [("2026-08-01", 10)]


def test_a_backlog_larger_than_one_rollup_batch_is_summarized_before_pruning(
    sink, db, clock
):
    days = [f"2026-07-{number:02d}" for number in range(1, 17)]
    for day in days:
        record_day(sink, clock, day, count=1)
    clock.day("2026-09-01")

    sink.flush()

    assert rows(db, "SELECT day FROM timing_day ORDER BY day") == [
        (day,) for day in days
    ]
    assert rows(db, "SELECT count(*) FROM timings") == [(0,)]


def test_the_sweep_runs_once_a_day(sink, db, clock):
    record_day(sink, clock, "2026-09-01")
    clock.day("2026-09-02")
    sink.flush()
    assert rows(db, "SELECT day FROM timing_day") == [("2026-09-01",)]
    # a second day's samples arrive and are flushed, but the sweep has already run today
    sink.record(sample())
    sink.flush()
    assert rows(db, "SELECT day FROM timing_day") == [("2026-09-01",)]


# -- The prune ----------------------------------------------------------------------------


def test_the_prune_deletes_past_the_window_and_keeps_the_rest(sink, db, clock):
    record_day(sink, clock, "2026-08-01")
    record_day(sink, clock, "2026-09-10")
    clock.day("2026-09-11")
    assert sink.prune() == 10
    assert rows(db, "SELECT DISTINCT substr(created_at, 1, 10) FROM timings") == [
        ("2026-09-10",)
    ]


def test_the_prune_keeps_everything_inside_the_window(sink, db, clock):
    record_day(sink, clock, "2026-09-01")
    clock.day("2026-09-10")
    assert sink.prune() == 0
    assert rows(db, "SELECT count(*) FROM timings") == [(10,)]


def test_the_prune_chunks_a_backlog(sink, db, clock, monkeypatch):
    monkeypatch.setattr("server.timings.PRUNE_CHUNK", 3)
    record_day(sink, clock, "2026-08-01", count=10)
    clock.day("2026-09-30")
    assert sink.prune() == 10
    assert rows(db, "SELECT count(*) FROM timings") == [(0,)]


def test_the_rollup_outlives_the_samples_it_came_from(sink, db, clock):
    record_day(sink, clock, "2026-08-01", count=100)
    clock.day("2026-08-02")
    sink.rollup()
    clock.day("2026-09-30")
    sink.prune()
    assert rows(db, "SELECT count(*) FROM timings") == [(0,)]
    assert rows(db, "SELECT count, p99_ms FROM timing_day") == [(100, 99.0)]


# -- The middleware -----------------------------------------------------------------------


@pytest.fixture
def client():
    with TestClient(create_app(Config(database=":memory:"))) as test_client:
        yield test_client


def recorded(client: TestClient) -> list[tuple]:
    app_state(client).timings.flush()
    with app_state(client).db.transaction() as conn:
        return [
            tuple(row)
            for row in conn.execute("SELECT route, method, status FROM timings")
        ]


def test_a_request_is_recorded_under_its_route_template(client):
    client.get("/h/aaaaaaaaaa")
    assert recorded(client) == [("/h/{seed_id}", "GET", 404)]


def test_a_path_matching_no_route_is_recorded_as_one_bucket(client):
    client.get("/nothing/here")
    assert recorded(client) == [("unmatched", "GET", 404)]


def test_a_mounted_app_is_recorded_under_its_mount(client):
    client.get("/static/site.css")
    client.get("/static/missing.css")
    assert recorded(client) == [("/static", "GET", 200), ("/static", "GET", 404)]


def test_each_content_page_is_recorded_as_its_own_route(tmp_path):
    for slug in ("about", "faq"):
        (tmp_path / f"{slug}.md").write_text(f'+++\ntitle = "{slug}"\n+++\n\nBody.\n')
    app = create_app(Config(database=":memory:"), pages=PageCatalog.load(tmp_path))
    with TestClient(app) as test_client:
        test_client.get("/pages/about")
        test_client.get("/pages/faq")
        test_client.get("/pages/missing")
        assert recorded(test_client) == [
            ("/pages/about", "GET", 200),
            ("/pages/faq", "GET", 200),
            ("unmatched", "GET", 404),
        ]


def test_a_response_carries_the_request_id_its_log_lines_use(client):
    response = client.get("/")
    request_id = response.headers["X-Request-Id"]
    assert len(request_id) == 16
    app_state(client).timings.flush()
    with app_state(client).db.transaction() as conn:
        stored = conn.execute(
            "SELECT route, status FROM timings WHERE request_id = ?", (request_id,)
        ).fetchone()
    assert tuple(stored) == ("/", 200)


def test_every_request_gets_its_own_id(client):
    first = client.get("/").headers["X-Request-Id"]
    assert client.get("/").headers["X-Request-Id"] != first


def test_the_shutdown_flush_writes_what_had_buffered(tmp_path):
    """A deploy restart loses nothing that buffered since the last flush."""
    path = str(tmp_path / "site.db")
    with TestClient(create_app(Config(database=path))) as test_client:
        test_client.get("/")
    reopened = Database(path)
    try:
        assert rows(reopened, "SELECT count(*) FROM timings") == [(1,)]
    finally:
        reopened.close()
