import os
import sqlite3
from datetime import datetime, timezone
from typing import List

DB_PATH = os.getenv("DB_PATH", "./purchases.sqlite")

PRODUCT_TO_INDEX = {
    "indices.nikkei225": "NIKKEI225",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS purchases(
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              product_id TEXT NOT NULL,
              granted_index_type TEXT NOT NULL,
              transaction_id TEXT NOT NULL UNIQUE,
              status TEXT NOT NULL DEFAULT 'active',
              created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def add_purchase(user_id: str, product_id: str, transaction_id: str) -> bool:
    granted_index_type = PRODUCT_TO_INDEX[product_id]
    created_at = datetime.now(timezone.utc).isoformat()

    with _connect() as conn:
        try:
            conn.execute(
                """
                INSERT INTO purchases(
                    user_id, product_id, granted_index_type, transaction_id, status, created_at
                ) VALUES (?, ?, ?, ?, 'active', ?)
                """,
                (user_id, product_id, granted_index_type, transaction_id, created_at),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False


def get_granted_index_types(user_id: str) -> List[str]:
    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT DISTINCT granted_index_type
            FROM purchases
            WHERE user_id = ? AND status = 'active'
            """,
            (user_id,),
        )
        return [str(row["granted_index_type"]) for row in cur.fetchall()]
