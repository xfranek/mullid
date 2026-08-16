import unittest

from tests.fake_socks import EchoServer, FakeSocks5Server


class SocksChainTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.echo = EchoServer()
        await self.echo.start()

    async def asyncTearDown(self):
        await self.echo.stop()

    async def test_single_hop_reaches_target(self):
        from mullid.socks import open_chain

        hop = FakeSocks5Server(
            upstream_map={("target.example", 80): (self.echo.host, self.echo.port)}
        )
        await hop.start()
        try:
            r, w = await open_chain([(hop.host, hop.port)], ("target.example", 80))
            w.write(b"ping")
            await w.drain()
            self.assertEqual(await r.readexactly(9), b"echo:ping")
            w.close()
        finally:
            await hop.stop()

    async def test_two_hop_chain_nests_correctly(self):
        # hop1 to wireproxy, hop2 to proxy relaya Mullvada.
        from mullid.socks import open_chain

        hop2 = FakeSocks5Server(
            upstream_map={("target.example", 443): (self.echo.host, self.echo.port)}
        )
        await hop2.start()
        hop1 = FakeSocks5Server(
            upstream_map={("relay.socks5.mullvad.net", 1080): (hop2.host, hop2.port)}
        )
        await hop1.start()
        try:
            r, w = await open_chain(
                [(hop1.host, hop1.port), ("relay.socks5.mullvad.net", 1080)],
                ("target.example", 443),
            )
            w.write(b"hi")
            await w.drain()
            self.assertEqual(await r.readexactly(7), b"echo:hi")
            w.close()

            self.assertEqual(hop1.requests, [("relay.socks5.mullvad.net", 1080)])
            self.assertEqual(hop2.requests, [("target.example", 443)])
        finally:
            await hop1.stop()
            await hop2.stop()

    async def test_hostname_is_sent_as_domain_not_resolved_locally(self):
        # Kluczowe dla prywatnosci: cel jedzie jako domena (ATYP 0x03).
        from mullid.socks import open_chain

        hop = FakeSocks5Server(
            upstream_map={("example.com", 80): (self.echo.host, self.echo.port)}
        )
        await hop.start()
        try:
            _r, w = await open_chain([(hop.host, hop.port)], ("example.com", 80))
            w.close()
            self.assertEqual(hop.requests, [("example.com", 80)])
        finally:
            await hop.stop()

    async def test_upstream_refusal_raises_with_code(self):
        from mullid.socks import SocksError, open_chain

        hop = FakeSocks5Server(fail_with=0x05)
        await hop.start()
        try:
            with self.assertRaises(SocksError) as ctx:
                await open_chain([(hop.host, hop.port)], ("target.example", 80))
            self.assertEqual(ctx.exception.reply_code, 0x05)
            self.assertIn("odrzuc", str(ctx.exception).lower())
        finally:
            await hop.stop()

    async def test_unreachable_first_hop_raises(self):
        from mullid.socks import SocksError, open_chain

        with self.assertRaises(SocksError):
            # Port 1 na loopbacku nie nasluchuje.
            await open_chain([("127.0.0.1", 1)], ("target.example", 80), timeout=2.0)

    async def test_long_hostname_is_rejected(self):
        from mullid.socks import SocksError, open_chain

        hop = FakeSocks5Server()
        await hop.start()
        try:
            with self.assertRaises(SocksError):
                await open_chain([(hop.host, hop.port)], ("a" * 256 + ".com", 80))
        finally:
            await hop.stop()


if __name__ == "__main__":
    unittest.main()
