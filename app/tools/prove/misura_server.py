"""Compare Linux RSS and request latency for the Python and Rust servers."""

from concurrent.futures import ThreadPoolExecutor
import http.client
import math
from pathlib import Path
import shutil
from statistics import median
import sys
import tempfile
import threading
import time

from prova_differenziale import ADMIN, APP, HOST, request, server


def rss(pid):
    status = Path(f"/proc/{pid}/status").read_text()
    return int(next(line.split()[1] for line in status.splitlines() if line.startswith("VmRSS:")))


def sample(port, path, count, start):
    connection = http.client.HTTPConnection(HOST, port, timeout=5)
    samples = []
    try:
        start.wait(timeout=5)
        for _ in range(count):
            before = time.perf_counter_ns()
            connection.request("GET", path, headers=ADMIN)
            response = connection.getresponse()
            response.read()
            assert response.status == 200
            samples.append((time.perf_counter_ns() - before) / 1e6)
    finally:
        connection.close()
    return samples


def main():
    python = [sys.executable, str(APP / "server/server.py")]
    rust = [str(Path(sys.argv[1]).resolve())]
    with tempfile.TemporaryDirectory() as work:
        work = Path(work)
        public = shutil.copytree(APP / "public", work / "public")
        for name, command in (("Python", python), ("Rust", rust)):
            with server(command, public, work / name, with_process=True) as (port, pid):
                assert request(port, "PUT", "/api/state", b'{"di":1,"updatedAt":1}', ADMIN)[0] == 200
                print(f"{name}: idle {rss(pid)} KiB", flush=True)
                for path in ("/api/health", "/js/main.js", "/api/state/versione"):
                    start = threading.Barrier(9)
                    with ThreadPoolExecutor(max_workers=8) as pool:
                        jobs = [pool.submit(sample, port, path, 100, start) for _ in range(8)]
                        start.wait(timeout=5)
                        peak = rss(pid)
                        while not all(job.done() for job in jobs):
                            peak = max(peak, rss(pid))
                            time.sleep(0.005)
                    times = sorted(t for job in jobs for t in job.result())
                    print(f"{path}: peak {peak} KiB, p50 {median(times):.3f} ms, "
                          f"p95 {times[math.ceil(len(times) * 0.95) - 1]:.3f} ms", flush=True)


if __name__ == "__main__":
    main()
