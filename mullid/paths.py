"""Lokalizacje plikow stanu i bezpieczny zapis.

Zapis idzie zawsze przez plik tymczasowy i os.replace, zeby przerwany
zapis nie zostawil obcietego state.json. Plik tymczasowy powstaje w tym
samym katalogu co docelowy, bo os.replace jest atomowe tylko w obrebie
jednego systemu plikow.
"""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path

log = logging.getLogger("mullid.paths")

_DEFAULT_HOME = Path.home() / ".mullid"


def mullid_dir() -> Path:
    d = Path(os.environ.get("MULLID_HOME", _DEFAULT_HOME))
    d.mkdir(parents=True, exist_ok=True)
    try:
        d.chmod(0o700)
    except PermissionError:
        # Katalog bywa wolumenem zamontowanym z hosta do kontenera — wtedy
        # chmod jest niedozwolony, a uprawnienia pochodza z hosta. Nie
        # przerywamy startu, ale nie przemilczamy zbyt szerokich uprawnien.
        mode = stat.S_IMODE(d.stat().st_mode)
        if mode & 0o077:
            log.warning(
                "katalog stanu %s ma uprawnienia %s i nie da sie ich zawezic",
                d,
                oct(mode),
            )
    return d


def state_path() -> Path:
    return mullid_dir() / "state.json"


def relays_path() -> Path:
    return mullid_dir() / "relays.json"


def wg_conf_path() -> Path:
    return mullid_dir() / "wg.conf"


def wireproxy_conf_path() -> Path:
    return mullid_dir() / "wireproxy.conf"


def wireproxy_bin_path() -> Path:
    # W obrazie kontenera binarka jest linuksowa i lezy poza ~/.mullid,
    # ktory montujemy z hosta razem z buildem darwin.
    override = os.environ.get("MULLID_WIREPROXY_BIN", "").strip()
    if override:
        return Path(override)
    return mullid_dir() / "bin" / "wireproxy"


def write_json_atomic(path: Path, data: object, *, secret: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Serializacja przed dotknieciem dysku: blad typu nie moze uszkodzic
    # pliku, ktory juz tam lezy.
    payload = json.dumps(data, indent=2, sort_keys=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.chmod(0o600 if secret else 0o644)
    os.replace(tmp, path)


def read_json(path: Path, default: object = None) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))
