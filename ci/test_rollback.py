import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


CI = Path(__file__).resolve().parent
TAG = "a" * 40
DIGEST = "b" * 64


class RollbackPreflight(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.release = self.base / "releases" / TAG
        (self.release / "ci").mkdir(parents=True)
        shutil.copyfile(CI / "image_config.py", self.release / "ci/image_config.py")
        (self.release / "docker-compose.yml").write_text("services: {}\n")
        (self.base / ".env").touch()
        (self.base / "previous-release").write_text(f"{self.release}\n")
        self.ids = self.release / "image-ids"
        self.ids.write_text("".join(f"{image}:{TAG} sha256:{DIGEST}\n" for image in ("everfit", "everfit-web")))
        # Retained Python releases have the manifest parser but no sqlite.sh.
        self.script = self.base / "rollback.sh"
        self.script.write_text((CI / "rollback.sh").read_text().replace(
            "BASE=/opt/everfit", 'BASE="$(dirname "$0")"', 1))
        bindir = self.base / "bin"
        bindir.mkdir()
        for image in ("everfit", "everfit-web"):
            payload = json.dumps([{
                "Config": f"blobs/sha256/{DIGEST}",
                "RepoTags": [f"{image}:{TAG}"],
            }]).encode()
            with tarfile.open(self.base / f"{image}.tar", "w") as archive:
                manifest = tarfile.TarInfo("manifest.json")
                manifest.size = len(payload)
                archive.addfile(manifest, io.BytesIO(payload))
        (bindir / "docker").write_text(
            '#!/bin/sh\n'
            'case "$1" in\n'
            '  save) cat "$ROLLBACK_FIXTURE/${2%%:*}.tar" ;;\n'
            '  compose) touch "$ROLLBACK_FIXTURE/compose-called" ;;\n'
            '  *) exit 1 ;;\n'
            'esac\n'
        )
        (bindir / "curl").write_text('#!/bin/sh\nprintf \'{"ok":true}\\n\'\n')
        for stub in bindir.iterdir():
            stub.chmod(0o700)
        self.env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", ROLLBACK_FIXTURE=str(self.base))

    def rollback(self):
        return subprocess.run(["bash", self.script, "previous"], env=self.env, capture_output=True, text=True)

    def test_retained_python_release_uses_archive_config(self):
        result = self.rollback()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("matches the retained release"), 2)
        self.assertEqual((self.base / "app").resolve(), self.release)

    def test_mismatched_config_stops_before_compose(self):
        self.ids.write_text(self.ids.read_text().replace(DIGEST, "c" * 64, 1))
        result = self.rollback()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"everfit:{TAG} config mismatch: expected sha256:", result.stderr)
        self.assertFalse((self.base / "compose-called").exists())

    def test_missing_image_ids_reports_error(self):
        self.ids.unlink()
        result = self.rollback()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("image digest list missing or empty", result.stderr)

    def test_explicit_release_uses_same_digest_preflight(self):
        result = subprocess.run(["bash", self.script, "release", TAG], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("matches the retained release"), 2)
        self.assertEqual((self.base / "app").resolve(), self.release)

    def test_explicit_release_rejects_invalid_sha(self):
        result = subprocess.run(["bash", self.script, "release", "../outside"], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("release requires a 40-character SHA", result.stderr)
        self.assertFalse((self.base / "compose-called").exists())
