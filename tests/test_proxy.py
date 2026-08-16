import asyncio
import base64
import os
import random
import tempfile
import unittest

from tests.fake_socks import EchoServer, FakeSocks5Server
from tests.test_relays import RAW


def auth(username: str) -> bytes:
    return base64.b64encode(f"{username}:x".encode())


class ProxyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MULLID_HOME"] = self._tmp.name + "/.mullid"

        from mullid.profiles import ProfileStore
        from mullid.proxy import ProxyServer
        from mullid.relays import RelayCatalog
        from mullid.resolver import ProfileResolver

        self.echo = EchoServer()
        await self.echo.start()

        # Drugi stopien: atrapa udajaca proxy relaya, ktore laczy do echo.
        self.exit_hop = FakeSocks5Server(
            upstream_map={("target.example", 80): (self.echo.host, self.echo.port)}
        )
        await self.exit_hop.start()

        # Pierwszy stopien: atrapa udajaca wireproxy — kazdy socks_name
        # z katalogu prowadzi do drugiego stopnia.
        self.relay_hop = FakeSocks5Server(
            upstream_map={
                (r["socks_name"], r["socks_port"]): (self.exit_hop.host, self.exit_hop.port)
                for r in RAW
                if r["socks_name"]
            }
        )
        await self.relay_hop.start()

        self.store = ProfileStore()
        self.resolver = ProfileResolver(
            RelayCatalog.from_raw(RAW), self.store, rng=random.Random(7)
        )
        self.server = ProxyServer(
            self.resolver, upstream=(self.relay_hop.host, self.relay_hop.port), port=0
        )
        await self.server.start()

    async def asyncTearDown(self):
        await self.server.stop()
        await self.relay_hop.stop()
        await self.exit_hop.stop()
        await self.echo.stop()
        self._tmp.cleanup()
        os.environ.pop("MULLID_HOME", None)

    async def connect(self):
        return await asyncio.open_connection("127.0.0.1", self.server.port)

    async def do_connect(self, username: str, target: bytes = b"target.example:80"):
        r, w = await self.connect()
        w.write(
            b"CONNECT " + target + b" HTTP/1.1\r\n"
            b"Host: " + target + b"\r\n"
            b"Proxy-Authorization: Basic " + auth(username) + b"\r\n\r\n"
        )
        await w.drain()
        status = await r.readline()
        while (await r.readline()) not in (b"\r\n", b""):
            pass
        return r, w, status

    async def test_connect_tunnels_bytes_end_to_end(self):
        r, w, status = await self.do_connect("alice")
        self.assertIn(b"200", status)
        w.write(b"ping")
        await w.drain()
        self.assertEqual(await r.readexactly(9), b"echo:ping")
        w.close()

    async def test_missing_auth_returns_407(self):
        r, w = await self.connect()
        w.write(b"CONNECT target.example:80 HTTP/1.1\r\nHost: target.example:80\r\n\r\n")
        await w.drain()
        self.assertIn(b"407", await r.readline())
        w.close()

    async def test_bad_profile_name_returns_407(self):
        _r, w, status = await self.do_connect("al ice")
        self.assertIn(b"407", status)
        w.close()

    async def test_unknown_country_returns_407(self):
        _r, w, status = await self.do_connect("alice-xx")
        self.assertIn(b"407", status)
        w.close()

    async def test_sticky_profile_keeps_same_relay_across_requests(self):
        _r1, w1, _ = await self.do_connect("alice")
        w1.close()
        first = self.store.get("alice")["relay"]
        _r2, w2, _ = await self.do_connect("alice")
        w2.close()
        self.assertEqual(self.store.get("alice")["relay"], first)

    async def test_sticky_profile_survives_resolver_restart(self):
        import random as _random

        from mullid.relays import RelayCatalog
        from mullid.resolver import ProfileResolver

        _r, w, _ = await self.do_connect("alice")
        w.close()
        first = self.store.get("alice")["relay"]

        fresh = ProfileResolver(
            RelayCatalog.from_raw(RAW), self.store, rng=_random.Random(999)
        )
        _spec, relay = fresh.resolve("alice")
        self.assertEqual(relay.hostname, first)

    async def test_country_pinned_profile_uses_that_country(self):
        _r, w, _ = await self.do_connect("bob-se")
        w.close()
        self.assertEqual(self.store.get("bob")["relay"], "se-sto-wg-007")
        self.assertEqual(self.store.get("bob")["country"], "se")

    async def test_random_profile_is_not_persisted(self):
        _r, w, _ = await self.do_connect("random")
        w.close()
        self.assertIsNone(self.store.get("random"))

    async def test_target_hostname_reaches_exit_hop_as_domain(self):
        _r, w, _ = await self.do_connect("alice")
        w.close()
        self.assertEqual(self.exit_hop.requests[-1], ("target.example", 80))

    async def test_first_hop_is_the_relay_socks_name(self):
        _r, w, _ = await self.do_connect("bob-se")
        w.close()
        self.assertEqual(
            self.relay_hop.requests[-1],
            ("se-sto-wg-socks5-007.relays.mullvad.net", 1080),
        )

    async def test_absolute_uri_get_is_forwarded(self):
        r, w = await self.connect()
        w.write(
            b"GET http://target.example/hello HTTP/1.1\r\n"
            b"Host: target.example\r\n"
            b"Proxy-Authorization: Basic " + auth("alice") + b"\r\n"
            b"Proxy-Connection: keep-alive\r\n\r\n"
        )
        await w.drain()
        # Echo odsyla to, co dostal: sprawdzamy przepisanie na postac origin-form
        # oraz usuniecie naglowkow warstwy proxy.
        data = await r.readexactly(len(b"echo:GET /hello HTTP/1.1\r\n"))
        self.assertEqual(data, b"echo:GET /hello HTTP/1.1\r\n")
        rest = await r.read(4096)
        self.assertNotIn(b"Proxy-Authorization", rest)
        self.assertNotIn(b"Proxy-Connection", rest)
        w.close()

    async def test_dead_upstream_returns_502_not_hang(self):
        from mullid.proxy import ProxyServer

        broken = ProxyServer(self.resolver, upstream=("127.0.0.1", 1), port=0)
        await broken.start()
        try:
            r, w = await asyncio.open_connection("127.0.0.1", broken.port)
            w.write(
                b"CONNECT target.example:80 HTTP/1.1\r\n"
                b"Proxy-Authorization: Basic " + auth("alice") + b"\r\n\r\n"
            )
            await w.drain()
            status = await asyncio.wait_for(r.readline(), timeout=10)
            self.assertIn(b"502", status)
            body = await r.read(4096)
            self.assertIn(b"wireproxy", body.lower())
            w.close()
        finally:
            await broken.stop()

    async def test_reassignment_when_stored_relay_vanishes(self):
        from mullid.relays import RelayCatalog
        from mullid.resolver import ProfileResolver

        self.store.assign("ghost", "relay-ktory-znikl", None)
        resolver = ProfileResolver(
            RelayCatalog.from_raw(RAW), self.store, rng=random.Random(3)
        )
        _spec, relay = resolver.resolve("ghost")
        self.assertNotEqual(relay.hostname, "relay-ktory-znikl")
        self.assertIsNotNone(self.store.get("ghost")["reassigned_at"])


if __name__ == "__main__":
    unittest.main()
