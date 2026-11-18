import argparse
import re
from pathlib import Path

NAME = "fit.everbright.it"
PORT = "4450"
ROUTE = '    { name: "tls"; host: "127.0.0.1"; port: "%s"; sni_hostnames: [ "%s" ]; },' % (PORT, NAME)
OPEN = re.compile(r"^protocols:\s*\(\n", re.M)


def updated_config(content):
    existing = [line for line in content.splitlines() if '"%s"' % NAME in line]
    if existing:
        if len(existing) != 1 or existing[0].strip() != ROUTE.strip():
            raise ValueError("Existing EverFit routing differs; no configuration changed")
        return content
    if '"%s"' % PORT in content:
        raise ValueError("Port %s already routed elsewhere; no configuration changed" % PORT)
    matches = list(OPEN.finditer(content))
    if len(matches) != 1:
        raise ValueError("Unexpected sslh configuration; no configuration changed")
    # Right after the opening of the list: above every catch-all route, since the first match wins.
    end = matches[0].end()
    return content[:end] + ROUTE + "\n" + content[end:]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    args.destination.write_text(updated_config(args.source.read_text()))
