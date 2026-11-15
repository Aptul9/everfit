#!/usr/bin/env python3
"""FitFuel bilancia sul server: la sentinella per Linux, senza icona, come servizio systemd.

Fa quello che fa sentinella.pyw sul portatile, ma dal server di casa, che non si spegne mai: il portatile scollegato
dalla corrente di notte si addormentava, e al mattino dal telefono non ci si pesava (dal 14 al 27/10/2026 nessuna
pesata). Aspetta le richieste dal server (GET api/bilancia/lavoro), fa la pesata con bilancia.py (bleak su BlueZ) e
manda avanzamenti e risultato (POST api/bilancia/notizie): vedi app/server/ponte.py.

Il servizio (fit-bilancia.service) la fa ripartire se esce, e anche se si blocca: a ogni giro dice a systemd che e'
viva, e se per tre minuti non lo dice systemd la chiude e la riapre (WatchdogSec).

    python3 sentinella_linux.py           avvio normale (lo fa il servizio)
    python3 sentinella_linux.py --prova   controlla server e Bluetooth, stampa l'esito ed esce

Configurazione in /etc/fit-bilancia/config.json, leggibile solo da root e dal servizio (c'e' il percorso segreto):
    url        l'indirizzo dell'app con il percorso segreto, che vale come l'account dell'amministratore
    connetti   facoltativo: l'IP a cui collegarsi al posto di quello del nome. 127.0.0.1 e' il Caddy di questo PC,
               cosi' non si passa dal DNS ne' dal router
    bilancia   l'indirizzo Bluetooth della bilancia, se gia' noto
    dettagli   true per avere nel registro anche i pacchetti della bilancia
L'indirizzo della bilancia trovato con una pesata va in /var/lib/fit-bilancia/stato.json (/etc il servizio non lo
puo' scrivere). Il registro e' nel journal: journalctl -u fit-bilancia
"""
import faulthandler
import http.client
import json
import logging
import os
import socket
import ssl
import sys
import threading
import time
import urllib.request
from pathlib import Path

import bilancia

CONFIG = Path(os.environ.get("FIT_BILANCIA_CONFIG", "/etc/fit-bilancia/config.json"))
STATO = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/fit-bilancia").split(":")[0]) / "stato.json"
MAX_PESATA = 300   # s: una pesata che dura di piu' e' bloccata. Si smette di avvisare systemd, che fa ripartire il servizio
log = logging.getLogger("fit.sentinella")


def systemd(messaggio):
    """sd_notify senza librerie: READY=1 all'avvio, WATCHDOG=1 per dire che e' ancora viva, STATUS=... per systemctl status."""
    dove = os.environ.get("NOTIFY_SOCKET")
    if not dove:
        return
    if dove.startswith("@"):
        dove = "\0" + dove[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
            s.connect(dove)
            s.sendall(messaggio.encode("utf-8"))
    except OSError as e:
        log.debug("systemd non risponde: %r", e)


def leggi_config():
    """config.json piu' quello che la sentinella ha imparato (stato.json). None se manca l'indirizzo https."""
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        config.update(json.loads(STATO.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return config if str(config.get("url", "")).startswith("https://") else None


def ricorda(chiave, valore):
    try:
        stato = json.loads(STATO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stato = {}
    if stato.get(chiave) == valore:
        return
    stato[chiave] = valore
    provvisorio = STATO.with_suffix(".tmp")
    provvisorio.write_text(json.dumps(stato, indent=1), encoding="utf-8")
    os.replace(provvisorio, STATO)


# ---------- il server ----------
class _Diretta(http.client.HTTPSConnection):
    """HTTPS verso l'IP scelto, tenendo il nome dell'indirizzo per il certificato e per Caddy."""

    def __init__(self, host, ip, **kw):
        super().__init__(host, **kw)
        self.ip = ip

    def connect(self):
        sock = socket.create_connection((self.ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _Gestore(urllib.request.HTTPSHandler):
    def __init__(self, ip):
        super().__init__(context=ssl.create_default_context())
        self.ip = ip

    def https_open(self, req):
        return self.do_open(lambda host, **kw: _Diretta(host, self.ip, **kw), req, context=self._context)


class Server:
    def __init__(self, base, connetti=None):
        self.base = base if base.endswith("/") else base + "/"
        self.apri = urllib.request.build_opener(_Gestore(connetti)).open if connetti else urllib.request.urlopen

    def chiama(self, metodo, percorso, corpo=None, attesa=15):
        dati = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        richiesta = urllib.request.Request(self.base + percorso, data=dati, method=metodo,
                                           headers={"Content-Type": "application/json", "User-Agent": "FitSentinella/1.0 (server)"})
        with self.apri(richiesta, timeout=attesa) as risposta:
            return None if risposta.status == 204 else json.load(risposta)


# ---------- il lavoro ----------
class Sentinella:
    def __init__(self, config):
        self.config = config
        self.server = Server(config["url"], config.get("connetti"))
        self.stato = "parto"

    def dico(self, stato):
        if stato != self.stato:
            self.stato = stato
            log.info(stato)
            systemd("STATUS=" + stato)

    def pesa(self, lavoro):
        ident = lavoro["id"]
        stop = threading.Event()
        finita = threading.Event()
        inizio = time.monotonic()
        self.dico("sto pesando")

        def notizia(**cosa):
            try:
                risposta = self.server.chiama("POST", "api/bilancia/notizie", dict(id=ident, **cosa), attesa=10)
                if risposta and risposta.get("annullata") and "esito" not in cosa:
                    stop.set()
            except (OSError, ValueError) as e:
                log.warning("notizia non consegnata: %r", e)

        def battito():
            # mentre pesa non aspetta lavoro: si fa sentire lo stesso, al server (cosi' sa anche se dal telefono hanno
            # annullato) e a systemd, ma solo per MAX_PESATA secondi: una pesata bloccata fa ripartire il servizio
            while not finita.wait(2):
                if time.monotonic() - inizio < MAX_PESATA:
                    systemd("WATCHDOG=1")
                notizia()

        threading.Thread(target=battito, name="battito", daemon=True).start()
        ultimo = [0.0]

        def evento(fase, kg=None):
            # il peso in diretta cambia quattro volte al secondo: al telefono ne basta una parte
            if fase == "peso" and time.monotonic() - ultimo[0] < 0.4:
                return
            ultimo[0] = time.monotonic()
            notizia(evento={"fase": fase, "kg": kg})

        try:
            esito = bilancia.misura(lavoro.get("profilo") or {}, evento=evento, stop=stop, indirizzo=self.config.get("bilancia"))
        except Exception:
            log.exception("pesata fallita")
            esito = {"ok": False, "errore": "Qualcosa e' andato storto sul server. Riprova; se succede ancora guarda journalctl -u fit-bilancia."}
        finita.set()
        log.info("pesata finita: %s", {k: v for k, v in esito.items() if k != "memoria"} | {"in_memoria": len(esito.get("memoria") or [])})
        notizia(esito=esito)
        if esito.get("ok") and esito.get("indirizzo") and esito["indirizzo"] != self.config.get("bilancia"):
            self.config["bilancia"] = esito["indirizzo"]
            ricorda("bilancia", esito["indirizzo"])

    def lavora(self):
        pausa = 1
        try:
            self.server.chiama("GET", "api/health", attesa=10)
            self.dico("in attesa")
        except (OSError, ValueError):
            self.dico("il server non risponde")
        while True:
            systemd("WATCHDOG=1")
            try:
                lavoro = self.server.chiama("GET", "api/bilancia/lavoro?attesa=25", attesa=40)
                pausa = 1
            except (OSError, ValueError) as e:
                self.dico("il server non risponde")
                log.info("attesa fallita: %r", e)
                time.sleep(pausa)
                # il server e' qui accanto (sulla stessa macchina): quando riparte ci si ricollega entro pochi secondi,
                # senza allungare le attese come si fa con un server lontano. Finche' manca, il pallino e' rosso.
                pausa = min(5, pausa * 2)
                continue
            if lavoro:
                self.pesa(lavoro)
            self.dico("in attesa")


def prova(config):
    esito = {}
    try:
        server = Server(config["url"], config.get("connetti"))
        esito["server"] = bool(server.chiama("GET", "api/health").get("ok"))
        esito["sentinella_vista_dal_server"] = server.chiama("GET", "api/bilancia/sentinella")
    except (OSError, ValueError) as e:
        esito["server"] = repr(e)
    esito["bluetooth"] = bilancia.radio_pronta()
    print(json.dumps(esito, ensure_ascii=False))
    return 0 if esito.get("server") is True and esito["bluetooth"].get("ok") else 1


def main():
    # se il watchdog la trova bloccata (SIGABRT) nel journal resta dove era ferma ogni thread
    faulthandler.enable()
    # il journal mette gia' data e ora
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("bleak").setLevel(logging.WARNING)
    config = leggi_config()
    if not config:
        log.error("manca l'indirizzo https dell'app in %s: rilancia desktop/installa_labpc.sh", CONFIG)
        return 2   # il servizio non riprova (RestartPreventExitStatus=2): senza configurazione non servirebbe
    if config.get("dettagli"):
        logging.getLogger("fit").setLevel(logging.DEBUG)
        logging.getLogger("bleak.backends.bluezdbus").setLevel(logging.DEBUG)
    if "--prova" in sys.argv:
        return prova(config)
    log.info("avviata: %s%s", config["url"].split("/")[2], ", passando da %s" % config["connetti"] if config.get("connetti") else "")
    systemd("READY=1")
    Sentinella(config).lavora()
    return 0


if __name__ == "__main__":
    sys.exit(main())
