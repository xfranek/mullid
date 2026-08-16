"""Jednorazowa inicjalizacja mullid.

Nie wypisuje klucza prywatnego, numeru konta ani tokenu — wylacznie postep
i metadane.
"""

from __future__ import annotations

import io
import sys
import tarfile
import urllib.request

from mullid import device, paths, relays, wireproxy

WIREPROXY_URL = (
    "https://github.com/whyvl/wireproxy/releases/download/"
    f"{wireproxy.WIREPROXY_VERSION}/wireproxy_darwin_arm64.tar.gz"
)


def pick_entry_relay(catalog: relays.RelayCatalog):
    """Relay wejsciowy sluzy tylko za wjazd do sieci Mullvada.

    Adres wyjsciowy wybiera pozniej mullid, per profil, wiec tutaj liczy sie
    wylacznie bliskosc. Amsterdam, potem cokolwiek niemieckiego, potem cokolwiek.
    """
    for country, city in (("nl", "ams"), ("de", None), (None, None)):
        try:
            options = catalog.eligible(country)
        except relays.UnknownCountry:
            continue
        if city is not None:
            options = [r for r in options if r.city_code == city]
        if options:
            return sorted(options, key=lambda r: r.hostname)[0]
    raise relays.RelayError("katalog nie zawiera zadnego uzywalnego relaya")


def main() -> int:
    print("1/5  pobieram katalog relayow…")
    raw = relays.fetch_relays()
    relays.save_relays(raw)
    catalog = relays.RelayCatalog.from_raw(raw)
    print(f"     zapisano {len(raw)} relayow, {len(catalog.countries())} krajow")

    print("2/5  generuje pare kluczy X25519…")
    private_b64, public_b64 = device.generate_keypair()
    print("     klucz wygenerowany lokalnie (nie zostanie nigdzie wypisany)")

    print("3/5  rejestruje urzadzenie na koncie…")
    try:
        account = device.read_account_number()
        access = device.get_access_token(account)
        registered = device.register_device(access, public_b64)
    except device.DeviceError as e:
        print(f"     BLAD: {e}", file=sys.stderr)
        print(
            "     Jesli to HTTP 400 lub 409, konto ma prawdopodobnie 5 z 5 urzadzen.\n"
            "     Zwolnij jedno na https://mullvad.net/account/devices i powtorz.",
            file=sys.stderr,
        )
        return 1
    print(f"     zarejestrowano jako {registered.get('name', '?')}")

    print("4/5  zapisuje konfiguracje…")
    entry = pick_entry_relay(catalog)
    conf = device.write_wg_conf(
        private_b64,
        registered["ipv4_address"],
        registered["ipv6_address"],
        entry.pubkey,
        f"{entry.ipv4_addr_in}:51820",
    )
    wg = wireproxy.parse_wg_conf(conf)
    paths.wireproxy_conf_path().write_text(wireproxy.render_wireproxy_conf(wg))
    paths.wireproxy_conf_path().chmod(0o600)
    print(f"     relay wejsciowy: {entry.hostname}")

    print("5/5  pobieram binarke wireproxy…")
    bin_path = paths.wireproxy_bin_path()
    bin_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(WIREPROXY_URL, timeout=60) as resp:
        blob = resp.read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        member = next((m for m in tar.getmembers() if m.name.endswith("wireproxy")), None)
        if member is None:
            print(
                "     BLAD: archiwum nie zawiera pliku wireproxy; "
                f"zawartosc: {[m.name for m in tar.getmembers()]}",
                file=sys.stderr,
            )
            return 1
        bin_path.write_bytes(tar.extractfile(member).read())
    bin_path.chmod(0o700)
    print(f"     zainstalowano w {bin_path}")

    print("\nGotowe. Uruchom:  python3 -m mullid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
