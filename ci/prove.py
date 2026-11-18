"""Runs the upstream test suites. prova_server.py has three AI checks that fail upstream too (2026-11-15):
the tests were not updated when the chat moved to Gemini's light model. Only those three are tolerated."""
import os
import subprocess
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
KNOWN = {
    "livelli: le istruzioni di base sono molto piu' corte",
    "modello principale muto: dopo l'attesa risponde quello di riserva",
    "dopo la prova risponde di nuovo Gemini",
}
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
errors = {line[len("ERRORE "):].split(" -> ")[0] for line in output.splitlines() if line.startswith("ERRORE ")}
passed = sum(1 for line in output.splitlines() if line.startswith("ok "))
print("prova_server: %d ok, known upstream failures: %s" % (passed, sorted(errors & KNOWN)))
if errors - KNOWN or "Traceback" in output or "registro del server" not in output or passed < 200:
    print(output)
    failed.append("prova_server: %s" % sorted(errors - KNOWN))

for name in ("prova_catena", "prova_ponte", "prova_spinta"):
    code, output = run("tools/prove/%s.py" % name)
    print("%s: exit %d, %s" % (name, code, output.strip().splitlines()[-1] if output.strip() else ""))
    if code:
        print(output)
        failed.append(name)

if failed:
    sys.exit("FAILED: %s" % failed)
print("Test suites: PASS")
