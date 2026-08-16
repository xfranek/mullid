"""Katalog relayow Mullvada i dobor wyjscia.

Adresy proxy bierzemy z pola socks_name zwracanego przez API, a nie
wyliczamy z zakresu 10.124.x.y. Nazwa domenowa jest rozwiazywana wewnatrz
tunelu przez wireproxy, wiec nic nie wycieka do lokalnego DNS.
"""

from __future__ import annotations

import json
import random
import urllib.request
from dataclasses import dataclass

from . import paths

RELAYS_URL = "https://api.mullvad.net/www/relays/wireguard/"


class RelayError(RuntimeError):
    """Katalog relayow jest niedostepny albo nie zawiera tego, czego szukamy."""


class UnknownCountry(RelayError):
    """Brak uzywalnego relaya w podanym kraju."""


@dataclass(frozen=True)
class Relay:
    hostname: str
    country_code: str
    city_code: str
    socks_name: str
    socks_port: int
    pubkey: str
    ipv4_addr_in: str


def fetch_relays(url: str = RELAYS_URL, timeout: float = 15.0) -> list[dict]:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        if resp.status != 200:
            raise RelayError(f"{url} zwrocilo HTTP {resp.status}")
        return json.loads(resp.read().decode("utf-8"))


def save_relays(raw: list[dict]) -> None:
    paths.write_json_atomic(paths.relays_path(), raw)


class RelayCatalog:
    def __init__(self, relays: list[Relay]):
        self._relays = relays

    @classmethod
    def from_raw(cls, raw: list[dict]) -> RelayCatalog:
        usable = [
            Relay(
                hostname=r["hostname"],
                country_code=r["country_code"],
                city_code=r["city_code"],
                socks_name=r["socks_name"],
                socks_port=int(r.get("socks_port") or 1080),
                pubkey=r["pubkey"],
                ipv4_addr_in=r["ipv4_addr_in"],
            )
            for r in raw
            if r.get("active") and r.get("socks_name")
        ]
        if not usable:
            raise RelayError("katalog relayow nie zawiera zadnego uzywalnego wpisu")
        return cls(usable)

    @classmethod
    def from_disk(cls) -> RelayCatalog:
        raw = paths.read_json(paths.relays_path())
        if not raw:
            raise RelayError(
                f"brak katalogu relayow w {paths.relays_path()}; uruchom najpierw setup.py"
            )
        return cls.from_raw(raw)

    def countries(self) -> list[str]:
        return sorted({r.country_code for r in self._relays})

    def eligible(self, country: str | None) -> list[Relay]:
        if country is None:
            return list(self._relays)
        found = [r for r in self._relays if r.country_code == country]
        if not found:
            raise UnknownCountry(
                f"brak aktywnego relaya w kraju {country!r}; "
                f"dostepne: {', '.join(self.countries())}"
            )
        return found

    def pick(
        self,
        country: str | None,
        *,
        rng: random.Random,
        exclude: str | None = None,
    ) -> Relay:
        # Sortowanie przed losowaniem: kolejnosc z API bywa zmienna, a wynik
        # przy ustalonym ziarnie ma byc powtarzalny.
        candidates = sorted(self.eligible(country), key=lambda r: r.hostname)
        if exclude is not None:
            narrowed = [r for r in candidates if r.hostname != exclude]
            # Gdy wykluczenie zabralo ostatnia opcje, lepiej oddac ten sam relay
            # niz wywalic sie bledem: rotacja w kraju z jednym serwerem to nie awaria.
            if narrowed:
                candidates = narrowed
        return rng.choice(candidates)

    def by_hostname(self, hostname: str) -> Relay | None:
        return next((r for r in self._relays if r.hostname == hostname), None)
