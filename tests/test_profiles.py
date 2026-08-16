import os
import tempfile
import unittest


class ParseProfileTest(unittest.TestCase):
    def test_plain_name_is_sticky_without_country(self):
        from mullid.profiles import parse_profile

        spec = parse_profile("alice")
        self.assertEqual(spec.name, "alice")
        self.assertIsNone(spec.country)
        self.assertFalse(spec.ephemeral)

    def test_country_suffix_is_split_off(self):
        from mullid.profiles import parse_profile

        spec = parse_profile("alice-de")
        self.assertEqual(spec.name, "alice")
        self.assertEqual(spec.country, "de")
        self.assertFalse(spec.ephemeral)

    def test_random_is_ephemeral(self):
        from mullid.profiles import parse_profile

        spec = parse_profile("random")
        self.assertTrue(spec.ephemeral)
        self.assertIsNone(spec.country)

    def test_random_with_country_is_ephemeral(self):
        from mullid.profiles import parse_profile

        spec = parse_profile("random-jp")
        self.assertTrue(spec.ephemeral)
        self.assertEqual(spec.country, "jp")

    def test_underscore_allowed_in_name(self):
        from mullid.profiles import parse_profile

        self.assertEqual(parse_profile("work_acct").name, "work_acct")

    def test_country_code_is_lowercased(self):
        from mullid.profiles import parse_profile

        self.assertEqual(parse_profile("Alice-DE").country, "de")

    def test_rejects_empty(self):
        from mullid.profiles import ProfileError, parse_profile

        with self.assertRaises(ProfileError):
            parse_profile("")

    def test_rejects_illegal_characters(self):
        from mullid.profiles import ProfileError, parse_profile

        for bad in ["al ice", "alice/../x", "alice.de", "-de", "alice-"]:
            with self.subTest(bad=bad), self.assertRaises(ProfileError):
                parse_profile(bad)

    def test_rejects_three_letter_suffix_as_country(self):
        # "alice-ger" nie jest kodem ISO; myslnik jest dozwolony wylacznie
        # jako separator dwuliterowego kodu kraju.
        from mullid.profiles import ProfileError, parse_profile

        with self.assertRaises(ProfileError):
            parse_profile("alice-ger")


class ProfileStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MULLID_HOME"] = self._tmp.name + "/.mullid"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("MULLID_HOME", None)

    def test_unknown_profile_is_none(self):
        from mullid.profiles import ProfileStore

        self.assertIsNone(ProfileStore().get("alice"))

    def test_assign_then_get(self):
        from mullid.profiles import ProfileStore

        store = ProfileStore()
        store.assign("alice", "de-fra-wg-101", "de")
        rec = store.get("alice")
        self.assertEqual(rec["relay"], "de-fra-wg-101")
        self.assertEqual(rec["country"], "de")
        self.assertIsNotNone(rec["created"])

    def test_assignment_survives_new_store_instance(self):
        # To jest wlasnie "sticky przezywa restart": nowy obiekt czyta z dysku.
        from mullid.profiles import ProfileStore

        ProfileStore().assign("alice", "de-fra-wg-101", "de")
        self.assertEqual(ProfileStore().get("alice")["relay"], "de-fra-wg-101")

    def test_rotate_changes_relay_and_stamps(self):
        from mullid.profiles import ProfileStore

        store = ProfileStore()
        store.assign("alice", "de-fra-wg-101", "de")
        rec = store.rotate("alice", "de-ber-wg-002")
        self.assertEqual(rec["relay"], "de-ber-wg-002")
        self.assertIsNotNone(rec["rotated_at"])

    def test_rotate_unknown_profile_raises(self):
        from mullid.profiles import ProfileError, ProfileStore

        with self.assertRaises(ProfileError):
            ProfileStore().rotate("nobody", "de-fra-wg-101")

    def test_mark_reassigned_records_broken_stickiness(self):
        from mullid.profiles import ProfileStore

        store = ProfileStore()
        store.assign("alice", "de-fra-wg-101", "de")
        rec = store.mark_reassigned("alice", "de-ber-wg-002")
        self.assertEqual(rec["relay"], "de-ber-wg-002")
        self.assertIsNotNone(rec["reassigned_at"])

    def test_touch_sets_last_used(self):
        from mullid.profiles import ProfileStore

        store = ProfileStore()
        store.assign("alice", "de-fra-wg-101", "de")
        self.assertIsNone(store.get("alice")["last_used"])
        store.touch("alice")
        self.assertIsNotNone(store.get("alice")["last_used"])


if __name__ == "__main__":
    unittest.main()
