"""Command line: `nutri serve`, `nutri sync`."""

import argparse
import logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="nutri")
    sub = parser.add_subparsers(dest="cmd", required=True)
    serve = sub.add_parser("serve", help="run the web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8096)
    sync = sub.add_parser("sync", help="mirror Cronometer once and push the outbox")
    sync.add_argument("--days", type=int, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.cmd == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips="*")
    elif args.cmd == "sync":
        from . import config
        from .api import App

        cfg = config.load()
        app = App(cfg)
        print(app.syncer.run(cfg.today(), args.days))


if __name__ == "__main__":
    main()
