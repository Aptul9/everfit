"""Prova il server con gli account: parte da una copia del database di prima (un solo proprietario),
lo fa migrare, e controlla accessi, separazione dei dati, persone, manifest e service worker.

    python prova_server.py <cartella app> <database di partenza o "-">
"""
import http.client
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

APP, PARTENZA = sys.argv[1], sys.argv[2]
PORTA = 8791
CODICE, VECCHIO = "11112222", "vecchiocookie0123456789"
cartella = tempfile.mkdtemp(prefix="fit-prova-")
if PARTENZA != "-":
    shutil.copy(PARTENZA, os.path.join(cartella, "fit.db"))
    db = sqlite3.connect(os.path.join(cartella, "fit.db"))
    print("prima:", {t: db.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] for t in ("stato", "stato_storia", "pesate", "circonferenze")})
    print("colonne stato prima:", [r[1] for r in db.execute("PRAGMA table_info(stato)")])
    db.close()

ambiente = dict(os.environ, FIT_CODICE=CODICE, FIT_COOKIE=VECCHIO, FIT_NOME="Admin", PYTHONIOENCODING="utf-8",
                FIT_GEMINI_URL=os.environ.get("FIT_GEMINI_URL", "http://127.0.0.1:8799/v1beta/models/%s:generateContent"),
                FIT_MISTRAL_URL=os.environ.get("FIT_MISTRAL_URL", "http://127.0.0.1:8799/v1/chat/completions"),
                FIT_ATTESA_ASSISTENTE="2", FIT_LOCALE_URL="http://127.0.0.1:8799", FIT_SPINTA_PROVA="http://127.0.0.1:8799/spinta/",
                FIT_DOMANDE_ORA="500")   # le prove fanno piu' di sessanta domande con lo stesso account
# FIT_SERVER: il comando di un altro server da provare con le stesse richieste (il binario Rust); senza, quello Python
comando = shlex.split(os.environ["FIT_SERVER"]) if os.environ.get("FIT_SERVER") else [sys.executable, "-u", os.path.join(APP, "server", "server.py")]
server = subprocess.Popen(comando + ["--root", os.path.join(APP, "public"),
                           "--data", cartella, "--host", "127.0.0.1", "--port", str(PORTA)],
                          env=ambiente, stdout=open(os.path.join(cartella, "server.log"), "w", encoding="utf-8"), stderr=subprocess.STDOUT)
sbagli = []


def chiedi(metodo, percorso, corpo=None, cookie=None, intestazioni=None, modulo=None):
    c = http.client.HTTPConnection("127.0.0.1", PORTA, timeout=20)
    h = dict(intestazioni or {})
    dati = None
    if corpo is not None:
        dati = json.dumps(corpo).encode()
        h["Content-Type"] = "application/json"
    if modulo is not None:
        dati = modulo.encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        h["Cookie"] = "fitk=" + cookie
    c.request(metodo, percorso, body=dati, headers=h)
    r = c.getresponse()
    testo = r.read()
    biscotti = [v for k, v in r.getheaders() if k.lower() == "set-cookie"]
    fitk = next((b.split(";")[0].split("=", 1)[1] for b in biscotti if b.startswith("fitk=")), None)
    try:
        j = json.loads(testo)
    except ValueError:
        j = None
    c.close()
    return r.status, j, testo, fitk, dict(r.getheaders())


def controlla(nome, vero, dettaglio=""):
    print(("ok   " if vero else "ERRORE ") + nome + (" -> " + str(dettaglio) if dettaglio and not vero else ""))
    if not vero:
        sbagli.append(nome)


try:
    for _ in range(50):
        try:
            if chiedi("GET", "/api/health")[0] == 200:
                break
        except OSError:
            time.sleep(0.1)

    # ---- chi non e' entrato
    s, j, t, _, _ = chiedi("GET", "/")
    controlla("senza cookie: pagina del codice (401)", s == 401 and b"Entra con il tuo nome utente" in t, s)
    controlla("pagina del codice: chiede nome utente e password", b'name="utente"' in t and b'name="password"' in t)
    controlla("pagina del codice: immagini di avvio", t.count(b"apple-touch-startup-image") == 13, t.count(b"apple-touch-startup-image"))
    controlla("senza cookie: api 401", chiedi("GET", "/api/state")[0] == 401)
    controlla("senza cookie: icona visibile", chiedi("GET", "/icons/icon-192.png")[0] == 200)
    s, j, t, _, _ = chiedi("GET", "/manifest.webmanifest")
    controlla("senza cookie: manifest generico", s == 200 and j["start_url"] == "./", j)
    controlla("senza cookie: js non visibile", chiedi("GET", "/js/main.js")[0] == 401)
    controlla("codice sbagliato: 401", chiedi("POST", "/accedi", modulo="utente=&password=00000000")[0] == 401)

    # ---- il capo entra con il suo codice
    s, j, t, capo, h = chiedi("POST", "/accedi", modulo="utente=&password=1111+2222")
    controlla("capo: entra con il solo codice, come prima (303 + cookie)", s == 303 and capo and h.get("Location") == "/", (s, capo, h))
    controlla("capo: entra anche con nome utente e codice", chiedi("POST", "/accedi", modulo="utente=Admin&password=11112222")[0] == 303)
    controlla("capo: nome utente giusto e password sbagliata", chiedi("POST", "/accedi", modulo="utente=admin&password=sbagliata1")[0] == 401)
    controlla("nome utente che non esiste", chiedi("POST", "/accedi", modulo="utente=nessuno&password=11112222")[0] == 401)
    s, io, *_ = chiedi("GET", "/api/io", cookie=capo)
    controlla("capo: /api/io", s == 200 and io["id"] == 1 and io["capo"] and io["nome"] == "Admin" and io["utente"] == "admin" and io["bilancia"], io)
    s, stato, *_ = chiedi("GET", "/api/state", cookie=capo)
    s2, misure, *_ = chiedi("GET", "/api/misure", cookie=capo)
    print("     stato del capo dopo la migrazione: %d chiavi, pesate %d, circonferenze %d" % (len(stato), len(misure["pesate"]), len(misure["circonferenze"])))
    if PARTENZA != "-":
        controlla("capo: ha ritrovato i dati di prima", bool(stato) and len(misure["pesate"]) > 0, (len(stato), len(misure["pesate"])))
    # vecchio cookie e percorso segreto valgono come capo
    controlla("vecchio cookie = capo", chiedi("GET", "/api/io", cookie=VECCHIO)[1]["id"] == 1)
    controlla("percorso segreto = capo", chiedi("GET", "/api/io", intestazioni={"X-Fit-Accesso": "ok"})[1]["id"] == 1)
    controlla("cookie inventato: fuori", chiedi("GET", "/api/io", cookie="pippo")[0] == 401)

    # ---- persone
    PW = "prova-anna.2026"
    controlla("persona senza password: rifiutata", chiedi("POST", "/api/persone", corpo={"nome": "Anna", "utente": "anna"}, cookie=capo)[0] == 400)
    controlla("password corta: rifiutata", chiedi("POST", "/api/persone", corpo={"nome": "Anna", "utente": "anna", "password": "corta"}, cookie=capo)[0] == 400)
    controlla("nome utente strano: rifiutato", chiedi("POST", "/api/persone", corpo={"nome": "Anna", "utente": "an na!", "password": PW}, cookie=capo)[0] == 400)
    s, anna, *_ = chiedi("POST", "/api/persone", corpo={"nome": "  Anna <b> ", "utente": "Anna", "password": PW}, cookie=capo)
    controlla("crea persona", s == 200 and anna["nome"] == "Anna b" and anna["utente"] == "anna" and "password" not in anna, anna)
    controlla("stesso nome utente due volte: rifiutato", chiedi("POST", "/api/persone", corpo={"nome": "Altra", "utente": "anna", "password": PW}, cookie=capo)[0] == 400)
    s, j, *_ = chiedi("GET", "/api/persone", cookie=capo)
    controlla("elenco persone", s == 200 and [p["nome"] for p in j["persone"]] == ["Admin", "Anna b"] and "password" not in j["persone"][1] and "codice" not in j["persone"][1], j)
    print("     piani in attesa di un account:", j["attese"])
    # ---- chi ha il piano pronto ma non ancora l'account
    attese = [a["utente"] for a in j["attese"]]
    controlla("in attesa: test", {"test"} <= set(attese), attese)
    controlla("capo: /api/io dice quanti account mancano", chiedi("GET", "/api/io", cookie=capo)[1].get("attese") == len(attese), chiedi("GET", "/api/io", cookie=capo)[1])
    s, _, t, *_ = chiedi("POST", "/accedi", modulo="utente=Test&password=una-password-qualsiasi")
    controlla("account in attesa: 401 con la spiegazione", s == 401 and "non è ancora attivo".encode() in t and b"Admin" in t, (s, t[-900:-600]))
    s, j2, *_ = chiedi("POST", "/accedi", modulo="utente=test&password=una-password-qualsiasi", intestazioni={"Accept": "application/json"})
    controlla("account in attesa: lo dice anche a uno script", s == 401 and "attivo" in (j2 or {}).get("errore", ""), j2)
    s, _, t, *_ = chiedi("POST", "/accedi", modulo="utente=nessuno&password=una-password-qualsiasi")
    controlla("nome utente sconosciuto: nessuna spiegazione in piu'", s == 401 and b"sbagliati" in t and "attivo".encode() not in t)
    PW_T = "prova-test.2026"
    s, di_prova, *_ = chiedi("POST", "/api/persone", corpo={"nome": "Test", "utente": "test", "password": PW_T}, cookie=capo)
    controlla("creo l'account in attesa", s == 200 and di_prova["utente"] == "test", di_prova)
    controlla("capo: un account in meno da attivare", chiedi("GET", "/api/io", cookie=capo)[1].get("attese") == len(attese) - 1)
    s, _, t, *_ = chiedi("POST", "/accedi", modulo="utente=test&password=sbagliata-2026")
    controlla("account creato: password sbagliata, messaggio normale", s == 401 and b"sbagliati" in t and "attivo".encode() not in t)
    s, _, _, cookie_test, _ = chiedi("POST", "/accedi", modulo="utente=test&password=" + PW_T)
    io_test = chiedi("GET", "/api/io", cookie=cookie_test)[1]
    controlla("account creato: entra, ha il suo piano, non vede le attese", s == 303 and io_test["piano"] and not io_test["capo"] and io_test.get("attese") == 0, io_test)
    controlla("il suo piano e' quello scritto per lui", bool(chiedi("GET", "/api/piano", cookie=cookie_test)[1].get("settimana")))
    controlla("tolgo l'account di prova", chiedi("DELETE", "/api/persone/%d" % di_prova["id"], cookie=capo)[0] == 200)
    controlla("Anna: password sbagliata", chiedi("POST", "/accedi", modulo="utente=anna&password=sbagliata-2026")[0] == 401)
    controlla("Anna: la password da sola, senza nome utente, non entra", chiedi("POST", "/accedi", modulo="utente=&password=" + PW)[0] == 401)
    s, j, t, cookie_anna, h = chiedi("POST", "/accedi", modulo="utente=ANNA&password=" + PW)
    controlla("Anna entra", s == 303 and cookie_anna, s)
    s, io_anna, *_ = chiedi("GET", "/api/io", cookie=cookie_anna)
    controlla("Anna: /api/io", io_anna["id"] == anna["id"] and not io_anna["capo"] and not io_anna["bilancia"] and not io_anna["piano"], io_anna)
    controlla("Anna: stato vuoto", chiedi("GET", "/api/state", cookie=cookie_anna)[1] == {})
    controlla("Anna: misure vuote", chiedi("GET", "/api/misure", cookie=cookie_anna)[1] == {"pesate": [], "circonferenze": [], "passi": []})
    controlla("Anna: non vede le persone", chiedi("GET", "/api/persone", cookie=cookie_anna)[0] == 403)
    controlla("Anna: bilancia spenta", chiedi("GET", "/api/bilancia/sentinella", cookie=cookie_anna)[1] == {"online": False, "occupata": False})
    controlla("Anna: non comanda la bilancia", chiedi("POST", "/api/bilancia/richiesta", corpo={"profilo": {}}, cookie=cookie_anna)[0] == 403)

    # ---- dati separati
    ora = int(time.time() * 1000)
    s, j, *_ = chiedi("PUT", "/api/state", corpo={"di": anna["id"], "updatedAt": ora, "giorni": {}, "sedute": [], "prova": "anna"}, cookie=cookie_anna)
    controlla("Anna: salva il suo stato", s == 200, (s, j))
    s, j, *_ = chiedi("PUT", "/api/state", corpo={"di": 1, "updatedAt": ora + 5, "prova": "furto"}, cookie=cookie_anna)
    controlla("Anna: uno stato del capo viene respinto", s == 409 and j["stato"].get("prova") == "anna", (s, j))
    s, j, *_ = chiedi("PUT", "/api/state", corpo={"updatedAt": ora + 9, "prova": "senza proprietario"}, cookie=cookie_anna)
    controlla("Anna: uno stato senza proprietario viene respinto", s == 409, s)
    controlla("capo: il suo stato non e' cambiato", chiedi("GET", "/api/state", cookie=capo)[1] == stato)
    s, p, *_ = chiedi("POST", "/api/pesate", corpo={"quando": "2026-10-10T08:00:00", "peso": 55.5}, cookie=cookie_anna)
    controlla("Anna: pesata", s == 200 and p["utente"] == anna["id"], p)
    controlla("capo: non vede la pesata di Anna", len(chiedi("GET", "/api/misure", cookie=capo)[1]["pesate"]) == len(misure["pesate"]))
    controlla("capo: non puo' cancellare la pesata di Anna", chiedi("DELETE", "/api/pesate/%d" % p["id"], cookie=capo)[0] == 404)
    s, p2, *_ = chiedi("POST", "/api/pesate", corpo={"quando": "2026-10-10T08:00:00", "peso": 70}, cookie=capo)
    controlla("stessa ora, due persone: due pesate", s == 200 and p2["id"] != p["id"] and p2["utente"] == 1, p2)
    chiedi("DELETE", "/api/pesate/%d" % p2["id"], cookie=capo)

    # ---- passi dall'iPhone: il comando di Comandi li manda con il suo codice, senza il cookie dell'app
    s, j, *_ = chiedi("GET", "/api/passi/codice", cookie=capo)
    controlla("passi: prima del codice non collegati", s == 200 and j == {"attivo": False, "ultimo": None}, (s, j))
    s, j, *_ = chiedi("POST", "/api/passi/codice", cookie=capo)
    codice = (j or {}).get("codice") or ""
    controlla("passi: codice creato", s == 200 and len(codice) >= 32, (s, j))
    s, j, *_ = chiedi("POST", "/api/passi", corpo={"codice": codice, "passi": "8.432 passi"})
    controlla("passi: dal comando, codice nel JSON e testo con il punto delle migliaia", s == 200 and j.get("passi") == 8432, (s, j))
    oggi_passi = (j or {}).get("giorno")
    s, j, *_ = chiedi("POST", "/api/passi", corpo={"passi": "1200\n2300,0"}, intestazioni={"Authorization": "Bearer " + codice})
    controlla("passi: codice nell'intestazione, piu' campioni sommati, rimpiazza il totale del giorno", s == 200 and j.get("passi") == 3500 and j.get("giorno") == oggi_passi, (s, j))
    controlla("passi: arrivano con le misure", {"giorno": oggi_passi, "passi": 3500} in [{k: x[k] for k in ("giorno", "passi")} for x in chiedi("GET", "/api/misure", cookie=capo)[1]["passi"]])
    controlla("passi: codice sbagliato 401", chiedi("POST", "/api/passi", corpo={"codice": codice[:-2] + "xx", "passi": 10})[0] == 401)
    controlla("passi: numero che non si capisce 400", chiedi("POST", "/api/passi", corpo={"codice": codice, "passi": "molti"})[0] == 400)
    controlla("passi: giorno troppo lontano 400", chiedi("POST", "/api/passi", corpo={"codice": codice, "passi": 10, "giorno": "2020-01-01"})[0] == 400)
    controlla("passi: il codice non apre il resto dell'app", chiedi("GET", "/api/state", cookie=codice)[0] == 401
              and chiedi("GET", "/api/misure", intestazioni={"Authorization": "Bearer " + codice})[0] == 401)
    controlla("passi: senza codice e senza cookie 401", chiedi("POST", "/api/passi", corpo={"passi": 10})[0] == 401)
    s, j, *_ = chiedi("GET", "/api/passi/codice", cookie=capo)
    controlla("passi: collegati, con l'ultimo invio", s == 200 and j["attivo"] is True and j["ultimo"]["passi"] == 3500, (s, j))
    controlla("passi: Anna non li vede", chiedi("GET", "/api/misure", cookie=cookie_anna)[1]["passi"] == [])
    vecchio_codice = codice
    codice = chiedi("POST", "/api/passi/codice", cookie=capo)[1]["codice"]
    controlla("passi: il codice nuovo spegne quello vecchio", chiedi("POST", "/api/passi", corpo={"codice": vecchio_codice, "passi": 1})[0] == 401
              and chiedi("POST", "/api/passi", corpo={"codice": codice, "passi": 3600})[0] == 200)
    chiedi("DELETE", "/api/passi/codice", cookie=capo)
    controlla("passi: scollegati, il codice non vale piu'", chiedi("POST", "/api/passi", corpo={"codice": codice, "passi": 1})[0] == 401
              and chiedi("GET", "/api/passi/codice", cookie=capo)[1]["attivo"] is False)
    s, j, *_ = chiedi("PUT", "/api/state", corpo=dict(stato, updatedAt=ora + 20), cookie=VECCHIO)
    controlla("capo: stato senza proprietario accettato (app di prima)", s == 200, (s, j))

    # ---- icona sulla Home
    s, m, *_ = chiedi("GET", "/manifest.webmanifest", cookie=cookie_anna)
    chiave = m["start_url"].split("#k=")[-1]
    controlla("manifest con la chiave di casa", m["start_url"].startswith("./#k=") and len(chiave) == 48, m["start_url"])
    controlla("manifest: stessa chiave la seconda volta", chiedi("GET", "/manifest.webmanifest", cookie=cookie_anna)[1]["start_url"] == m["start_url"])
    controlla("manifest dal percorso segreto: senza chiave", chiedi("GET", "/manifest.webmanifest", intestazioni={"X-Fit-Accesso": "ok"})[1]["start_url"] == "./")
    s, j, t, casa, h = chiedi("POST", "/accedi", modulo="k=" + chiave, intestazioni={"Accept": "application/json"})
    controlla("la chiave di casa diventa un cookie", s == 200 and j["ok"] and casa and casa != cookie_anna, (s, j))
    controlla("quel cookie e' di Anna", chiedi("GET", "/api/io", cookie=casa)[1]["id"] == anna["id"])
    controlla("chiave di casa sbagliata: 401", chiedi("POST", "/accedi", modulo="k=" + "a" * 48)[0] == 401)
    # esce dall'icona: la chiave non deve piu' funzionare, ma Safari resta dentro
    s, j, t, _, h = chiedi("POST", "/api/esci", corpo={}, cookie=casa)
    controlla("esci", s == 200, s)
    controlla("dopo esci: cookie spento", chiedi("GET", "/api/io", cookie=casa)[0] == 401)
    controlla("dopo esci: la chiave di casa non vale piu'", chiedi("POST", "/accedi", modulo="k=" + chiave)[0] == 401)
    controlla("dopo esci: Safari e' ancora dentro", chiedi("GET", "/api/io", cookie=cookie_anna)[0] == 200)

    # ---- due richieste sulla stessa connessione: il corpo della prima va letto anche se non serve
    c = http.client.HTTPConnection("127.0.0.1", PORTA, timeout=20)
    c.request("POST", "/api/ai/prova", body=b"{}", headers={"Content-Type": "application/json", "Cookie": "fitk=" + capo})
    r1 = c.getresponse(); r1.read()
    c.request("GET", "/api/io", headers={"Cookie": "fitk=" + capo})
    r2 = c.getresponse(); r2.read()
    c.close()
    controlla("stessa connessione: la seconda richiesta passa", r2.status == 200, (r1.status, r2.status))

    # ---- chi gestisce l'app vede quando e quanto gli altri la usano, non cosa ci scrivono
    s, j, *_ = chiedi("GET", "/api/persone", cookie=capo)
    lei = next((x for x in (j or {}).get("persone", []) if x["id"] == anna["id"]), {})
    controlla("persone: ultimo accesso, attivita' e conteggi", s == 200 and str(lei.get("visto") or "").endswith("Z") and lei.get("vista") and "giorni" in lei
              and "pesate" in lei and lei.get("ai") == [] and lei.get("piano") is False and "json" not in lei, lei)
    controlla("persone: niente di quello che hanno scritto", not any(k in lei for k in ("stato", "chat", "peso", "extra")), sorted(lei))

    # ---- nome, codice nuovo, eliminazione
    s, j, *_ = chiedi("POST", "/api/io", corpo={"nome": "Annina"}, cookie=cookie_anna)
    controlla("cambia nome", s == 200 and j["nome"] == "Annina", j)
    s, j, *_ = chiedi("POST", "/api/persone/%d/password" % anna["id"], corpo={"password": "nuova-password.26"}, cookie=capo)
    controlla("password nuova", s == 200 and j["ok"], j)
    controlla("la password vecchia non entra", chiedi("POST", "/accedi", modulo="utente=anna&password=" + PW)[0] == 401)
    controlla("la password nuova entra", chiedi("POST", "/accedi", modulo="utente=anna&password=nuova-password.26")[0] == 303)
    controlla("Anna non cambia le password degli altri", chiedi("POST", "/api/persone/1/password", corpo={"password": "qualcosa-2026"}, cookie=cookie_anna)[0] == 403)
    # il capo si sceglie una password sua: da li' entra con quella oppure, come prima, con il codice
    controlla("capo: prima di sceglierla, quella password non entra", chiedi("POST", "/accedi", modulo="utente=admin&password=la-mia-password.26")[0] == 401)
    controlla("capo: password troppo corta rifiutata", chiedi("POST", "/api/persone/1/password", corpo={"password": "corta"}, cookie=capo)[0] == 400)
    controlla("capo: si sceglie una password", chiedi("POST", "/api/persone/1/password", corpo={"password": "la-mia-password.26"}, cookie=capo)[0] == 200)
    s, _, _, capo2, _ = chiedi("POST", "/accedi", modulo="utente=admin&password=la-mia-password.26")
    controlla("capo: entra con la sua password", s == 303 and chiedi("GET", "/api/io", cookie=capo2)[1]["capo"] is True, s)
    controlla("capo: entra ancora con nome utente e codice", chiedi("POST", "/accedi", modulo="utente=admin&password=11112222")[0] == 303)
    controlla("capo: entra ancora con il solo codice", chiedi("POST", "/accedi", modulo="utente=&password=11112222")[0] == 303)
    controlla("capo: la sua password da sola, senza nome utente, non entra", chiedi("POST", "/accedi", modulo="utente=&password=la-mia-password.26")[0] == 401)
    controlla("capo: il cookie di prima vale ancora", chiedi("GET", "/api/io", cookie=capo)[1]["id"] == 1)
    controlla("il capo non si elimina", chiedi("DELETE", "/api/persone/1", cookie=capo)[0] == 400)

    # ---- intelligenza artificiale per account
    controlla("capo: nessuna chiave", chiedi("GET", "/api/ai", cookie=capo)[1]["motore"] is None)
    s, j, *_ = chiedi("POST", "/api/ai/chiave", corpo={"motore": "gemini", "chiave": "AQ.finta-chiave_di_prova_1234567890abcdef"}, cookie=capo)
    print("     salva chiave (serve il servizio finto sulla 8799):", s, j)
    if j and j.get("ok"):
        controlla("capo: chiave salvata", chiedi("GET", "/api/io", cookie=capo)[1]["ai"] is True)
        controlla("Anna: non usa la chiave del capo", chiedi("GET", "/api/io", cookie=cookie_anna)[1]["ai"] is False)
        controlla("Anna: assistente spento", chiedi("POST", "/api/chat", corpo={"messaggi": [{"r": "io", "t": "ciao"}]}, cookie=cookie_anna)[0] == 503)
        s, j, *_ = chiedi("POST", "/api/chat", corpo={"contesto": "Persona: Admin, 30 anni.", "messaggi": [{"r": "ai", "t": "scarta"}, {"r": "io", "t": "Quante proteine oggi?"}]}, cookie=capo)
        controlla("capo: l'assistente risponde", s == 200 and j.get("testo"), (s, j))
        print("     risposta:", (j or {}).get("testo"))
        controlla("chat senza domanda: 400", chiedi("POST", "/api/chat", corpo={"messaggi": [{"r": "ai", "t": "x"}]}, cookie=capo)[0] == 400)
        # ---- l'assistente che fa le cose: il server rimanda le azioni ripulite, non le esegue
        controlla("domanda semplice: nessuna azione", j.get("azioni") == [], j.get("azioni"))
        chat = lambda testo: chiedi("POST", "/api/chat", corpo={"contesto": "CATALOGO\nVoci del diario di oggi (identificativo: cosa): abc123: Nutella", "messaggi": [{"r": "io", "t": testo}]}, cookie=capo)
        s, j, *_ = chat("Ho mangiato una pizza e un gelato, bevuto acqua e fatto una camminata, peso 62,5")
        tipi = [a["tipo"] for a in (j or {}).get("azioni", [])]
        controlla("azioni: diario, acqua, movimento e peso", s == 200 and tipi == ["mangiato", "mangiato", "acqua", "movimento", "peso"], (s, tipi))
        pizza = (j.get("azioni") or [{}])[0]
        controlla("azione ripulita: solo i suoi campi, numeri a posto", pizza.get("pasto") == "cena" and pizza.get("kcal") == 820 and pizza.get("p") == 33
                  and pizza.get("al_posto") == "tutto" and pizza.get("giorno") == "" and "proteine" not in pizza, pizza)
        # i grammi di oggi (dose), una voce con un'altra quantita' (cambia_voce), un pasto mangiato in parte (solo)
        s, j, *_ = chat("dose pollo")
        controlla("azioni: dose di oggi ripulita, quella senza grammi scartata", s == 200 and j.get("azioni") == [
            {"tipo": "dose", "giorno": "", "pasto": "pranzo", "cibo": "pollo", "grammi": 137}] and j.get("scartate") == 1, j)
        s, j, *_ = chat("cambia voce")
        controlla("azioni: cambia_voce con la quantita' nuova, quella senza numero scartata", s == 200 and j.get("azioni") == [
            {"tipo": "cambia_voce", "giorno": "", "voce": "abc123", "quantita": "35 g"}] and j.get("scartate") == 1, j)
        s, j, *_ = chat("solo pasta")
        controlla("azioni: pasto fatto solo in parte", s == 200 and j.get("azioni") == [
            {"tipo": "pasto_fatto", "giorno": "", "pasto": "pranzo", "fatto": True, "solo": ["pasta"]}], j)
        s, j, *_ = chat("giovedi a cena metti il salmone")
        controlla("azioni: cambio di un pasto", s == 200 and j["azioni"] == [{"tipo": "cambia_pasto", "giorni": [3], "pasto": "cena", "ricetta": "salmone-patate"}], j.get("azioni"))
        s, j, *_ = chat("fammi un piatto nuovo")
        piatto = (j.get("azioni") or [{}])[0]
        controlla("azioni: piatto nuovo con un cibo che non c'era", piatto.get("tipo") == "nuovo_piatto" and len(piatto.get("ingredienti", [])) == 3
                  and piatto["ingredienti"][2].get("nome") == "Ceci in scatola" and piatto["ingredienti"][2].get("p") == 7 and piatto.get("giorni") == [1], piatto)
        s, j, *_ = chat("togli la voce")
        controlla("azioni: toglie la voce che trova nel catalogo", j["azioni"] == [{"tipo": "togli_voce", "giorno": "", "voce": "abc123"}], j.get("azioni"))
        s, j, *_ = chat("fai una cosa rotto")
        controlla("azione di tipo sconosciuto scartata, le altre passano all'app", [a["tipo"] for a in j["azioni"]] == ["cambia_pasto"], j.get("azioni"))
        # ---- la modifica libera: passa solo se tutte le operazioni hanno la forma giusta e toccano parti ammesse
        s, j, *_ = chat("porta le calorie a 2500 e nascondi l'acqua")
        ops = [o for a in j["azioni"] for o in a.get("operazioni", [])]
        # (il servizio finto, leggendo "acqua", segna anche mezzo litro: qui contano le due modifiche)
        controlla("modifica: obiettivi, opzioni e ora di un pasto", [a["tipo"] for a in j["azioni"]] == ["acqua", "modifica", "modifica"]
                  and ops[0] == {"op": "metti", "percorso": ["mie", "obiettivi", "train", "kcal"], "valore": 2500} and ops[1]["valore"] is False and len(ops) == 3, j.get("azioni"))
        s, j, *_ = chat("fai una modifica vietata")
        controlla("modifica: la conversazione e il resto non si toccano", j["azioni"] == [], j.get("azioni"))
        s, j, *_ = chat("tema chiaro e misure")
        controlla("azioni: aspetto e misure del corpo", j["azioni"] == [{"tipo": "tema", "aspetto": "chiaro"}, {"tipo": "misure", "cm": {"vita": 78.5, "collo": 37.0}}], j.get("azioni"))
        # ---- una foto insieme alla domanda
        import base64
        jpeg = base64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 3000).decode()
        con_foto = lambda testo, immagine: chiedi("POST", "/api/chat", corpo={"contesto": "CATALOGO", "messaggi": [{"r": "io", "t": testo}], "immagine": immagine}, cookie=capo)
        s, j, *_ = con_foto("cosa c'e' in questa foto?", jpeg)
        controlla("chat con una foto: arriva al servizio", s == 200 and "[foto image/jpeg" in j.get("testo", "") and j["azioni"] == [], (s, j))
        s, j, *_ = con_foto("l'ho mangiato, segna", jpeg)
        controlla("chat con una foto: puo' segnare quello che vede", s == 200 and [a["tipo"] for a in j["azioni"]] == ["mangiato"], (s, j))
        controlla("foto che non e' una foto: 400", con_foto("guarda", base64.b64encode(b"ciao" * 500).decode())[0] == 400)
        controlla("foto non in base64: 400", con_foto("guarda", "questo non e' base64!")[0] == 400)
        s, j, *_ = chat("prova400 acqua")   # il servizio finto rifiuterebbe lo schema: a Gemini non lo si manda piu'
        controlla("a Gemini si chiede solo JSON, senza schema", s == 200 and [a["tipo"] for a in j["azioni"]] == ["acqua"] and j.get("testo"), (s, j))
        # ---- due livelli: di norma partono le istruzioni corte; i dati completi li chiede l'app o l'assistente
        import re as _re
        lunghe = lambda j: int((_re.search(r"(\d+) caratteri di istruzioni", (j or {}).get("testo", "")) or [0, 0])[1])
        livello = lambda testo, liv: chiedi("POST", "/api/chat", corpo={"contesto": "CATALOGO", "livello": liv, "messaggi": [{"r": "io", "t": testo}]}, cookie=capo)
        s, j, *_ = livello("ciao", "base")
        corte = lunghe(j)
        s, j, *_ = livello("ciao", "tutto")
        # (misurate il 18/11/2026: 13.342 caratteri di base, 18.953 con tutto; le regole aggiunte dal 26/10 hanno superato
        # la vecchia soglia fissa di 11.000, quindi conta il rapporto)
        controlla("livelli: le istruzioni di base sono molto piu' corte", 0 < corte <= 0.75 * lunghe(j), (corte, lunghe(j)))
        s, j, *_ = livello("servetutto cambia la scheda", "base")
        controlla("livello base: l'assistente chiede i dati completi", s == 200 and j == {"serve": "tutto"}, (s, j))
        s, j, *_ = livello("servetutto cambia la scheda", "tutto")
        controlla("livello tutto: risponde e agisce", s == 200 and [a["tipo"] for a in j.get("azioni", [])] == ["modifica"], (s, j))
        s, j, *_ = livello("ciao", "qualcosa di strano")
        controlla("livello sconosciuto: vale come base", s == 200 and lunghe(j) == corte, (s, j))
        # ---- il limite del servizio gratuito
        # (per primo: dopo che il modello principale ha detto basta o e' rimasto muto, per dieci minuti non lo si aspetta piu')
        # (la chat va subito al modello leggero, cibo.GEMINI_CHAT_LEGGERO: il principale muto non si aspetta affatto)
        inizio = time.time()
        s, j, *_ = chat("appeso ciao")
        controlla("modello principale muto: la chat non lo aspetta, risponde il leggero", s == 200 and "flash-lite]" in j.get("testo", "") and time.time() - inizio < 1.5,
                  (s, j, round(time.time() - inizio, 1)))
        s, j, *_ = chat("limite429 ciao")
        controlla("limite sul modello principale: risponde quello di riserva", s == 200 and "flash-lite]" in j.get("testo", ""), (s, j))
        s, j, *_ = chat("limitetutti ciao")
        controlla("limite al minuto: 429 con i secondi da aspettare", s == 429 and j.get("attesa") == 7 and j.get("giornaliero") is False and j.get("errore"), (s, j))
        s, j, *_ = chat("limitegiorno ciao")
        controlla("limite del giorno: 429 detto chiaro", s == 429 and j.get("giornaliero") is True and "domani" in j.get("errore", ""), (s, j))
        s, j, *_ = chat("sovraccarico ciao")
        controlla("modello principale sovraccarico (503): risponde quello di riserva", s == 200 and "flash-lite]" in j.get("testo", ""), (s, j))
        # ---- un secondo servizio in fila: quando il primo e' pieno risponde lui
        s, j, *_ = chiedi("POST", "/api/ai/chiave", corpo={"motore": "mistral", "chiave": "chiave0sbagliata0di0mistral0123456"}, cookie=capo)
        controlla("Mistral: una chiave sbagliata non si tiene", s == 200 and j.get("ok") is False and j["chiavi"]["mistral"] is False and j["motore"] == "gemini", (s, j))
        s, j, *_ = chiedi("POST", "/api/ai/chiave", corpo={"motore": "mistral", "chiave": "finta0chiave0di0mistral0123456789"}, cookie=capo)
        controlla("Mistral: chiave salvata, in fila dietro Gemini", s == 200 and j.get("ok") and j.get("fila") == ["gemini", "mistral", "locale"] and j["motore"] == "gemini", (s, j))
        s, j, *_ = chat("ciao")
        controlla("con due servizi risponde il primo", s == 200 and j.get("motore") == "gemini", (s, j))
        s, j, *_ = chat("limitetutti ho mangiato una pizza")
        controlla("Gemini pieno: risponde Mistral, con le azioni", s == 200 and j.get("motore") == "mistral" and "[mistral-medium-latest]" in j.get("testo", "")
                  and [a["tipo"] for a in j["azioni"]] == ["mangiato"], (s, j))
        s, j, *_ = chat("limitetutti mistralpieno ciao")
        controlla("Mistral pieno sul modello principale: risponde quello leggero", s == 200 and "[mistral-small-latest]" in j.get("testo", ""), (s, j))
        s, j, *_ = chat("limitetutti mistralpienotutto ciao")
        controlla("tutti pieni: 429 con l'attesa del primo", s == 429 and j.get("attesa") == 7, (s, j))
        s, j, *_ = con_foto("limitetutti l'ho mangiato, segna", jpeg)
        controlla("Mistral: la foto arriva e puo' segnare", s == 200 and "[foto image/jpeg" in j.get("testo", "") and [a["tipo"] for a in j["azioni"]] == ["mangiato"], (s, j))
        # ---- chi risponde: l'app chiede a uno per volta, per nome
        per_nome = lambda chi, testo: chiedi("POST", "/api/chat", corpo={"motore": chi, "contesto": "CATALOGO", "messaggi": [{"r": "io", "t": testo}]}, cookie=capo)
        s, j, *_ = per_nome("mistral", "ciao")
        controlla("chiesto per nome: risponde quello, e dice con quale modello", s == 200 and j.get("motore") == "mistral" and j.get("modello") == "mistral-medium-latest", (s, j))
        s, j, *_ = per_nome("gemini", "limite429 ciao")
        controlla("il nome del modello di riserva arriva all'app", s == 200 and j.get("motore") == "gemini" and "lite" in (j.get("modello") or ""), (s, j))
        s, j, *_ = per_nome("gemini", "limitetutti ciao")
        controlla("chiesto per nome e pieno: dice a chi passare", s == 429 and j.get("motore") == "gemini" and j.get("prossimo") == "mistral" and j.get("attesa") == 7, (s, j))
        s, j, *_ = per_nome("mistral", "mistralpienotutto ciao")
        controlla("l'ultimo con la chiave passa all'AI della VM", s == 429 and j.get("motore") == "mistral" and j.get("prossimo") == "locale", (s, j))
        # ---- Mistral con il piano gratuito: i modelli grandi sono chiusi (limite zero), rispondono i piccoli, guidati
        ids_m = {"giorni": ["2026-10-11", "2026-10-10"], "pasti": ["colazione", "pranzo", "cena"], "ricette": ["pollo-riso", "salmone-patate"], "cibi": ["riso", "pollo"], "voci": []}
        guidato = lambda testo, livello="base": chiedi("POST", "/api/chat", corpo={
            "motore": "mistral", "livello": livello, "ids": ids_m, "messaggi": [{"r": "io", "t": testo}],
            "contesto": "DATI\nCATALOGO\n\nPIANO DI QUESTI GIORNI\nsettimana\n\nADESSO\nSono le 12:00." + ("\n\nSTATO (JSON: tutto)\n{\"segreto\": 1}" if livello == "tutto" else "")}, cookie=capo)
        s, j, *_ = guidato("mistralchiusi ho mangiato una pizza")
        controlla("Mistral, modelli grandi chiusi: risponde il piccolo, con lo schema e le azioni", s == 200 and j.get("motore") == "mistral" and j.get("modello") == "ministral-14b-latest"
                  and "con schema" in j.get("testo", "") and [a["tipo"] for a in j["azioni"]] == ["mangiato"], (s, j))
        s, j, *_ = guidato("ciao")
        controlla("i modelli chiusi restano a mente: la domanda dopo va subito al piccolo", s == 200 and j.get("modello") == "ministral-14b-latest" and "con schema" in j.get("testo", ""), (s, j))
        s, j, *_ = guidato("porta le calorie a 2000 obiettivo calorie", "tutto")
        controlla("al piccolo i dati completi non arrivano, e le azioni semplici passano", s == 200 and [a["tipo"] for a in j["azioni"]] == ["obiettivo"]
                  and j.get("modello") == "ministral-14b-latest" and "stato completo" not in j.get("testo", ""), (s, j))
        s, j, *_ = guidato("porta le calorie a 2000, obiettivo pieno")
        controlla("al piccolo: dell'obiettivo passano solo i numeri nominati", s == 200 and j["azioni"] == [{"tipo": "obiettivo", "giorni": "palestra", "kcal": 2000}], (s, j))
        s, j, *_ = guidato("calorie a 2000 e proteine a 150, obiettivo pieno")
        controlla("al piccolo: due numeri nominati, due passano", s == 200 and j["azioni"] == [{"tipo": "obiettivo", "giorni": "palestra", "kcal": 2000, "p": 150}], (s, j))
        s, j, *_ = guidato("birre storte")
        controlla("al piccolo: conti storti, li richiede e li sistema", s == 200 and [(a["kcal"], a["f"]) for a in j["azioni"]] == [(340, 0)], (s, j))
        s, j, *_ = chat("limitetutti acqua")
        controlla("Gemini pieno e modelli grandi chiusi: risponde il piccolo di Mistral", s == 200 and j.get("motore") == "mistral" and j.get("modello") == "ministral-14b-latest"
                  and [a["tipo"] for a in j["azioni"]] == ["acqua"], (s, j))
        s, j, *_ = chiedi("POST", "/api/ai/prova", corpo={"motore": "mistral"}, cookie=capo)
        controlla("la prova di Mistral ricontrolla i modelli e dice quale ha risposto", s == 200 and j.get("ok") and j.get("modello") == "mistral-medium-latest", (s, j))
        s, j, *_ = per_nome("mistral", "ciao")
        controlla("dopo la prova i modelli grandi tornano a rispondere", s == 200 and j.get("modello") == "mistral-medium-latest", (s, j))
        s, j, *_ = per_nome("mistral", "mistraltier ciao")
        controlla("modello non compreso nel piano (403): non e' la chiave, risponde il successivo", s == 200 and j.get("modello") == "mistral-small-latest", (s, j))
        s, j, *_ = guidato("mistralgrandipieni ciao")
        controlla("modelli grandi pieni (non chiusi): risponde il piccolo, con lo schema", s == 200 and j.get("modello") == "ministral-14b-latest" and "con schema" in j.get("testo", ""), (s, j))
        s, j, *_ = guidato("servetutto ciao", "tutto")
        controlla("ai modelli grandi i dati completi arrivano", s == 200 and j.get("modello") == "mistral-small-latest" and "stato completo" in j.get("testo", ""), (s, j))
        chiedi("POST", "/api/ai/prova", corpo={"motore": "mistral"}, cookie=capo)
        s, j, *_ = per_nome("mistral", "mistralsenzapiano ciao")
        controlla("Mistral che non lascia usare nessun modello: lo dice, e non c'e' da aspettare", s == 429 and "non lascia usare" in (j.get("perche") or "") and j.get("giornaliero") is True
                  and "piano" in j.get("errore", "") and j.get("prossimo") == "locale", (s, j))
        chiedi("POST", "/api/ai/prova", corpo={"motore": "mistral"}, cookie=capo)
        # il piano gratuito vero: i modelli grandi chiusi per chat/completions rispondono per l'altra strada (conversations)
        s, j, *_ = guidato("mistralconv ho bevuto acqua")
        controlla("modelli grandi chiusi per una strada: rispondono per l'altra, con le azioni", s == 200 and j.get("modello") == "mistral-medium-latest"
                  and "per conversations" in j.get("testo", "") and "con schema" not in j.get("testo", "") and [a["tipo"] for a in j["azioni"]] == ["acqua"], (s, j))
        s, j, *_ = guidato("ciao")
        controlla("la strada chiusa resta a mente: la domanda dopo passa subito dall'altra", s == 200 and j.get("modello") == "mistral-medium-latest" and "per conversations" in j.get("testo", ""), (s, j))
        s, j, *_ = chiedi("POST", "/api/chat", corpo={"motore": "mistral", "contesto": "CATALOGO", "messaggi": [{"r": "io", "t": "mistralconv cosa vedi?"}], "immagine": jpeg}, cookie=capo)
        controlla("con una foto i grandi rispondono per l'altra strada, e la vedono", s == 200 and j.get("modello") == "mistral-medium-latest"
                  and "per conversations" in j.get("testo", "") and "[foto image/jpeg" in j.get("testo", ""), (s, j))
        chiedi("POST", "/api/ai/prova", corpo={"motore": "mistral"}, cookie=capo)   # si riparte puliti: le prove dopo usano i modelli grandi
        # il modello principale di Gemini, dopo che e' rimasto muto, riposa: la domanda dopo va subito a quello di riserva
        inizio = time.time()
        s, j, *_ = per_nome("gemini", "appeso di nuovo")
        controlla("Gemini a riposo: la domanda dopo non aspetta piu' il modello principale", s == 200 and "lite" in (j.get("modello") or "") and time.time() - inizio < 1.5,
                  (s, j, round(time.time() - inizio, 1)))
        s, j, *_ = chat("fai una cosa rotto")
        controlla("azioni scritte male: l'app sa quante", s == 200 and j.get("scartate") == 1, j)
        s, j, *_ = chat("dice fatto")
        controlla("dice fatto senza azioni: l'app lo sa", s == 200 and j.get("vuoto") is True and j["azioni"] == [], j)
        s, j, *_ = chat("ciao")
        controlla("risposta normale: niente avvisi", s == 200 and "vuoto" not in j and "scartate" not in j, j)
        # ---- l'AI che gira sulla VM: si chiede per nome, risponde un numero, la risposta si passa a prendere
        ids = {"pasti": ["colazione", "pranzo", "cena"], "ricette": ["pollo-riso", "salmone-patate"], "cibi": ["riso", "pollo"], "voci": []}
        locale = lambda testo, chi=None: chiedi("POST", "/api/chat", corpo={"motore": "locale", "contesto": "CATALOGO", "ids": ids, "messaggi": [{"r": "io", "t": testo}]}, cookie=chi or capo)

        def ritira(numero, chi=None):
            for _ in range(60):
                s, j, *_ = chiedi("GET", "/api/chat/lavoro/" + numero, cookie=chi or capo)
                if s != 200 or not j.get("in_corso"):
                    return s, j
                time.sleep(0.2)
            return s, j
        s, j, *_ = locale("lento ho bevuto acqua")
        controlla("AI della VM: risponde subito con un numero", s == 202 and j.get("lavoro") and j.get("motore") == "locale", (s, j))
        numero = (j or {}).get("lavoro") or "x" * 12
        s2, j2, *_ = chiedi("GET", "/api/chat/lavoro/" + numero, cookie=capo)
        controlla("AI della VM: intanto dice che sta lavorando", s2 == 200 and j2.get("in_corso") is True, (s2, j2))
        controlla("AI della VM: la risposta di un altro non si ritira", chiedi("GET", "/api/chat/lavoro/" + numero, cookie=cookie_anna)[0] == 404)
        s, j = ritira(numero)
        controlla("AI della VM: la risposta arriva con le azioni, lo schema e il nome", s == 200 and j.get("fatto") is True and j.get("codice") == 200 and j.get("motore") == "locale"
                  and [a["tipo"] for a in j.get("azioni", [])] == ["acqua"] and "con forma" in j.get("testo", ""), (s, j))
        s, j, *_ = locale("obiettivo calorie, quantita riso e orario cena")
        s, j = ritira((j or {}).get("lavoro") or "x" * 12)
        controlla("azioni semplici per il piano: obiettivi, grammi, orario", j.get("azioni") == [
            {"tipo": "obiettivo", "giorni": "palestra", "kcal": 2000},
            {"tipo": "quantita", "ricetta": "pollo-riso", "cibo": "riso", "grammi": 100, "grammi_palestra": 120},
            {"tipo": "orario", "pasto": "cena", "ora": "21:00"}], j)
        s, j, *_ = locale("birre storte")
        s, j = ritira((j or {}).get("lavoro") or "x" * 12)
        birra = (j.get("azioni") or [{}])[0]
        controlla("AI della VM: conti che non tornano, richiesti una seconda volta e sistemati", birra.get("f") == 0 and birra.get("kcal") == 340 and birra.get("al_posto") == "niente", j)
        s, j, *_ = locale("birre storte non sistemare")
        s, j = ritira((j or {}).get("lavoro") or "x" * 12)
        birra = (j.get("azioni") or [{}])[0]
        controlla("AI della VM: se non li sistema, i grammi si riducono in proporzione", birra.get("kcal") == 340 and 0 < birra.get("f", 0) < 40
                  and abs(4 * birra["p"] + 4 * birra["c"] + 9 * birra["f"] - 340) < 6, j)
        s, j, *_ = locale("nopensa ciao")
        s, j = ritira((j or {}).get("lavoro") or "x" * 12)
        controlla("AI della VM: un modello senza ragionamento da spegnere risponde lo stesso", j.get("codice") == 200 and j.get("testo"), j)
        controlla("AI della VM: un numero inventato non c'e'", chiedi("GET", "/api/chat/lavoro/numeroinventato123", cookie=capo)[0] == 404)
        controlla("Anna non ha l'AI della VM", locale("ciao", cookie_anna)[0] == 503)
        dati = "DATI (cambiano di rado)\nPersona: prova\n\nPIANO DI QUESTI GIORNI\nObiettivi: 1700 kcal\n\nADESSO\nSono le 12:00."
        s, j, *_ = chiedi("POST", "/api/chat/scalda", corpo={"contesto": dati}, cookie=capo)
        controlla("all'apertura dell'assistente l'AI della VM si prepara", s == 200 and j.get("ok") is True, (s, j))
        s, j, *_ = chiedi("POST", "/api/chat/scalda", corpo={"contesto": dati}, cookie=cookie_anna)
        controlla("chi non ha l'AI della VM non la prepara", s == 200 and j.get("ok") is False, (s, j))
        # ---- la domanda come lavoro: il server prova i servizi uno dopo l'altro e dice chi sta rispondendo
        lavoro = lambda testo, **piu: chiedi("POST", "/api/chat", corpo=dict({"lavoro": True, "contesto": "CATALOGO", "mondo": "STATO {}", "ids": ids, "messaggi": [{"r": "io", "t": testo}]}, **piu), cookie=capo)
        s, j, *_ = lavoro("ciao")
        controlla("lavoro: subito un numero e la fila", s == 202 and j.get("lavoro") and j.get("fila") == ["gemini", "mistral", "locale"], (s, j))
        s, j = ritira(j["lavoro"])
        controlla("lavoro: risponde il primo della fila", s == 200 and j.get("codice") == 200 and j.get("motore") == "gemini" and j.get("testo"), (s, j))
        s, j, *_ = lavoro("limitetutti mistralpienotutto lento ho bevuto acqua")
        numero = j["lavoro"]
        visti = set()
        for _ in range(80):
            s, j, *_ = chiedi("GET", "/api/chat/lavoro/" + numero, cookie=capo)
            if not j.get("in_corso"):
                break
            visti.add((j.get("chi"), j.get("nota")))
            time.sleep(0.1)
        controlla("lavoro: pieni Gemini e Mistral, risponde l'AI della VM", j.get("codice") == 200 and j.get("motore") == "locale" and [a["tipo"] for a in j.get("azioni", [])] == ["acqua"], j)
        controlla("lavoro: intanto dice chi sta rispondendo e perche'", ("locale", "Mistral ha troppe richieste in questo momento") in visti, visti)
        s, j, *_ = lavoro("servetutto cambia la scheda")
        s, j = ritira(j["lavoro"])
        controlla("lavoro: se servono i dati completi il server richiede da solo", j.get("codice") == 200 and [a["tipo"] for a in j.get("azioni", [])] == ["modifica"], j)
        # ---- Gemini giu' con tutti i modelli: la domanda passa a Mistral e, per un po', Gemini va in fondo alla fila
        s, j, *_ = lavoro("giututto ho bevuto acqua")
        s, j = ritira(j["lavoro"])
        controlla("Gemini giu' con tutti i modelli: risponde Mistral", j.get("codice") == 200 and j.get("motore") == "mistral" and [a["tipo"] for a in j.get("azioni", [])] == ["acqua"], j)
        s, j, *_ = lavoro("limite429 ciao")   # (se Gemini fosse ancora il primo, questa parola farebbe rispondere il suo modello leggero)
        s, j = ritira(j["lavoro"])
        controlla("dopo la caduta Gemini va in fondo alla fila: la domanda dopo va subito a Mistral", j.get("codice") == 200 and j.get("motore") == "mistral", j)
        s, j, *_ = chat("ciao")
        controlla("vale anche per le domande fatte alla vecchia maniera", s == 200 and j.get("motore") == "mistral", (s, j))
        s, j, *_ = chiedi("POST", "/api/ai/prova", corpo={"motore": "gemini"}, cookie=capo)
        controlla("la prova di Gemini lo rimette al suo posto", s == 200 and j.get("ok") and j.get("motore") == "gemini", (s, j))
        s, j, *_ = lavoro("ciao")
        s, j = ritira(j["lavoro"])
        controlla("dopo la prova risponde di nuovo Gemini", j.get("codice") == 200 and j.get("motore") == "gemini", j)
        # ---- notifiche: iscrizione, sveglia firmata, il telefono passa a prendere il testo
        s, j, *_ = chiedi("GET", "/api/notifiche/chiave", cookie=capo)
        controlla("notifiche: la chiave pubblica del server", s == 200 and len(j.get("chiave", "")) == 87, (s, j))
        controlla("notifiche: un indirizzo qualunque non si iscrive", chiedi("POST", "/api/notifiche/iscrizione", corpo={"indirizzo": "https://esempio.it/x"}, cookie=capo)[0] == 400)
        s, j, *_ = chiedi("POST", "/api/notifiche/iscrizione", corpo={"indirizzo": "http://127.0.0.1:8799/spinta/telefono1", "fuso": 120, "orari": {"pranzo": "13:00", "cena": "21:00", "altro": "x"}}, cookie=capo)
        controlla("notifiche: telefono iscritto, promemoria accesi", s == 200 and j.get("promemoria") is True, (s, j))
        chiedi("POST", "/api/notifiche/iscrizione", corpo={"indirizzo": "http://127.0.0.1:8799/spinta/andata", "fuso": 120, "orari": {}}, cookie=capo)
        s, j, *_ = chiedi("POST", "/api/notifiche/prova", corpo={}, cookie=capo)
        controlla("notifiche: la prova sveglia il telefono buono", s == 200 and j.get("ok") is True and j.get("telefoni") == 1, (s, j))
        s, j, *_ = chiedi("GET", "/api/notifiche/prossime", cookie=capo)
        controlla("notifiche: il telefono passa a prendere il testo", s == 200 and [x["testo"] for x in j.get("notifiche", [])] == ["Le notifiche funzionano."], (s, j))
        controlla("notifiche: una volta sola", chiedi("GET", "/api/notifiche/prossime", cookie=capo)[1] == {"notifiche": []})
        controlla("notifiche: quelle di un altro non si vedono", chiedi("GET", "/api/notifiche/prossime", cookie=cookie_anna)[1] == {"notifiche": []})
        s, j, *_ = chiedi("POST", "/api/notifiche/prova", corpo={}, cookie=capo)
        controlla("notifiche: l'iscrizione scaduta e' stata buttata", j.get("telefoni") == 1, j)
        s, j, *_ = lavoro("ciao a dopo")   # nessuno passa a ritirarla: dopo dodici secondi parte la notifica
        time.sleep(14)
        s, j, *_ = chiedi("GET", "/api/notifiche/prossime", cookie=capo)
        controlla("notifiche: FitAI ha risposto e nessuno ha ritirato", [x["titolo"] for x in j.get("notifiche", [])][-1:] == ["FitAI ti ha risposto"] and j["notifiche"][-1].get("dove") == "./?apri=fitai", j)
        s, j, *_ = chiedi("POST", "/api/notifiche/iscrizione", corpo={"indirizzo": "http://127.0.0.1:8799/spinta/telefono1", "fuso": 120, "orari": {"pranzo": "13:00"}, "promemoria": False}, cookie=capo)
        controlla("notifiche: promemoria spenti", j.get("promemoria") is False, j)
        s, j, *_ = chiedi("POST", "/api/ai/prova", corpo={"motore": "locale"}, cookie=capo)
        controlla("prova dell'AI della VM", s == 200 and j.get("motore") == "locale", (s, j))
        s, j, *_ = chiedi("POST", "/api/ai/prova", corpo={"motore": "mistral"}, cookie=capo)
        controlla("prova della sola chiave di Mistral", s == 200 and j.get("motore") == "mistral", (s, j))
        chiedi("DELETE", "/api/ai/chiave/gemini", cookie=capo)
        s, j, *_ = chiedi("GET", "/api/ai", cookie=capo)
        controlla("tolta Gemini resta Mistral", j.get("motore") == "mistral" and j.get("fila") == ["mistral", "locale"] and j["chiavi"] == {"anthropic": False, "gemini": False, "mistral": True}, j)
        s, j, *_ = chat("ho bevuto acqua")
        controlla("Mistral da solo: assistente con azioni", s == 200 and j.get("motore") == "mistral" and [a["tipo"] for a in j["azioni"]] == ["acqua"], (s, j))
        s, j, *_ = chiedi("POST", "/api/foto", corpo={"immagine": jpeg}, cookie=capo)
        controlla("Mistral da solo: stima di un piatto dalla foto", s == 200 and len((j or {}).get("voci", [])) == 1, (s, j))
        chiedi("DELETE", "/api/ai/chiave/mistral", cookie=capo)
        chiedi("POST", "/api/ai/chiave", corpo={"motore": "gemini", "chiave": "AQ.finta-chiave_di_prova_1234567890abcdef"}, cookie=capo)
        controlla("file della chiave", os.path.isfile(os.path.join(cartella, "chiavi", "1-gemini.key")))
        chiedi("DELETE", "/api/ai/chiave/gemini", cookie=capo)
        j = chiedi("GET", "/api/io", cookie=capo)[1]
        controlla("chiavi tolte: resta solo l'AI della VM", j["motore"] is None and j["fila"] == ["locale"] and j["ai"] is True, j)

    # ---- service worker e piano
    s, j, t, _, h = chiedi("GET", "/sw.js", cookie=capo)
    controlla("sw.js con versione e file", s == 200 and b"__VERSIONE__" not in t and b"__FILE__" not in t, t[:160])
    s, j, t, _, h = chiedi("GET", "/api/piano", cookie=cookie_anna)
    controlla("Anna: nessun piano scritto a mano", s == 200 and j == {}, j)
    s, j, t, _, h = chiedi("GET", "/api/piano", cookie=capo)
    print("     piano del capo:", s, (list(j)[:8] if isinstance(j, dict) else j))

    controlla("elimina persona", chiedi("DELETE", "/api/persone/%d" % anna["id"], cookie=capo)[0] == 200)
    controlla("eliminata: il cookie non vale piu'", chiedi("GET", "/api/io", cookie=cookie_anna)[0] == 401)
    db = sqlite3.connect(os.path.join(cartella, "fit.db"))
    resti = {t: db.execute("SELECT COUNT(*) FROM %s WHERE utente = ?" % t, (anna["id"],)).fetchone()[0] for t in ("sessioni", "stato", "pesate", "circonferenze")}
    controlla("eliminata: non resta niente di suo", not any(resti.values()), resti)
    print("     tabelle:", sorted(r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")))
    db.close()

    # ---- troppi tentativi
    for _ in range(31):
        s = chiedi("POST", "/accedi", modulo="utente=admin&password=99999999")[0]
        if s == 429:
            break
    controlla("troppi codici sbagliati: 429", s == 429, s)

    # ---- le regole di FitAI dopo gli sbagli del 26/10/2026 (cioccolato preso per la barretta del piano, foto descritta
    # senza averla, correzione non fatta, "137 g di pollo oggi" diventato la dose del piano per sempre)
    sys.path.insert(0, os.path.join(APP, "server"))
    import assistente  # noqa: E402
    for livello in ("base", "tutto"):
        testo = assistente.istruzioni(livello)
        controlla("istruzioni %s: foto vista solo con il suo messaggio, correzioni, dettatura, dosi di oggi nel diario" % livello,
                  "non la vedi piu'" in testo and "ha ragione la persona" in testo and "dettati a voce" in testo
                  and "il piano non cambia" in testo and "mai da quello che c'e' nel piano" in testo
                  and "non aggiungere un'altra voce" in testo and "- dose:" in testo and "- cambia_voce:" in testo)
    for regola in ("9. Una foto la vedi solo", "10. Se ti corregge", "11. I messaggi spesso", "12. Quanto ha messo oggi"):
        controlla("istruzioni dell'AI della VM: " + regola, regola in assistente.ISTRUZIONI_LOCALE)
    forma = assistente.forma_locale({"pasti": ["pranzo"], "cibi": ["pollo", "riso"], "giorni": ["2026-10-26"]})
    mangiato = next(a for a in forma["properties"]["azioni"]["items"]["anyOf"] if a["properties"]["tipo"]["enum"] == ["mangiato"])
    controlla("AI della VM: puo' cambiare un solo ingrediente del pasto (parte, tolti tra i cibi veri)",
              "parte" in mangiato["properties"]["al_posto"]["enum"] and mangiato["properties"]["tolti"]["items"]["enum"] == ["pollo", "riso"]
              and "tolti" in mangiato["required"], mangiato["properties"].get("tolti"))
    tipi_locale = {a["properties"]["tipo"]["enum"][0]: a for a in assistente.forma_locale(
        {"pasti": ["pranzo"], "cibi": ["pollo"], "voci": ["v1"]})["properties"]["azioni"]["items"]["anyOf"]}
    controlla("AI della VM: dose, cambia_voce e pasto fatto in parte", "dose" in tipi_locale and "cambia_voce" in tipi_locale
              and tipi_locale["pasto_fatto"]["properties"]["senza"]["items"]["enum"] == ["pollo"], sorted(tipi_locale))
    pulita = assistente._azione({"tipo": "mangiato", "pasto": "pranzo", "nome": "Petto di pollo", "quantita": "137 g", "kcal": 148,
                                 "proteine": 32, "carboidrati": 0, "grassi": 2, "al_posto": "parte", "tolti": ["pollo"]})
    controlla("azione 'pollo di oggi': resta parte, con l'ingrediente tolto", pulita and pulita["al_posto"] == "parte" and pulita["tolti"] == ["pollo"], pulita)
finally:
    server.terminate()
    server.wait(timeout=5)
    uscita = open(os.path.join(cartella, "server.log"), encoding="utf-8").read()
    righe = uscita.strip().splitlines()
    print("---- registro del server (inizio e fine)")
    print("\n".join(righe[:6] + ["..."] + righe[-4:]))
    shutil.rmtree(cartella, ignore_errors=True)

print("\nERRORI: %s" % sbagli if sbagli else "\nTUTTO BENE")
sys.exit(1 if sbagli else 0)
