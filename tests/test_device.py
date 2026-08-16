import base64
import os
import pathlib
import re
import stat
import tempfile
import unittest


class KeypairTest(unittest.TestCase):
    def test_generate_keypair_shapes(self):
        from mullid.device import generate_keypair

        priv, pub = generate_keypair()
        for label, key in (("priv", priv), ("pub", pub)):
            with self.subTest(key=label):
                self.assertEqual(len(base64.b64decode(key)), 32)
                self.assertRegex(key, r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$")

    def test_generate_keypair_is_not_constant(self):
        from mullid.device import generate_keypair

        self.assertNotEqual(generate_keypair()[0], generate_keypair()[0])


class WgConfTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MULLID_HOME"] = self._tmp.name + "/.mullid"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("MULLID_HOME", None)

    def test_write_wg_conf_is_600(self):
        from mullid.device import write_wg_conf

        p = write_wg_conf(
            "cHJpdg==", "10.64.0.2/32", "fc00::2/128", "cHViaw==", "1.2.3.4:51820"
        )
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)

    def test_round_trip_through_parser(self):
        from mullid.device import write_wg_conf
        from mullid.wireproxy import parse_wg_conf

        p = write_wg_conf(
            "cHJpdg==", "10.64.0.2/32", "fc00::2/128", "cHViaw==", "1.2.3.4:51820"
        )
        wg = parse_wg_conf(p)
        self.assertEqual(wg["private_key"], "cHJpdg==")
        self.assertEqual(wg["address_v4"], "10.64.0.2/32")
        self.assertEqual(wg["peer_pubkey"], "cHViaw==")
        self.assertEqual(wg["endpoint"], "1.2.3.4:51820")


class RenderTest(unittest.TestCase):
    WG = {
        "private_key": "cHJpdg==",
        "address_v4": "10.64.0.2/32",
        "address_v6": "fc00::2/128",
        "peer_pubkey": "cHViaw==",
        "endpoint": "1.2.3.4:51820",
    }

    def test_render_has_required_sections(self):
        from mullid.wireproxy import render_wireproxy_conf

        out = render_wireproxy_conf(self.WG)
        for section in ("[Interface]", "[Peer]", "[Socks5]"):
            self.assertIn(section, out)

    def test_socks_binds_loopback_only(self):
        from mullid.wireproxy import render_wireproxy_conf

        out = render_wireproxy_conf(self.WG)
        self.assertIn("BindAddress = 127.0.0.1:1080", out)
        self.assertNotIn("0.0.0.0:", out)

    def test_allowed_ips_cover_mullvad_socks_range(self):
        # Bez trasy obejmujacej 10.124.0.0/20 proxy relayow sa nieosiagalne
        # i caly pomysl upada.
        from mullid.wireproxy import render_wireproxy_conf

        out = render_wireproxy_conf(self.WG)
        self.assertRegex(out, r"AllowedIPs\s*=\s*0\.0\.0\.0/0")

    def test_dns_is_mullvad_internal(self):
        from mullid.wireproxy import render_wireproxy_conf

        self.assertIn("DNS = 10.64.0.1", render_wireproxy_conf(self.WG))


class SecretHygieneTest(unittest.TestCase):
    def test_device_module_never_prints_secrets(self):
        # Zapora statyczna: zaden print/log w device.py nie moze brac
        # zmiennej o nazwie sugerujacej sekret.
        src = pathlib.Path("mullid/device.py").read_text()
        for m in re.finditer(r"(?:print|log\.\w+)\((.*)", src):
            arg = m.group(1)
            for word in ("priv", "token", "account_number", "secret"):
                self.assertNotIn(word, arg.lower(), f"podejrzane wypisanie: {m.group(0)}")


if __name__ == "__main__":
    unittest.main()
