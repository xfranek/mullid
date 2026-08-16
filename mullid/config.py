"""Ustawienia wdrozeniowe czytane ze srodowiska.

Osobno od paths.py, ktore odpowiada za lokalizacje na dysku. Tutaj lada
to, co zalezy od sposobu uruchomienia — natywnie na hoscie czy w kontenerze.
"""

from __future__ import annotations

import os

LOOPBACK = "127.0.0.1"


def bind_host() -> str:
    """Adres, na ktorym nasluchuja proxy i control API.

    Domyslnie petla zwrotna. W kontenerze musi byc 0.0.0.0, bo inaczej
    uslugi sa nieosiagalne spoza namespace'u — wystawieniem na zewnatrz
    steruje wtedy publikacja portow, nie ten adres.

    Pusta lub bialoznakowa wartosc traktowana jest jak brak: literowka
    w skrypcie wdrozeniowym ma dac bezpieczny domysl, nie nasluch na wszystkim.
    """
    return os.environ.get("MULLID_BIND", "").strip() or LOOPBACK
