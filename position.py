"""
position.py — Callsign construction and APRS packet formatting.
"""

import time
from typing import Optional


# ------------------------------------------------------------------
# Callsign construction
# ------------------------------------------------------------------

def lxmf_hash_to_callsign(destination_hash: bytes) -> str:
    """
    Derive an APRS callsign from the last 3 hex digits of an LXMF hash.
    Result is RETxxx where xxx is uppercase hex, e.g. RET3F7.
    Max 9 chars — RET + 3 hex = 6 chars, well within APRS limit.
    """
    suffix = destination_hash.hex()[-3:].upper()
    return f"RET{suffix}"


# ------------------------------------------------------------------
# Coordinate conversion: decimal degrees → APRS DDmm.mmH format
# ------------------------------------------------------------------

def decimal_to_aprs(lat: float, lon: float) -> tuple[str, str]:
    """
    Convert decimal degree lat/lon to APRS position format.
    Returns (lat_str, lon_str) e.g. ("3342.18S", "15106.34E")
    """
    lat_hemi = 'N' if lat >= 0 else 'S'
    lon_hemi = 'E' if lon >= 0 else 'W'
    lat = abs(lat)
    lon = abs(lon)

    lat_deg = int(lat)
    lat_min = (lat - lat_deg) * 60
    lon_deg = int(lon)
    lon_min = (lon - lon_deg) * 60

    lat_str = f"{lat_deg:02d}{lat_min:05.2f}{lat_hemi}"
    lon_str = f"{lon_deg:03d}{lon_min:05.2f}{lon_hemi}"
    return lat_str, lon_str


# ------------------------------------------------------------------
# APRS packet builder
# ------------------------------------------------------------------

def build_aprs_position_packet(
    callsign: str,
    lat: float,
    lon: float,
    alt_metres: float = 0.0,
    course: float = 0,
    speed_ms: float = 0.0,
    symbol_table: str = "/",
    symbol_code: str = "[",
    comment: Optional[str] = None,
) -> str:
    """
    Build a complete APRS-IS position packet string (without trailing CRLF).

    Format:
        CALLSIGN>APRS,TCPIP*:!DDMM.mmN/DDDMM.mmE[/A= FFFFFF] comment
    """
    lat_str, lon_str = decimal_to_aprs(lat, lon)
    alt_feet = int(alt_metres * 3.28084)

    # Course and speed (knots) — include if non-zero
    if course > 0 or speed_ms > 0:
        speed_knots = int(speed_ms * 1.94384)
        data_ext = f"{int(course):03d}/{speed_knots:03d}"
    else:
        data_ext = ""

    altitude = f"/A={alt_feet:06d}" if alt_metres > 0 else ""
    comment_str = f" {comment}" if comment else ""

    packet = (
        f"{callsign}>APRS,TCPIP*:"
        f"!{lat_str}{symbol_table}{lon_str}{symbol_code}"
        f"{data_ext}{altitude}{comment_str}"
    )
    return packet


def build_comment(
    comment_prefix: str,
    lxmf_hash_hex: str,
    display_name: Optional[str],
    include_display: bool = True,
) -> str:
    """
    Build the APRS comment field.
    Example: "RNS [Steve VK2XYZ]"  or  "RNS [a1b2c3d4]"
    """
    if include_display and display_name:
        label = display_name
    else:
        label = lxmf_hash_hex[-6:].upper()

    return f"{comment_prefix} [{label}]"
