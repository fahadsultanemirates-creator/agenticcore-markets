"""SQLite-backed persistence for support/resistance zone memory --
survives across requests (and restarts), unlike everything else in this
framework, which is stateless and recomputes fresh on every call. This is
the actual "memory system" a level-based trading framework needs: which
price zones have been tested how many times, and whether they held or
broke, accumulated over real elapsed time, not just the current request's
bar window.

A local file, not a separate database server -- zero added infrastructure
for a single-process deployment. Each call opens and closes its own
connection; this service's request volume is nowhere near the scale where
that becomes a bottleneck, and it avoids holding a long-lived connection
across async request handling.
"""

import sqlite3
from contextlib import contextmanager

from app.config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sr_zones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    price REAL NOT NULL,
    kind TEXT NOT NULL,
    touch_count INTEGER NOT NULL DEFAULT 1,
    hold_count INTEGER NOT NULL DEFAULT 0,
    break_count INTEGER NOT NULL DEFAULT 0,
    first_seen REAL NOT NULL,
    last_tested REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sr_zones_symbol ON sr_zones(symbol);

CREATE TABLE IF NOT EXISTS sr_symbol_state (
    symbol TEXT PRIMARY KEY,
    last_touched_ts REAL NOT NULL DEFAULT 0
);
"""


@contextmanager
def _connect():
    conn = sqlite3.connect(settings.sr_memory_db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


class SrMemoryStore:
    def get_zones(self, symbol: str) -> list[dict]:
        with _connect() as conn:
            rows = conn.execute("SELECT * FROM sr_zones WHERE symbol = ?", (symbol,)).fetchall()
            return [dict(r) for r in rows]

    def find_nearby_zone(self, symbol: str, price: float, tolerance_pct: float) -> dict | None:
        """Merges a new pivot into an existing zone if it's within a
        relative tolerance band -- otherwise the caller should create a
        new zone. Returns the closest match when more than one qualifies."""
        candidates = [z for z in self.get_zones(symbol) if price > 0 and abs(z["price"] - price) / price <= tolerance_pct]
        if not candidates:
            return None
        return min(candidates, key=lambda z: abs(z["price"] - price))

    def create_zone(self, symbol: str, price: float, kind: str, ts: float) -> int:
        # `ts` is the triggering bar's own timestamp (market-data time),
        # not wall-clock time -- first_seen/last_tested must stay in the
        # same time domain the break/hold scanners compare bar timestamps
        # against, or every comparison silently breaks (bar time and
        # server wall-clock time are never guaranteed to line up).
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO sr_zones (symbol, price, kind, touch_count, hold_count, break_count, first_seen, last_tested) "
                "VALUES (?, ?, ?, 1, 0, 0, ?, ?)",
                (symbol, price, kind, ts, ts),
            )
            return cur.lastrowid

    def record_touch(self, zone_id: int, new_price_estimate: float, outcome: str, ts: float) -> None:
        """outcome: 'hold' or 'break'. Re-centers the zone's stored price
        as a running average weighted toward its existing history (prior
        price weighted by prior touch count, the new estimate counts
        once), so the level converges toward the true price over multiple
        touches without jumping around on any single one. A confirmed
        break flips the zone's kind (classic "old resistance becomes new
        support" behavior) rather than retiring it -- it stays a live,
        trackable level, just on the other side. `ts` is the triggering
        bar's timestamp, same time domain as create_zone above."""
        with _connect() as conn:
            row = conn.execute("SELECT * FROM sr_zones WHERE id = ?", (zone_id,)).fetchone()
            if row is None:
                return
            touch_count = row["touch_count"] + 1
            hold_count = row["hold_count"] + (1 if outcome == "hold" else 0)
            break_count = row["break_count"] + (1 if outcome == "break" else 0)
            new_price = (row["price"] * row["touch_count"] + new_price_estimate) / touch_count
            new_kind = ("resistance" if row["kind"] == "support" else "support") if outcome == "break" else row["kind"]
            conn.execute(
                "UPDATE sr_zones SET price=?, kind=?, touch_count=?, hold_count=?, break_count=?, last_tested=? WHERE id=?",
                (new_price, new_kind, touch_count, hold_count, break_count, ts, zone_id),
            )

    def get_watermark(self, symbol: str) -> float:
        with _connect() as conn:
            row = conn.execute("SELECT last_touched_ts FROM sr_symbol_state WHERE symbol = ?", (symbol,)).fetchone()
            return row["last_touched_ts"] if row else 0.0

    def set_watermark(self, symbol: str, ts: float) -> None:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO sr_symbol_state (symbol, last_touched_ts) VALUES (?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET last_touched_ts = excluded.last_touched_ts",
                (symbol, ts),
            )
