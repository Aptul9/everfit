#!/usr/bin/env python3
"""FitFuel per PC: l'app del telefono in una finestra, con in piu' il collegamento Bluetooth alla bilancia.

    pythonw fit_pc.pyw            apre l'app
    python  fit_pc.pyw --prova    apre, controlla che pagina, ponte con la bilancia e Bluetooth rispondano, e chiude

Accanto alla cartella dell'app (o nella cartella indicata da FIT_CASA) tiene:
    config.json   {"url": "https://.../<percorso segreto>/", "bilancia": "indirizzo dell'ultima bilancia usata",
                   "dettagli": true per avere nel registro ogni pacchetto della bilancia e i passi del collegamento}
    fit.log       cosa e' successo, per capire un errore
    web/          cookie e copia per l'uso senza rete (profilo del browser interno)

La pagina chiama window.pywebview.api.misura(profilo) e riceve gli avanzamenti su window.fitBilancia({fase, kg}).
I dati non restano qui: la pagina li manda al database del server, come dal telefono.

Aprendola parte anche la sentinella (sentinella.pyw), se non e' gia' accesa: e' lei che fa le pesate chieste dal telefono.
"""
import ctypes
import json
import logging
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from urllib.parse import urlsplit

from comune import CASA, CONFIG, QUI, dettagli, in_esecuzione, leggi_config, registro, ricorda, unica

TITOLO = "FitFuel"
IDENTITA = "com.example.fitfuel"
SENTINELLA = "com.example.fitfuel.sentinella"
SFONDO = "#090a0d"
LARGHEZZA, ALTEZZA = 480, 900

log = logging.getLogger("fit.pc")
user32 = ctypes.WinDLL("user32", use_last_error=True)


def avviso(testo):
    user32.MessageBoxW(None, testo, TITOLO, 0x10)


def porta_davanti():
    """C'e' gia' una finestra di FitFuel: invece di aprirne un'altra (due parlerebbero insieme con la bilancia) la mostra."""
    user32.FindWindowW.restype = wintypes.HWND
    # "Fit" e' il titolo di una finestra rimasta aperta da prima che l'app cambiasse nome
    finestra = user32.FindWindowW(None, TITOLO) or user32.FindWindowW(None, "Fit")
    if finestra:
        user32.ShowWindow(wintypes.HWND(finestra), 9)  # SW_RESTORE
        user32.SetForegroundWindow(wintypes.HWND(finestra))


def accendi_sentinella(config):
    if config.get("sentinella", True) and not in_esecuzione(SENTINELLA):
        try:
            subprocess.Popen([sys.executable.replace("python.exe", "pythonw.exe"), str(QUI / "sentinella.pyw")], cwd=str(QUI))
        except OSError:
            log.exception("la sentinella non parte")


def altezza_finestra():
    """Alta come un telefono, ma dentro lo schermo: l'area di lavoro in pixel logici, meno un margine."""
    try:
        area = wintypes.RECT()
        user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0)  # SPI_GETWORKAREA
        logica = (area.bottom - area.top) * 96 / (user32.GetDpiForSystem() or 96)
        return int(max(560, min(ALTEZZA, logica - 48)))
    except Exception:
        return 760


def vesti(finestra):
    """Barra del titolo scura, dello stesso colore dell'app."""
    try:
        try:
            hwnd = finestra.native.Handle.ToInt64()
        except Exception:
            user32.FindWindowW.restype = wintypes.HWND
            hwnd = user32.FindWindowW(None, TITOLO)
        if not hwnd:
            return
        hwnd = wintypes.HWND(hwnd)
        dwm = ctypes.WinDLL("dwmapi")
        scuro = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(scuro), 4)       # DWMWA_USE_IMMERSIVE_DARK_MODE
        colore = ctypes.c_int(0x000D0A09)                                 # #090a0d scritto come 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(colore), 4)      # DWMWA_CAPTION_COLOR (Windows 11)
    except Exception:
        log.exception("non riesco a scurire la barra del titolo")


class Ponte:
    """Quello che la pagina puo' chiedere al PC. I nomi con il trattino basso restano fuori dalla pagina."""

    def __init__(self, config):
        self._config = config
        self._finestra = None
        self._stop = threading.Event()
        self._occupato = threading.Lock()
        self._origine = "{0.scheme}://{0.netloc}/".format(urlsplit(config["url"]))

    def _evento(self, fase, kg=None):
        try:
            self._finestra.evaluate_js("window.fitBilancia && window.fitBilancia(%s)" % json.dumps({"fase": fase, "kg": kg}))
        except Exception:
            log.exception("avanzamento non consegnato")

    def misura(self, profilo=None):
        """Aspetta la bilancia, fa la pesata e la restituisce alla pagina."""
        # la bilancia si offre solo all'app: non a una pagina qualsiasi finita dentro la finestra
        if not (self._finestra.get_current_url() or "").startswith(self._origine):
            return {"ok": False, "errore": "La bilancia funziona solo dentro FitFuel."}
        if not self._occupato.acquire(blocking=False):
            return {"ok": False, "errore": "Sto gia' pesando: aspetta che finisca."}
        try:
            import bilancia
            self._stop.clear()
            log.info("pesata chiesta")
            esito = bilancia.misura(profilo or {}, evento=self._evento, stop=self._stop, indirizzo=self._config.get("bilancia"))
            log.info("pesata finita: %s", {k: v for k, v in esito.items() if k != "memoria"} | {"in_memoria": len(esito.get("memoria") or [])})
            if esito.get("ok") and esito.get("indirizzo") and esito["indirizzo"] != self._config.get("bilancia"):
                self._config["bilancia"] = esito["indirizzo"]
                ricorda("bilancia", esito["indirizzo"])
            return esito
        except Exception:
            log.exception("pesata fallita")
            return {"ok": False, "errore": "Qualcosa e' andato storto con la bilancia. Riprova; se succede ancora guarda il file fit.log."}
        finally:
            self._occupato.release()

    def annulla(self):
        self._stop.set()
        return True


def controlla(finestra, esito):
    """Per --prova: aspetta pagina e ponte, guarda che la schermata delle misure offra la bilancia, poi chiude."""
    try:
        fine = time.time() + 45
        while time.time() < fine:
            stato = finestra.evaluate_js(
                "({pagina: !!document.getElementById('tabbar'),"
                " ponte: !!(window.pywebview && window.pywebview.api && window.pywebview.api.misura && window.pywebview.api.annulla),"
                " titolo: document.title, larghezza: innerWidth, altezza: innerHeight})")
            esito.update(stato or {})
            if esito.get("pagina") and esito.get("ponte"):
                break
            time.sleep(0.5)
        finestra.evaluate_js("location.hash = '#/progressi'")
        time.sleep(1.5)
        esito["pesati_ora"] = bool(finestra.evaluate_js("[...document.querySelectorAll('button')].some((b) => b.textContent.includes('Pesati ora'))"))
        import bilancia
        esito["bluetooth"] = bilancia.radio_pronta()
    except Exception as e:
        log.exception("prova fallita")
        esito["eccezione"] = repr(e)
    finally:
        finestra.destroy()


def main():
    prova = "--prova" in sys.argv
    registro("fit")
    config = leggi_config()
    if not config:
        avviso("Manca l'indirizzo dell'app.\n\nRilancia l'installazione:\n    python installa.py --url https://.../\n\n(%s)" % CONFIG)
        return 2
    if not prova:
        accendi_sentinella(config)
        if not unica(IDENTITA):
            porta_davanti()
            return 0
    dettagli(config)
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(IDENTITA)

    import webview
    from importlib.metadata import version

    log.info("avvio: %s, pywebview %s, bleak %s", urlsplit(config["url"]).hostname, version("pywebview"), version("bleak"))
    webview.settings["ALLOW_DOWNLOADS"] = True  # l'esportazione dei dati dalla scheda Piano
    ponte = Ponte(config)
    finestra = webview.create_window(TITOLO, config["url"], js_api=ponte, width=LARGHEZZA, height=altezza_finestra(),
                                     min_size=(380, 560), background_color=SFONDO)
    ponte._finestra = finestra
    finestra.events.shown += lambda: vesti(finestra)
    finestra.events.closing += lambda: ponte._stop.set()
    opzioni = {"private_mode": False, "storage_path": str(CASA / "web"), "icon": str(QUI / "fit.ico")}
    if not prova:
        webview.start(**opzioni)
        return 0
    esito = {}
    webview.start(controlla, (finestra, esito), **opzioni)
    print(json.dumps(esito, ensure_ascii=False))
    return 0 if esito.get("pagina") and esito.get("ponte") and esito.get("pesati_ora") else 1


if __name__ == "__main__":
    sys.exit(main())
