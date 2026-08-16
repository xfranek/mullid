import os
import random
import tempfile
import unittest

RAW = [
    {
        "hostname": "de-fra-wg-101", "country_code": "de", "city_code": "fra",
        "socks_name": "de-fra-wg-socks5-101.relays.mullvad.net", "socks_port": 1080,
        "active": True, "pubkey": "AAA=", "ipv4_addr_in": "1.1.1.1",
    },
    {
        "hostname": "de-ber-wg-002", "country_code": "de", "city_code": "ber",
        "socks_name": "de-ber-wg-socks5-002.relays.mullvad.net", "socks_port": 1080,
        "active": True, "pubkey": "BBB=", "ipv4_addr_in": "1.1.1.2",
    },
    {
        "hostname": "se-sto-wg-007", "country_code": "se", "city_code": "sto",
        "socks_name": "se-sto-wg-socks5-007.relays.mullvad.net", "socks_port": 1080,
        "active": True, "pubkey": "CCC=", "ipv4_addr_in": "1.1.1.3",
    },
    {
        "hostname": "no-osl-wg-dead", "country_code": "no", "city_code": "osl",
        "socks_name": "no-osl-wg-socks5-dead.relays.mullvad.net", "socks_port": 1080,
        "active": False, "pubkey": "DDD=", "ipv4_addr_in": "1.1.1.4",
    },
    {
        "hostname": "fi-hel-wg-nosocks", "country_code": "fi", "city_code": "hel",
        "socks_name": "", "socks_port": 1080,
        "active": True, "pubkey": "EEE=", "ipv4_addr_in": "1.1.1.5",
    },
]


class RelayCatalogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MULLID_HOME"] = self._tmp.name + "/.mullid"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("MULLID_HOME", None)

    def cat(self):
        from mullid.relays import RelayCatalog

        return RelayCatalog.from_raw(RAW)

    def test_inactive_relays_are_excluded(self):
        self.assertNotIn("no-osl-wg-dead", [r.hostname for r in self.cat().eligible(None)])

    def test_relays_without_socks_are_excluded(self):
        self.assertNotIn("fi-hel-wg-nosocks", [r.hostname for r in self.cat().eligible(None)])

    def test_country_filter(self):
        got = sorted(r.hostname for r in self.cat().eligible("de"))
        self.assertEqual(got, ["de-ber-wg-002", "de-fra-wg-101"])

    def test_unknown_country_raises(self):
        from mullid.relays import UnknownCountry

        with self.assertRaises(UnknownCountry):
            self.cat().eligible("xx")

    def test_inactive_only_country_raises_unknown(self):
        # "no" ma wylacznie nieaktywny relay, wiec z punktu widzenia doboru
        # nie istnieje i musi dac ten sam czytelny blad co literowka.
        from mullid.relays import UnknownCountry

        with self.assertRaises(UnknownCountry):
            self.cat().eligible("no")

    def test_pick_is_deterministic_for_a_seed(self):
        a = self.cat().pick(None, rng=random.Random(42)).hostname
        b = self.cat().pick(None, rng=random.Random(42)).hostname
        self.assertEqual(a, b)

    def test_pick_respects_country(self):
        r = self.cat().pick("se", rng=random.Random(1))
        self.assertEqual(r.hostname, "se-sto-wg-007")

    def test_pick_can_exclude_current_relay(self):
        for seed in range(20):
            r = self.cat().pick("de", rng=random.Random(seed), exclude="de-fra-wg-101")
            self.assertEqual(r.hostname, "de-ber-wg-002")

    def test_exclude_ignored_when_it_is_the_only_option(self):
        r = self.cat().pick("se", rng=random.Random(0), exclude="se-sto-wg-007")
        self.assertEqual(r.hostname, "se-sto-wg-007")

    def test_by_hostname(self):
        self.assertEqual(self.cat().by_hostname("se-sto-wg-007").country_code, "se")
        self.assertIsNone(self.cat().by_hostname("nope"))

    def test_countries_sorted_unique(self):
        self.assertEqual(self.cat().countries(), ["de", "se"])

    def test_save_and_load_from_disk(self):
        from mullid.relays import RelayCatalog, save_relays

        save_relays(RAW)
        self.assertEqual(RelayCatalog.from_disk().countries(), ["de", "se"])

    def test_from_disk_without_cache_raises(self):
        from mullid.relays import RelayCatalog, RelayError

        with self.assertRaises(RelayError):
            RelayCatalog.from_disk()


if __name__ == "__main__":
    unittest.main()
