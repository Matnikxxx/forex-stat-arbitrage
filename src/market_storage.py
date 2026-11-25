"""SQLite storage for timeframe-isolated historical market candles."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.market_data import Candle, validate_candle_series


class CandleStorage:
    """Store candles independently by currency pair, timeframe, and timestamp."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._create_table()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS candles (
                pair TEXT NOT NULL,
                timeframe TEXT NOT NULL DEFAULT 'unknown',
                timestamp TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                PRIMARY KEY (pair, timeframe, timestamp)
            )
            """
        )

    def _create_table(self) -> None:
        with self._connect() as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(candles)")
            }
            if not columns:
                self._create_schema(connection)
                return
            if "timeframe" not in columns:
                connection.execute("ALTER TABLE candles RENAME TO candles_legacy")
                self._create_schema(connection)
                connection.execute(
                    """
                    INSERT INTO candles
                    (pair, timeframe, timestamp, open, high, low, close, volume)
                    SELECT pair, 'unknown', timestamp, open, high, low, close, volume
                    FROM candles_legacy
                    """
                )
                connection.execute("DROP TABLE candles_legacy")

    @staticmethod
    def _validate_timeframe(timeframe: str | None) -> str | None:
        if timeframe is not None and (
            not isinstance(timeframe, str) or not timeframe.strip()
        ):
            raise ValueError("Timeframe must be a non-empty string.")
        return timeframe

    def save_candles(
        self,
        candles: list[Candle],
        timeframe: str = "unknown",
    ) -> int:
        """Validate and save candles in the specified timeframe partition."""
        self._validate_timeframe(timeframe)
        validated = validate_candle_series(candles)
        rows = [
            (
                candle.pair,
                timeframe,
                candle.timestamp.astimezone(timezone.utc).isoformat(),
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume,
            )
            for candle in validated
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR REPLACE INTO candles
                (pair, timeframe, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def delete_timeframe(
        self,
        pair: str,
        timeframe: str,
    ) -> int:
        """Delete one pair/timeframe partition, returning removed row count."""
        self._validate_timeframe(timeframe)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM candles WHERE pair = ? AND timeframe = ?",
                (pair, timeframe),
            )
        return cursor.rowcount

    def load_candles(
        self,
        pair: str,
        start: datetime | None = None,
        end: datetime | None = None,
        timeframe: str | None = None,
    ) -> list[Candle]:
        """Load candles chronologically, optionally filtering timeframe and dates.

        Omitting timeframe returns every stored timeframe for backwards
        compatibility. Trading and research code should always specify it.
        """
        if not pair or "/" not in pair:
            raise ValueError("Currency pair must use BASE/QUOTE format.")
        self._validate_timeframe(timeframe)
        if start is not None and (
            start.tzinfo is None or start.utcoffset() is None
        ):
            raise ValueError("Start time must include a timezone.")
        if end is not None and (end.tzinfo is None or end.utcoffset() is None):
            raise ValueError("End time must include a timezone.")
        if start is not None and end is not None and start > end:
            raise ValueError("Start time must not be after end time.")

        query = "SELECT * FROM candles WHERE pair = ?"
        parameters: list[str] = [pair]
        if timeframe is not None:
            query += " AND timeframe = ?"
            parameters.append(timeframe)
        if start is not None:
            query += " AND timestamp >= ?"
            parameters.append(start.astimezone(timezone.utc).isoformat())
        if end is not None:
            query += " AND timestamp <= ?"
            parameters.append(end.astimezone(timezone.utc).isoformat())
        query += " ORDER BY timestamp ASC, timeframe ASC"

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [
            Candle(
                pair=row[0],
                timestamp=datetime.fromisoformat(row[2]),
                open=row[3],
                high=row[4],
                low=row[5],
                close=row[6],
                volume=row[7],
            )
            for row in rows
        ]
