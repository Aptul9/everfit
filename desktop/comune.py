"""Quello che l'app per PC e la sentinella hanno in comune: cartelle, configurazione, registro, una sola copia per volta."""
import ctypes
import json
import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

QUI = Path(__file__).resolve().parent
CASA = Path(os.environ.get("FIT_CASA") or QUI.parent)
CONFIG = CASA / "config.json"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_tenuti = []   # i mutex devono restare aperti finche' il programma vive


def registro(nome="fit"):
    """Scrive in CASA\\<nome>.log (300 KB, una copia vecchia). pythonw non ha una console: tutto finisce li'."""
    CASA.mkdir(parents=True, exist_ok=True)
    gestore = logging.handlers.RotatingFileHandler(CASA / (nome + ".log"), maxBytes=300_000, backupCount=1, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[gestore], format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("bleak").setLevel(logging.WARNING)
    if sys.stdout is None:
        sys.stdout = sys.stderr = open(os.devnull, "w")
    log = logging.getLogger("fit")
    sys.excepthook = lambda *e: log.error("errore non gestito", exc_info=e)
    threading.excepthook = lambda a: log.error("errore in %s", a.thread.name if a.thread else "?", exc_info=(a.exc_type, a.exc_value, a.exc_traceback))


def dettagli(config):
    """Con "dettagli": true nel config, nel registro finiscono anche i pacchetti della bilancia e i passi del collegamento."""
    if config.get("dettagli"):
        logging.getLogger("fit").setLevel(logging.DEBUG)
        logging.getLogger("bleak.backends.winrt.client").setLevel(logging.DEBUG)


def leggi_config():
    """Il contenuto di config.json, o None se manca o l'indirizzo non e' sicuro."""
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    url = config.get("url", "")
    sicuro = url.startswith("https://") or urlsplit(url).hostname in ("localhost", "127.0.0.1")
    return config if sicuro else None


def ricorda(chiave, valore):
    """Cambia una sola voce di config.json: app e sentinella lo scrivono entrambe, nessuna deve coprire l'altra."""
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    if config.get(chiave) == valore:
        return
    config[chiave] = valore
    provvisorio = CONFIG.with_suffix(".%d.tmp" % os.getpid())
    provvisorio.write_text(json.dumps(config, indent=1), encoding="utf-8")
    os.replace(provvisorio, CONFIG)


def unica(identita):
    """True se questa e' la sola copia in esecuzione con quel nome (e da ora lo resta)."""
    maniglia = kernel32.CreateMutexW(None, False, identita)
    if ctypes.get_last_error() == 183:   # ERROR_ALREADY_EXISTS
        return False
    _tenuti.append(maniglia)
    return True


def in_esecuzione(identita):
    """True se un altro programma tiene gia' quel nome."""
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    maniglia = kernel32.OpenMutexW(0x00100000, False, identita)   # SYNCHRONIZE
    if maniglia:
        kernel32.CloseHandle(ctypes.c_void_p(maniglia))
    return bool(maniglia)
