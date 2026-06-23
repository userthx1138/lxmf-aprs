"""
peer_store.py — SQLite store for known LXMF peers, display names, and last positions.
"""

import sqlite3
import time
import math
import logging
import os
from typing import Optional

log = logging.getLogger(__name__)


class PeerStore:
    def __init__(self, db_path: str):
        db_path = os.path.expanduser(db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS peers (
                lxmf_hash      TEXT PRIMARY KEY,
                callsign       TEXT NOT NULL,
                display_name   TEXT,
                last_lat       REAL,
                last_lon       REAL,
                last_alt       REAL,
                last_position_ts INTEGER,
                last_aprs_ts   INTEGER,
                first_seen     INTEGER NOT NULL,
                last_seen      INTEGER NOT NULL,
                symbol_table   TEXT,
                symbol_code    TEXT,
                message_count  INTEGER DEFAULT 0
            )
        """)
        self.conn.commit()

    # ------------------------------------------------------------------
    # Peer registration / display name update (from LXMF announces)
    # ------------------------------------------------------------------

    def update_display_name(self, lxmf_hash: str, callsign: str, display_name: str):
        """Called when an LXMF announce is received for a peer."""
        now = int(time.time())
        self.conn.execute("""
            INSERT INTO peers (lxmf_hash, callsign, display_name, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(lxmf_hash) DO UPDATE SET
                display_name = excluded.display_name,
                callsign     = excluded.callsign,
                last_seen    = excluded.last_seen
        """, (lxmf_hash, callsign, display_name, now, now))
        self.conn.commit()
        log.debug(f"Updated display name for {lxmf_hash}: {display_name}")

    # ------------------------------------------------------------------
    # Position updates
    # ------------------------------------------------------------------

    def should_forward(self, lxmf_hash: str, lat: float, lon: float,
                       dedupe_window: int, dedupe_distance: float) -> bool:
        """
        Returns True if this position should be forwarded to APRS-IS.
        Suppresses if last forwarded position was within dedupe_window seconds
        AND the peer has moved less than dedupe_distance metres.
        """
        row = self.conn.execute("""
            SELECT last_lat, last_lon, last_aprs_ts FROM peers WHERE lxmf_hash = ?
        """, (lxmf_hash,)).fetchone()

        if row is None:
            return True

        last_lat, last_lon, last_aprs_ts = row

        if last_aprs_ts is None:
            return True

        age = int(time.time()) - last_aprs_ts
        if age >= dedupe_window:
            return True

        if last_lat is None or last_lon is None:
            return True

        dist = _haversine_metres(last_lat, last_lon, lat, lon)
        if dist >= dedupe_distance:
            return True

        log.debug(f"Suppressing duplicate position for {lxmf_hash} "
                  f"(age={age}s, dist={dist:.1f}m)")
        return False

    def update_position(self, lxmf_hash: str, callsign: str,
                        lat: float, lon: float, alt: float):
        """Record that we forwarded a position for this peer."""
        now = int(time.time())
        self.conn.execute("""
            INSERT INTO peers (lxmf_hash, callsign, last_lat, last_lon, last_alt,
                               last_position_ts, last_aprs_ts, first_seen, last_seen,
                               message_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(lxmf_hash) DO UPDATE SET
                callsign         = excluded.callsign,
                last_lat         = excluded.last_lat,
                last_lon         = excluded.last_lon,
                last_alt         = excluded.last_alt,
                last_position_ts = excluded.last_position_ts,
                last_aprs_ts     = excluded.last_aprs_ts,
                last_seen        = excluded.last_seen,
                message_count    = message_count + 1
        """, (lxmf_hash, callsign, lat, lon, alt, now, now, now, now))
        self.conn.commit()

    # ------------------------------------------------------------------
    # Peer symbol overrides (per-peer APRS symbol, if desired later)
    # ------------------------------------------------------------------

    def get_symbol(self, lxmf_hash: str) -> tuple[Optional[str], Optional[str]]:
        """Returns (symbol_table, symbol_code) override for a peer, or (None, None)."""
        row = self.conn.execute("""
            SELECT symbol_table, symbol_code FROM peers WHERE lxmf_hash = ?
        """, (lxmf_hash,)).fetchone()
        if row:
            return row[0], row[1]
        return None, None

    def get_display_name(self, lxmf_hash: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT display_name FROM peers WHERE lxmf_hash = ?", (lxmf_hash,)
        ).fetchone()
        return row[0] if row else None

    def close(self):
        self.conn.close()


def _haversine_metres(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in metres."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
