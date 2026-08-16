import os
import unittest


class BindHostTest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("MULLID_BIND", None)

    def test_defaults_to_loopback(self):
        # Uruchomienie natywne ma sie nie zmienic: bez zmiennej srodowiskowej
        # nasluch zostaje na petli zwrotnej.
        from mullid.config import bind_host

        os.environ.pop("MULLID_BIND", None)
        self.assertEqual(bind_host(), "127.0.0.1")

    def test_env_overrides(self):
        from mullid.config import bind_host

        os.environ["MULLID_BIND"] = "0.0.0.0"
        self.assertEqual(bind_host(), "0.0.0.0")

    def test_blank_env_falls_back_to_loopback(self):
        # Pusta zmienna to najczestsza literowka w skrypcie wdrozeniowym.
        # Ma dac bezpieczny domysl, a nie nasluch na wszystkim.
        from mullid.config import bind_host

        os.environ["MULLID_BIND"] = "   "
        self.assertEqual(bind_host(), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
