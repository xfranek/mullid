import os
import stat
import tempfile
import unittest


class PathsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["MULLID_HOME"] = self._tmp.name + "/.mullid"

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("MULLID_HOME", None)

    def test_mullid_dir_is_created_private(self):
        from mullid import paths

        d = paths.mullid_dir()
        self.assertTrue(d.is_dir())
        mode = stat.S_IMODE(d.stat().st_mode)
        self.assertEqual(mode, 0o700, f"katalog stanu musi byc 700, jest {oct(mode)}")

    def test_write_json_atomic_round_trip(self):
        from mullid import paths

        target = paths.state_path()
        paths.write_json_atomic(target, {"a": 1})
        self.assertEqual(paths.read_json(target), {"a": 1})

    def test_write_json_atomic_leaves_no_tmp_file(self):
        from mullid import paths

        target = paths.state_path()
        paths.write_json_atomic(target, {"a": 1})
        leftovers = [p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_secret_files_are_600(self):
        from mullid import paths

        target = paths.mullid_dir() / "secret.json"
        paths.write_json_atomic(target, {"k": "v"}, secret=True)
        mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(mode, 0o600, f"plik z sekretem musi byc 600, jest {oct(mode)}")

    def test_read_json_missing_returns_default(self):
        from mullid import paths

        self.assertEqual(paths.read_json(paths.state_path(), default={}), {})

    def test_existing_file_is_not_truncated_when_write_fails(self):
        from mullid import paths

        target = paths.state_path()
        paths.write_json_atomic(target, {"good": True})

        class Unserialisable:
            pass

        with self.assertRaises(TypeError):
            paths.write_json_atomic(target, {"bad": Unserialisable()})
        self.assertEqual(paths.read_json(target), {"good": True})


if __name__ == "__main__":
    unittest.main()
