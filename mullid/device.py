"""Generacja klucza i rejestracja urzadzenia w API Mullvada.

Klucz prywatny, numer konta i token nie trafiaja nigdy do logow ani na
standardowe wyjscie. Komunikaty o bledach operuja kodami HTTP i nazwami pol.
Pilnuje tego test SecretHygieneTest w tests/test_device.py.
"""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import paths

AUTH_URL = "https://api.mullvad.net/auth/v1/token"
DEVICES_URL = "https://api.mullvad.net/accounts/v1/devices"


class DeviceError(RuntimeError):
    """Rejestracja urzadzenia sie nie powiodla."""


def generate_keypair() -> tuple[str, str]:
    der_priv = subprocess.run(
        ["openssl", "genpkey", "-algorithm", "X25519", "-outform", "DER"],
        capture_output=True,
        check=True,
    ).stdout
    der_pub = subprocess.run(
        ["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"],
        input=der_priv,
        capture_output=True,
        check=True,
    ).stdout
    # DER opakowuje surowy klucz naglowkiem ASN.1; ostatnie 32 bajty to
    # material, ktorego chce WireGuard (48 B dla prywatnego, 44 B dla publicznego).
    return (
        base64.b64encode(der_priv[-32:]).decode(),
        base64.b64encode(der_pub[-32:]).decode(),
    )


def read_account_number() -> str:
    out = subprocess.run(
        ["mullvad", "account", "get"], capture_output=True, text=True, check=True
    ).stdout
    for line in out.splitlines():
        if "account" in line.lower():
            candidate = line.split()[-1].strip()
            if candidate.isdigit():
                return candidate
    raise DeviceError(
        "nie udalo sie odczytac numeru konta z `mullvad account get` — "
        "czy aplikacja jest zalogowana?"
    )


def _post_json(url: str, payload: dict, token: str | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        # Tresc bledu moze zawierac echo zadania, wiec nie wchodzi do komunikatu.
        raise DeviceError(f"{url} zwrocilo HTTP {e.code}") from None


def get_access_token(account_number: str) -> str:
    data = _post_json(AUTH_URL, {"account_number": account_number})
    if "access_token" not in data:
        raise DeviceError("odpowiedz /auth/v1/token nie zawiera pola access_token")
    return data["access_token"]


def register_device(access_token: str, public_b64: str) -> dict:
    data = _post_json(DEVICES_URL, {"pubkey": public_b64, "hijack_dns": False}, access_token)
    missing = [k for k in ("ipv4_address", "ipv6_address") if k not in data]
    if missing:
        raise DeviceError(
            f"odpowiedz /accounts/v1/devices nie zawiera pol: {', '.join(missing)}; "
            f"otrzymane pola: {', '.join(sorted(data))}"
        )
    return data


def write_wg_conf(
    private_b64: str, ipv4: str, ipv6: str, peer_pubkey: str, endpoint: str
) -> Path:
    path = paths.wg_conf_path()
    path.write_text(
        "[Interface]\n"
        f"PrivateKey = {private_b64}\n"
        f"Address = {ipv4}, {ipv6}\n"
        "DNS = 10.64.0.1\n\n"
        "[Peer]\n"
        f"PublicKey = {peer_pubkey}\n"
        f"Endpoint = {endpoint}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path
