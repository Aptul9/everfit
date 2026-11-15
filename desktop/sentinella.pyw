#!/usr/bin/env python3
"""FitFuel bilancia: la sentinella.

Sta tra le icone vicino all'orologio e aspetta. Quando dal telefono si preme «Pesati ora» la richiesta arriva
al server; lei la raccoglie, fa la pesata con la bilancia via Bluetooth e manda indietro avanzamenti e risultato
(il telefono non puo' farlo da solo: Safari non ha il Bluetooth). Si avvia da sola con Windows; dal menu
dell'icona si chiude, o si toglie l'avvio automatico.

Finche' il PC e' attaccato alla corrente gli chiede di non addormentarsi da solo: il PC del capo e' un portatile
con lo standby moderno, e addormentato non risponde al telefono (il 14/10/2026 dormiva dalle 02:31 alle 09:16, proprio
quando ci si pesa). Lo schermo si spegne lo stesso; chiudendo il coperchio o premendo il tasto di accensione si
addormenta come sempre; a batteria non si chiede niente. Dal menu dell'icona: "Tieni sveglio il PC in carica".

    pythonw sentinella.pyw           avvio normale
    python  sentinella.pyw --prova   controlla server, Bluetooth e avvio automatico, stampa l'esito ed esce

Usa lo stesso config.json dell'app per PC e scrive in sentinella.log.
"""
import ctypes
import json
import logging
import msvcrt
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import winreg
from ctypes import wintypes

import bilancia
from comune import CASA, QUI, dettagli, in_esecuzione, leggi_config, registro, ricorda, unica

NOME = "Fit bilancia"       # il nome nel registro di Windows (avvio automatico): resta quello di quando l'app si chiamava Fit
MOSTRA = "FitFuel bilancia"  # il nome che si legge: icona, menu, avvisi
IDENTITA = "com.example.fitfuel.sentinella"
APP = "com.example.fitfuel"
AVVIO = r"Software\Microsoft\Windows\CurrentVersion\Run"
log = logging.getLogger("fit.sentinella")

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


# ---------- il PC attaccato alla corrente resta sveglio ----------
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
kernel32.SetThreadExecutionState.restype = ctypes.c_uint
kernel32.SetThreadExecutionState.argtypes = [ctypes.c_uint]


class ALIMENTAZIONE(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]


kernel32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(ALIMENTAZIONE)]


def in_carica():
    """True se il PC e' attaccato alla corrente (un PC fisso lo e' sempre)."""
    a = ALIMENTAZIONE()
    return bool(kernel32.GetSystemPowerStatus(ctypes.byref(a))) and a.ACLineStatus == 1


# ---------- avvio automatico ----------
def comando_avvio():
    # sempre pythonw, anche se per una prova e' stata lanciata con python: all'avvio di Windows non deve aprirsi una console
    return '"%s" "%s"' % (sys.executable.replace("python.exe", "pythonw.exe"), QUI / "sentinella.pyw")


def avvio_automatico():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AVVIO) as chiave:
            return winreg.QueryValueEx(chiave, NOME)[0] == comando_avvio()
    except OSError:
        return False


def metti_avvio(acceso):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, AVVIO, 0, winreg.KEY_SET_VALUE) as chiave:
        if acceso:
            winreg.SetValueEx(chiave, NOME, 0, winreg.REG_SZ, comando_avvio())
        else:
            try:
                winreg.DeleteValue(chiave, NOME)
            except OSError:
                pass


def appdata_privata():
    """True se a lanciarmi e' stato un programma dello Store: quello che scrivo nel profilo (AppData, e con lei
    le impostazioni dell'utente) finisce in una sua copia privata, e fuori da li' non esiste. In quel caso
    l'avvio automatico non va registrato da qui: lo fa la prima copia aperta dal desktop."""
    percorso = os.path.join(os.environ.get("APPDATA", ""), "fit-%d.tmp" % os.getpid())
    try:
        with open(percorso, "w") as f:
            vero = ctypes.create_unicode_buffer(1024)
            kernel32.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
            kernel32.GetFinalPathNameByHandleW(wintypes.HANDLE(msvcrt.get_osfhandle(f.fileno())), vero, 1024, 0)
        os.remove(percorso)
        return "\\packages\\" in vero.value.lower()
    except OSError:
        return False


# ---------- il server ----------
class Server:
    def __init__(self, base):
        self.base = base if base.endswith("/") else base + "/"

    def chiama(self, metodo, percorso, corpo=None, attesa=15):
        dati = json.dumps(corpo).encode("utf-8") if corpo is not None else None
        richiesta = urllib.request.Request(self.base + percorso, data=dati, method=metodo,
                                           headers={"Content-Type": "application/json", "User-Agent": "FitSentinella/1.0"})
        with urllib.request.urlopen(richiesta, timeout=attesa) as risposta:
            return None if risposta.status == 204 else json.load(risposta)


# ---------- l'icona vicino all'orologio ----------
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class GUID(ctypes.Structure):
    _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD), ("d", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON), ("szTip", wintypes.WCHAR * 128),
                ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.LPVOID]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.RegisterWindowMessageW.restype = wintypes.UINT
user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

MSG_ICONA = 0x8001        # WM_APP + 1: clic sull'icona
MSG_STATO = 0x8002        # WM_APP + 2: il lavoro in sottofondo chiede di aggiornare la scritta
APRI, AVVIA, REGISTRO, SVEGLIO, ESCI = 1, 2, 3, 4, 9


class Icona:
    def __init__(self, sentinella):
        self.s = sentinella
        self.hwnd = None
        self.proc = WNDPROC(self._messaggio)   # va tenuto: Windows lo chiama finche' la finestra esiste
        self.rinascita = user32.RegisterWindowMessageW("TaskbarCreated")
        self.saluto = None

    def _dati(self, flag):
        d = NOTIFYICONDATAW()
        d.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        d.hWnd = self.hwnd
        d.uID = 1
        d.uFlags = flag
        d.uCallbackMessage = MSG_ICONA
        d.hIcon = self.icona
        d.szTip = ("%s · %s" % (MOSTRA, self.s.stato))[:127]
        return d

    def crea(self):
        modulo = kernel32.GetModuleHandleW(None)
        classe = WNDCLASSW()
        classe.lpfnWndProc = self.proc
        classe.hInstance = modulo
        classe.lpszClassName = "FitSentinella"
        user32.RegisterClassW(ctypes.byref(classe))
        # finestra invisibile: serve solo a ricevere i clic sull'icona
        self.hwnd = user32.CreateWindowExW(0, "FitSentinella", MOSTRA, 0, 0, 0, 0, 0, None, None, modulo, None)
        lato = user32.GetSystemMetrics(49) or 16                                         # SM_CXSMICON: la misura delle icone piccole
        self.icona = user32.LoadImageW(None, str(QUI / "fit.ico"), 1, lato, lato, 0x10)  # IMAGE_ICON, da file
        shell32.Shell_NotifyIconW(0, ctypes.byref(self._dati(1 | 2 | 4)))                # NIM_ADD: messaggi, icona, scritta

    def aggiorna(self):
        """Si puo' chiamare da qualunque thread: la scritta viene cambiata dal thread della finestra."""
        if self.hwnd:
            user32.PostMessageW(self.hwnd, MSG_STATO, 0, 0)

    def avvisa(self, titolo, testo):
        self.saluto = (titolo, testo)
        self.aggiorna()

    def _menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, 1, 0, "%s · %s" % (MOSTRA, self.s.stato))            # riga di stato, grigia
        user32.AppendMenuW(menu, 0x800, 0, None)
        user32.AppendMenuW(menu, 0, APRI, "Apri FitFuel")
        privata = self.s.privata
        user32.AppendMenuW(menu, (1 if privata else 0) | (8 if avvio_automatico() else 0), AVVIA, "Avvia con Windows")
        user32.AppendMenuW(menu, 8 if self.s.config.get("sveglio", True) else 0, SVEGLIO, "Tieni sveglio il PC in carica")
        user32.AppendMenuW(menu, 0, REGISTRO, "Apri il registro")
        user32.AppendMenuW(menu, 0x800, 0, None)
        user32.AppendMenuW(menu, 0, ESCI, "Esci")
        punto = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(punto))
        user32.SetForegroundWindow(self.hwnd)   # senza, il menu non si chiude cliccando altrove
        scelta = user32.TrackPopupMenu(menu, 0x0002 | 0x0100 | 0x0080, punto.x, punto.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, 0, 0, 0)
        user32.DestroyMenu(menu)
        if scelta == APRI:
            self.s.apri_fit()
        elif scelta == AVVIA:
            acceso = not avvio_automatico()
            metti_avvio(acceso)
            ricorda("avvio", acceso)
        elif scelta == SVEGLIO:
            acceso = not self.s.config.get("sveglio", True)
            self.s.config["sveglio"] = acceso
            ricorda("sveglio", acceso)
            self.s.cambio.set()
        elif scelta == REGISTRO:
            os.startfile(str(CASA / "sentinella.log"))
        elif scelta == ESCI:
            self.s.chiudi()
            shell32.Shell_NotifyIconW(2, ctypes.byref(self._dati(0)))   # NIM_DELETE
            user32.DestroyWindow(self.hwnd)

    def _messaggio(self, hwnd, msg, wparam, lparam):
        try:
            if msg == MSG_ICONA:
                if lparam in (0x0202, 0x0205, 0x007B):   # un clic, sinistro o destro: il menu
                    self._menu()
                return 0
            if msg == MSG_STATO:
                d = self._dati(4)
                if self.saluto:
                    d.uFlags |= 0x10                # NIF_INFO: il fumetto
                    d.szInfoTitle, d.szInfo = self.saluto[0][:63], self.saluto[1][:255]
                    d.dwInfoFlags = 1 | 0x80        # icona "informazione", rispetta le ore di quiete
                    self.saluto = None
                shell32.Shell_NotifyIconW(1, ctypes.byref(d))   # NIM_MODIFY
                return 0
            if msg == self.rinascita:               # Esplora risorse e' ripartito: l'icona va rimessa
                shell32.Shell_NotifyIconW(0, ctypes.byref(self._dati(1 | 2 | 4)))
                return 0
            if msg == 0x0002:                       # WM_DESTROY
                user32.PostQuitMessage(0)
                return 0
        except Exception:
            log.exception("icona")
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def ciclo(self):
        m = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(m), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(m))
            user32.DispatchMessageW(ctypes.byref(m))


# ---------- il lavoro ----------
class Sentinella:
    def __init__(self, config):
        self.config = config
        self.server = Server(config["url"])
        self.stato = "parto"
        self.fine = threading.Event()
        self.cambio = threading.Event()   # e' cambiata l'opzione "tieni sveglio": il filo che veglia ricontrolla subito
        self.ferma_pesata = None
        self.privata = appdata_privata()
        self.icona = Icona(self)

    def dico(self, stato):
        if stato != self.stato:
            self.stato = stato
            log.info(stato)
            self.icona.aggiorna()

    def apri_fit(self):
        try:
            subprocess.Popen([sys.executable, str(QUI / "fit_pc.pyw")], cwd=str(QUI))
        except OSError:
            log.exception("non riesco ad aprire FitFuel")

    def chiudi(self):
        log.info("chiusa dal menu")
        self.fine.set()
        if self.ferma_pesata:
            self.ferma_pesata.set()

    def pesa(self, lavoro):
        ident = lavoro["id"]
        stop = self.ferma_pesata = threading.Event()
        finita = threading.Event()
        self.dico("sto pesando")

        def notizia(**cosa):
            try:
                risposta = self.server.chiama("POST", "api/bilancia/notizie", dict(id=ident, **cosa), attesa=10)
                if risposta and risposta.get("annullata") and "esito" not in cosa:
                    stop.set()
            except (OSError, ValueError) as e:
                log.warning("notizia non consegnata: %r", e)

        def battito():
            # mentre pesa non aspetta lavoro: si fa sentire lo stesso, e cosi' sa se dal telefono hanno annullato
            while not finita.wait(2):
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
            esito = {"ok": False, "errore": "Qualcosa e' andato storto sul PC. Riprova; se succede ancora guarda sentinella.log."}
        finita.set()
        self.ferma_pesata = None
        log.info("pesata finita: %s", {k: v for k, v in esito.items() if k != "memoria"} | {"in_memoria": len(esito.get("memoria") or [])})
        notizia(esito=esito)
        if esito.get("ok") and esito.get("indirizzo") and esito["indirizzo"] != self.config.get("bilancia"):
            self.config["bilancia"] = esito["indirizzo"]
            ricorda("bilancia", esito["indirizzo"])

    def lavora(self):
        pausa = 2
        try:
            self.server.chiama("GET", "api/health", attesa=10)
            self.dico("in attesa")
        except (OSError, ValueError):
            self.dico("il server non risponde")
        while not self.fine.is_set():
            try:
                lavoro = self.server.chiama("GET", "api/bilancia/lavoro?attesa=25", attesa=40)
                pausa = 2
            except (OSError, ValueError) as e:
                self.dico("il server non risponde")
                log.debug("attesa fallita: %r", e)
                self.fine.wait(pausa)
                pausa = min(60, pausa * 2)
                continue
            if lavoro and not self.fine.is_set():
                self.pesa(lavoro)
            self.dico("in attesa")

    def veglia(self):
        """Il filo che tiene sveglio il PC. La richiesta a Windows vale finche' questo filo e' vivo; si ricontrolla ogni
        minuto, e subito quando dal menu si cambia l'opzione: attaccato alla corrente sveglio, altrimenti libero."""
        sveglio = None
        while not self.fine.is_set():
            vuole = bool(self.config.get("sveglio", True)) and in_carica()
            if vuole != sveglio:
                kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if vuole else 0))
                log.info("PC tenuto sveglio: e' attaccato alla corrente" if vuole else "PC libero di addormentarsi")
                sveglio = vuole
            self.cambio.wait(60)
            self.cambio.clear()
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)

    def parti(self):
        self.icona.crea()
        threading.Thread(target=self.veglia, name="veglia", daemon=True).start()
        # la prima copia aperta fuori da un programma dello Store si iscrive da sola all'avvio di Windows
        if self.config.get("avvio", True) and not self.privata and not avvio_automatico():
            try:
                metti_avvio(True)
                log.info("iscritta all'avvio di Windows")
            except OSError:
                log.exception("non riesco a iscrivermi all'avvio di Windows")
        log.info("avviata: %s, avvio automatico %s%s", self.server.base.split("/")[2], avvio_automatico(),
                 ", profilo privato di un programma dello Store" if self.privata else "")
        threading.Thread(target=self.lavora, name="lavoro", daemon=True).start()
        if not self.config.get("salutata"):
            ricorda("salutata", True)
            self.icona.avvisa("FitFuel bilancia è accesa", "Resta qui tra le icone. Dal telefono premi «Pesati ora», sali sulla bilancia e ci pensa lei.")
        self.icona.ciclo()


def prova(config):
    esito = {"avvio_automatico": avvio_automatico(), "profilo_privato": appdata_privata(), "gia_accesa": in_esecuzione(IDENTITA),
             "in_carica": in_carica(), "tiene_sveglio": bool(config.get("sveglio", True))}
    try:
        server = Server(config["url"])
        esito["server"] = bool(server.chiama("GET", "api/health").get("ok"))
        esito["sentinella_vista_dal_server"] = server.chiama("GET", "api/bilancia/sentinella")
    except (OSError, ValueError) as e:
        esito["server"] = repr(e)
    esito["bluetooth"] = bilancia.radio_pronta()
    print(json.dumps(esito, ensure_ascii=False))
    return 0 if esito.get("server") is True and esito["bluetooth"].get("ok") else 1


def main():
    registro("sentinella")
    config = leggi_config()
    if not config:
        user32.MessageBoxW(None, "Manca l'indirizzo dell'app: rilancia installa.py --url https://.../", MOSTRA, 0x10)
        return 2
    dettagli(config)
    if "--prova" in sys.argv:
        return prova(config)
    if not unica(IDENTITA):
        return 0
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP + ".sentinella")
    Sentinella(config).parti()
    return 0


if __name__ == "__main__":
    sys.exit(main())
