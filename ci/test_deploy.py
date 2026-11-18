import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class DeploymentTests(unittest.TestCase):
    def test_script_has_its_own_input_file(self):
        workflow = (ROOT / ".github/workflows/ci-cd.yml").read_text()
        self.assertNotIn("| bash -s", workflow)
        self.assertIn("bash /opt/everfit/ci/deploy.sh", workflow)

    def test_secret_path_is_required(self):
        compose = (ROOT / "docker-compose.yml").read_text()
        self.assertIn("${FIT_PERCORSO:?", compose)
        self.assertIn("${FIT_CODICE:?", compose)

    def test_admin_header_set_only_on_secret_path(self):
        caddy = (ROOT / "Caddyfile").read_text()
        self.assertEqual(caddy.count("request_header X-Fit-Accesso ok"), 1)
        self.assertIn("request_header -X-Fit-Accesso", caddy)
        self.assertIn("handle_path /{$FIT_PERCORSO}/*", caddy)

    def test_code_baked_into_image_only_data_mounted(self):
        compose = (ROOT / "docker-compose.yml").read_text()
        self.assertIn(":/data", compose)
        self.assertNotIn("./public", compose)
        self.assertNotIn("./server", compose)
        for option in ("read_only: true", "cap_drop: [ALL]", "no-new-privileges:true"):
            self.assertEqual(compose.count(option), 2, option)
        self.assertIn("USER 10001:10001", (ROOT / "Dockerfile").read_text())


if __name__ == "__main__":
    unittest.main()
