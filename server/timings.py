"""Request timings: the only code that writes `timings` and `timing_day`.

Every request produces one `Sample`. The middleware in `server/app.py` makes it, times the
request and hands it to a `TimingSink`; a route adds the phases it can see from the inside,
such as how long a build waited for the build semaphore against how long it then took. The
sink buffers samples in memory and writes them in batches, so no request pays for a
database write of its own.

Raw samples answer any percentile over any window, which matters more than a small table
at this traffic: a site that generates a few dozen seeds a day has no p99 worth the name
inside a histogram's buckets. They are kept `RETENTION_DAYS` days. Before a day's samples
can age out, `rollup` summarizes them into `timing_day`, which is kept for good and carries
the long trend.

Flushing takes the database lock, so it never runs on the event loop: `flush_periodically`
drives it through the threadpool. See docs/randomizer_devplan.md, "Data model".
"""

import asyncio
import json
import logging
import math
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from itertools import groupby

from starlette.concurrency import run_in_threadpool

from .db import Database

log = logging.getLogger(__name__)

#: seconds between flushes of the buffer
FLUSH_SECONDS = 30.0
#: days a raw sample is kept before the prune deletes it
RETENTION_DAYS = 30
#: rows one delete removes, so a backlog cannot hold the database lock for one statement
PRUNE_CHUNK = 10_000
#: complete days one rollup query covers while catching up after a long outage
ROLLUP_DAYS = 14
#: a request at least this slow gets a log line even though it succeeded
SLOW_MS = 1000.0

#: the timestamp format the rest of the schema uses (`seeds.utc_now`), which sorts as text
STAMP = "%Y-%m-%dT%H:%M:%SZ"
#: the first ten characters of a timestamp, the UTC day a sample belongs to
DAY = "%Y-%m-%d"

#: what an outcome says beyond the status code, for the refusals a 400 cannot tell apart
OK = "ok"
EXCEPTION = "exception"

_INSERT = """
INSERT INTO timings
    (created_at, request_id, route, method, status, total_ms, outcome, detail)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""

#: complete days with raw samples that have not been summarized yet, oldest first
_DAYS_TO_ROLL = """
SELECT DISTINCT substr(created_at, 1, 10) AS day
  FROM timings
 WHERE created_at < ?
   AND substr(created_at, 1, 10) NOT IN (SELECT day FROM timing_day)
 ORDER BY day
 LIMIT ?
"""

#: one day's samples, grouped and sorted so each group's durations arrive in order
_DAY_SAMPLES = """
SELECT route, method, status, total_ms
  FROM timings
 WHERE created_at >= ? AND created_at < ?
 ORDER BY route, method, total_ms
"""

_INSERT_DAY = """
INSERT OR REPLACE INTO timing_day
    (day, route, method, count, errors, p50_ms, p90_ms, p99_ms, max_ms)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# SQLite here is built without SQLITE_ENABLE_UPDATE_DELETE_LIMIT, so `DELETE ... LIMIT` is
# a syntax error and the rows to delete are chosen by a subquery instead.
_PRUNE = """
DELETE FROM timings
 WHERE id IN (SELECT id FROM timings WHERE created_at < ? LIMIT ?)
"""


def utc_now() -> datetime:
    return datetime.now(UTC)


def percentile(ordered: Sequence[float], fraction: float) -> float:
    """The nearest-rank percentile of an already sorted, non-empty sequence.

    Nearest rank keeps the answer a value that was actually observed rather than an
    interpolation between two, which is what makes a stored daily percentile honest about
    the day it covers.
    """
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


@dataclass
class Sample:
    """One request's timing, filled in as the request runs.

    The middleware makes it and sets the route, status and total; a route adds phases and
    an outcome. Only one thread touches a sample at a time - the route awaits the
    threadpool call that fills its phases in - so it needs no lock of its own.
    """

    method: str
    request_id: str
    route: str = ""
    status: int = 0
    total_ms: float = 0.0
    #: what the status code cannot say, such as which refusal a 400 was
    outcome: str | None = None
    #: named milliseconds inside the request, such as the build queue and the build
    phases: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        """Time a named part of the request, adding to it if the name is entered twice."""
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.phases[name] = self.phases.get(name, 0.0) + elapsed

    @property
    def notable(self) -> bool:
        """Whether this request is worth a log line of its own."""
        return self.status >= 400 or self.total_ms >= SLOW_MS


@contextmanager
def phase(sample: Sample | None, name: str) -> Iterator[None]:
    """Time a phase when there is a sample to record it on, and do nothing when there is not.

    It lets code that can see a phase from the inside, such as `SeedBuilder.build`, stay
    callable without one - from a test, a CLI or the editor.
    """
    if sample is None:
        yield
        return
    with sample.phase(name):
        yield


@dataclass(frozen=True)
class DaySummary:
    day: str
    route: str
    method: str
    count: int
    errors: int
    p50_ms: float
    p90_ms: float
    p99_ms: float
    max_ms: float

    @classmethod
    def of(
        cls, day: str, route: str, method: str, rows: Sequence[tuple[int, float]]
    ) -> "DaySummary":
        """Summarize one route's samples for one day. `rows` is (status, ms), ms ascending."""
        durations = [ms for _status, ms in rows]
        return cls(
            day=day,
            route=route,
            method=method,
            count=len(rows),
            errors=sum(1 for status, _ms in rows if status >= 400),
            p50_ms=percentile(durations, 0.50),
            p90_ms=percentile(durations, 0.90),
            p99_ms=percentile(durations, 0.99),
            max_ms=durations[-1],
        )

    def row(self) -> tuple:
        return (
            self.day,
            self.route,
            self.method,
            self.count,
            self.errors,
            self.p50_ms,
            self.p90_ms,
            self.p99_ms,
            self.max_ms,
        )


class TimingSink:
    """Buffers samples and writes them in batches, with the rollup and the prune.

    `flush_seconds` of None leaves the sink to be flushed by hand, which is what tests do
    so no background task runs during them.
    """

    def __init__(
        self,
        db: Database,
        now: Callable[[], datetime] = utc_now,
        flush_seconds: float | None = FLUSH_SECONDS,
        retention_days: int = RETENTION_DAYS,
    ):
        self.db = db
        self.flush_seconds = flush_seconds
        self.retention_days = retention_days
        self._now = now
        self._lock = threading.Lock()
        self._buffer: list[tuple[str, Sample]] = []
        #: the last day the rollup and the prune ran, so they run about daily
        self._swept: str | None = None

    def record(self, sample: Sample) -> None:
        """Buffer one sample. Touches no database: the request path does no I/O here."""
        with self._lock:
            self._buffer.append((self._now().strftime(STAMP), sample))

    def flush(self) -> None:
        """Write what has buffered, then sweep once a day. Takes the database lock.

        The rollup runs before the prune, so a day is always summarized before it can be
        deleted. That makes the ordering structural rather than a matter of the retention
        window happening to be longer than the rollup's reach.
        """
        with self._lock:
            pending, self._buffer = self._buffer, []
        if pending:
            with self.db.transaction() as conn:
                conn.executemany(_INSERT, [_row(at, s) for at, s in pending])
        now = self._now()
        today = now.strftime(DAY)
        if self._swept != today:
            self.rollup(now)
            self.prune(now)
            self._swept = today

    def rollup(self, now: datetime | None = None) -> list[str]:
        """Summarize the complete days that have raw samples but no `timing_day` rows.

        Only days before today, so no day is summarized while samples are still arriving
        for it, which is what makes the prune unable to reach an unsummarized day. Days
        already summarized are skipped, so a repeat pass costs one scan and changes
        nothing. A gap left by an outage is processed in batches until every complete day
        has a summary; only then may the caller prune old samples.
        """
        now = now if now is not None else self._now()
        midnight = now.strftime(DAY) + "T00:00:00Z"
        rolled = []
        while True:
            with self.db.transaction() as conn:
                days = [
                    row[0]
                    for row in conn.execute(_DAYS_TO_ROLL, (midnight, ROLLUP_DAYS))
                ]
            if not days:
                return rolled
            for day in days:
                with self.db.transaction() as conn:
                    conn.executemany(
                        _INSERT_DAY,
                        [summary.row() for summary in _summaries(conn, day)],
                    )
                rolled.append(day)

    def prune(self, now: datetime | None = None) -> int:
        """Delete raw samples past the retention window, in chunks. Returns rows deleted.

        Chunked so the backlog a long outage leaves cannot hold the database lock for the
        length of one statement. The freed pages stay on SQLite's freelist and are reused,
        so the file plateaus rather than shrinking - never VACUUM this database to reclaim
        it, because that rewrites every page and makes Litestream ship the whole file.
        """
        now = now if now is not None else self._now()
        cutoff = (now - timedelta(days=self.retention_days)).strftime(STAMP)
        deleted = 0
        while True:
            with self.db.transaction() as conn:
                gone = conn.execute(_PRUNE, (cutoff, PRUNE_CHUNK)).rowcount
            deleted += gone
            if gone < PRUNE_CHUNK:
                return deleted


def _row(created_at: str, sample: Sample) -> tuple:
    return (
        created_at,
        sample.request_id,
        sample.route,
        sample.method,
        sample.status,
        sample.total_ms,
        sample.outcome,
        json.dumps({"phases": sample.phases}, sort_keys=True),
    )


def _summaries(conn: sqlite3.Connection, day: str) -> Iterator[DaySummary]:
    """One summary per route and method with samples on `day`."""
    start = f"{day}T00:00:00Z"
    end = (datetime.strptime(day, DAY) + timedelta(days=1)).strftime(DAY) + "T00:00:00Z"
    rows = conn.execute(_DAY_SAMPLES, (start, end)).fetchall()
    for (route, method), group in groupby(rows, key=lambda row: (row[0], row[1])):
        yield DaySummary.of(day, route, method, [(row[2], row[3]) for row in group])


async def flush_periodically(sink: TimingSink) -> None:
    """Flush the sink on its interval until canceled, writing off the event loop.

    A failed write is logged and the loop goes on: losing one batch of timings must not
    take the collection down with it.
    """
    assert sink.flush_seconds is not None
    while True:
        await asyncio.sleep(sink.flush_seconds)
        try:
            await run_in_threadpool(sink.flush)
        except Exception:
            log.exception("could not write request timings")
