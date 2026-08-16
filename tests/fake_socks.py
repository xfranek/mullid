"""Atrapa serwera SOCKS5 — tyle protokolu, ile trzeba do testow lancucha."""

from __future__ import annotations

import asyncio


class FakeSocks5Server:
    """Przyjmuje SOCKS5 bez uwierzytelniania i laczy dalej wg upstream_map.

    requests zbiera wszystkie zadane cele, dzieki czemu test moze sprawdzic,
    ze nazwa hosta pojechala jako domena, a nie jako rozwiazany adres IP.
    """

    def __init__(self, upstream_map=None, fail_with=None):
        self.upstream_map = upstream_map or {}
        self.fail_with = fail_with
        self.requests: list[tuple[str, int]] = []
        self._server = None
        self.host = "127.0.0.1"
        self.port = 0

    async def start(self):
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            _ver, nmethods = await reader.readexactly(2)
            await reader.readexactly(nmethods)
            writer.write(b"\x05\x00")
            await writer.drain()

            _ver, _cmd, _rsv, atyp = await reader.readexactly(4)
            if atyp == 0x01:
                host = ".".join(str(b) for b in await reader.readexactly(4))
            elif atyp == 0x03:
                ln = (await reader.readexactly(1))[0]
                host = (await reader.readexactly(ln)).decode()
            else:
                raise AssertionError(f"nieobslugiwany ATYP {atyp}")
            port = int.from_bytes(await reader.readexactly(2), "big")
            self.requests.append((host, port))

            if self.fail_with is not None:
                writer.write(bytes([0x05, self.fail_with, 0x00, 0x01, 0, 0, 0, 0, 0, 0]))
                await writer.drain()
                writer.close()
                return

            dest = self.upstream_map.get((host, port))
            if dest is None:
                writer.write(bytes([0x05, 0x04, 0x00, 0x01, 0, 0, 0, 0, 0, 0]))
                await writer.drain()
                writer.close()
                return

            up_r, up_w = await asyncio.open_connection(*dest)
            writer.write(bytes([0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0]))
            await writer.drain()
            await asyncio.gather(
                _pipe(reader, up_w), _pipe(up_r, writer), return_exceptions=True
            )
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()


async def _pipe(reader, writer):
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    finally:
        writer.close()


class EchoServer:
    """Zwraca to, co dostal — koniec lancucha w testach."""

    def __init__(self):
        self._server = None
        self.host = "127.0.0.1"
        self.port = 0

    async def start(self):
        self._server = await asyncio.start_server(self._handle, self.host, 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer):
        try:
            while chunk := await reader.read(65536):
                writer.write(b"echo:" + chunk)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()
