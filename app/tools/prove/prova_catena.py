"""La fila di FitAI (server/assistente.py: catena, avvia, con_i_codici) con servizi finti: muti, lenti, che dicono
basta, che si rompono. Il 28/10/2026 il capo: "se non funziona un modello deve esserci l'altro disponibile".
Non chiama nessun servizio vero e non tocca i dati.

    python prova_catena.py
"""
import contextlib
import io
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server"))
import assistente  # noqa: E402
import cibo  # noqa: E402
from cibo import Problema  # noqa: E402

assistente.SPINTA, assistente.LOCALE_DOPO = 0.3, 1.2
sbagli = []


def controlla(nome, vero, dettaglio=""):
    print(("ok   " if vero else "NO   ") + nome + ("" if vero else "  %r" % (dettaglio,)))
    if not vero:
        sbagli.append(nome)


# Ogni servizio finto fa quello che gli si dice: ("risponde", secondi) | ("muto", secondi, poi errore) | ("basta",
# Problema) | ("rotto",). `chiamati` tiene chi e' stato chiamato, quando, e con quale `conta`.
copione, chiamati = {}, []


def rispondi_finto(motore, utente, contesto, messaggi, immagine=None, livello="base", ids=None, conta=True):
    chi = motore[0]
    chiamati.append((chi, time.time(), conta))
    cosa = copione[chi]
    if cosa[0] == "risponde":
        time.sleep(cosa[1])
        return {"testo": "risposta di " + chi, "azioni": [], "motore": chi, "modello": chi, "domanda": messaggi[-1]["t"]}
    if cosa[0] == "muto":
        time.sleep(cosa[1])
        raise Problema(502, "Il servizio di AI non risponde. Riprova tra poco.")
    if cosa[0] == "basta":
        raise cosa[1]
    raise KeyError("rotto")


assistente.rispondi = rispondi_finto
cibo.fermo = lambda nome: False
MOTORI = [("gemini", "k"), ("mistral", "k"), ("locale", "")]
DOMANDA = {"contesto": "c", "messaggi": [{"r": "io", "t": "ciao"}]}


def gira(**servizi):
    copione.clear()
    copione.update(servizi)
    chiamati.clear()
    assistente._fiacchi.clear()
    stato, inizio = {}, time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        codice, j = assistente.catena(MOTORI, 1, dict(DOMANDA), stato)
    return codice, j, time.time() - inizio, [c[0] for c in chiamati], stato


codice, j, durata, chi, _ = gira(gemini=("risponde", 0.05), mistral=("risponde", 0.05), locale=("risponde", 0.05))
controlla("il primo risponde subito: e' lui, e gli altri non si disturbano", codice == 200 and j["motore"] == "gemini" and chi == ["gemini"], (codice, j, chi))

codice, j, durata, chi, stato = gira(gemini=("muto", 3), mistral=("risponde", 0.1), locale=("risponde", 0.1))
controlla("il primo tace: dopo SPINTA si chiede anche al secondo, e vince lui", codice == 200 and j["motore"] == "mistral" and chi == ["gemini", "mistral"], (codice, j, chi))
controlla("...senza aspettare che il primo si arrenda", durata < 1.0, durata)
controlla("...e sopra i puntini c'e' scritto perche'", "chiedo anche a Mistral" in (stato.get("nota") or ""), stato)

codice, j, durata, chi, _ = gira(gemini=("basta", Problema(429, "pieno", remoto=429)), mistral=("risponde", 0.05), locale=("risponde", 0.05))
controlla("il primo dice basta: il secondo parte subito", codice == 200 and j["motore"] == "mistral" and durata < 0.25, (codice, j, durata))

codice, j, durata, chi, _ = gira(gemini=("basta", Problema(502, "x", remoto=503)), mistral=("basta", Problema(502, "x", remoto=500)), locale=("risponde", 0.05))
controlla("i servizi dicono tutti basta: l'AI sulla VM parte subito, senza aspettare LOCALE_DOPO", codice == 200 and j["motore"] == "locale" and durata < 0.5, (codice, j, durata))

codice, j, durata, chi, _ = gira(gemini=("muto", 5), mistral=("muto", 5), locale=("risponde", 0.05))
controlla("i servizi tacciono tutti: l'AI sulla VM parte dopo LOCALE_DOPO", codice == 200 and j["motore"] == "locale" and 1.1 < durata < 2.0, (codice, j, durata))

codice, j, durata, chi, _ = gira(gemini=("rotto",), mistral=("risponde", 0.05), locale=("risponde", 0.05))
controlla("un errore di programma dentro un servizio non ferma gli altri", codice == 200 and j["motore"] == "mistral", (codice, j))

codice, j, durata, chi, _ = gira(gemini=("basta", Problema(400, "manca la domanda")), mistral=("risponde", 0.05), locale=("risponde", 0.05))
controlla("una domanda sbagliata lo e' per tutti: si risponde subito con l'errore", codice == 400 and chi == ["gemini"], (codice, j, chi))

codice, j, durata, chi, _ = gira(gemini=("muto", 0.05), mistral=("muto", 0.05), locale=("muto", 0.05))
controlla("non ce la fa nessuno: errore, dopo averli provati tutti", codice == 502 and chi == ["gemini", "mistral", "locale"] and "errore" in j, (codice, j, chi))

copione.update(gemini=("muto", 3), mistral=("risponde", 0.05), locale=("risponde", 0.05))
chiamati.clear()
assistente._fiacchi.clear()
with contextlib.redirect_stdout(io.StringIO()):
    assistente.catena(MOTORI, 1, dict(DOMANDA), {})
controlla("ogni domanda conta una volta sola, anche se si chiede a due", [c[2] for c in chiamati] == [True, False], chiamati)
copione.update(gemini=("basta", Problema(502, "x", remoto=503)))
with contextlib.redirect_stdout(io.StringIO()):
    assistente.catena(MOTORI, 1, dict(DOMANDA), {})
chiamati.clear()
copione.update(gemini=("risponde", 0.05))
with contextlib.redirect_stdout(io.StringIO()):
    codice, j = assistente.catena(MOTORI, 1, dict(DOMANDA), {})
controlla("chi e' appena caduto va in fondo alla fila per qualche minuto", chiamati[0][0] == "mistral" and j["motore"] == "mistral", chiamati)

# superata da una domanda nuova: smette senza aspettare il servizio lento
copione.clear()
copione.update(gemini=("muto", 3), mistral=("muto", 3), locale=("muto", 3))
assistente._fiacchi.clear()
stato = {}
threading.Timer(0.4, lambda: stato.update(superato=True)).start()
inizio = time.time()
with contextlib.redirect_stdout(io.StringIO()):
    codice, j = assistente.catena(MOTORI, 1, dict(DOMANDA), stato)
controlla("una domanda superata da una nuova smette subito", codice == 409 and time.time() - inizio < 1.5, (codice, j, time.time() - inizio))

# avvia: la stessa domanda rimandata riprende lo stesso lavoro; una nuova fa smettere le vecchie
assistente.AL_TERMINE = None
lento = threading.Event()
with contextlib.redirect_stdout(io.StringIO()):
    primo = assistente.avvia(7, lambda st: (lento.wait(3), (200, {"testo": "a"}))[1], "q1")
    di_nuovo = assistente.avvia(7, lambda st: (200, {"testo": "doppione"}), "q1")
controlla("la stessa domanda rimandata riprende lo stesso lavoro (non la si esegue due volte)", primo == di_nuovo)
with contextlib.redirect_stdout(io.StringIO()):
    secondo = assistente.avvia(7, lambda st: (200, {"testo": "b"}), "q2")
controlla("una domanda nuova e' un lavoro nuovo", secondo != primo)
controlla("...e quella di prima risulta superata", assistente._lavori[primo]["stato"].get("superato") is True)
lento.set()
time.sleep(0.2)
controlla("la risposta della domanda nuova si ritira", assistente.ritira(7, secondo) == (200, {"testo": "b"}))
controlla("il lavoro di un altro non si ritira", assistente.ritira(8, secondo) is None)

# i codici a barre nell'ultima domanda
cercati = []


def prodotto_finto(ean):
    cercati.append(ean)
    if ean == "5900020017420":
        return {"n": "Nesquik Maxi Choco", "marca": "Nesquik", "kcal": 400, "p": 6.7, "c": 64.9, "f": 12.2, "pz": None, "pzn": ["porzione", "porzioni"], "conf": 25}
    if ean == "8000500310427":
        raise Problema(502, "il catalogo non risponde")
    return None


cibo.prodotto_ean = prodotto_finto
with contextlib.redirect_stdout(io.StringIO()):
    m = assistente.con_i_codici([{"r": "ai", "t": "prima"}, {"r": "io", "t": "Mangiata spuntino pomeriggio\n[con una foto allegata]\n[codice a barre nella foto: 5900020017420]"}])
controlla("il prodotto del codice nella foto va accanto alla domanda, con i valori", "Nesquik Maxi Choco (Nesquik), confezione da 25 g; per 100 g 400 kcal, proteine 6.7 g" in m[-1]["t"], m[-1]["t"])
controlla("...e i messaggi di prima restano com'erano", m[0] == {"r": "ai", "t": "prima"})
cercati.clear()
with contextlib.redirect_stdout(io.StringIO()):
    m = assistente.con_i_codici([{"r": "io", "t": "ho mangiato 12345678 gallette e questa 5900020017421"}])
controlla("numeri che non sono codici (cifra di controllo sbagliata) non si cercano", cercati == [] and m[-1]["t"].endswith("5900020017421"), (cercati, m))
with contextlib.redirect_stdout(io.StringIO()):
    m = assistente.con_i_codici([{"r": "io", "t": "e questo? 8000500310427"}])
controlla("catalogo giu': si dice di non indovinare", "non indovinare" in m[-1]["t"].lower(), m[-1]["t"])
with contextlib.redirect_stdout(io.StringIO()):
    m = assistente.con_i_codici([{"r": "io", "t": "codice 4006381333931"}])
controlla("codice che il catalogo non conosce: si chiedono nome e valori", "non lo conosce" in m[-1]["t"], m[-1]["t"])
controlla("una risposta (non una domanda) in fondo non si tocca", assistente.con_i_codici([{"r": "ai", "t": "5900020017420"}]) == [{"r": "ai", "t": "5900020017420"}])

# il codice arriva fino al servizio: catena passa la domanda con il prodotto accanto
copione.clear()
copione.update(gemini=("risponde", 0.01), mistral=("risponde", 0.01), locale=("risponde", 0.01))
with contextlib.redirect_stdout(io.StringIO()):
    codice, j = assistente.catena(MOTORI, 1, {"contesto": "c", "messaggi": [{"r": "io", "t": "[codice a barre nella foto: 5900020017420]"}]}, {})
controlla("il servizio riceve la domanda con il prodotto del codice", "Nesquik Maxi Choco" in j.get("domanda", ""), j)

print("\n%d controlli sbagliati" % len(sbagli) if sbagli else "\ntutto giusto")
sys.exit(1 if sbagli else 0)
