from __future__ import annotations

import sqlite3
from contextlib import closing

from .config import Settings


class EventStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def init_db(self) -> None:
        with closing(sqlite3.connect(self.settings.db_path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_events (
                    event_key TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def remember_event(self, event_key: str) -> bool:
        with closing(sqlite3.connect(self.settings.db_path)) as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO processed_events (event_key) VALUES (?)",
                (event_key,),
            )
            conn.commit()
            return cur.rowcount == 1
