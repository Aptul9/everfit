import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import env

CI = Path(__file__).resolve().parent
GOOD = {
    "OIDC_ISSUER": "https://id.everbright.it/application/o/everfit/",
    "OIDC_CLIENT_ID": "everfit",
    "OIDC_CLIENT_SECRET": "abcDEF123-_.~",
    "FIT_OWNER_EMAIL": "Owner@Example.com",
}


class EnvFileTests(unittest.TestCase):
    def write(self, values):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, values, clear=True):
            path = os.path.join(d, "environment.new")
            env.main(path)
            return Path(path).read_text()

    def test_required_lines(self):
        text = self.write(GOOD)
        lines = text.splitlines()
        self.assertEqual(len(lines), 5)
        self.assertIn("NUTRI_OWNER_EMAIL=owner@example.com", lines)
        self.assertFalse(any(line.startswith("CRONOMETER_") for line in lines))
        self.assertEqual(lines[-1], "FIT_DATA_DIR=/opt/everfit/coach")

    def test_optional_values(self):
        lines = self.write(GOOD | {"NUTRI_AGENT_MODEL": "claude-opus-5-5"}).splitlines()
        self.assertEqual(len(lines), 6)
        self.assertIn("NUTRI_AGENT_MODEL=claude-opus-5-5", lines)

    def test_missing_or_malformed_values_stop_the_deploy(self):
        for broken in ({"OIDC_CLIENT_SECRET": ""}, {"OIDC_ISSUER": "http://evil/"}, {"OIDC_CLIENT_SECRET": "it's"},
                       {"FIT_OWNER_EMAIL": "nobody"}, {"NUTRI_AGENT_MODEL": "x; rm -rf /"}):
            with self.subTest(broken=broken), self.assertRaises(SystemExit):
                self.write(GOOD | broken)

    def test_deploy_script_accepts_what_env_writes(self):
        """The shape checks in deploy.sh, run against the file env.py writes."""
        text = self.write(GOOD | {"NUTRI_AGENT_MODEL": "claude-opus-5-5"})
        script = (CI / "deploy.sh").read_text()
        checks = re.findall(r"^grep -Eq '([^']+)' environment\.new$", script, re.M)
        self.assertGreaterEqual(len(checks), 4)
        for pattern in checks:
            with self.subTest(pattern=pattern):
                self.assertTrue(re.search(pattern.replace("[:space:]", r"\s"), text, re.M), pattern)

    @unittest.skipUnless(os.name == "posix", "bash -n runs on the CI runner")
    def test_shell_syntax(self):
        for script in CI.glob("*.sh"):
            subprocess.run(["bash", "-n", str(script)], check=True)


if __name__ == "__main__":
    unittest.main()
