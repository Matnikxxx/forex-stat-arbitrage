"""SQLite persistence for reproducible historical backfill job definitions."""

from dataclasses import dataclass
from datetime import datetime, timezone
import sqlite3
from pathlib import Path

from src.market_feed import CandleRequest, validate_request


@dataclass(frozen=True)
class BackfillJob:
    """Original request parameters required to reproduce a backfill."""

    pair: str
    timeframe: str
    start: datetime
    end: datetime
    max_candles: int = 5000


class BackfillJobStorage:
    """Persist backfill definitions independently from transient retry state."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backfill_jobs (
                    pair TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    start TEXT NOT NULL,
                    end TEXT NOT NULL,
                    max_candles INTEGER NOT NULL,
                    PRIMARY KEY (pair, timeframe)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    @staticmethod
    def _validate(job: BackfillJob) -> BackfillJob:
        if not isinstance(job, BackfillJob):
            raise ValueError("A BackfillJob is required.")
        for label, value in (("Start", job.start), ("End", job.end)):
            if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{label} time must include a timezone.")
        start = job.start.astimezone(timezone.utc)
        end = job.end.astimezone(timezone.utc)
        if start >= end:
            raise ValueError("Start time must be before end time.")
        if (
            isinstance(job.max_candles, bool)
            or not isinstance(job.max_candles, int)
            or not 2 <= job.max_candles <= 5000
        ):
            raise ValueError("Maximum candles must be between 2 and 5000.")
        validate_request(
            CandleRequest(
                pair=job.pair,
                timeframe=job.timeframe,
                limit=job.max_candles,
                start=start,
                end=end,
            )
        )
        return BackfillJob(job.pair, job.timeframe, start, end, job.max_candles)

    @staticmethod
    def _from_row(row: tuple) -> BackfillJob:
        return BackfillJob(
            pair=row[0],
            timeframe=row[1],
            start=datetime.fromisoformat(row[2]),
            end=datetime.fromisoformat(row[3]),
            max_candles=row[4],
        )

    def save(self, job: BackfillJob) -> None:
        """Insert or replace a job using its pair/timeframe identity."""
        clean = self._validate(job)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO backfill_jobs (pair, timeframe, start, end, max_candles)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(pair, timeframe) DO UPDATE SET
                    start = excluded.start,
                    end = excluded.end,
                    max_candles = excluded.max_candles
                """,
                (
                    clean.pair,
                    clean.timeframe,
                    clean.start.isoformat(),
                    clean.end.isoformat(),
                    clean.max_candles,
                ),
            )

    def load(self, pair: str, timeframe: str) -> BackfillJob | None:
        """Load one saved job definition, if present."""
        if not isinstance(pair, str) or not pair.strip():
            raise ValueError("Currency pair must be a non-empty string.")
        if not isinstance(timeframe, str) or not timeframe.strip():
            raise ValueError("Timeframe must be a non-empty string.")
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT pair, timeframe, start, end, max_candles
                FROM backfill_jobs WHERE pair = ? AND timeframe = ?
                """,
                (pair, timeframe),
            ).fetchone()
        return None if row is None else self._from_row(row)

    def load_all(self) -> list[BackfillJob]:
        """Load every saved job in deterministic pair/timeframe order."""
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pair, timeframe, start, end, max_candles
                FROM backfill_jobs ORDER BY pair ASC, timeframe ASC
                """
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def delete(self, pair: str, timeframe: str) -> bool:
        """Delete one saved job and report whether it existed."""
        if not isinstance(pair, str) or not pair.strip():
            raise ValueError("Currency pair must be a non-empty string.")
        if not isinstance(timeframe, str) or not timeframe.strip():
            raise ValueError("Timeframe must be a non-empty string.")
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM backfill_jobs WHERE pair = ? AND timeframe = ?",
                (pair, timeframe),
            )
        return cursor.rowcount > 0
