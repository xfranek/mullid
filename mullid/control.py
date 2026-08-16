"""Control API na 127.0.0.1:8889.

Bez uwierzytelniania i swiadomie: nasluch jest wylacznie na petli zwrotnej,
a procesy tego uzytkownika i tak czytaja ~/.mullid. Odpowiedzi nie zawieraja
zadnego materialu z wg.conf.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

from .profiles import ProfileError, ProfileStore
from .relays import RelayError
from .resolver import ProfileResolver

log = logging.getLogger("mullid.control")


class ControlServer:
    def __init__(
        self,
        resolver: ProfileResolver,
        store: ProfileStore,
        health: Callable[[], dict],
        *,
        host: str = "127.0.0.1",
        port: int = 8889,
    ):
        self._resolver = resolver
        self._store = store
        self._health = health
        self._host = host
        self._requested_port = port
        self._server: asyncio.Server | None = None
        self.port = port

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, self._host, self._requested_port
        )
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("control API nasluchuje na %s:%s", self._host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=15)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError):
            writer.close()
            return
        try:
            method, path, _ = head.split(b"\r\n", 1)[0].split(b" ", 2)
            status, body = self._route(method.decode(), path.decode())
        except Exception as e:
            log.exception("blad control API")
            status, body = 500, {"error": str(e)}
        _write_json(writer, status, body)
        await writer.drain()
        writer.close()

    def _route(self, method: str, path: str) -> tuple[int, dict]:
        if path == "/profiles":
            if method != "GET":
                return 405, {"error": "uzyj GET"}
            return 200, {"profiles": self._list_profiles()}

        if path == "/health":
            if method != "GET":
                return 405, {"error": "uzyj GET"}
            return 200, self._health()

        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "profiles" and parts[2] == "rotate":
            if method != "POST":
                return 405, {"error": "uzyj POST"}
            try:
                relay = self._resolver.rotate(parts[1])
            except ProfileError as e:
                return 404, {"error": str(e)}
            except RelayError as e:
                return 409, {"error": str(e)}
            return 200, {
                "name": parts[1],
                "relay": relay.hostname,
                "country": relay.country_code,
                "city": relay.city_code,
            }

        return 404, {"error": f"nieznana trasa {path}"}

    def _list_profiles(self) -> list[dict]:
        out = []
        for name, rec in sorted(self._store.all().items()):
            out.append(
                {
                    "name": name,
                    **{
                        k: rec.get(k)
                        for k in (
                            "relay",
                            "country",
                            "created",
                            "last_used",
                            "rotated_at",
                            "reassigned_at",
                        )
                    },
                }
            )
        return out


def _write_json(writer, status: int, body: dict) -> None:
    reason = {
        200: "OK",
        404: "Not Found",
        405: "Method Not Allowed",
        409: "Conflict",
        500: "Internal Server Error",
    }.get(status, "Error")
    payload = json.dumps(body, indent=2).encode("utf-8")
    writer.write(
        b"\r\n".join(
            [
                f"HTTP/1.1 {status} {reason}".encode(),
                b"Content-Type: application/json; charset=utf-8",
                f"Content-Length: {len(payload)}".encode(),
                b"Connection: close",
                b"",
                b"",
            ]
        )
        + payload
    )
