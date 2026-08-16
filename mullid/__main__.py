"""Uruchamia wireproxy, proxy HTTP i control API."""

from __future__ import annotations

import asyncio
import logging

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

    store = ProfileStore()
    resolver = ProfileResolver(RelayCatalog.from_disk(), store)
    proxy = ProxyServer(resolver)
    control = ControlServer(resolver, store, supervisor.health)

    await proxy.start()
    await control.start()
    print("proxy   : http://127.0.0.1:8888   (nazwa profilu jako uzytkownik)")
    print("control : http://127.0.0.1:8889/profiles")
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
