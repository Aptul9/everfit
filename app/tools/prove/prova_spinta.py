"""Prova la firma delle notifiche (server/spinta.py) contro OpenSSL: una chiave fatta qui, una firma fatta qui, e
OpenSSL che la verifica; poi il contrario non serve (al servizio di Apple o Google basta poter verificare).

    python tools/prove/prova_spinta.py        (dalla cartella app; serve il comando openssl)
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "server"))
import spinta  # noqa: E402

# due punti noti della curva: 1*G e 2*G (dal documento NIST)
assert spinta.pubblica(1)[1:33].hex() == "6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296"
assert spinta.pubblica(2)[1:33].hex() == "7cf27b188d034f7e8a52380304b51ac3c08969e277f21b35a60b48fc47669978"
print("ok   punti della curva")

d = 0x1F2E3D4C5B6A79880123456789ABCDEFFEDCBA98765432100F1E2D3C4B5A6978
pub = spinta.pubblica(d)
messaggio = b"eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9.eyJhdWQiOiJodHRwczovL3dlYi5wdXNoLmFwcGxlLmNvbSJ9"
f = spinta.firma(d, messaggio)
assert spinta.verifica(pub, messaggio, f) and not spinta.verifica(pub, messaggio + b"x", f)
print("ok   firma e verifica in casa")

# la chiave pubblica come la vuole OpenSSL (SubjectPublicKeyInfo) e la firma in DER
spki = bytes.fromhex("3059301306072a8648ce3d020106082a8648ce3d030107034200") + pub
intero = lambda b: (lambda v: b"\x02" + bytes([len(v)]) + v)((b"\x00" if b.lstrip(b"\x00")[:1] >= b"\x80" else b"") + (b.lstrip(b"\x00") or b"\x00"))
r, s = intero(f[:32]), intero(f[32:])
der = b"\x30" + bytes([len(r) + len(s)]) + r + s
with tempfile.TemporaryDirectory() as cartella:
    percorso = lambda nome: os.path.join(cartella, nome)
    open(percorso("pub.der"), "wb").write(spki)
    open(percorso("firma.der"), "wb").write(der)
    open(percorso("messaggio"), "wb").write(messaggio)
    esito = subprocess.run(["openssl", "dgst", "-sha256", "-verify", percorso("pub.der"), "-keyform", "DER", "-signature", percorso("firma.der"), percorso("messaggio")],
                           capture_output=True, text=True)
    print(("ok   " if "Verified OK" in esito.stdout else "ERRORE ") + "OpenSSL verifica la firma: " + (esito.stdout + esito.stderr).strip())
    sys.exit(0 if "Verified OK" in esito.stdout else 1)
