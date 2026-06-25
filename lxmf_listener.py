"""
lxmf_listener.py — LXMF message and announce handler.

Extracts Sideband-format telemetry from LXMF messages without requiring sbapp.

Sideband telemetry structure:
  message.fields[LXMF.FIELD_TELEMETRY]  →  msgpack-packed dict {sensor_id: packed_data}
  Sensor ID 0x02 = Location sensor
  Location packed_data = [lat_i32, lon_i32, alt_i32, speed_u32, bearing_i32, accuracy_u16, last_update]
  where lat/lon are int32 * 1e6, alt is int32 * 1e2, speed is uint32 * 1e2,
  bearing is int32 * 1e2, accuracy is uint16 * 1e2
"""

import logging
import struct
from typing import Callable, Optional

import LXMF
import umsgpack

log = logging.getLogger(__name__)

# Sideband sensor IDs (from sbapp/sideband/sense.py)
SID_LOCATION = 0x02


def _unpack_location(packed_data: list) -> Optional[dict]:
    """
    Unpack a Sideband location sensor payload.
    packed_data is a list of 7 items as packed by Location.pack().
    """
    try:
        return {
            "latitude":   struct.unpack("!i", packed_data[0])[0] / 1e6,
            "longitude":  struct.unpack("!i", packed_data[1])[0] / 1e6,
            "altitude":   struct.unpack("!i", packed_data[2])[0] / 1e2,
            "speed":      struct.unpack("!I", packed_data[3])[0] / 1e2,
            "bearing":    struct.unpack("!i", packed_data[4])[0] / 1e2,
            "accuracy":   struct.unpack("!H", packed_data[5])[0] / 1e2,
            "last_update": packed_data[6],
        }
    except Exception as e:
        log.debug(f"Failed to unpack location sensor data: {e}")
        return None


def _extract_location(packed_telemetry: bytes) -> Optional[dict]:
    """
    Unpack a Telemeter msgpack blob and extract the location sensor data.
    Returns a dict with lat/lon/alt/speed/bearing/accuracy or None.
    """
    try:
        sensors = umsgpack.unpackb(packed_telemetry)
    except Exception as e:
        log.debug(f"Failed to msgpack-unpack telemetry: {e}")
        return None

    if not isinstance(sensors, dict):
        log.debug(f"Unexpected telemetry structure (not a dict): {type(sensors)}")
        return None

    log.debug(f"Telemetry sensor IDs present: {[hex(k) for k in sensors.keys()]}")

    if SID_LOCATION not in sensors:
        log.debug(f"No location sensor (0x{SID_LOCATION:02x}) in telemetry")
        return None

    return _unpack_location(sensors[SID_LOCATION])


class LXMFListener:
    """
    Wraps LXMF router callbacks and extracts position data from incoming messages.

    Callbacks:
        on_position(source_hash, lat, lon, alt, speed_ms, heading)
        on_announce(destination_hash, display_name)
    """

    def __init__(self, on_position: Callable, on_announce: Callable):
        self._on_position = on_position
        self._on_announce = on_announce

    def message_received(self, message) -> None:
        """
        Called by the LXMF router for every received message.
        Filters for messages containing FIELD_TELEMETRY with a location sensor.
        """
        try:
            fields = message.fields
            log.debug(
                f"LXMF message received from {message.source_hash.hex()}, "
                f"fields: {[hex(k) for k in fields.keys()] if fields else None}"
            )

            if not fields:
                log.debug("Message has no fields — skipping")
                return

            if LXMF.FIELD_TELEMETRY not in fields:
                log.debug(
                    f"No FIELD_TELEMETRY (0x{LXMF.FIELD_TELEMETRY:02x}) in message "
                    f"(got: {[hex(k) for k in fields.keys()]})"
                )
                return

            packed = fields[LXMF.FIELD_TELEMETRY]
            if not packed:
                log.debug("FIELD_TELEMETRY is empty — skipping")
                return

            loc = _extract_location(packed)
            if loc is None:
                return

            lat     = loc.get("latitude")
            lon     = loc.get("longitude")
            if lat is None or lon is None:
                log.debug(f"Location missing lat/lon: {loc}")
                return

            alt     = loc.get("altitude", 0.0) or 0.0
            speed   = loc.get("speed", 0.0) or 0.0
            bearing = loc.get("bearing", 0.0) or 0.0

            log.debug(
                f"Position from {message.source_hash.hex()}: "
                f"lat={lat:.5f} lon={lon:.5f} alt={alt:.1f}m "
                f"spd={speed:.1f}m/s bearing={bearing:.0f}°"
            )

            self._on_position(
                source_hash=message.source_hash,
                lat=lat,
                lon=lon,
                alt=alt,
                speed_ms=speed,
                heading=bearing,
            )

        except Exception as e:
            log.error(f"Error processing LXMF message: {e}", exc_info=True)

    def announce_received(self, destination_hash, announced_identity, app_data) -> None:
        """
        Called by RNS when an LXMF announce is received.
        Extracts display name and notifies the bridge.
        """
        try:
            display_name: Optional[str] = None
            if app_data:
                try:
                    display_name = app_data.decode("utf-8").strip()
                except Exception:
                    pass

            log.debug(f"Announce from {destination_hash.hex()}: display_name={display_name!r}")

            self._on_announce(
                destination_hash=destination_hash,
                display_name=display_name,
            )

        except Exception as e:
            log.error(f"Error processing announce: {e}", exc_info=True)
