"""Zamiana nazwy profilu na konkretny relay wyjsciowy."""

from __future__ import annotations

import random

from .profiles import ProfileError, ProfileSpec, ProfileStore, parse_profile
from .relays import Relay, RelayCatalog


class ProfileResolver:
    def __init__(
        self,
        catalog: RelayCatalog,
        store: ProfileStore,
        *,
        rng: random.Random | None = None,
    ):
        self._catalog = catalog
        self._store = store
        self._rng = rng or random.Random()

    def resolve(self, username: str) -> tuple[ProfileSpec, Relay]:
        spec = parse_profile(username)

        if spec.ephemeral:
            return spec, self._catalog.pick(spec.country, rng=self._rng)

        record = self._store.get(spec.name)
        if record is None:
            relay = self._catalog.pick(spec.country, rng=self._rng)
            self._store.assign(spec.name, relay.hostname, spec.country)
            self._store.touch(spec.name)
            return spec, relay

        relay = self._catalog.by_hostname(record["relay"])
        if relay is None:
            # Relay wypadl z katalogu. Trwalosc zostala zlamana nie z naszej
            # winy, ale musi to byc widoczne w /profiles, a nie przemilczane.
            relay = self._catalog.pick(record.get("country"), rng=self._rng)
            self._store.mark_reassigned(spec.name, relay.hostname)

        self._store.touch(spec.name)
        return spec, relay

    def rotate(self, name: str) -> Relay:
        record = self._store.get(name)
        if record is None:
            raise ProfileError(f"profil {name!r} nie istnieje")
        relay = self._catalog.pick(
            record.get("country"), rng=self._rng, exclude=record["relay"]
        )
        self._store.rotate(name, relay.hostname)
        return relay
