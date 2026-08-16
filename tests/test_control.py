import asyncio
import json
import os
import random
import tempfile
import unittest

from tests.test_relays import RAW


class ControlTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MULLID_HOME"] = self._tmp.name + "/.mullid"

        from mullid.control import ControlServer
        from mullid.profiles import ProfileStore
        from mullid.relays import RelayCatalog
        from mullid.resolver import ProfileResolver

        self.store = ProfileStore()
        self.resolver = ProfileResolver(
            RelayCatalog.from_raw(RAW), self.store, rng=random.Random(5)
        )
        self.health = {"wireproxy_running": True, "last_handshake_age_s": 12}
        self.server = ControlServer(self.resolver, self.store, lambda: self.health, port=0)
        await self.server.start()

    async def asyncTearDown(self):
        await self.server.stop()
        self._tmp.cleanup()
        os.environ.pop("MULLID_HOME", None)

    async def request(self, method: str, path: str):
        r, w = await asyncio.open_connection("127.0.0.1", self.server.port)
        w.write(f"{method} {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n".encode())
        await w.drain()
        raw = await r.read()
        w.close()
        head, _, body = raw.partition(b"\r\n\r\n")
        status = int(head.split(b" ")[1])
        return status, (json.loads(body) if body else None)

    async def test_profiles_empty(self):
        status, body = await self.request("GET", "/profiles")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"profiles": []})

    async def test_profiles_lists_assignment(self):
        self.resolver.resolve("alice-de")
        status, body = await self.request("GET", "/profiles")
        self.assertEqual(status, 200)
        names = [p["name"] for p in body["profiles"]]
        self.assertEqual(names, ["alice"])
        self.assertEqual(body["profiles"][0]["country"], "de")
        self.assertTrue(body["profiles"][0]["relay"].startswith("de-"))

    async def test_rotate_changes_relay(self):
        self.resolver.resolve("alice-de")
        before = self.store.get("alice")["relay"]
        status, body = await self.request("POST", "/profiles/alice/rotate")
        self.assertEqual(status, 200)
        self.assertNotEqual(body["relay"], before)
        self.assertEqual(self.store.get("alice")["relay"], body["relay"])

    async def test_rotate_unknown_profile_404(self):
        status, body = await self.request("POST", "/profiles/nobody/rotate")
        self.assertEqual(status, 404)
        self.assertIn("nie istnieje", body["error"])

    async def test_health_passthrough(self):
        status, body = await self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["wireproxy_running"])
        self.assertEqual(body["last_handshake_age_s"], 12)

    async def test_unknown_route_404(self):
        status, _ = await self.request("GET", "/nope")
        self.assertEqual(status, 404)

    async def test_wrong_method_405(self):
        status, _ = await self.request("GET", "/profiles/alice/rotate")
        self.assertEqual(status, 405)

    async def test_no_secret_material_in_any_response(self):
        # Twarda zapora: control API nie ma prawa oddac niczego z wg.conf.
        self.resolver.resolve("alice")
        for path in ("/profiles", "/health"):
            _status, body = await self.request("GET", path)
            blob = json.dumps(body).lower()
            for forbidden in ("privatekey", "private_key", "access_token", "account"):
                self.assertNotIn(forbidden, blob)


if __name__ == "__main__":
    unittest.main()
