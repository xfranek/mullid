"""Uruchamia wireproxy, proxy HTTP i control API."""

from __future__ import annotations

import asyncio
import logging

from .config import bind_host
from .control import ControlServer
from .profiles import ProfileStore
from .proxy import ProxyServer
from .relays import RelayCatalog
from .resolver import ProfileResolver
from .wireproxy import WireproxySupervisor


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    supervisor = WireproxySupervisor()
    supervisor.start()
    await asyncio.sleep(2)  # handshake WireGuard

    host = bind_host()
    store = ProfileStore()
    resolver = ProfileResolver(RelayCatalog.from_disk(), store)
    proxy = ProxyServer(resolver, host=host)
    control = ControlServer(resolver, store, supervisor.health, host=host)

    await proxy.start()
    await control.start()
    print(f"proxy   : http://{host}:8888   (nazwa profilu jako uzytkownik)")
    print(f"control : http://{host}:8889/profiles")
    if host != "127.0.0.1":
        print(
            "UWAGA: nasluch poza petla zwrotna, a proxy nie sprawdza hasla — "
            "kazdy, kto siegnie tego portu, wyjdzie przez twoje konto Mullvad."
        )
    try:
        await asyncio.Event().wait()
    finally:
        await proxy.stop()
        await control.stop()
        supervisor.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
