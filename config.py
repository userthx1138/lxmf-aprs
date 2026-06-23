"""
config.py — Configuration dataclass and INI loader for lxmf_aprs_bridge
"""

import configparser
import os
from dataclasses import dataclass, field


@dataclass
class LXMFConfig:
    storage_path: str = "~/.lxmf_aprs_bridge"


@dataclass
class APRSConfig:
    host: str = "localhost"
    port: int = 14580
    callsign: str = "NOCALL"
    passcode: str = "-1"
    symbol_table: str = "/"     # primary symbol table
    symbol_code: str = "["      # [ = person (default)
    comment_prefix: str = "RNS"


@dataclass
class BridgeConfig:
    db_path: str = "~/.lxmf_aprs_bridge/peers.db"
    keepalive_interval: int = 600       # seconds between APRS-IS keepalives
    dedupe_window: int = 60             # suppress duplicate positions within this window (seconds)
    dedupe_distance: float = 10.0       # suppress if moved less than this many metres
    announce_listen: bool = True        # listen for LXMF announces to capture display names
    lxmf_display_in_comment: bool = True  # include display name in APRS comment field


@dataclass
class Config:
    lxmf: LXMFConfig = field(default_factory=LXMFConfig)
    aprs: APRSConfig = field(default_factory=APRSConfig)
    bridge: BridgeConfig = field(default_factory=BridgeConfig)


def load_config(path: str = "config.ini") -> Config:
    cfg = Config()
    if not os.path.exists(path):
        return cfg

    parser = configparser.ConfigParser()
    parser.read(path)

    if "lxmf" in parser:
        s = parser["lxmf"]
        cfg.lxmf.storage_path = s.get("storage_path", cfg.lxmf.storage_path)

    if "aprs" in parser:
        s = parser["aprs"]
        cfg.aprs.host             = s.get("host",           cfg.aprs.host)
        cfg.aprs.port             = s.getint("port",        cfg.aprs.port)
        cfg.aprs.callsign         = s.get("callsign",       cfg.aprs.callsign)
        cfg.aprs.passcode         = s.get("passcode",       cfg.aprs.passcode)
        cfg.aprs.symbol_table     = s.get("symbol_table",   cfg.aprs.symbol_table)
        cfg.aprs.symbol_code      = s.get("symbol_code",    cfg.aprs.symbol_code)
        cfg.aprs.comment_prefix   = s.get("comment_prefix", cfg.aprs.comment_prefix)

    if "bridge" in parser:
        s = parser["bridge"]
        cfg.bridge.db_path                = s.get("db_path",                cfg.bridge.db_path)
        cfg.bridge.keepalive_interval     = s.getint("keepalive_interval",  cfg.bridge.keepalive_interval)
        cfg.bridge.dedupe_window          = s.getint("dedupe_window",       cfg.bridge.dedupe_window)
        cfg.bridge.dedupe_distance        = s.getfloat("dedupe_distance",   cfg.bridge.dedupe_distance)
        cfg.bridge.announce_listen        = s.getboolean("announce_listen", cfg.bridge.announce_listen)
        cfg.bridge.lxmf_display_in_comment = s.getboolean("lxmf_display_in_comment", cfg.bridge.lxmf_display_in_comment)

    return cfg
