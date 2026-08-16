"""Konfiguracja i nadzor procesu wireproxy."""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from . import paths

log = logging.getLogger("mullid.wireproxy")

WIREPROXY_VERSION = "v1.1.3"


def parse_wg_conf(path: Path) -> dict:
    section, out = None, {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]").lower()
            continue
        key, _, value = line.partition("=")
        key, value = key.strip().lower(), value.strip()
        if section == "interface" and key == "privatekey":
            out["private_key"] = value
        elif section == "interface" and key == "address":
            for part in (p.strip() for p in value.split(",")):
                out["address_v6" if ":" in part else "address_v4"] = part
        elif section == "peer" and key == "publickey":
            out["peer_pubkey"] = value
        elif section == "peer" and key == "endpoint":
            out["endpoint"] = value
    missing = [
        k for k in ("private_key", "address_v4", "peer_pubkey", "endpoint") if k not in out
    ]
    if missing:
        raise ValueError(f"{path} nie zawiera pol: {', '.join(missing)}")
    return out


def render_wireproxy_conf(wg: dict, *, socks_bind: str = "127.0.0.1:1080") -> str:
    address = wg["address_v4"]
    if wg.get("address_v6"):
        address += ", " + wg["address_v6"]
    return (
        "[Interface]\n"
        f"Address = {address}\n"
        f"PrivateKey = {wg['private_key']}\n"
        "DNS = 10.64.0.1\n"
        "MTU = 1380\n\n"
        "[Peer]\n"
        f"PublicKey = {wg['peer_pubkey']}\n"
        f"Endpoint = {wg['endpoint']}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        "PersistentKeepalive = 25\n\n"
        "[Socks5]\n"
        f"BindAddress = {socks_bind}\n"
    )


class WireproxySupervisor:
    def __init__(self, bin_path: Path | None = None, conf_path: Path | None = None):
        self._bin = bin_path or paths.wireproxy_bin_path()
        self._conf = conf_path or paths.wireproxy_conf_path()
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        if self.is_running():
            return
        if not self._bin.exists():
            raise FileNotFoundError(f"brak binarki wireproxy w {self._bin}; uruchom setup.py")
        self._proc = subprocess.Popen(
            [str(self._bin), "-c", str(self._conf)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.info("wireproxy wystartowal, pid %s", self._proc.pid)

    def stop(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def health(self) -> dict:
        """Stan tunelu.

        direct_ip to adres widziany BEZ tunelu — sluzy jako kontrola szczelnosci:
        ma pokazywac adres domowy, co dowodzi, ze routing systemowy jest nietkniety.
        Adres wyjsciowy per profil sprawdza sie curlem przez proxy, nie tutaj.
        """
        out = {
            "wireproxy_running": self.is_running(),
            "socks_reachable": False,
            "direct_ip": None,
            "checked_at": datetime.now(UTC).isoformat(),
        }
        if not out["wireproxy_running"]:
            out["error"] = "proces wireproxy nie dziala"
            return out
        try:
            with socket.create_connection(("127.0.0.1", 1080), timeout=3):
                out["socks_reachable"] = True
        except OSError as e:
            out["error"] = f"SOCKS5 na 127.0.0.1:1080 nieosiagalny ({e})"
            return out
        try:
            with urllib.request.urlopen("https://am.i.mullvad.net/json", timeout=8) as r:
                out["direct_ip"] = json.loads(r.read().decode()).get("ip")
        except Exception as e:
            out["error"] = f"nie udalo sie ustalic adresu bezposredniego ({e})"
        return out
