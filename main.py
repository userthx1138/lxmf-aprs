"""
main.py — LXMF → APRS-IS bridge entry point.

Listens for LXMF messages containing Sideband-format location fields and
forwards them to an APRS-IS server as position packets.

Apparent callsign: RETxxx where xxx is last 3 hex digits of the LXMF source hash.
Display name sourced from LXMF announce packets.
"""

import logging
import os
import signal
import sys
import time

import RNS
import LXMF

from config import load_config
from peer_store import PeerStore
from aprs_client import APRSClient
from lxmf_listener import LXMFListener
from position import (
    lxmf_hash_to_callsign,
    build_aprs_position_packet,
    build_comment,
)

log = logging.getLogger(__name__)


class LXMFAPRSBridge:
    def __init__(self, config_path: str = "config.ini"):
        self.cfg = load_config(config_path)
        self.running = False

        # Expand paths
        storage_path = os.path.expanduser(self.cfg.lxmf.storage_path)
        os.makedirs(storage_path, exist_ok=True)

        # Initialise subsystems
        self.peer_store = PeerStore(self.cfg.bridge.db_path)

        self.aprs = APRSClient(
            host=self.cfg.aprs.host,
            port=self.cfg.aprs.port,
            callsign=self.cfg.aprs.callsign,
            passcode=self.cfg.aprs.passcode,
            keepalive_interval=self.cfg.bridge.keepalive_interval,
        )

        self.lxmf_listener = LXMFListener(
            on_position=self._on_position,
            on_announce=self._on_announce,
        )

        # Initialise RNS
        log.info("Starting Reticulum...")
        self.rns = RNS.Reticulum(storage_path)

        # Initialise LXMF router
        log.info("Starting LXMF router...")
        self.router = LXMF.LXMRouter(storagepath=storage_path)
        self.identity = RNS.Identity()
        self.destination = self.router.register_delivery_identity(
            self.identity,
            display_name="LXMF-APRS Bridge",
        )
        self.router.register_delivery_callback(self.lxmf_listener.message_received)

        # Register announce handler if enabled
        if self.cfg.bridge.announce_listen:
            RNS.Transport.register_announce_handler(
                _AnnounceHandler(self.lxmf_listener.announce_received)
            )

        log.info(f"LXMF bridge address: {RNS.prettyhexrep(self.destination.hash)}")

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_position(self, source_hash: bytes, lat: float, lon: float,
                     alt: float, speed_ms: float, heading: float):
        """Called when a position-bearing LXMF message is received."""
        hash_hex = source_hash.hex()
        callsign = lxmf_hash_to_callsign(source_hash)

        # Deduplication check
        if not self.peer_store.should_forward(
            hash_hex, lat, lon,
            self.cfg.bridge.dedupe_window,
            self.cfg.bridge.dedupe_distance,
        ):
            return

        # Symbol — check for per-peer override, fall back to global config
        sym_table, sym_code = self.peer_store.get_symbol(hash_hex)
        sym_table = sym_table or self.cfg.aprs.symbol_table
        sym_code  = sym_code  or self.cfg.aprs.symbol_code

        # Display name from announce cache
        display_name = self.peer_store.get_display_name(hash_hex)

        comment = build_comment(
            comment_prefix=self.cfg.aprs.comment_prefix,
            lxmf_hash_hex=hash_hex,
            display_name=display_name,
            include_display=self.cfg.bridge.lxmf_display_in_comment,
        )

        packet = build_aprs_position_packet(
            callsign=callsign,
            lat=lat,
            lon=lon,
            alt_metres=alt,
            course=heading,
            speed_ms=speed_ms,
            symbol_table=sym_table,
            symbol_code=sym_code,
            comment=comment,
        )

        try:
            self.aprs.send(packet)
            self.peer_store.update_position(hash_hex, callsign, lat, lon, alt)
        except Exception as e:
            log.error(f"Failed to send APRS packet for {callsign}: {e}")

    def _on_announce(self, destination_hash: bytes, display_name: str | None):
        """Called when an LXMF announce is received — update peer display name."""
        hash_hex = destination_hash.hex()
        callsign = lxmf_hash_to_callsign(destination_hash)
        self.peer_store.update_display_name(hash_hex, callsign, display_name or "")
        log.info(f"Peer announce: {callsign} ({hash_hex}) → {display_name!r}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        log.info("Connecting to APRS-IS...")
        self.aprs.connect()
        self.aprs.start_keepalive()

        # Announce ourselves on the Reticulum network
        self.destination.announce()
        log.info("LXMF-APRS bridge running. Press Ctrl+C to stop.")

        self.running = True
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        log.info("Shutting down...")
        self.running = False
        self.aprs.disconnect()
        self.peer_store.close()


# ------------------------------------------------------------------
# RNS Announce Handler shim
# ------------------------------------------------------------------

class _AnnounceHandler:
    """
    Shim to fit our callback into the RNS announce handler interface.
    Only processes LXMF.LXMFDelivery aspect announces.
    """
    aspect_filter = "lxmf.delivery"

    def __init__(self, callback):
        self._callback = callback

    def received_announce(self, destination_hash, announced_identity, app_data):
        self._callback(destination_hash, announced_identity, app_data)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="LXMF → APRS-IS position bridge")
    parser.add_argument("--config", default="config.ini", help="Path to config file")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    setup_logging(args.log_level)

    bridge = LXMFAPRSBridge(config_path=args.config)

    def _sigterm(sig, frame):
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm)
    bridge.start()
