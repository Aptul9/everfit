"""A repeated release must not replace an existing release directory."""

import os
import gzip
import io
import json
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

CI = Path(__file__).resolve().parent
TAG = "a" * 40


class DeployCollisionTests(unittest.TestCase):
    def test_existing_release_is_left_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            release = base / "releases" / TAG
            release.mkdir(parents=True)
            (release / "keep").write_text("fixture\n")
            for name in ("release.tar.gz", "images.tar.gz", "image-ids"):
                (base / name).write_text("fixture\n")
            (base / "environment.new").write_text(
                "FIT_CODICE=fixturecode123\nFIT_PERCORSO=fixturepath1234567890123456789012345\n")
            script = base / "deploy.sh"
            script.write_text((CI / "deploy.sh").read_text().replace("/opt/everfit", str(base)))
            bindir = base / "bin-stub"
            bindir.mkdir()
            install = bindir / "install"
            install.write_text('#!/bin/sh\nfor last do :; done\nmkdir -p "$last"\n')
            install.chmod(0o700)
            env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
            result = subprocess.run(["bash", script, TAG], env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to replace it", result.stderr)
            self.assertEqual((release / "keep").read_text(), "fixture\n")

    def test_routing_change_is_refused_before_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "sslh.cfg").write_text("original routing\n")
            (base / "environment.new").write_text(
                "FIT_CODICE=fixturecode123\nFIT_PERCORSO=fixturepath1234567890123456789012345\n")
            digest = "b" * 64
            (base / "image-ids").write_text("".join(
                f"{name}:{TAG} sha256:{digest}\n" for name in ("everfit", "everfit-web")))
            with gzip.open(base / "images.tar.gz", "wb") as archive:
                archive.write(b"fixture images")
            entries = {
                "ci/sqlite.sh": "# fixture\n",
                "ci/image_config.py": (CI / "image_config.py").read_text(),
                "ci/routing.py": "import pathlib,sys\npathlib.Path(sys.argv[2]).write_text('changed routing\\n')\n",
            }
            with tarfile.open(base / "release.tar.gz", "w:gz") as archive:
                for name, value in entries.items():
                    payload = value.encode()
                    info = tarfile.TarInfo(name)
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            for name in ("everfit", "everfit-web"):
                payload = json.dumps([{"Config": f"blobs/sha256/{digest}", "RepoTags": [f"{name}:{TAG}"]}]).encode()
                with tarfile.open(base / f"{name}.tar", "w") as archive:
                    info = tarfile.TarInfo("manifest.json")
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
            bindir = base / "bin-stub"
            bindir.mkdir()
            (bindir / "install").write_text('#!/bin/sh\nfor last do :; done\nmkdir -p "$last"\n')
            (bindir / "docker").write_text(
                '#!/bin/sh\ncase "$1" in load) cat >/dev/null ;; '
                'save) cat "$FIXTURE/${2%%:*}.tar" ;; compose) exit 0 ;; *) exit 1 ;; esac\n')
            (bindir / "systemctl").write_text('#!/bin/sh\ntouch "$FIXTURE/systemctl-called"\n')
            for stub in bindir.iterdir():
                stub.chmod(0o700)
            script = base / "deploy.sh"
            source = (CI / "deploy.sh").read_text().replace("/opt/everfit", str(base))
            script.write_text(source.replace("/etc/sslh.cfg", f'"{base}/sslh.cfg"'))
            env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FIXTURE=str(base),
                       EVERFIT_DISALLOW_ROUTING_CHANGE="1", EVERFIT_KEEP_ALL_BACKUPS="1")
            result = subprocess.run(["bash", script, TAG], env=env, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("refusing to alter it or restart sslh", result.stderr)
            self.assertEqual((base / "sslh.cfg").read_text(), "original routing\n")
            self.assertFalse((base / "systemctl-called").exists())


if __name__ == "__main__":
    unittest.main()
