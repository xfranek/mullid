"""Gramatyka nazw profili i trwale przypisania profil -> relay."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import paths

EPHEMERAL_NAME = "random"

# Nazwa nie zawiera myslnika, wiec myslnik jednoznacznie oddziela kod kraju.
# Dzieki temu "alice-de" nie jest dwuznaczne, a "alice-ger" po prostu nie pasuje.
_PROFILE_RE = re.compile(r"^([a-z0-9_]+)(?:-([a-z]{2}))?$")


class ProfileError(ValueError):
    """Nazwa profilu jest niepoprawna albo profil nie istnieje."""


@dataclass(frozen=True)
class ProfileSpec:
    name: str
    country: str | None
    ephemeral: bool


def parse_profile(username: str) -> ProfileSpec:
    m = _PROFILE_RE.match((username or "").strip().lower())
    if not m:
        raise ProfileError(
            f"niepoprawna nazwa profilu {username!r}; "
            "oczekiwano [a-z0-9_]+ z opcjonalnym sufiksem -<kod kraju>, "
            "np. alice albo alice-de"
        )
    name, country = m.group(1), m.group(2)
    return ProfileSpec(name=name, country=country, ephemeral=(name == EPHEMERAL_NAME))


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ProfileStore:
    """Przypisania profil -> relay trzymane w state.json.

    Kazda mutacja zapisuje caly plik atomowo. Plik jest maly (dziesiatki
    profili), wiec nie ma powodu komplikowac tego zapisem przyrostowym.
    """

    def __init__(self, path: Path | None = None):
        self._path = path or paths.state_path()

    def _load(self) -> dict[str, dict]:
        return dict(paths.read_json(self._path, default={}) or {})

    def _save(self, data: dict[str, dict]) -> None:
        paths.write_json_atomic(self._path, data)

    def all(self) -> dict[str, dict]:
        return self._load()

    def get(self, name: str) -> dict | None:
        return self._load().get(name)

    def assign(self, name: str, relay: str, country: str | None) -> dict:
        data = self._load()
        data[name] = {
            "relay": relay,
            "country": country,
            "created": _now(),
            "last_used": None,
            "rotated_at": None,
            "reassigned_at": None,
        }
        self._save(data)
        return data[name]

    def _mutate(self, name: str, **fields) -> dict:
        data = self._load()
        if name not in data:
            raise ProfileError(f"profil {name!r} nie istnieje")
        data[name].update(fields)
        self._save(data)
        return data[name]

    def touch(self, name: str) -> None:
        self._mutate(name, last_used=_now())

    def rotate(self, name: str, relay: str) -> dict:
        return self._mutate(name, relay=relay, rotated_at=_now())

    def mark_reassigned(self, name: str, relay: str) -> dict:
        return self._mutate(name, relay=relay, reassigned_at=_now())
