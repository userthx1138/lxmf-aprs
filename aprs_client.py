"""
aprs_client.py — APRS-IS TCP client with login, send, keepalive, and reconnection.
"""

import socket
import time
import logging
import threading

log = logging.getLogger(__name__)

APRS_VERSION = "lxmf-aprs-bridge 0.1"
RECV_TIMEOUT = 30       # seconds
RECONNECT_DELAY = 30    # seconds between reconnect attempts


class APRSClient:
    def __init__(self, host: str, port: int, callsign: str, passcode: str,
                 keepalive_interval: int = 600):
        self.host = host
        self.port = port
        self.callsign = callsign
        self.passcode = passcode
        self.keepalive_interval = keepalive_interval
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._keepalive_thread: threading.Thread | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self):
        """Establish connection and log in to APRS-IS server."""
        log.info(f"Connecting to APRS-IS {self.host}:{self.port}")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(RECV_TIMEOUT)
        sock.connect((self.host, self.port))

        # Read server banner
        banner = sock.recv(1024).decode("ascii", errors="replace").strip()
        log.info(f"APRS-IS banner: {banner}")

        # Send login
        login = (
            f"user {self.callsign} pass {self.passcode} "
            f"vers {APRS_VERSION} filter r/-33.703/151.099/100\r\n"
        )
        sock.sendall(login.encode("ascii"))

        # Read login response
        resp = sock.recv(1024).decode("ascii", errors="replace").strip()
        log.info(f"APRS-IS login response: {resp}")
        if "unverified" in resp.lower():
            log.warning("APRS-IS login unverified — check callsign and passcode")

        self._sock = sock
        log.info("Connected to APRS-IS")

    def disconnect(self):
        self._running = False
        with self._lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _ensure_connected(self):
        """Reconnect if socket is not available."""
        if self._sock is None:
            while True:
                try:
                    self.connect()
                    break
                except Exception as e:
                    log.error(f"APRS-IS reconnect failed: {e} — retrying in {RECONNECT_DELAY}s")
                    time.sleep(RECONNECT_DELAY)

    # ------------------------------------------------------------------
    # Packet sending
    # ------------------------------------------------------------------

    def send(self, packet: str):
        """Send a single APRS packet. Reconnects automatically on failure."""
        with self._lock:
            self._ensure_connected()
            try:
                line = f"{packet}\r\n"
                self._sock.sendall(line.encode("ascii"))
                log.info(f"APRS-IS TX: {packet}")
            except Exception as e:
                log.error(f"APRS-IS send error: {e} — will reconnect on next send")
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None
                raise

    # ------------------------------------------------------------------
    # Keepalive
    # ------------------------------------------------------------------

    def start_keepalive(self):
        """Start background thread sending periodic keepalive comments."""
        self._running = True
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="aprs-keepalive"
        )
        self._keepalive_thread.start()

    def _keepalive_loop(self):
        while self._running:
            time.sleep(self.keepalive_interval)
            if not self._running:
                break
            with self._lock:
                if self._sock:
                    try:
                        self._sock.sendall(b"# lxmf-aprs-bridge keepalive\r\n")
                        log.debug("APRS-IS keepalive sent")
                    except Exception as e:
                        log.warning(f"APRS-IS keepalive failed: {e}")
                        try:
                            self._sock.close()
                        except Exception:
                            pass
                        self._sock = None
