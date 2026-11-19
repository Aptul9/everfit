import re
import unittest
from pathlib import Path

import csp

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github/workflows/ci-cd.yml").read_text()
COMPOSE = (ROOT / "docker-compose.yml").read_text()
CADDY = (ROOT / "Caddyfile").read_text()


class DeploymentTests(unittest.TestCase):
    def test_script_has_its_own_input_file(self):
        self.assertNotIn("| bash -s", WORKFLOW)
        self.assertIn("bash /opt/everfit/ci/deploy.sh", WORKFLOW)

    def test_deploy_needs_the_pull_request_guard(self):
        self.assertIn("needs: [check, guard]", WORKFLOW)
        self.assertIn("merged_at != null", WORKFLOW)

    def test_vm_never_builds_or_pulls(self):
        self.assertNotIn("build:", COMPOSE)
        self.assertEqual(COMPOSE.count("pull_policy: never"), 2)
        deploy = (ROOT / "ci/deploy.sh").read_text()
        self.assertNotIn("compose build", deploy)
        self.assertIn("docker load", deploy)

    def test_base_images_pinned_by_digest(self):
        for name in ("Dockerfile", "Dockerfile.caddy", "ci/Dockerfile.python"):
            first = (ROOT / name).read_text().splitlines()[0]
            self.assertRegex(first, r"^FROM [a-z0-9.:/-]+@sha256:[a-f0-9]{64}(?: AS build)?$", name)

    def test_actions_pinned_by_sha(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            for use in re.findall(r"uses: (\S+)", path.read_text()):
                self.assertRegex(use, r"@[a-f0-9]{40}$", "%s in %s" % (use, path.name))

    def test_secrets_are_required(self):
        self.assertIn("${FIT_PERCORSO:?", COMPOSE)
        self.assertIn("${FIT_CODICE:?", COMPOSE)

    def test_admin_header_set_only_on_secret_path(self):
        self.assertEqual(CADDY.count("request_header X-Fit-Accesso ok"), 1)
        self.assertIn("request_header -X-Fit-Accesso", CADDY)
        self.assertIn("handle_path /{$FIT_PERCORSO}/*", CADDY)

    def test_code_baked_into_image_only_data_mounted(self):
        self.assertIn(":/data", COMPOSE)
        self.assertNotIn("./public", COMPOSE)
        self.assertNotIn("./server", COMPOSE)
        for option in ("read_only: true", "cap_drop: [ALL]", "no-new-privileges:true"):
            self.assertEqual(COMPOSE.count(option), 2, option)
        for name in ("Dockerfile", "Dockerfile.caddy"):
            text = (ROOT / name).read_text()
            self.assertIn("USER 10001:10001", text, name)
            self.assertIn("HEALTHCHECK", text, name)

    def test_app_image_runtime(self):
        image = (ROOT / "Dockerfile").read_text().split("FROM scratch\n", 1)[1]
        self.assertIn('ENTRYPOINT ["/fit"]', image)
        self.assertIn('CMD ["/fit", "--healthcheck"]', image)
        self.assertNotIn("python", image)
        self.assertNotIn("COPY app/server ", image)

    def test_csp_allows_exactly_the_inline_scripts_served(self):
        policy = re.search(r'Content-Security-Policy "([^"]+)"', CADDY).group(1)
        script_src = re.search(r"script-src ([^;]+)", policy).group(1).split()
        self.assertEqual(sorted(s for s in script_src if s.startswith("'sha256-")), csp.inline_hashes())
        self.assertNotIn("'unsafe-inline'", script_src)
        self.assertIn('Strict-Transport-Security "max-age=31536000"', CADDY)
        self.assertNotIn("preload", CADDY)

    def test_csp_lets_the_android_shell_check_for_updates(self):
        # js/apk.js reads EverFit-Android.json from the download page; nothing else leaves the origin
        policy = re.search(r'Content-Security-Policy "([^"]+)"', CADDY).group(1)
        self.assertEqual(re.search(r"connect-src ([^;]+)", policy).group(1).split(), ["'self'", "https://servizi.everbright.it"])
        self.assertIn("https://servizi.everbright.it/download/EverFit-Android.json", (ROOT / "app/public/js/apk.js").read_text())


if __name__ == "__main__":
    unittest.main()
