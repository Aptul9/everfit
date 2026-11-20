import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "everid_env.py"
ISSUER = "https://id.everbright.it/application/o/everfit/"


class EverIDEnvTests(unittest.TestCase):
    def run_script(self, **values):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OIDC_", "FIT_"))}
        env.update(values)
        with tempfile.TemporaryDirectory() as scratch:
            path = Path(scratch) / "environment.new"
            path.write_text("FIT_CODICE=x\nFIT_PERCORSO=y\n")
            result = subprocess.run([sys.executable, str(SCRIPT), str(path)], env=env, capture_output=True, text=True)
            return result.returncode, path.read_text().splitlines()[2:], result.stdout + result.stderr

    def test_unconfigured_adds_nothing(self):
        self.assertEqual(self.run_script(OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID="everfit")[:2], (0, []))

    def test_configured_lines(self):
        code, lines, _ = self.run_script(OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID="everfit", OIDC_CLIENT_SECRET="abc_DEF-1",
                                         FIT_OWNER_EMAIL="Owner@Example.org", FIT_LOGIN_CODICE="0")
        self.assertEqual(code, 0)
        self.assertEqual(lines, ["FIT_OIDC_ISSUER=" + ISSUER, "FIT_OIDC_CLIENT_ID=everfit", "FIT_OIDC_CLIENT_SECRET=abc_DEF-1",
                                 "FIT_OWNER_EMAIL=owner@example.org", "FIT_LOGIN_CODICE=0"])

    def test_rejects_bad_values_without_writing(self):
        base = dict(OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID="everfit", OIDC_CLIENT_SECRET="abc")
        for change in ({"OIDC_ISSUER": "http://id.everbright.it/application/o/everfit/"}, {"OIDC_CLIENT_SECRET": "a b"},
                       {"OIDC_CLIENT_SECRET": "a'b"}, {"FIT_LOGIN_CODICE": "no"}, {"FIT_OWNER_EMAIL": "nobody"}):
            code, lines, _ = self.run_script(**{**base, **change})
            self.assertNotEqual(code, 0, change)
            self.assertEqual(lines, [], change)


if __name__ == "__main__":
    unittest.main()
