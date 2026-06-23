"""
test_bridge.py — Unit tests for lxmf_aprs_bridge components.
"""

import math
import os
import tempfile
import time
import pytest

from position import (
    lxmf_hash_to_callsign,
    decimal_to_aprs,
    build_aprs_position_packet,
    build_comment,
)
from peer_store import PeerStore, _haversine_metres


# ------------------------------------------------------------------
# Callsign construction
# ------------------------------------------------------------------

class TestCallsign:
    def test_basic(self):
        h = bytes.fromhex("aabbccddeeff00112233445566778899aabbccdd")
        cs = lxmf_hash_to_callsign(h)
        assert cs == "RETCDD"

    def test_length(self):
        h = bytes(16)
        cs = lxmf_hash_to_callsign(h)
        assert len(cs) == 6
        assert cs.startswith("RET")

    def test_uppercase(self):
        h = bytes.fromhex("00000000000000000000000000abcdef")
        cs = lxmf_hash_to_callsign(h)
        assert cs == cs.upper()

    def test_different_hashes_different_callsigns(self):
        h1 = bytes.fromhex("00000000000000000000000000000001")
        h2 = bytes.fromhex("00000000000000000000000000000002")
        assert lxmf_hash_to_callsign(h1) != lxmf_hash_to_callsign(h2)


# ------------------------------------------------------------------
# Coordinate conversion
# ------------------------------------------------------------------

class TestCoordinates:
    def test_sydney_positive(self):
        # Sydney: -33.8688, 151.2093
        lat_s, lon_s = decimal_to_aprs(-33.8688, 151.2093)
        assert lat_s.endswith("S")
        assert lon_s.endswith("E")
        assert lat_s.startswith("33")
        assert lon_s.startswith("151")

    def test_northern_hemisphere(self):
        lat_s, lon_s = decimal_to_aprs(51.5074, -0.1278)  # London
        assert lat_s.endswith("N")
        assert lon_s.endswith("W")

    def test_format_lengths(self):
        lat_s, lon_s = decimal_to_aprs(-33.703, 151.099)
        # DDmm.mmH = 2+2+1+2+1 = 8 chars for lat
        # DDDmm.mmH = 3+2+1+2+1 = 9 chars for lon
        assert len(lat_s) == 8
        assert len(lon_s) == 9

    def test_zero_zero(self):
        lat_s, lon_s = decimal_to_aprs(0.0, 0.0)
        assert "N" in lat_s or "S" in lat_s
        assert "E" in lon_s or "W" in lon_s

    def test_minute_conversion(self):
        # 0.5 degrees = 30 minutes
        lat_s, _ = decimal_to_aprs(-33.5, 151.0)
        assert "30.00" in lat_s


# ------------------------------------------------------------------
# APRS packet building
# ------------------------------------------------------------------

class TestPacketBuilding:
    def test_basic_packet(self):
        pkt = build_aprs_position_packet(
            callsign="RET3F7",
            lat=-33.703,
            lon=151.099,
        )
        assert pkt.startswith("RET3F7>APRS,TCPIP*:!")
        assert "S" in pkt
        assert "E" in pkt

    def test_symbol_in_packet(self):
        pkt = build_aprs_position_packet(
            callsign="RET3F7",
            lat=-33.703,
            lon=151.099,
            symbol_table="/",
            symbol_code="[",
        )
        # Packet format: !DDMM.mmS/DDDMM.mmE[
        # Symbol table '/' appears between lat and lon, symbol code '[' at end of position
        assert "/" in pkt
        assert "[" in pkt

    def test_altitude_included(self):
        pkt = build_aprs_position_packet(
            callsign="RET3F7",
            lat=-33.703,
            lon=151.099,
            alt_metres=100.0,
        )
        assert "/A=" in pkt
        # 100m ≈ 328 feet
        assert "000328" in pkt

    def test_no_altitude_when_zero(self):
        pkt = build_aprs_position_packet(
            callsign="RET3F7",
            lat=-33.703,
            lon=151.099,
            alt_metres=0.0,
        )
        assert "/A=" not in pkt

    def test_comment_included(self):
        pkt = build_aprs_position_packet(
            callsign="RET3F7",
            lat=-33.703,
            lon=151.099,
            comment="RNS [Steve VK2XYZ]",
        )
        assert "RNS [Steve VK2XYZ]" in pkt

    def test_course_speed(self):
        pkt = build_aprs_position_packet(
            callsign="RET3F7",
            lat=-33.703,
            lon=151.099,
            course=90.0,
            speed_ms=10.0,  # ~19 knots
        )
        assert "090/" in pkt

    def test_no_course_speed_when_zero(self):
        pkt = build_aprs_position_packet(
            callsign="RET3F7",
            lat=-33.703,
            lon=151.099,
            course=0.0,
            speed_ms=0.0,
        )
        # Should not have course/speed extension
        assert "000/000" not in pkt


# ------------------------------------------------------------------
# Comment building
# ------------------------------------------------------------------

class TestComment:
    def test_with_display_name(self):
        c = build_comment("RNS", "aabbcc", "Steve VK2XYZ", include_display=True)
        assert c == "RNS [Steve VK2XYZ]"

    def test_without_display_name(self):
        c = build_comment("RNS", "aabbccddeeff", None, include_display=True)
        assert "DDEEFF" in c  # last 6 hex chars uppercased

    def test_display_disabled(self):
        c = build_comment("RNS", "aabbccddeeff", "Steve", include_display=False)
        assert "Steve" not in c
        assert "DDEEFF" in c

    def test_custom_prefix(self):
        c = build_comment("RETICULUM", "aabbcc", "Rob", include_display=True)
        assert c.startswith("RETICULUM")


# ------------------------------------------------------------------
# Haversine distance
# ------------------------------------------------------------------

class TestHaversine:
    def test_zero_distance(self):
        d = _haversine_metres(-33.703, 151.099, -33.703, 151.099)
        assert d == pytest.approx(0.0, abs=0.01)

    def test_known_distance(self):
        # Hornsby to Sydney CBD ≈ 21km (straight line)
        d = _haversine_metres(-33.703, 151.099, -33.8688, 151.2093)
        assert 19_000 < d < 23_000

    def test_small_movement(self):
        # ~11m north
        d = _haversine_metres(-33.703, 151.099, -33.7029, 151.099)
        assert d == pytest.approx(11.1, abs=1.0)


# ------------------------------------------------------------------
# Peer store
# ------------------------------------------------------------------

class TestPeerStore:
    @pytest.fixture
    def store(self, tmp_path):
        db = str(tmp_path / "test.db")
        ps = PeerStore(db)
        yield ps
        ps.close()

    def test_update_and_retrieve_display_name(self, store):
        store.update_display_name("aabbcc", "RETABC", "Steve VK2XYZ")
        name = store.get_display_name("aabbcc")
        assert name == "Steve VK2XYZ"

    def test_unknown_peer_no_display_name(self, store):
        assert store.get_display_name("unknown") is None

    def test_should_forward_new_peer(self, store):
        assert store.should_forward("aabbcc", -33.703, 151.099, 60, 10.0) is True

    def test_should_suppress_duplicate(self, store):
        store.update_position("aabbcc", "RETABC", -33.703, 151.099, 0.0)
        # Same position immediately after — should suppress
        result = store.should_forward("aabbcc", -33.703, 151.099, 60, 10.0)
        assert result is False

    def test_should_forward_after_window(self, store):
        store.update_position("aabbcc", "RETABC", -33.703, 151.099, 0.0)
        # Manually backdate last_aprs_ts
        store.conn.execute(
            "UPDATE peers SET last_aprs_ts = ? WHERE lxmf_hash = ?",
            (int(time.time()) - 120, "aabbcc")
        )
        store.conn.commit()
        result = store.should_forward("aabbcc", -33.703, 151.099, 60, 10.0)
        assert result is True

    def test_should_forward_after_movement(self, store):
        store.update_position("aabbcc", "RETABC", -33.703, 151.099, 0.0)
        # Move >10m
        result = store.should_forward("aabbcc", -33.7029, 151.099, 60, 10.0)
        assert result is True

    def test_symbol_override_none_by_default(self, store):
        t, c = store.get_symbol("aabbcc")
        assert t is None
        assert c is None

    def test_position_update_increments_count(self, store):
        store.update_position("aabbcc", "RETABC", -33.703, 151.099, 0.0)
        store.update_position("aabbcc", "RETABC", -33.704, 151.100, 0.0)
        row = store.conn.execute(
            "SELECT message_count FROM peers WHERE lxmf_hash = ?", ("aabbcc",)
        ).fetchone()
        assert row[0] == 2
