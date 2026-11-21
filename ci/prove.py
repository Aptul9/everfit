"""Runs the upstream test suites (app/tools/prove) with the fake AI service; every check must pass."""
import os
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
env = dict(os.environ, PYTHONIOENCODING="utf-8")


def run(*args):
    result = subprocess.run([sys.executable, *args], cwd=APP, env=env, capture_output=True, text=True, encoding="utf-8")
    return result.returncode, result.stdout + result.stderr


failed = []
fake = subprocess.Popen([sys.executable, "tools/prove/finta_gemini2.py", "8799"], cwd=APP, env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    time.sleep(1)
    code, output = run("tools/prove/prova_server.py", ".", "-")
finally:
    fake.terminate()
    fake.wait(timeout=5)
lines = output.splitlines()
passed = sum(1 for line in lines if line.startswith("ok "))
errors = [line for line in lines if line.startswith("ERRORE ")]
print("prova_server: exit %d, %d ok, %d errors" % (code, passed, len(errors)))
if code or errors or "TUTTO BENE" not in output:
    print(output)
    failed.append("prova_server")

for name in ("prova_catena", "prova_ponte", "prova_spinta"):
    code, output = run("tools/prove/%s.py" % name)
    print("%s: exit %d, %s" % (name, code, output.strip().splitlines()[-1] if output.strip() else ""))
    if code:
        print(output)
        failed.append(name)

if failed:
    sys.exit("FAILED: %s" % failed)
print("Test suites: PASS")
