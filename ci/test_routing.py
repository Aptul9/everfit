import unittest
from routing import ROUTE, updated_config

LIVE = '''user: "sslh";

listen:
(
    { host: "0.0.0.0"; port: "443"; }
);

protocols:
(
    { name: "ssh"; host: "127.0.0.1"; port: "22"; },
    { name: "tls"; host: "127.0.0.1"; port: "4448"; sni_hostnames: [ "push.everbright.it" ]; },
    { name: "tls"; host: "127.0.0.1"; port: "4449"; sni_hostnames: [ "flow.everbright.it" ]; },
    { name: "tls"; host: "127.0.0.1"; port: "4443"; },
    { name: "anyprot"; host: "127.0.0.1"; port: "4443"; }
);
'''


class RoutingTests(unittest.TestCase):
    def test_only_adds_new_route_and_is_idempotent(self):
        updated = updated_config(LIVE)
        self.assertEqual(updated.replace(ROUTE + "\n", "", 1), LIVE)
        self.assertLess(updated.index(ROUTE), updated.index('port: "4443"'))
        self.assertEqual(updated_config(updated), updated)

    def test_compact_format_is_accepted(self):
        compact = LIVE.replace("protocols:\n(", "protocols: (")
        self.assertIn(ROUTE, updated_config(compact))

    def test_unexpected_existing_route_is_rejected(self):
        with self.assertRaises(ValueError):
            updated_config(LIVE + ROUTE.replace("4450", "4451"))

    def test_port_already_used_is_rejected(self):
        with self.assertRaises(ValueError):
            updated_config(LIVE.replace("4449", "4450"))

    def test_unexpected_format_is_rejected(self):
        with self.assertRaises(ValueError):
            updated_config("invalid configuration")


if __name__ == "__main__":
    unittest.main()
