"""Chi entra nell'app: account, password e cookie.

Ogni persona ha un account con un nome, un nome utente e una password. Si scrivono una volta per dispositivo:
da li' in poi il dispositivo ha un cookie (fitk) legato a quell'account, rinnovato a ogni apertura, e non li
chiede piu'. Ognuno vede solo i propri dati.

Il primo account e' quello del capo (id 1), l'unico amministratore: e' l'unico che vede e crea le altre persone
(Piano -> Persone). Il suo codice sta in FIT_CODICE (/opt/fit/accesso.env) e vale sia da solo, come prima, sia come
password insieme al suo nome utente. Delle password degli altri nel database c'e' solo l'impasto (PBKDF2): non si
possono rileggere, solo cambiare.

Entrano senza codice, come capo:
  - le richieste che Caddy segna con "X-Fit-Accesso: ok" perche' arrivano dal percorso segreto (l'app per PC e la
    sentinella della bilancia); Caddy toglie quell'intestazione a tutte le altre;
  - il vecchio cookie uguale per tutti (FIT_COOKIE), che Caddy da' ancora a chi passa dal percorso segreto.
Senza FIT_CODICE (in locale) non c'e' nessun controllo e tutto e' del capo.

L'icona sulla schermata Home dell'iPhone ha una memoria separata da Safari e ripartirebbe senza cookie: per non
far riscrivere il codice, l'indirizzo di avvio scritto nel manifest porta con se' una chiave (dopo il #, cosi' non
arriva mai al server dentro un indirizzo) che la pagina del codice scambia con un cookie nuovo.
"""
import hashlib
import hmac
import html
import os
import re
import secrets
import threading
import time
from collections import deque
from urllib.parse import quote

COOKIE_VECCHIO = os.environ.get("FIT_COOKIE", "").strip()
CODICE_CAPO = "".join(ch for ch in os.environ.get("FIT_CODICE", "") if ch.isalnum())
NOME_CAPO = os.environ.get("FIT_NOME", "").strip() or "Admin"
ACCESO = bool(CODICE_CAPO)
CAPO = 1
ITERAZIONI = 240_000              # giri di PBKDF2 per le password: qualche decimo di secondo a tentativo
RE_UTENTE = re.compile(r"[a-z0-9][a-z0-9._-]{2,23}")
DURATA = 400 * 86400              # i browser non tengono un cookie piu' a lungo: viene rinnovato a ogni apertura
MAX_SBAGLI, FINESTRA = 30, 3600   # codici sbagliati ammessi in un'ora, da chiunque arrivino

# le misure degli schermi di iPhone per cui esiste l'immagine di avvio (tools/make_icons.py le disegna)
SCHERMI = ((320, 568, 2), (375, 667, 2), (414, 736, 3), (375, 812, 3), (414, 896, 2), (414, 896, 3), (390, 844, 3),
           (428, 926, 3), (393, 852, 3), (430, 932, 3), (402, 874, 3), (440, 956, 3), (420, 912, 3))

_sbagli = deque()
_lucchetto = threading.Lock()


def impronta(valore):
    return hashlib.sha256(str(valore).encode("utf-8", "replace")).hexdigest()


def firma(segreto, testo):
    return hmac.new(segreto.encode("utf-8"), testo.encode("utf-8", "replace"), hashlib.sha256).hexdigest()


def uguali(a, b):
    return hmac.compare_digest(str(a).encode("utf-8", "replace"), str(b).encode("utf-8", "replace"))


def pulisci_codice(codice):
    return "".join(ch for ch in str(codice or "") if ch.isalnum())[:40]


def nome_utente(testo):
    """Il nome utente in minuscolo, oppure None se non e' fatto di lettere, cifre, punti e trattini (3-24 caratteri)."""
    u = str(testo or "").strip().lower()
    return u if RE_UTENTE.fullmatch(u) else None


UTENTE_CAPO = nome_utente(os.environ.get("FIT_UTENTE") or NOME_CAPO) or "admin"


def impasta(password, sale=None):
    sale = sale or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), bytes.fromhex(sale), ITERAZIONI).hex()
    return "pbkdf2$%d$%s$%s" % (ITERAZIONI, sale, h)


def combacia(password, impasto):
    try:
        _, giri, sale, atteso = str(impasto).split("$")
        prova = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), bytes.fromhex(sale), int(giri)).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(prova, atteso)


# un impasto qualunque: quando il nome utente non esiste si fa lo stesso il conto, cosi' la risposta ci mette uguale
FINTO = impasta(secrets.token_hex(8))


def nuovo_gettone():
    return secrets.token_urlsafe(32)


def troppi_sbagli():
    """True se nell'ultima ora ci sono stati troppi codici sbagliati: non si prova nemmeno."""
    ora = time.time()
    with _lucchetto:
        while _sbagli and ora - _sbagli[0] > FINESTRA:
            _sbagli.popleft()
        return len(_sbagli) >= MAX_SBAGLI


def segna_sbaglio():
    with _lucchetto:
        _sbagli.append(time.time())
    time.sleep(1)   # chi prova a caso va piano


# ---------- cookie ----------
def leggi_cookie(intestazioni, nome):
    for pezzo in (intestazioni.get("Cookie") or "").split(";"):
        chiave, _, valore = pezzo.strip().partition("=")
        if chiave == nome:
            return valore
    return ""


def biscotti(gettone, nome):
    """I due cookie di chi e' dentro: fitk e' la sessione (il codice della pagina non lo vede), fitn e' solo il
    nome, che la schermata di benvenuto legge prima ancora che l'app sia partita."""
    return ["fitk=%s; Path=/; Max-Age=%d; Secure; HttpOnly; SameSite=Lax" % (gettone, DURATA),
            "fitn=%s; Path=/; Max-Age=%d; Secure; SameSite=Lax" % (quote(nome, safe=""), DURATA)]


def biscotti_spenti():
    return ["fitk=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax", "fitn=; Path=/; Max-Age=0; Secure; SameSite=Lax"]


# ---------- pagina del codice ----------
def avvio_iphone(prefisso=""):
    """I <link> delle immagini di avvio: senza, aprendo l'app dalla Home l'iPhone mostra uno schermo bianco."""
    return "\n".join(
        '<link rel="apple-touch-startup-image" href="%sicons/splash-%dx%d.png" media="(device-width: %dpx) and '
        '(device-height: %dpx) and (-webkit-device-pixel-ratio: %d) and (orientation: portrait)">'
        % (prefisso, w * k, h * k, w, h, k) for w, h, k in SCHERMI)


PAGINA = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#090a0d">
<meta name="color-scheme" content="dark">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="FitFuel">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">
<link rel="icon" type="image/png" sizes="192x192" href="/icons/icon-192.png">
__AVVIO__
<title>FitFuel</title>
<style>
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html { background: #090a0d; color-scheme: dark; height: 100%; }
  body { margin: 0; min-height: 100%; display: grid; place-items: center;
    padding: calc(env(safe-area-inset-top, 0px) + 24px) 24px calc(env(safe-area-inset-bottom, 0px) + 24px);
    font: 16px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #f4f5f7;
    background: radial-gradient(90% 46% at 50% -8%, rgba(200, 255, 77, .13), transparent 70%) #090a0d;
    -webkit-user-select: none; user-select: none; }
  form { width: 100%; max-width: 340px; display: flex; flex-direction: column; gap: 14px; text-align: center; }
  img { width: 88px; height: 88px; border-radius: 24px; margin: 0 auto 6px; display: block; }
  h1 { margin: 0; font-size: 32px; font-weight: 800; letter-spacing: -.025em; }
  h1 em { font-style: normal; color: #c8ff4d; }
  .firma { position: fixed; left: 0; right: 0; bottom: calc(env(safe-area-inset-bottom, 0px) + 18px); text-align: center; font-size: 11.5px; color: #6d7282; }
  p { margin: 0; color: #a6abb8; font-size: 15px; }
  input { height: 58px; border-radius: 18px; border: 1.5px solid transparent; background: #1c1f26; color: #f4f5f7;
    font: 600 18px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; text-align: center; outline: none; width: 100%;
    -webkit-user-select: text; user-select: text; }
  input::placeholder { color: #6d7282; font-weight: 500; }
  input:focus { border-color: #c8ff4d; }
  button { height: 56px; border: 0; border-radius: 18px; font-family: inherit; font-size: 17px; font-weight: 700; color: #0d1400;
    background: linear-gradient(135deg, #c8ff4d, #6dffa0); transition: transform .15s; }
  button:active { transform: scale(.97); }
  .errore { color: #ff7a7a; font-weight: 600; min-height: 21px; }
  .nascosto { position: absolute; left: -9999px; }
  .entro form > :not(img):not(h1) { visibility: hidden; }
  .giro { display: none; width: 30px; height: 30px; margin: 0 auto; border-radius: 50%; border: 3px solid #262a33; border-top-color: #c8ff4d; animation: g .8s linear infinite; }
  .entro .giro { display: block; position: absolute; left: 50%; top: 58%; margin-left: -15px; }
  @keyframes g { to { transform: rotate(360deg); } }
</style>
</head>
<body>
<form method="post" action="/accedi">
  <img src="/icons/icon-192.png" alt="">
  <h1>Fit<em>Fuel</em></h1>
  <p>Entra con il tuo nome utente.<br>Su questo dispositivo lo chiedo una volta sola.</p>
  <input type="text" name="utente" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" placeholder="Nome utente" aria-label="Nome utente" __FUOCO__>
  <input type="password" name="password" autocomplete="current-password" placeholder="Password" aria-label="Password" required>
  <p class="errore" role="alert">__MESSAGGIO__</p>
  <button type="submit">Entra</button>
</form>
<div class="giro"></div>
<p class="firma">Sviluppata da DIEFFE di Daniele Fortunio &middot; &copy; 2026</p>
<script>
// L'icona sulla Home parte con una chiave dopo il # (vedi accesso.py): la scambio con il cookie senza chiedere il codice.
(function () {
  var m = /[#&]k=([A-Za-z0-9_-]{20,})/.exec(location.hash);
  if (!m) return;
  document.documentElement.className = 'entro';
  var fine = function (dentro) {
    try { history.replaceState(null, '', location.pathname); } catch (e) {}
    if (dentro) location.replace('/'); else document.documentElement.className = '';
  };
  fetch('/accedi', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json' }, body: 'k=' + m[1] })
    .then(function (r) { fine(r.ok); }, function () { fine(false); });
})();
</script>
</body>
</html>
"""


def pagina(messaggio=""):
    return (PAGINA.replace("__AVVIO__", avvio_iphone("/")).replace("__MESSAGGIO__", html.escape(messaggio))
            .replace("__FUOCO__", "autofocus")).encode("utf-8")
