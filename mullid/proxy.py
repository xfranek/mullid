"""Proxy HTTP na 127.0.0.1:8888 — nazwa profilu jedzie w Proxy-Authorization."""

from __future__ import annotations

import asyncio
import base64
import logging

from .profiles import ProfileError
from .relays import RelayError
from .resolver import ProfileResolver
from .socks import SocksError, open_chain

log = logging.getLogger("mullid.proxy")

_HOP_BY_HOP = (b"proxy-authorization", b"proxy-connection")


class ProxyServer:
    def __init__(
        self,
        resolver: ProfileResolver,
        *,
        upstream: tuple[str, int] = ("127.0.0.1", 1080),
        host: str = "127.0.0.1",
        port: int = 8888,
    ):
        self._resolver = resolver
        self._upstream = upstream
        self._host = host
        self._requested_port = port
        self._server: asyncio.Server | None = None
        self.port = port

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._handle, self._host, self._requested_port
        )
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("proxy nasluchuje na %s:%s", self._host, self.port)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
        except (
            asyncio.IncompleteReadError,
            asyncio.TimeoutError,
            asyncio.LimitOverrunError,
        ):
            writer.close()
            return

        try:
            lines = head.split(b"\r\n")
            method, target, version = lines[0].split(b" ", 2)
            headers = [ln for ln in lines[1:] if ln]

            username = _extract_profile(headers)
            if username is None:
                await _reply(
                    writer,
                    407,
                    "Podaj nazwe profilu jako uzytkownika w Proxy-Authorization, np. "
                    "curl -x http://alice:x@127.0.0.1:8888 ...",
                )
                return

            try:
                _spec, relay = self._resolver.resolve(username)
            except (ProfileError, RelayError) as e:
                await _reply(writer, 407, str(e))
                return

            host, port = _split_target(method, target)
            hops = [self._upstream, (relay.socks_name, relay.socks_port)]

            try:
                up_r, up_w = await open_chain(hops, (host, port))
            except SocksError as e:
                await _reply(
                    writer,
                    502,
                    f"nie udalo sie zestawic wyjscia przez {relay.hostname}: {e}. "
                    "Sprawdz, czy wireproxy dziala — GET http://127.0.0.1:8889/health",
                )
                return

            if method == b"CONNECT":
                writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                await writer.drain()
            else:
                up_w.write(_rewrite_request(method, target, version, headers))
                await up_w.drain()

            await _splice(reader, writer, up_r, up_w)
        except Exception:
            log.exception("blad obslugi zadania")
            writer.close()


def _extract_profile(headers: list[bytes]) -> str | None:
    for h in headers:
        name, _, value = h.partition(b":")
        if name.strip().lower() != b"proxy-authorization":
            continue
        scheme, _, blob = value.strip().partition(b" ")
        if scheme.lower() != b"basic":
            return None
        try:
            decoded = base64.b64decode(blob, validate=True).decode("utf-8", "replace")
        except Exception:
            return None
        return decoded.split(":", 1)[0]
    return None


def _split_target(method: bytes, target: bytes) -> tuple[str, int]:
    if method == b"CONNECT":
        host, _, port = target.decode().rpartition(":")
        return host, int(port)
    rest = target.decode().split("://", 1)[-1]
    authority = rest.split("/", 1)[0]
    if ":" in authority:
        host, _, port = authority.rpartition(":")
        return host, int(port)
    return authority, 80


def _rewrite_request(
    method: bytes, target: bytes, version: bytes, headers: list[bytes]
) -> bytes:
    rest = target.decode().split("://", 1)[-1]
    _authority, slash, path = rest.partition("/")
    origin_form = ("/" + path) if slash else "/"
    kept = [h for h in headers if h.partition(b":")[0].strip().lower() not in _HOP_BY_HOP]
    return b"\r\n".join(
        [method + b" " + origin_form.encode() + b" " + version, *kept, b"", b""]
    )


async def _reply(writer, status: int, message: str) -> None:
    reason = {407: "Proxy Authentication Required", 502: "Bad Gateway"}.get(status, "Error")
    body = message.encode("utf-8")
    head = [
        f"HTTP/1.1 {status} {reason}".encode(),
        b"Content-Type: text/plain; charset=utf-8",
        f"Content-Length: {len(body)}".encode(),
    ]
    if status == 407:
        head.append(b'Proxy-Authenticate: Basic realm="mullid"')
    head += [b"Connection: close", b"", b""]
    writer.write(b"\r\n".join(head) + body)
    try:
        await writer.drain()
    finally:
        writer.close()


async def _splice(c_r, c_w, u_r, u_w) -> None:
    async def pump(src, dst):
        try:
            while chunk := await src.read(65536):
                dst.write(chunk)
                await dst.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            dst.close()

    await asyncio.gather(pump(c_r, u_w), pump(u_r, c_w), return_exceptions=True)
