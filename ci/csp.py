import base64
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app/server"))
import accesso  # noqa: E402

INLINE = re.compile(r"<script>(.*?)</script>", re.S)


def inline_hashes():
    """CSP hashes of every inline script the server sends: the app shell and the login page."""
    pages = [(ROOT / "app/public/index.html").read_text(encoding="utf-8"), accesso.pagina().decode("utf-8")]
    return sorted({"'sha256-%s'" % base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()
                   for page in pages for s in INLINE.findall(page)})


if __name__ == "__main__":
    print(" ".join(inline_hashes()))
