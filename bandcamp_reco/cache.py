import json
import sqlite3


class Cache:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS kv ("
            "  namespace TEXT NOT NULL,"
            "  key TEXT NOT NULL,"
            "  value TEXT NOT NULL,"
            "  PRIMARY KEY (namespace, key)"
            ")"
        )
        self._conn.commit()

    def get(self, namespace: str, key: str) -> dict | list | None:
        row = self._conn.execute(
            "SELECT value FROM kv WHERE namespace = ? AND key = ?",
            (namespace, key),
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, namespace: str, key: str, value) -> None:
        self._conn.execute(
            "INSERT INTO kv (namespace, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(namespace, key) DO UPDATE SET value = excluded.value",
            (namespace, key, json.dumps(value)),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
