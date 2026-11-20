"""Run the Python reference for differential API tests with credential login disabled."""

import sys
from pathlib import Path
from urllib.parse import urlsplit

APP = Path(sys.argv.pop(1)).resolve()
sys.path.insert(0, str(APP / "server"))
import server  # noqa: E402

original_post = server.Fit.do_POST


def post_without_login(self):
    if urlsplit(self.path).path == "/accedi":
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()
        return
    original_post(self)


server.Fit.do_POST = post_without_login
server.main()
