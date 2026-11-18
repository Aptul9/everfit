"""Prints "<tag> sha256:<config digest>" for every image in a docker save archive's manifest.json (read from stdin).
The config digest covers every layer (rootfs diff_ids), and unlike the image ID it is the same on the classic and the
containerd image store: CI and the VM compare it to prove the deployed image is the tested one."""
import json
import re
import sys

for entry in json.load(sys.stdin):
    digest = re.search(r"([a-f0-9]{64})", entry["Config"]).group(1)
    for tag in entry.get("RepoTags") or []:
        print(tag, "sha256:" + digest)
