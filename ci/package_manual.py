"""Package two already-tested local image pairs and their committed release files, without secrets."""

import argparse
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHA = re.compile(r"[a-f0-9]{40}")


def command(*args, capture=False):
    result = subprocess.run(args, cwd=ROOT, check=True, capture_output=capture)
    return result.stdout.decode().strip() if capture else ""


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def package(directory, sha):
    directory.mkdir()
    archive = directory / "release.tar.gz"
    command("git", "-c", "core.autocrlf=false", "archive", "--format=tar.gz", "-o", str(archive),
            sha, "docker-compose.yml", "ci")
    raw = directory / "images.tar"
    images = [f"everfit:{sha}", f"everfit-web:{sha}"]
    command("docker", "save", "-o", str(raw), *images)
    with tarfile.open(raw, "r") as bundle:
        manifest = json.load(bundle.extractfile("manifest.json"))
    found = {}
    for item in manifest:
        match = re.search(r"([a-f0-9]{64})", item["Config"])
        if not match:
            raise SystemExit("Image archive has an invalid config digest")
        for tag in item.get("RepoTags") or []:
            if tag in images:
                if tag in found:
                    raise SystemExit("Duplicate image tag in archive")
                found[tag] = match.group(1)
    if set(found) != set(images):
        raise SystemExit("Image archive is missing a requested tag")
    (directory / "image-ids").write_text("".join(f"{tag} sha256:{found[tag]}\n" for tag in images),
                                         encoding="ascii", newline="\n")
    with raw.open("rb") as source, (directory / "images.tar.gz").open("wb") as target:
        with gzip.GzipFile(filename="", fileobj=target, mode="wb", mtime=0) as compressed:
            shutil.copyfileobj(source, compressed)
    with gzip.open(directory / "images.tar.gz", "rb") as compressed:
        compressed_digest = hashlib.file_digest(compressed, "sha256").hexdigest()
    if compressed_digest != digest(raw):
        raise SystemExit("Compressed archive differs from the original")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate")
    parser.add_argument("rollback")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if not SHA.fullmatch(args.candidate) or not SHA.fullmatch(args.rollback) or args.candidate == args.rollback:
        raise SystemExit("Candidate and rollback must be different 40-character commit SHAs")
    if command("git", "rev-parse", "HEAD", capture=True) != args.candidate:
        raise SystemExit("Candidate is not the current checkout")
    if command("git", "status", "--porcelain", capture=True):
        raise SystemExit("Worktree is not clean")
    for sha in (args.candidate, args.rollback):
        command("git", "cat-file", "-e", f"{sha}^{{commit}}")
    args.output.mkdir(parents=True, exist_ok=False)
    package(args.output / "candidate", args.candidate)
    package(args.output / "rollback", args.rollback)
    files = [Path(name) / file for name in ("candidate", "rollback")
             for file in ("release.tar.gz", "images.tar.gz", "image-ids")]
    (args.output / "SHA256SUMS").write_text("".join(f"{digest(args.output / file)}  {file.as_posix()}\n" for file in files),
                                            encoding="ascii", newline="\n")
    print("Candidate:", args.candidate)
    print("Safe rollback:", args.rollback)
    print("Bundle:", args.output)
    print("Six checksums written. Uncompressed image archives retained locally.")


if __name__ == "__main__":
    main()
