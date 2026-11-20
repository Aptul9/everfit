"""Preflight checks against a temporary fixture; no production files or credentials."""

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

CI = Path(__file__).resolve().parent
CANDIDATE = "a" * 40
SAFE = "b" * 40
CURRENT = "c" * 40


class ManualPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        current = self.base / "releases" / CURRENT
        (current / "ci").mkdir(parents=True)
        (current / "ci/sqlite.sh").write_text("# fixture\n")
        (current / "image-ids").write_text("fixture\n")
        (self.base / "app").symlink_to(current, target_is_directory=True)
        (self.base / ".env").write_text("fixture\n")
        self.stage = self.base / "staging" / CANDIDATE
        (self.stage / "candidate").mkdir(parents=True)
        (self.stage / "rollback").mkdir()
        test_file = self.stage / "candidate" / "fixture"
        test_file.write_text("fixture\n")
        checksum = hashlib.sha256(test_file.read_bytes()).hexdigest()
        (self.stage / "SHA256SUMS").write_text(f"{checksum}  candidate/fixture\n")
        self.script = self.base / "manual_deploy.sh"
        self.script.write_text((CI / "manual_deploy.sh").read_text().replace("BASE=/opt/everfit", f'BASE="{self.base}"', 1))

    def run_script(self, candidate=CANDIDATE, safe=SAFE, expected=CURRENT):
        return subprocess.run(["bash", self.script, candidate, safe, expected], capture_output=True, text=True,
                              env={"PATH": os.environ["PATH"]}, timeout=20)

    def test_refuses_a_different_live_release_before_backup(self):
        result = self.run_script(expected="d" * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("live release differs", result.stderr)
        self.assertFalse((self.base / "backups").exists())
        self.assertEqual((self.base / ".env").read_text(), "fixture\n")

    def test_refuses_checksum_mismatch_before_backup(self):
        (self.stage / "candidate" / "fixture").write_text("changed\n")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bundle checksums do not match", result.stderr)
        self.assertFalse((self.base / "backups").exists())

    def test_refuses_existing_rollback_release_without_overwriting_it(self):
        existing = self.base / "releases" / SAFE
        existing.mkdir()
        (existing / "keep").write_text("user data\n")
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("backup or target release already exists", result.stderr)
        self.assertEqual((existing / "keep").read_text(), "user data\n")

    def test_refuses_invalid_or_identical_shas(self):
        for candidate, safe in (("../bad", SAFE), (CANDIDATE, CANDIDATE)):
            result = self.run_script(candidate=candidate, safe=safe)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((self.base / "backups").exists())

    def test_synthetic_bundle_preserves_sessions_and_stages_rollback(self):
        digest = "d" * 64
        def image_tar(path, tags):
            payload = json.dumps([{"Config": f"blobs/sha256/{digest}", "RepoTags": tags}]).encode()
            with tarfile.open(path, "w") as archive:
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

        def release_tar(path, entries):
            with tarfile.open(path, "w:gz") as archive:
                for name, value in entries.items():
                    payload = value.encode()
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))

        bindir = self.base / "bin"
        bindir.mkdir()
        image_tar(self.base / "current.tar", [f"everfit:{CURRENT}", f"everfit-web:{CURRENT}"])
        image_tar(self.base / "safe-app.tar", [f"everfit:{SAFE}"])
        image_tar(self.base / "safe-web.tar", [f"everfit-web:{SAFE}"])
        (bindir / "docker").write_text(
            '#!/bin/sh\ncase "$1" in\n'
            '  image) if [ "${3:-}" = --format ]; then echo 10000000; else exit 1; fi ;;\n'
            '  load) cat >/dev/null ;;\n'
            '  save) if [ "$#" -eq 3 ]; then cat "$FIXTURE/current.tar"; '
            'elif [ "${2%%:*}" = everfit ]; then cat "$FIXTURE/safe-app.tar"; '
            'else cat "$FIXTURE/safe-web.tar"; fi ;;\n'
            '  *) exit 1 ;;\nesac\n')
        (bindir / "df").write_text('#!/bin/sh\nprintf "Filesystem 1024-blocks Used Available Capacity Mounted\\nfixture 99999999 0 99999999 0%% /\\n"\n')
        for stub in bindir.iterdir():
            stub.chmod(0o700)
        current = self.base / "releases" / CURRENT
        shutil.copyfile(CI / "sqlite.sh", current / "ci/sqlite.sh")
        shutil.copyfile(CI / "image_config.py", current / "ci/image_config.py")
        (current / "image-ids").write_text("".join(f"{name}:{CURRENT} sha256:{digest}\n" for name in ("everfit", "everfit-web")))
        (self.base / ".env").write_text(
            "FIT_CODICE=fixturecode123\nFIT_PERCORSO=fixturepath1234567890123456789012345\n"
            "FIT_OIDC_ISSUER=https://id.everbright.it/application/o/everfit/\n"
            "FIT_OIDC_CLIENT_ID=everfit\nFIT_OIDC_CLIENT_" + "SECRET" + "=" + "fixture" + "value\n"
            "FIT_OWNER_EMAIL=" + "owner" + "@" + "example.invalid\n")
        original_env = (self.base / ".env").read_bytes()
        (self.base / "sslh.cfg").write_text("fixture routing\n")
        (self.base / "backups").mkdir()
        data = self.base / "data"
        data.mkdir()
        with sqlite3.connect(data / "fit.db") as db:
            db.executescript("CREATE TABLE utenti(id INTEGER); INSERT INTO utenti VALUES(1);"
                             "CREATE TABLE stato(utente INTEGER); INSERT INTO stato VALUES(1);"
                             "CREATE TABLE stato_storia(utente INTEGER); CREATE TABLE pesate(utente INTEGER);"
                             "CREATE TABLE circonferenze(utente INTEGER); CREATE TABLE pareri(utente INTEGER);"
                             "CREATE TABLE sessioni(id TEXT, impronta TEXT, utente INTEGER, tipo TEXT, da TEXT, creata REAL, vista REAL);"
                             "INSERT INTO sessioni(id) VALUES('home-key'); CREATE TABLE everid(id TEXT);"
                             "CREATE TABLE everid_sessioni(id TEXT); INSERT INTO everid_sessioni VALUES('id-token');")
        candidate = self.stage / "candidate"
        safe = self.stage / "rollback"
        release_tar(candidate / "release.tar.gz", {
            "ci/deploy.sh": f'#!/bin/bash\nset -eu\n[ "$EVERFIT_KEEP_RELEASES" = 1000000 ]\n'
                            f'[ "$EVERFIT_KEEP_ALL_BACKUPS" = 1 ]\n[ "$EVERFIT_DISALLOW_ROUTING_CHANGE" = 1 ]\n'
                            f'cp "{self.base}/environment.new" "{self.base}/.env"\n',
            "ci/rollback.sh": "#!/bin/bash\nexit 0\n",
            "ci/routing.py": "import shutil,sys\nshutil.copyfile(sys.argv[1], sys.argv[2])\n",
        })
        release_tar(safe / "release.tar.gz", {
            "ci/safe-rollback-marker": "everfit-oidc-only-no-cleanup-v1\n",
            "ci/image_config.py": (CI / "image_config.py").read_text(),
            "docker-compose.yml": "services: {}\n",
        })
        for name, sha in (("candidate", CANDIDATE), ("rollback", SAFE)):
            directory = self.stage / name
            (directory / "image-ids").write_text("".join(f"{image}:{sha} sha256:{digest}\n" for image in ("everfit", "everfit-web")))
            import gzip
            with gzip.open(directory / "images.tar.gz", "wb") as archive:
                archive.write(b"fixture image bytes")
        files = [Path(name) / filename for name in ("candidate", "rollback")
                 for filename in ("release.tar.gz", "images.tar.gz", "image-ids")]
        (self.stage / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256((self.stage / path).read_bytes()).hexdigest()}  {path.as_posix()}\n" for path in files))
        text = self.script.read_text().replace("/etc/sslh.cfg", f'"{self.base}/sslh.cfg"')
        self.script.write_text(text)
        env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FIXTURE=str(self.base))
        result = subprocess.run(["bash", self.script, CANDIDATE, SAFE, CURRENT], env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Safe rollback release:", result.stdout)
        self.assertNotIn("fixturesecret", result.stdout + result.stderr)
        self.assertEqual((self.base / ".env").read_bytes(), original_env)
        self.assertTrue((self.base / "releases" / SAFE / "image-ids").is_file())
        self.assertEqual((self.base / "previous-release").read_text().strip(), str(self.base / "releases" / SAFE))
        self.assertTrue((self.base / "backups" / ("manual-" + CANDIDATE) / "fit.db").is_file())
        with sqlite3.connect(data / "fit.db") as db:
            self.assertEqual(db.execute("SELECT id FROM sessioni").fetchall(), [("home-key",)])
            self.assertEqual(db.execute("SELECT id FROM everid_sessioni").fetchall(), [("id-token",)])
            self.assertEqual(db.execute("SELECT COUNT(*) FROM stato").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
