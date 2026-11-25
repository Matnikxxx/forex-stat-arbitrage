"""SQLite persistence for scheduled historical backfill retries."""

from dataclasses import dataclass
from datetime import datetime, timezone
import math
import sqlite3
from pathlib import Path


@dataclass(frozen=True)
class BackfillRetryState:
    """Persisted retry metadata for one pair and timeframe."""

    pair: str
    timeframe: str
    attempt: int
    next_attempt_at: datetime
    delay_seconds: float
    provider_delay_seconds: float


class BackfillRetryStorage:
    """Store retry schedules durably without starting timers or workers."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS backfill_retries (
                    pair TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    next_attempt_at TEXT NOT NULL,
                    delay_seconds REAL NOT NULL,
                    provider_delay_seconds REAL NOT NULL,
                    PRIMARY KEY (pair, timeframe)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    @staticmethod
    def _validate_key(pair: str, timeframe: str) -> None:
        if not isinstance(pair, str) or "/" not in pair:
            raise ValueError("Currency pair must use BASE/QUOTE format.")
        if not isinstance(timeframe, str) or not timeframe.strip():
            raise ValueError("Timeframe must be a non-empty string.")

    @staticmethod
    def _validate_time(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Retry time must include a timezone.")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _validate_delay(label: str, value: float, allow_zero: bool) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or (value < 0 if allow_zero else value <= 0)
        ):
            qualifier = "non-negative" if allow_zero else "positive"
            raise ValueError(f"{label} must be a finite {qualifier} number.")
        return float(value)

    def save(self, state: BackfillRetryState) -> None:
        """Insert or replace the retry schedule for one pair/timeframe."""
        if not isinstance(state, BackfillRetryState):
            raise ValueError("A BackfillRetryState is required.")
        self._validate_key(state.pair, state.timeframe)
        if isinstance(state.attempt, bool) or not isinstance(state.attempt, int) or state.attempt < 1:
            raise ValueError("Attempt must be a positive integer.")
        next_attempt = self._validate_time(state.next_attempt_at)
        delay = self._validate_delay("Delay", state.delay_seconds, False)
        provider_delay = self._validate_delay("Provider delay", state.provider_delay_seconds, True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO backfill_retries
                (pair, timeframe, attempt, next_attempt_at, delay_seconds,
                 provider_delay_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(pair, timeframe) DO UPDATE SET
                    attempt = excluded.attempt,
                    next_attempt_at = excluded.next_attempt_at,
                    delay_seconds = excluded.delay_seconds,
                    provider_delay_seconds = excluded.provider_delay_seconds
                """,
                (state.pair, state.timeframe, state.attempt, next_attempt.isoformat(), delay, provider_delay),
            )

    @staticmethod
    def _to_state(row) -> BackfillRetryState:
        return BackfillRetryState(
            pair=row[0], timeframe=row[1], attempt=row[2],
            next_attempt_at=datetime.fromisoformat(row[3]),
            delay_seconds=row[4], provider_delay_seconds=row[5],
        )

    def load(self, pair: str, timeframe: str) -> BackfillRetryState | None:
        """Load one retry schedule, if present."""
        self._validate_key(pair, timeframe)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT pair, timeframe, attempt, next_attempt_at,
                       delay_seconds, provider_delay_seconds
                FROM backfill_retries WHERE pair = ? AND timeframe = ?
                """, (pair, timeframe),
            ).fetchone()
        return None if row is None else self._to_state(row)

    def load_due(self, now: datetime) -> list[BackfillRetryState]:
        """Return all due schedules in deterministic time/key order."""
        current = self._validate_time(now)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT pair, timeframe, attempt, next_attempt_at,
                       delay_seconds, provider_delay_seconds
                FROM backfill_retries
                WHERE next_attempt_at <= ?
                ORDER BY next_attempt_at ASC, pair ASC, timeframe ASC
                """, (current.isoformat(),),
            ).fetchall()
        return [self._to_state(row) for row in rows]

    def delete(self, pair: str, timeframe: str) -> bool:
        """Delete one schedule and report whether a row was removed."""
        self._validate_key(pair, timeframe)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM backfill_retries WHERE pair = ? AND timeframe = ?",
                (pair, timeframe),
            )
        return cursor.rowcount > 0
