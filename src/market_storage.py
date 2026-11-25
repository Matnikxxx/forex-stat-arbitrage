"""SQLite storage for validated historical market candles."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from src.market_data import Candle, validate_candle_series


class CandleStorage:
    """Store and retrieve candles using a small local SQLite database."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._create_table()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path)

    def _create_table(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    pair TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    PRIMARY KEY (pair, timestamp)
                )
                """
            )

    def save_candles(self, candles: list[Candle]) -> int:
        """Validate and save candles, replacing matching pair/time records."""
        validated = validate_candle_series(candles)
        rows = [
            (
                candle.pair,
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
                (pair, timestamp, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def load_candles(
        self,
        pair: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[Candle]:
        """Load one pair in chronological order, optionally within a time range."""
        if not pair or "/" not in pair:
            raise ValueError("Currency pair must use BASE/QUOTE format.")
        if start is not None and (start.tzinfo is None or start.utcoffset() is None):
            raise ValueError("Start time must include a timezone.")
        if end is not None and (end.tzinfo is None or end.utcoffset() is None):
            raise ValueError("End time must include a timezone.")

        query = "SELECT * FROM candles WHERE pair = ?"
        parameters: list[str] = [pair]
        if start is not None:
            query += " AND timestamp >= ?"
            parameters.append(start.astimezone(timezone.utc).isoformat())
        if end is not None:
            query += " AND timestamp <= ?"
            parameters.append(end.astimezone(timezone.utc).isoformat())
        query += " ORDER BY timestamp ASC"

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()

        return [
            Candle(
                pair=row[0],
                timestamp=datetime.fromisoformat(row[1]),
                open=row[2],
                high=row[3],
                low=row[4],
                close=row[5],
                volume=row[6],
            )
            for row in rows
        ]
