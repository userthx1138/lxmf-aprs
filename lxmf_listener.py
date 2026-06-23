"""
lxmf_listener.py — LXMF message and announce handler.

Watches for incoming LXMF messages containing Sideband-format location fields
and dispatches them to the APRS bridge.
"""

import logging
import time
from typing import Callable, Optional

log = logging.getLogger(__name__)

# Sideband LXMF telemetry field keys (from LXMF/LXMessage.py)
FIELD_LATITUDE   = 0x82
FIELD_LONGITUDE  = 0x83
FIELD_ALTITUDE   = 0x84
FIELD_SPEED      = 0x85
FIELD_HEADING    = 0x86
FIELD_ACCURACY   = 0x88
FIELD_TIMESTAMP  = 0x90


class LXMFListener:
    """
    Wraps LXMF router callbacks and extracts position data from incoming messages.

    Callbacks provided by the bridge:
        on_position(source_hash, display_name, lat, lon, alt, speed, heading)
        on_announce(source_hash, display_name)
    """

    def __init__(
        self,
        on_position: Callable,
        on_announce: Callable,
    ):
        self._on_position = on_position
        self._on_announce = on_announce

    def message_received(self, message) -> None:
        """
        Called by the LXMF router for every received message.
        Filters for messages containing position fields.
        """
        try:
            fields = message.fields
            if not fields:
                return

            if FIELD_LATITUDE not in fields or FIELD_LONGITUDE not in fields:
                return  # not a position message

            source_hash = message.source_hash  # bytes
            lat  = float(fields[FIELD_LATITUDE])
            lon  = float(fields[FIELD_LONGITUDE])
            alt  = float(fields.get(FIELD_ALTITUDE, 0.0))
            spd  = float(fields.get(FIELD_SPEED, 0.0))
            hdg  = float(fields.get(FIELD_HEADING, 0.0))

            log.debug(
                f"Position from {source_hash.hex()}: "
                f"lat={lat:.5f} lon={lon:.5f} alt={alt:.1f}m "
                f"spd={spd:.1f}m/s hdg={hdg:.0f}°"
            )

            self._on_position(
                source_hash=source_hash,
                lat=lat,
                lon=lon,
                alt=alt,
                speed_ms=spd,
                heading=hdg,
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

            hash_hex = destination_hash.hex()
            log.debug(f"Announce from {hash_hex}: display_name={display_name!r}")

            self._on_announce(
                destination_hash=destination_hash,
                display_name=display_name,
            )

        except Exception as e:
            log.error(f"Error processing announce: {e}", exc_info=True)
