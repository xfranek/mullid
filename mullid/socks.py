"""Klient SOCKS5 i lancuch skokow.

Lancuch dziala tak: laczymy sie z pierwszym skokiem zwyklym TCP, a kazdy
kolejny adres zamawiamy poleceniem CONNECT na strumieniu juz zestawionym.
Po udanym CONNECT strumien jest przezroczysty, wiec kolejne powitanie
SOCKS5 trafia juz do nastepnego serwera w lancuchu.
"""

from __future__ import annotations

import asyncio

SOCKS5_ERRORS = {
    0x01: "ogolna awaria serwera SOCKS",
    0x02: "polaczenie niedozwolone przez regule",
    0x03: "siec nieosiagalna",
    0x04: "host nieosiagalny",
    0x05: "polaczenie odrzucone przez cel",
    0x06: "TTL wygasl",
    0x07: "polecenie nieobslugiwane",
    0x08: "typ adresu nieobslugiwany",
}


class SocksError(RuntimeError):
    def __init__(self, message: str, reply_code: int | None = None):
        super().__init__(message)
        self.reply_code = reply_code


def _encode_host(host: str) -> bytes:
    try:
        encoded = host.encode("ascii") if host.isascii() else host.encode("idna")
    except UnicodeError as e:
        raise SocksError(f"nie mozna zakodowac nazwy hosta ({e})") from None
    if len(encoded) > 255:
        raise SocksError(f"nazwa hosta dluzsza niz 255 bajtow: {len(encoded)}")
    return encoded


async def socks5_connect(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    host: str,
    port: int,
) -> None:
    is_ip = _is_ipv4(host)
    encoded = None if is_ip else _encode_host(host)

    writer.write(b"\x05\x01\x00")  # VER=5, jedna metoda, brak uwierzytelniania
    await writer.drain()
    try:
        ver, method = await reader.readexactly(2)
    except asyncio.IncompleteReadError as e:
        raise SocksError("skok SOCKS5 zerwal polaczenie w trakcie powitania") from e
    if ver != 0x05:
        raise SocksError(f"skok odpowiedzial wersja {ver}, oczekiwano 5")
    if method != 0x00:
        raise SocksError(
            f"skok zada metody uwierzytelniania {method:#04x}, obslugujemy tylko brak"
        )

    if is_ip:
        addr = b"\x01" + bytes(int(p) for p in host.split("."))
    else:
        addr = b"\x03" + bytes([len(encoded)]) + encoded
    writer.write(b"\x05\x01\x00" + addr + port.to_bytes(2, "big"))
    await writer.drain()

    try:
        _ver, rep, _rsv, atyp = await reader.readexactly(4)
    except asyncio.IncompleteReadError as e:
        raise SocksError("skok SOCKS5 zerwal polaczenie w trakcie CONNECT") from e
    if rep != 0x00:
        raise SocksError(
            f"{host}:{port} — {SOCKS5_ERRORS.get(rep, f'nieznany kod {rep:#04x}')}",
            reply_code=rep,
        )

    # Adres zwiazany trzeba wyczytac do konca, inaczej zostanie w buforze
    # i zaklamie pierwsze bajty wlasciwego strumienia.
    if atyp == 0x01:
        await reader.readexactly(4)
    elif atyp == 0x03:
        ln = (await reader.readexactly(1))[0]
        await reader.readexactly(ln)
    elif atyp == 0x04:
        await reader.readexactly(16)
    else:
        raise SocksError(f"skok zwrocil nieznany ATYP {atyp}")
    await reader.readexactly(2)


async def open_chain(
    hops: list[tuple[str, int]],
    target: tuple[str, int],
    *,
    timeout: float = 20.0,
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    if not hops:
        raise SocksError("lancuch musi miec co najmniej jeden skok")

    first_host, first_port = hops[0]
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(first_host, first_port), timeout
        )
    except (OSError, asyncio.TimeoutError) as e:
        raise SocksError(f"nie mozna polaczyc sie z {first_host}:{first_port} ({e})") from e

    try:
        for host, port in [*hops[1:], target]:
            await asyncio.wait_for(socks5_connect(reader, writer, host, port), timeout)
    except asyncio.TimeoutError as e:
        writer.close()
        raise SocksError(f"lancuch SOCKS5 nie odpowiedzial w {timeout}s") from e
    except BaseException:
        writer.close()
        raise
    return reader, writer


def _is_ipv4(host: str) -> bool:
    parts = host.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)
