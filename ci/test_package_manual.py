"""Package checks using synthetic archives, without Docker or real credentials."""

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import package_manual

TAG = "a" * 40


class PackageTests(unittest.TestCase):
    def fake_command(self, *args, capture=False, omit_web=False):
        if args[0] == "git":
            Path(args[args.index("-o") + 1]).write_bytes(b"fixture release")
            return ""
        if args[:2] == ("docker", "save"):
            path = Path(args[args.index("-o") + 1])
            images = args[-2:-1] if omit_web else args[-2:]
            entries = [{"Config": "blobs/sha256/" + ("b" if i == 0 else "c") * 64, "RepoTags": [image]}
                       for i, image in enumerate(images)]
            payload = json.dumps(entries).encode()
            with tarfile.open(path, "w") as archive:
                info = tarfile.TarInfo("manifest.json")
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
            return ""
        raise AssertionError(args)

    def test_package_has_two_tags_and_a_verified_compressed_archive(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(package_manual, "command", self.fake_command):
            out = Path(temporary) / "candidate"
            package_manual.package(out, TAG)
            self.assertTrue((out / "release.tar.gz").is_file())
            self.assertTrue((out / "images.tar.gz").is_file())
            self.assertEqual(len((out / "image-ids").read_text().splitlines()), 2)

    def test_package_refuses_a_missing_image(self):
        def missing(*args, **kwargs):
            return self.fake_command(*args, omit_web=True, **kwargs)
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(package_manual, "command", missing):
            out = Path(temporary) / "candidate"
            with self.assertRaisesRegex(SystemExit, "missing a requested tag"):
                package_manual.package(out, TAG)


if __name__ == "__main__":
    unittest.main()
