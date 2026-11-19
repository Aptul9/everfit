import base64
import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INLINE = re.compile(r"<script>(.*?)</script>", re.S)


def inline_hashes():
    """CSP hashes of every inline script the server sends: the app shell and the login page."""
    pages = [(ROOT / p).read_text(encoding="utf-8")
             for p in ("app/public/index.html", "app/server-rs/testi/pagina.html")]
    return sorted({"'sha256-%s'" % base64.b64encode(hashlib.sha256(s.encode("utf-8")).digest()).decode()
                   for page in pages for s in INLINE.findall(page)})


if __name__ == "__main__":
    print(" ".join(inline_hashes()))
