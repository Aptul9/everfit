"""Prova cio' che serve all'app Android (Trusted Web Activity) dal server con FIT_CODICE acceso:
/.well-known/assetlinks.json letto senza cookie come JSON, e il manifest di chi e' entrato che tiene ?apk=<n>.

    python tools/prove/prova_android.py <cartella app>
"""
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

APP = sys.argv[1]
PORTA = 8792
CODICE = "11112222"
cartella = tempfile.mkdtemp(prefix="fit-android-")
radice = os.path.join(cartella, "public")
shutil.copytree(os.path.join(APP, "public"), radice)

# manifest con query e un # da buttare: il server deve tenere la prima e rimpiazzare il secondo
percorso_manifest = os.path.join(radice, "manifest.webmanifest")
with open(percorso_manifest, encoding="utf-8") as f:
    manifest = json.load(f)
manifest["start_url"] = "./?apk=7#vecchio"
with open(percorso_manifest, "w", encoding="utf-8") as f:
    json.dump(manifest, f)

percorso_legami = os.path.join(radice, ".well-known", "assetlinks.json")
if not os.path.isfile(percorso_legami):   # prima che ci sia quello vero, uno di prova con la stessa forma
    os.makedirs(os.path.dirname(percorso_legami), exist_ok=True)
    with open(percorso_legami, "w", encoding="utf-8") as f:
        json.dump([{"relation": ["delegate_permission/common.handle_all_urls"],
                    "target": {"namespace": "android_app", "package_name": "prova",
                               "sha256_cert_fingerprints": ["00" + ":00" * 31]}}], f)

ambiente = dict(os.environ, FIT_CODICE=CODICE, FIT_NOME="Admin", PYTHONIOENCODING="utf-8")
server = subprocess.Popen([sys.executable, "-u", os.path.join(APP, "server", "server.py"), "--root", radice,
                           "--data", cartella, "--host", "127.0.0.1", "--port", str(PORTA)],
                          env=ambiente, stdout=open(os.path.join(cartella, "server.log"), "w", encoding="utf-8"), stderr=subprocess.STDOUT)
sbagli = []


def chiedi(metodo, percorso, cookie=None, modulo=None):
    c = http.client.HTTPConnection("127.0.0.1", PORTA, timeout=20)
    h, dati = {}, None
    if modulo is not None:
        dati = modulo.encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        h["Cookie"] = "fitk=" + cookie
    c.request(metodo, percorso, body=dati, headers=h)
    r = c.getresponse()
    testo = r.read()
    fitk = next((v.split(";")[0].split("=", 1)[1] for k, v in r.getheaders()
                 if k.lower() == "set-cookie" and v.startswith("fitk=")), None)
    c.close()
    return r.status, testo, fitk, dict(r.getheaders())


def controlla(nome, vero, dettaglio=""):
    print(("ok   " if vero else "ERRORE ") + nome + (" -> " + str(dettaglio) if dettaglio and not vero else ""))
    if not vero:
        sbagli.append(nome)


try:
    for _ in range(50):
        if server.poll() is not None:
            break
        try:
            if chiedi("GET", "/api/health")[0] == 200:
                break
        except OSError:
            time.sleep(0.1)

    s, t, _, h = chiedi("GET", "/.well-known/assetlinks.json")
    try:
        legami = json.loads(t)
    except ValueError:
        legami = None
    controlla("senza cookie: assetlinks 200", s == 200, s)
    controlla("senza cookie: assetlinks application/json", h.get("Content-Type", "").startswith("application/json"), h.get("Content-Type"))
    controlla("assetlinks: lista con un android_app", isinstance(legami, list) and any(
        (x.get("target") or {}).get("namespace") == "android_app" for x in legami), t[:200])
    controlla("senza cookie: assetlinks HEAD 200", chiedi("HEAD", "/.well-known/assetlinks.json")[0] == 200)
    controlla("senza cookie: assetlinks POST no", chiedi("POST", "/.well-known/assetlinks.json", modulo="x=1")[0] in (401, 405))
    controlla("senza cookie: altro in .well-known 401", chiedi("GET", "/.well-known/security.txt")[0] == 401)
    controlla("senza cookie: assetlinks con giri strani 401", chiedi("GET", "/.well-known/../js/main.js")[0] == 401)
    controlla("senza cookie: js ancora 401", chiedi("GET", "/js/main.js")[0] == 401)

    s, _, capo, _ = chiedi("POST", "/accedi", modulo="utente=&codice=" + CODICE)
    controlla("capo entra", s == 303 and capo, s)
    s, t, _, _ = chiedi("GET", "/manifest.webmanifest", cookie=capo)
    start = json.loads(t).get("start_url", "") if s == 200 else ""
    controlla("manifest da dentro: tiene ?apk=7", start.startswith("./?apk=7#k="), start)
    controlla("manifest da dentro: un solo #, senza il vecchio", start.count("#") == 1 and "vecchio" not in start, start)
    s, t, _, _ = chiedi("GET", "/manifest.webmanifest")
    controlla("manifest senza cookie: com'e' scritto", s == 200 and json.loads(t).get("start_url") == "./?apk=7#vecchio", t[:200])
finally:
    server.terminate()
    server.wait(timeout=5)
    shutil.rmtree(cartella, ignore_errors=True)

print("\nERRORI: %s" % sbagli if sbagli else "\nTUTTO BENE")
sys.exit(1 if sbagli else 0)
