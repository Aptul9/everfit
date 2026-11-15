"""Notifiche sul telefono (Web Push), con la sola libreria standard.

Come funziona: il telefono, quando la persona accetta le notifiche, si iscrive presso il servizio del suo sistema (Apple,
Google, Mozilla) e ci da' un indirizzo. Per svegliarlo basta una POST a quell'indirizzo, firmata con la chiave del
server (VAPID, RFC 8292). Qui la POST parte SENZA contenuto: cosi' non serve cifrare niente (per il contenuto ci
vorrebbero AES-GCM e uno scambio di chiavi che la libreria standard non ha). Il testo della notifica il telefono se lo
viene a prendere subito dopo, con il suo cookie, da /api/notifiche/prossime (vedi public/sw.js).

La firma e' ECDSA sulla curva P-256, scritta qui a mano: una sessantina di righe di aritmetica, provate contro OpenSSL
(tools/prove/prova_spinta.py).
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------- la curva P-256 ----------
P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
A = P - 3
N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
     0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def _somma(p, q):
    if p is None:
        return q
    if q is None:
        return p
    (x1, y1), (x2, y2) = p, q
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        k = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        k = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (k * k - x1 - x2) % P
    return x3, (k * (x1 - x3) - y1) % P


def _per(k, p):
    fuori = None
    while k:
        if k & 1:
            fuori = _somma(fuori, p)
        p = _somma(p, p)
        k >>= 1
    return fuori


def pubblica(d):
    """La chiave pubblica (65 byte: 0x04, x, y) di una chiave privata (un numero)."""
    x, y = _per(d, G)
    return b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")


def firma(d, messaggio):
    """La firma ES256 di `messaggio` (64 byte: r e s)."""
    z = int.from_bytes(hashlib.sha256(messaggio).digest(), "big")
    while True:
        k = secrets.randbelow(N - 1) + 1
        r = _per(k, G)[0] % N
        s = pow(k, -1, N) * (z + r * d) % N
        if r and s:
            return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def verifica(pub, messaggio, f):
    """Vero se `f` e' la firma di `messaggio` fatta con la chiave di cui `pub` e' la parte pubblica."""
    q = (int.from_bytes(pub[1:33], "big"), int.from_bytes(pub[33:65], "big"))
    r, s = int.from_bytes(f[:32], "big"), int.from_bytes(f[32:], "big")
    if not (0 < r < N and 0 < s < N):
        return False
    z = int.from_bytes(hashlib.sha256(messaggio).digest(), "big")
    w = pow(s, -1, N)
    punto = _somma(_per(z * w % N, G), _per(r * w % N, q))
    return punto is not None and punto[0] % N == r


# ---------- la chiave del server ----------
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")
_chiave = {}


def chiave(cartella):
    """(privata, pubblica in base64 per il telefono). La privata sta in <data>/vapid.key e si crea la prima volta."""
    if cartella not in _chiave:
        percorso = os.path.join(cartella, "vapid.key")
        try:
            with open(percorso, encoding="ascii") as f:
                d = int(f.read().strip(), 16)
        except (OSError, ValueError):
            d = secrets.randbelow(N - 1) + 1
            with open(os.open(percorso, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="ascii") as f:
                f.write("%064x\n" % d)
        _chiave[cartella] = (d, b64(pubblica(d)))
    return _chiave[cartella]


# ---------- mandare ----------
# I soli servizi a cui il server manda: l'indirizzo arriva dal telefono, e non deve poter diventare una richiesta
# verso un posto qualunque.
SERVIZI = (".push.apple.com", "fcm.googleapis.com", ".push.services.mozilla.com", ".notify.windows.com")
CHI_SIAMO = os.environ.get("FIT_SITO", "https://fit.example.com")
PROVA = os.environ.get("FIT_SPINTA_PROVA", "")   # nelle prove: l'indirizzo (http://127.0.0.1:porta) di un finto servizio


def indirizzo_buono(indirizzo):
    u = urllib.parse.urlsplit(str(indirizzo or ""))
    if PROVA and str(indirizzo).startswith(PROVA):
        return True
    return u.scheme == "https" and bool(u.hostname) and any(u.hostname == s or u.hostname.endswith(s) for s in SERVIZI) and len(str(indirizzo)) < 1000


def spingi(cartella, indirizzo, urgente=True, vita=3600):
    """Sveglia un telefono. Restituisce il codice del servizio (201 = preso in carico; 404 e 410 = l'iscrizione non
    vale piu' e va buttata; 0 = non raggiunto)."""
    if not indirizzo_buono(indirizzo):
        return 0
    d, pub = chiave(cartella)
    u = urllib.parse.urlsplit(indirizzo)
    testa = b64(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    corpo = b64(json.dumps({"aud": "%s://%s" % (u.scheme, u.netloc), "exp": int(time.time()) + 12 * 3600, "sub": CHI_SIAMO}, separators=(",", ":")).encode())
    gettone = "%s.%s.%s" % (testa, corpo, b64(firma(d, ("%s.%s" % (testa, corpo)).encode("ascii"))))
    richiesta = urllib.request.Request(indirizzo, data=b"", method="POST", headers={
        "TTL": str(int(vita)), "Urgency": "high" if urgente else "normal", "Content-Length": "0",
        "Authorization": "vapid t=%s, k=%s" % (gettone, pub)})
    try:
        with urllib.request.urlopen(richiesta, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        try:
            perche = e.read()[:200].decode("utf-8", "replace")
        except Exception:
            perche = ""
        print("notifiche: %s ha risposto %s %s" % (u.hostname, e.code, perche), flush=True)
        return e.code
    except (OSError, ValueError) as e:
        print("notifiche: %s non raggiunto (%s)" % (u.hostname, type(e).__name__), flush=True)
        return 0
