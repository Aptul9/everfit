#!/usr/bin/env python3
"""Fit: serve i file dell'app e conserva i dati di ogni persona in un database SQLite.

Solo libreria standard. Ogni persona ha il suo account (accesso.py): si entra con un codice scritto una volta per
dispositivo, e da li' in poi ogni richiesta vede solo i dati di quell'account. Dal percorso segreto si entra senza
codice come capo, e a dirlo e' Caddy con un'intestazione: per questo il container non va mai esposto direttamente.

    server.py --root public --data /data --port 8080

Database: <data>/fit.db
    utenti           gli account: nome, nome utente e impasto della password. Il primo (id 1) e' il capo
    sessioni         i dispositivi entrati: impronta del cookie -> account
    stato            lo stato dell'app di ciascuno (pasti spuntati, diario, sedute, carichi, profilo)
    stato_storia     una copia al giorno dello stato, per poter tornare indietro
    pesate           ogni pesata: peso, impedenza grezza e composizione corporea calcolata
    circonferenze    le misure prese con il metro, una riga per giorno
    prodotti         i prodotti gia' cercati per codice a barre (vedi cibo.py): sono di tutti
    pareri           i pareri scritti dall'AI sui prodotti, per persona

Intelligenza artificiale (foto dei piatti, parere sui prodotti, assistente): ogni account ha la sua chiave, in
<data>/chiavi/. Chi non ne ha una non usa niente di tutto questo (vedi cibo.py, parere.py, assistente.py).

Bilancia dal telefono: /api/bilancia/... fa da ponte con la sentinella accesa sul PC del capo (vedi ponte.py).
"""
import argparse
import contextlib
import hashlib
import json
import mimetypes
import os
import posixpath
import re
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit
from zoneinfo import ZoneInfo

import accesso
import assistente
import cibo
import parere
import ponte
import spinta

QUI = os.path.dirname(os.path.abspath(__file__))
MAX_CORPO = 2 * 1024 * 1024
GIORNI_STORIA = 30
GIORNI_PRODOTTO = 60     # dopo, un prodotto viene richiesto di nuovo al catalogo
MAX_PERSONE = 30

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("image/svg+xml", ".svg")

SCHEMA = """
CREATE TABLE IF NOT EXISTS utenti (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    codice TEXT NOT NULL UNIQUE,          -- impronta del codice del capo (vedi accesso.py); per gli altri non serve
    utente TEXT,                          -- nome utente, in minuscolo: a lui si aggancia il piano scritto a mano
    password TEXT,                        -- impasto PBKDF2 della password
    capo INTEGER NOT NULL DEFAULT 0,
    creato TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    visto TEXT
);
CREATE TABLE IF NOT EXISTS sessioni (
    impronta TEXT PRIMARY KEY,            -- sha256 del valore del cookie, o della chiave dell'icona sulla Home
    utente INTEGER NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'cookie',  -- cookie oppure casa
    da TEXT,                              -- la chiave "casa" da cui e' nato questo cookie
    creata REAL NOT NULL,
    vista REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessioni_utente ON sessioni (utente);
CREATE TABLE IF NOT EXISTS impostazioni (
    chiave TEXT PRIMARY KEY,
    valore TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stato (
    utente INTEGER PRIMARY KEY,
    aggiornato REAL NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stato_storia (
    utente INTEGER NOT NULL,
    giorno TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY (utente, giorno)
);
CREATE TABLE IF NOT EXISTS pesate (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utente INTEGER NOT NULL DEFAULT 1,
    quando TEXT NOT NULL,                 -- ora locale, AAAA-MM-GGTHH:MM:SS
    giorno TEXT NOT NULL,
    fonte TEXT NOT NULL,                  -- bilancia, memoria (pesata fatta senza app), manuale, starfit
    peso REAL NOT NULL,
    impedenza INTEGER,                    -- ohm, cosi' come li manda la bilancia
    altezza INTEGER, eta INTEGER, sesso TEXT,   -- il profilo usato per il calcolo
    imc REAL, grasso REAL, muscolo REAL, scheletrico REAL, acqua REAL, proteine REAL,
    ossa_kg REAL, sottocutaneo REAL, viscerale REAL, bmr INTEGER, eta_corporea INTEGER,
    algoritmo TEXT,
    nota TEXT,
    creato TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (utente, quando)
);
CREATE INDEX IF NOT EXISTS pesate_di ON pesate (utente, giorno);
CREATE TABLE IF NOT EXISTS passi (
    utente INTEGER NOT NULL,
    giorno TEXT NOT NULL,                 -- AAAA-MM-GG, ora di casa
    passi INTEGER NOT NULL,               -- il totale del giorno come lo dice l'app Salute dell'iPhone
    aggiornato REAL NOT NULL,
    PRIMARY KEY (utente, giorno)
);
CREATE TABLE IF NOT EXISTS circonferenze (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utente INTEGER NOT NULL DEFAULT 1,
    giorno TEXT NOT NULL,
    collo REAL, spalle REAL, petto REAL, vita REAL, fianchi REAL,
    braccio REAL, coscia REAL, polpaccio REAL,
    nota TEXT,
    creato TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    UNIQUE (utente, giorno)
);
CREATE TABLE IF NOT EXISTS prodotti (
    ean TEXT PRIMARY KEY,
    json TEXT NOT NULL,                   -- il prodotto gia' ridotto ai campi che usa l'app
    preso REAL NOT NULL                   -- quando e' stato chiesto al catalogo (secondi unix)
);
CREATE TABLE IF NOT EXISTS pareri (
    utente INTEGER NOT NULL,
    ean TEXT NOT NULL,
    motore TEXT NOT NULL,                 -- quale servizio di AI l'ha scritto
    json TEXT NOT NULL,
    quando REAL NOT NULL,
    PRIMARY KEY (utente, ean)
);
CREATE TABLE IF NOT EXISTS iscrizioni (
    indirizzo TEXT PRIMARY KEY,           -- dove svegliare quel telefono: lo da' il suo servizio di notifiche (vedi spinta.py)
    utente INTEGER NOT NULL,
    fuso INTEGER NOT NULL DEFAULT 120,    -- minuti da aggiungere all'ora UTC per avere quella del telefono
    orari TEXT NOT NULL DEFAULT '{}',     -- {"pranzo": "13:00", "cena": "21:00"}: a che ora mangia, per i promemoria
    promemoria INTEGER NOT NULL DEFAULT 1,
    creata REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS notifiche (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    utente INTEGER NOT NULL,
    etichetta TEXT NOT NULL,              -- una per cosa: "2026-10-11-pranzo", "fitai-<numero del lavoro>"
    titolo TEXT NOT NULL,
    testo TEXT NOT NULL,
    dove TEXT,                            -- dove porta il tocco sulla notifica
    creata REAL NOT NULL,
    consegnata INTEGER NOT NULL DEFAULT 0,
    UNIQUE (utente, etichetta)
)
"""
# le tabelle che prima degli account avevano un solo proprietario: all'avvio passano tutte al capo
DI_UNO = ("stato", "stato_storia", "pesate", "circonferenze")

# campo -> (tipo, minimo, massimo). Tutto il resto del corpo della richiesta viene ignorato.
CAMPI_PESATA = {
    "peso": (float, 20, 300), "impedenza": (int, 0, 3000), "altezza": (int, 80, 250), "eta": (int, 5, 120),
    "imc": (float, 5, 100), "grasso": (float, 1, 75), "muscolo": (float, 5, 100), "scheletrico": (float, 5, 100),
    "acqua": (float, 5, 100), "proteine": (float, 1, 60), "ossa_kg": (float, 0.2, 10),
    "sottocutaneo": (float, 0, 75), "viscerale": (float, 0, 60), "bmr": (int, 300, 6000),
    "eta_corporea": (int, 5, 120),
}
CAMPI_CIRC = ("collo", "spalle", "petto", "vita", "fianchi", "braccio", "coscia", "polpaccio")
FONTI = ("bilancia", "memoria", "manuale", "starfit")
RE_QUANDO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")
RE_GIORNO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# l'ora di casa: il container gira in UTC, e i passi di una sera dopo l'una diventerebbero del giorno prima
FUSO = ZoneInfo(os.environ.get("FIT_FUSO", "Europe/Rome"))


def conta_passi(valore):
    """I passi che manda il comando dell'iPhone: un numero, oppure il testo in cui Comandi trasforma i campioni di
    Salute ("8432", "8.432", "8.432 passi", "8432,0"; con piu' righe, una per campione, si sommano). None se non si capisce."""
    if isinstance(valore, bool) or valore is None:
        return None
    if isinstance(valore, (int, float)):
        n = int(valore)
    elif isinstance(valore, list):
        parti = [conta_passi(v) for v in valore[:2000]]
        if not parti or any(p is None for p in parti):
            return None
        n = sum(parti)
    elif isinstance(valore, str):
        righe = [r for r in re.split(r"[\r\n;]+", valore) if r.strip()]
        if not righe or len(righe) > 2000:
            return None
        n = 0
        for r in righe:
            # via i decimali ("8432,0"), poi le cifre restano quelle del numero ("8.432" e "8 432" sono 8432)
            cifre = re.sub(r"\D", "", re.sub(r"[.,]\d{1,2}(?!\d)", "", r))
            if not cifre:
                return None
            n += int(cifre)
    else:
        return None
    return n if 0 <= n <= 200000 else None
# (i controlli del telefono sulla sentinella, `/api/bilancia/sentinella`, dal 28/10/2026 si vedono: arrivano solo con
# la carta della bilancia aperta, e dicono se il telefono ha chiesto davvero quando "Pesati ora" non c'era)
ZITTI = ("/api/health", "/api/bilancia/lavoro", "/api/state/versione")

_scrittura = threading.Lock()


class Errore(Exception):
    def __init__(self, codice, testo):
        super().__init__(testo)
        self.codice, self.testo = codice, testo


def numero(valore, tipo, minimo, massimo, campo):
    if valore is None or valore == "":
        return None
    try:
        v = tipo(float(valore)) if tipo is int else float(valore)
    except (TypeError, ValueError):
        raise Errore(400, "%s non e' un numero" % campo)
    if not (minimo <= v <= massimo):
        raise Errore(400, "%s fuori dai limiti (%s-%s)" % (campo, minimo, massimo))
    return v


def nome_pulito(nome):
    nome = " ".join("".join(ch for ch in str(nome or "") if ch.isprintable() and ch not in "<>\"&;=").split())[:24].strip()
    if not nome:
        raise Errore(400, "Scrivi un nome")
    return nome


class Dati:
    """Accesso al database. Una connessione per richiesta: SQLite regge benissimo una manciata di persone."""

    def __init__(self, cartella):
        self.cartella = cartella
        os.makedirs(cartella, exist_ok=True)
        self.percorso = os.path.join(cartella, "fit.db")
        with self.apri() as db:
            db.execute("BEGIN IMMEDIATE")   # tutto o niente: se il passaggio agli account si rompe a meta', non resta traccia
            self._prepara(db)
            self.segreto = db.execute("SELECT valore FROM impostazioni WHERE chiave = 'segreto'").fetchone()[0]
            codice = accesso.firma(self.segreto, accesso.CODICE_CAPO) if accesso.ACCESO else "nessuno"
            db.execute("INSERT OR IGNORE INTO utenti (id, nome, codice, capo) VALUES (?, ?, ?, 1)", (accesso.CAPO, accesso.NOME_CAPO, codice))
            db.execute("UPDATE utenti SET codice = ? WHERE id = ?", (codice, accesso.CAPO))
            db.execute("UPDATE utenti SET utente = ? WHERE id = ? AND utente IS NULL", (accesso.UTENTE_CAPO, accesso.CAPO))
            db.execute("DELETE FROM sessioni WHERE vista < ?", (time.time() - accesso.DURATA,))
        self._importa_vecchio_stato()

    @contextlib.contextmanager
    def apri(self):
        """Apre, conferma le modifiche se tutto va bene e chiude sempre."""
        db = sqlite3.connect(self.percorso, timeout=15)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            with db:
                yield db
        finally:
            db.close()

    def _prepara(self, db):
        """Crea le tabelle; se trova quelle di prima degli account (un solo proprietario) le passa al capo."""
        tabelle = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

        def colonne(tabella):
            return [r[1] for r in db.execute("PRAGMA table_info(%s)" % tabella)]

        vecchie = [t for t in DI_UNO if t in tabelle and "utente" not in colonne(t)]
        for t in vecchie:
            db.execute("ALTER TABLE %s RENAME TO %s_v1" % (t, t))
        if vecchie:
            db.execute("DROP INDEX IF EXISTS pesate_giorno")
        if "pareri" in tabelle and "utente" not in colonne("pareri"):
            db.execute("DROP TABLE pareri")   # e' solo una memoria: si riscrivono alla prossima richiesta
        for istruzione in SCHEMA.split(";\n"):
            if istruzione.strip():
                db.execute(istruzione)
        for t in vecchie:
            comuni = ", ".join(c for c in colonne(t + "_v1") if c in colonne(t) and not (t == "stato" and c == "id"))
            db.execute("INSERT INTO %s (utente, %s) SELECT %d, %s FROM %s_v1" % (t, comuni, accesso.CAPO, comuni, t))
            db.execute("DROP TABLE %s_v1" % t)
        if vecchie:
            print("database: passato agli account, i dati di prima sono del capo (%s)" % ", ".join(vecchie), flush=True)
        # gli account nati con il solo codice non avevano nome utente e password
        for colonna in ("utente", "password"):
            if colonna not in colonne("utenti"):
                db.execute("ALTER TABLE utenti ADD COLUMN %s TEXT" % colonna)
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS utenti_utente ON utenti (utente) WHERE utente IS NOT NULL")
        db.execute("INSERT OR IGNORE INTO impostazioni (chiave, valore) VALUES ('segreto', ?)", (accesso.nuovo_gettone(),))

    def _importa_vecchio_stato(self):
        """Prima del database lo stato stava in state.json: lo porta dentro una volta sola."""
        vecchio = os.path.join(self.cartella, "state.json")
        if not os.path.exists(vecchio):
            return
        try:
            with open(vecchio, "rb") as f:
                testo = f.read().decode("utf-8")
            dati = json.loads(testo)
            with self.apri() as db:
                if db.execute("SELECT 1 FROM stato WHERE utente = ?", (accesso.CAPO,)).fetchone() is None and isinstance(dati, dict) and dati:
                    db.execute("INSERT INTO stato (utente, aggiornato, json) VALUES (?, ?, ?)",
                               (accesso.CAPO, float(dati.get("updatedAt") or 0), testo))
            os.replace(vecchio, vecchio + ".importato")
        except Exception as e:  # il file vecchio non deve mai impedire l'avvio
            print("stato vecchio non importato:", e, flush=True)

    # ---- account e dispositivi
    def utente(self, ident):
        with self.apri() as db:
            r = db.execute("SELECT id, nome, capo, utente FROM utenti WHERE id = ?", (ident,)).fetchone()
        return dict(r) if r else None

    def entra(self, nome, segreto):
        """L'account a cui corrispondono nome utente e password, oppure None. Senza nome utente vale solo il codice del capo."""
        nome = str(nome or "").strip().lower()
        segreto = str(segreto or "")
        if not segreto:
            return None
        del_capo = accesso.firma(self.segreto, accesso.pulisci_codice(segreto))
        with self.apri() as db:
            if not nome:
                r = db.execute("SELECT id, nome, capo, utente FROM utenti WHERE codice = ? AND capo = 1", (del_capo,)).fetchone()
                return dict(r) if r else None
            r = db.execute("SELECT id, nome, capo, utente, password, codice FROM utenti WHERE utente = ?", (nome,)).fetchone()
        if not r:
            accesso.combacia(segreto, accesso.FINTO)   # stesso tempo di quando il nome utente esiste
            return None
        if (r["password"] and accesso.combacia(segreto, r["password"])) or (r["capo"] and accesso.uguali(r["codice"], del_capo)):
            return {"id": r["id"], "nome": r["nome"], "capo": r["capo"], "utente": r["utente"]}
        return None

    def sessione(self, gettone, tipo="cookie"):
        """L'account a cui appartiene quel cookie (o quella chiave "casa"), oppure None."""
        if not gettone:
            return None
        imp = accesso.impronta(gettone)
        with self.apri() as db:
            r = db.execute("SELECT u.id, u.nome, u.capo, u.utente, s.vista FROM sessioni s JOIN utenti u ON u.id = s.utente "
                           "WHERE s.impronta = ? AND s.tipo = ?", (imp, tipo)).fetchone()
        if not r:
            return None
        if time.time() - r["vista"] > 3600:   # "visto l'ultima volta": basta aggiornarlo ogni tanto
            with _scrittura, self.apri() as db:
                db.execute("UPDATE sessioni SET vista = ? WHERE impronta = ?", (time.time(), imp))
                db.execute("UPDATE utenti SET visto = datetime('now', 'localtime') WHERE id = ?", (r["id"],))
        return {"id": r["id"], "nome": r["nome"], "capo": r["capo"], "utente": r["utente"]}

    def apri_sessione(self, utente, tipo="cookie", gettone=None, da=None):
        gettone = gettone or accesso.nuovo_gettone()
        ora = time.time()
        with _scrittura, self.apri() as db:
            db.execute("INSERT OR IGNORE INTO sessioni (impronta, utente, tipo, da, creata, vista) VALUES (?, ?, ?, ?, ?, ?)",
                       (accesso.impronta(gettone), utente, tipo, da, ora, ora))
            db.execute("UPDATE utenti SET visto = datetime('now', 'localtime') WHERE id = ?", (utente,))
        return gettone

    def _casa(self, utente, seme):
        return accesso.firma(self.segreto, "casa:%s:%s" % (utente, seme))[:48]

    def chiave_casa(self, utente, seme):
        """La chiave che l'icona sulla Home porta nell'indirizzo di avvio: sempre la stessa per lo stesso cookie."""
        chiave = self._casa(utente, seme)
        if not self.sessione(chiave, "casa"):
            self.apri_sessione(utente, "casa", chiave)
        return chiave

    def chiudi_sessione(self, utente, gettone):
        """Esce da questo dispositivo: via il cookie, la chiave da cui era nato e quella nata da lui."""
        imp = accesso.impronta(gettone)
        with _scrittura, self.apri() as db:
            r = db.execute("SELECT da FROM sessioni WHERE impronta = ?", (imp,)).fetchone()
            db.execute("DELETE FROM sessioni WHERE impronta IN (?, ?, ?)",
                       (imp, (r["da"] if r else None) or "", accesso.impronta(self._casa(utente, gettone))))

    def persone(self):
        """L'elenco per chi gestisce l'app. Di ognuno si sa quando e quanto usa l'app (ultimo accesso, ultima cosa
        salvata, quanti giorni ha segnato), mai che cosa: niente cibi, niente pesi."""
        # creato e visto sono scritti con l'ora del container, che e' UTC: lo si dice, cosi' l'app li mostra nell'ora giusta
        utc = lambda v: v.replace(" ", "T") + "Z" if v else None
        fuori = []
        with self.apri() as db:
            for r in db.execute(
                    "SELECT u.id, u.nome, u.utente, u.capo, u.creato, u.visto, "
                    "(SELECT COUNT(*) FROM sessioni s WHERE s.utente = u.id AND s.tipo = 'cookie') AS dispositivi, "
                    "(SELECT MAX(s.vista) FROM sessioni s WHERE s.utente = u.id AND s.tipo != 'passi') AS vista, "
                    "(SELECT COUNT(*) FROM pesate p WHERE p.utente = u.id) AS pesate, "
                    "(SELECT MAX(p.giorno) FROM pesate p WHERE p.utente = u.id) AS ultima_pesata, "
                    "(SELECT st.aggiornato FROM stato st WHERE st.utente = u.id) AS attivo, "
                    "(SELECT st.json FROM stato st WHERE st.utente = u.id) AS json "
                    "FROM utenti u ORDER BY u.id"):
                p = dict(r)
                try:
                    stato = json.loads(p.pop("json") or "{}")
                except ValueError:
                    stato = {}
                giorni = sorted(g for g, v in (stato.get("giorni") or {}).items() if isinstance(v, dict) and (v.get("pasti") or v.get("extra")))
                # i giorni di palestra contati senza la seduta segnata (store.js, allenato) sono allenamenti anche loro
                contati = sum(1 for v in (stato.get("giorni") or {}).values() if isinstance(v, dict) and v.get("gym") is True)
                p.update(creato=utc(p["creato"]), visto=utc(p["visto"]),
                         # l'ultima volta che uno dei suoi dispositivi si e' fatto vivo (si aggiorna al massimo ogni ora)
                         vista=int(p["vista"] * 1000) if p["vista"] else None,
                         attivo=int(p["attivo"]) if p["attivo"] else None,       # l'ultima cosa salvata, in millisecondi
                         giorni=len(giorni), ultimo_giorno=giorni[-1] if giorni else None,
                         sedute=len(stato.get("sedute") or []) + contati, domande=bool(stato.get("profilo")),
                         ai=[m for m in parere.fila(self.cartella, p["id"])],
                         piano=bool(p["utente"]) and os.path.isfile(os.path.join(QUI, "piani", "%s.json" % p["utente"])))
                fuori.append(p)
        return fuori

    def pulisci_chat(self):
        """Cancella le conversazioni con l'assistente di tutti gli account (una volta a settimana, di notte: vedi main).
        Restituisce quanti account ne avevano una. Lo stato prende una data di un minuto e mezzo avanti, cosi' un
        dispositivo rimasto aperto non rimanda indietro la sua copia con la conversazione dentro."""
        quanti = 0
        with _scrittura, self.apri() as db:
            for r in db.execute("SELECT utente, json FROM stato").fetchall():
                try:
                    stato = json.loads(r["json"])
                except ValueError:
                    continue
                if not isinstance(stato, dict) or not stato.get("chat"):
                    continue
                giorno = time.strftime("%Y-%m-%d")
                db.execute("INSERT OR IGNORE INTO stato_storia (utente, giorno, json) VALUES (?, ?, ?)", (r["utente"], giorno, r["json"]))
                stato["chat"] = []
                stato["updatedAt"] = int(time.time() * 1000) + 90000
                db.execute("UPDATE stato SET aggiornato = ?, json = ? WHERE utente = ?",
                           (float(stato["updatedAt"]), json.dumps(stato, ensure_ascii=False, separators=(",", ":")), r["utente"]))
                quanti += 1
        return quanti

    # ---------- notifiche sul telefono (vedi spinta.py) ----------
    def iscrivi(self, u, indirizzo, fuso, orari, promemoria=None):
        """Segna (o aggiorna) il telefono di quella persona. Restituisce se i promemoria dei pasti sono accesi."""
        if not spinta.indirizzo_buono(indirizzo):
            raise Errore(400, "Questo telefono non si puo' iscrivere alle notifiche")
        puliti = {k: v for k, v in (orari if isinstance(orari, dict) else {}).items() if k in ("pranzo", "cena") and re.fullmatch(r"[0-2]\d:[0-5]\d", str(v))}
        try:
            fuso = max(-720, min(840, int(fuso)))
        except (TypeError, ValueError):
            fuso = 120
        with _scrittura, self.apri() as db:
            c_era = db.execute("SELECT promemoria FROM iscrizioni WHERE indirizzo = ?", (indirizzo,)).fetchone()
            acceso = int(bool(promemoria)) if promemoria is not None else (c_era["promemoria"] if c_era else 1)
            db.execute("INSERT INTO iscrizioni (indirizzo, utente, fuso, orari, promemoria, creata) VALUES (?, ?, ?, ?, ?, ?) "
                       "ON CONFLICT(indirizzo) DO UPDATE SET utente = excluded.utente, fuso = excluded.fuso, orari = excluded.orari, promemoria = excluded.promemoria",
                       (indirizzo, u, fuso, json.dumps(puliti), acceso, time.time()))
        return bool(acceso)

    def disiscrivi(self, indirizzo, u=None):
        with _scrittura, self.apri() as db:
            if u is None:
                db.execute("DELETE FROM iscrizioni WHERE indirizzo = ?", (indirizzo,))
            else:
                db.execute("DELETE FROM iscrizioni WHERE indirizzo = ? AND utente = ?", (indirizzo, u))

    def avvisa(self, u, etichetta, titolo, testo, dove=None):
        """Mette da parte una notifica per quella persona e sveglia i suoi telefoni, che passano a prenderla. Con la
        stessa etichetta non la crea due volte. Restituisce quanti telefoni ha svegliato."""
        with _scrittura, self.apri() as db:
            nuova = db.execute("INSERT OR IGNORE INTO notifiche (utente, etichetta, titolo, testo, dove, creata) VALUES (?, ?, ?, ?, ?, ?)",
                               (u, etichetta, titolo[:80], testo[:240], dove, time.time())).rowcount
            db.execute("DELETE FROM notifiche WHERE creata < ?", (time.time() - 7 * 86400,))
            telefoni = [r["indirizzo"] for r in db.execute("SELECT indirizzo FROM iscrizioni WHERE utente = ?", (u,))]
        if not nuova:
            return 0
        svegliati = 0
        for indirizzo in telefoni:
            codice = spinta.spingi(self.cartella, indirizzo)
            if codice in (404, 410):   # l'iscrizione non vale piu' (app tolta, permesso revocato)
                self.disiscrivi(indirizzo)
            svegliati += 200 <= codice < 300
        print("notifiche: u%s %s, telefoni svegliati %d su %d" % (u, etichetta.split("-")[0] if etichetta.startswith("fitai") else etichetta, svegliati, len(telefoni)), flush=True)
        return svegliati

    def prossime(self, u):
        """Le notifiche che quella persona non ha ancora ricevuto (delle ultime dodici ore): il telefono, svegliato,
        passa a prenderle e da qui in poi risultano consegnate."""
        with _scrittura, self.apri() as db:
            righe = [dict(r) for r in db.execute("SELECT id, etichetta, titolo, testo, dove FROM notifiche WHERE utente = ? AND consegnata = 0 AND creata > ? ORDER BY id",
                                                 (u, time.time() - 12 * 3600))]
            db.execute("UPDATE notifiche SET consegnata = 1 WHERE utente = ? AND consegnata = 0", (u,))
        return righe

    def giro_promemoria(self):
        """Chi a quest'ora doveva aver pranzato o cenato e non l'ha segnato riceve un promemoria, una volta sola.
        Tre quarti d'ora dopo l'ora del pasto, e per le due ore seguenti (se il server era spento, recupera)."""
        with self.apri() as db:
            telefoni = [dict(r) for r in db.execute("SELECT utente, fuso, orari FROM iscrizioni WHERE promemoria = 1 GROUP BY utente")]
            gia = {(r["utente"], r["etichetta"]) for r in db.execute("SELECT utente, etichetta FROM notifiche WHERE creata > ?", (time.time() - 2 * 86400,))}
        for t in telefoni:
            li = time.gmtime(time.time() + t["fuso"] * 60)
            oggi, minuti = time.strftime("%Y-%m-%d", li), li.tm_hour * 60 + li.tm_min
            try:
                orari = json.loads(t["orari"] or "{}")
            except ValueError:
                orari = {}
            for pasto, titolo, cosa in (("pranzo", "Hai pranzato?", "il pranzo"), ("cena", "Hai cenato?", "la cena")):
                ora = re.fullmatch(r"(\d\d):(\d\d)", str(orari.get(pasto) or ""))
                if not ora:
                    continue
                quando = int(ora.group(1)) * 60 + int(ora.group(2)) + 45
                etichetta = "%s-%s" % (oggi, pasto)
                if not (quando <= minuti < quando + 120) or (t["utente"], etichetta) in gia:
                    continue
                try:
                    giorno = (json.loads(self.stato(t["utente"])).get("giorni") or {}).get(oggi) or {}
                except ValueError:
                    giorno = {}
                segnato = bool((giorno.get("pasti") or {}).get(pasto)) or any(isinstance(e, dict) and e.get("mom") == pasto for e in giorno.get("extra") or [])
                if not segnato:
                    self.avvisa(t["utente"], etichetta, titolo, "Segna %s su EverFit: basta un tocco." % cosa, "./#/oggi")

    def impostazione(self, chiave, valore=None):
        """Legge (o scrive, se c'e' un valore) una voce delle impostazioni del server."""
        with _scrittura, self.apri() as db:
            if valore is not None:
                db.execute("INSERT INTO impostazioni (chiave, valore) VALUES (?, ?) ON CONFLICT(chiave) DO UPDATE SET valore = excluded.valore", (chiave, str(valore)))
                return str(valore)
            r = db.execute("SELECT valore FROM impostazioni WHERE chiave = ?", (chiave,)).fetchone()
            return r["valore"] if r else None

    def attese(self):
        """I piani scritti a mano che aspettano il loro account: {"utente", "nome"} per ogni file di server/piani
        senza una persona con quel nome utente. Chi gestisce l'app li vede e deve solo scegliere la password."""
        with self.apri() as db:
            presenti = {r[0] for r in db.execute("SELECT utente FROM utenti WHERE utente IS NOT NULL")}
        attese = []
        try:
            nomi = sorted(os.listdir(os.path.join(QUI, "piani")))
        except OSError:
            nomi = []
        for nome in nomi:
            utente = accesso.nome_utente(nome[:-5]) if nome.endswith(".json") else None
            if not utente or utente in presenti:
                continue
            try:
                with open(os.path.join(QUI, "piani", nome), encoding="utf-8") as f:
                    profilo = json.load(f).get("profilo") or {}
            except (OSError, ValueError):
                continue
            attese.append({"utente": utente, "nome": str(profilo.get("nome") or utente.capitalize())[:24]})
        return attese

    @staticmethod
    def _password_valida(password):
        password = str(password or "")
        if not (8 <= len(password) <= 100):
            raise Errore(400, "La password deve avere almeno 8 caratteri")
        return password

    def crea_persona(self, nome, utente, password):
        nome = nome_pulito(nome)
        utente = accesso.nome_utente(utente)
        if not utente:
            raise Errore(400, "Il nome utente va scritto con lettere minuscole, cifre, punti o trattini (da 3 a 24)")
        impasto = accesso.impasta(self._password_valida(password))
        with self.apri() as db:
            if db.execute("SELECT COUNT(*) FROM utenti").fetchone()[0] >= MAX_PERSONE:
                raise Errore(400, "Ci sono gia' troppe persone")
        try:
            with _scrittura, self.apri() as db:
                # "codice" e' il vecchio modo di entrare, rimasto solo al capo: agli altri va un valore che nessuno conosce
                cur = db.execute("INSERT INTO utenti (nome, utente, password, codice) VALUES (?, ?, ?, ?)",
                                 (nome, utente, impasto, accesso.firma(self.segreto, accesso.nuovo_gettone())))
                return {"id": cur.lastrowid, "nome": nome, "utente": utente}
        except sqlite3.IntegrityError:
            raise Errore(400, "Questo nome utente c'e' gia'")

    def cambia_password(self, ident, password):
        """Una password nuova per quella persona. I dispositivi gia' entrati restano dentro.
        Vale anche per il capo: se ne sceglie una sua, e il codice di accesso.env continua a valere accanto a quella."""
        if not self.utente(ident):
            raise Errore(400, "Persona sconosciuta")
        impasto = accesso.impasta(self._password_valida(password))
        with _scrittura, self.apri() as db:
            db.execute("UPDATE utenti SET password = ? WHERE id = ?", (impasto, ident))
        return {"id": ident, "ok": True}

    def rinomina(self, ident, nome):
        nome = nome_pulito(nome)
        with _scrittura, self.apri() as db:
            db.execute("UPDATE utenti SET nome = ? WHERE id = ?", (nome, ident))
        return nome

    def elimina_persona(self, ident):
        if ident == accesso.CAPO or not self.utente(ident):
            raise Errore(400, "Questo account non si puo' eliminare")
        with _scrittura, self.apri() as db:
            for tabella in ("sessioni", "stato", "stato_storia", "pesate", "circonferenze", "passi", "pareri", "iscrizioni", "notifiche"):
                db.execute("DELETE FROM %s WHERE utente = ?" % tabella, (ident,))
            db.execute("DELETE FROM utenti WHERE id = ?", (ident,))
        for motore in parere.MOTORI:
            parere.togli_chiave(self.cartella, ident, motore)

    # ---- stato dell'app
    def stato(self, u):
        with self.apri() as db:
            r = db.execute("SELECT json FROM stato WHERE utente = ?", (u,)).fetchone()
        return r["json"] if r else "{}"

    def versione_stato(self, u):
        with self.apri() as db:
            r = db.execute("SELECT aggiornato FROM stato WHERE utente = ?", (u,)).fetchone()
        return r["aggiornato"] if r else 0

    def salva_stato(self, u, testo, nuovo):
        """None se salvato; altrimenti lo stato che c'e' sul server, che il dispositivo deve prendere al posto del suo."""
        di = nuovo.get("di")
        with _scrittura, self.apri() as db:
            r = db.execute("SELECT aggiornato, json FROM stato WHERE utente = ?", (u,)).fetchone()
            # uno stato scritto per un altro account (telefono passato di mano) non deve finire qui dentro
            if (di is not None and di != u) or (di is None and u != accesso.CAPO):
                return json.loads(r["json"]) if r else {"di": u, "updatedAt": 0}
            if r and r["aggiornato"] > float(nuovo.get("updatedAt") or 0):
                return json.loads(r["json"])          # sul server c'e' una versione piu' recente: vince lei
            if r:
                giorno = time.strftime("%Y-%m-%d")
                db.execute("INSERT OR IGNORE INTO stato_storia (utente, giorno, json) VALUES (?, ?, ?)", (u, giorno, r["json"]))
                db.execute("DELETE FROM stato_storia WHERE utente = ? AND giorno NOT IN "
                           "(SELECT giorno FROM stato_storia WHERE utente = ? ORDER BY giorno DESC LIMIT ?)", (u, u, GIORNI_STORIA))
            db.execute("INSERT INTO stato (utente, aggiornato, json) VALUES (?, ?, ?) "
                       "ON CONFLICT(utente) DO UPDATE SET aggiornato = excluded.aggiornato, json = excluded.json",
                       (u, float(nuovo.get("updatedAt") or 0), testo))
        return None

    # ---- misure
    def misure(self, u):
        with self.apri() as db:
            pesate = [dict(r) for r in db.execute("SELECT * FROM pesate WHERE utente = ? ORDER BY quando", (u,))]
            circ = [dict(r) for r in db.execute("SELECT * FROM circonferenze WHERE utente = ? ORDER BY giorno", (u,))]
            passi = [dict(r) for r in db.execute("SELECT giorno, passi, aggiornato FROM passi WHERE utente = ? AND giorno >= ? ORDER BY giorno",
                                                 (u, (datetime.now(FUSO) - timedelta(days=120)).strftime("%Y-%m-%d")))]
        return {"pesate": pesate, "circonferenze": circ, "passi": passi}

    # ---- passi: li manda il comando dell'iPhone (app Comandi), che li legge dall'app Salute
    # Il comando non ha il cookie dell'app: si fa riconoscere con un codice suo (una sessione di tipo "passi"), che
    # vale solo per mandare i passi. Ogni nuovo codice cancella quello di prima.
    def salva_passi(self, u, valore, giorno=None):
        n = conta_passi(valore)
        if n is None:
            raise Errore(400, "passi: serve un numero (anche come testo, per esempio \"8.432\")")
        oggi = datetime.now(FUSO).date()
        try:
            g = datetime.strptime(str(giorno), "%Y-%m-%d").date() if giorno else oggi
        except ValueError:
            raise Errore(400, "giorno deve essere AAAA-MM-GG")
        if not timedelta(days=-7) <= g - oggi <= timedelta(days=1):
            raise Errore(400, "giorno troppo lontano da oggi")
        with _scrittura, self.apri() as db:
            db.execute("INSERT INTO passi (utente, giorno, passi, aggiornato) VALUES (?, ?, ?, ?) "
                       "ON CONFLICT(utente, giorno) DO UPDATE SET passi = excluded.passi, aggiornato = excluded.aggiornato",
                       (u, g.isoformat(), n, time.time()))
        return {"ok": True, "giorno": g.isoformat(), "passi": n}

    def utente_dei_passi(self, codice):
        if not codice:
            return None
        imp = accesso.impronta(codice)
        with self.apri() as db:
            r = db.execute("SELECT utente, vista FROM sessioni WHERE impronta = ? AND tipo = 'passi'", (imp,)).fetchone()
        if r and time.time() - r["vista"] > 3600:
            with _scrittura, self.apri() as db:
                db.execute("UPDATE sessioni SET vista = ? WHERE impronta = ?", (time.time(), imp))
        return r["utente"] if r else None

    def nuovo_codice_passi(self, u):
        with _scrittura, self.apri() as db:
            db.execute("DELETE FROM sessioni WHERE utente = ? AND tipo = 'passi'", (u,))
        return self.apri_sessione(u, "passi")

    def togli_codice_passi(self, u):
        with _scrittura, self.apri() as db:
            db.execute("DELETE FROM sessioni WHERE utente = ? AND tipo = 'passi'", (u,))

    def stato_passi(self, u):
        with self.apri() as db:
            attivo = db.execute("SELECT 1 FROM sessioni WHERE utente = ? AND tipo = 'passi'", (u,)).fetchone() is not None
            ultimo = db.execute("SELECT giorno, passi, aggiornato FROM passi WHERE utente = ? ORDER BY aggiornato DESC LIMIT 1", (u,)).fetchone()
        return {"attivo": attivo, "ultimo": dict(ultimo) if ultimo else None}

    def salva_pesata(self, u, d):
        quando = str(d.get("quando") or "")
        if not RE_QUANDO.match(quando):
            raise Errore(400, "quando deve essere AAAA-MM-GGTHH:MM:SS")
        if len(quando) == 16:
            quando += ":00"
        fonte = d.get("fonte") if d.get("fonte") in FONTI else "manuale"
        riga = {"utente": u, "quando": quando, "giorno": quando[:10], "fonte": fonte,
                "sesso": d.get("sesso") if d.get("sesso") in ("m", "f") else None,
                "algoritmo": str(d["algoritmo"])[:40] if d.get("algoritmo") else None,
                "nota": str(d["nota"])[:300] if d.get("nota") else None}
        for campo, (tipo, lo, hi) in CAMPI_PESATA.items():
            riga[campo] = numero(d.get(campo), tipo, lo, hi, campo)
        if riga["peso"] is None:
            raise Errore(400, "manca il peso")
        colonne = list(riga)
        with _scrittura, self.apri() as db:
            db.execute(
                "INSERT INTO pesate (%s) VALUES (%s) ON CONFLICT(utente, quando) DO UPDATE SET %s" % (
                    ", ".join(colonne), ", ".join("?" for _ in colonne),
                    ", ".join("%s = excluded.%s" % (c, c) for c in colonne if c not in ("utente", "quando"))),
                [riga[c] for c in colonne])
            return dict(db.execute("SELECT * FROM pesate WHERE utente = ? AND quando = ?", (u, quando)).fetchone())

    def salva_circonferenze(self, u, d):
        giorno = str(d.get("giorno") or "")
        if not RE_GIORNO.match(giorno):
            raise Errore(400, "giorno deve essere AAAA-MM-GG")
        riga = {"utente": u, "giorno": giorno, "nota": str(d["nota"])[:300] if d.get("nota") else None}
        for campo in CAMPI_CIRC:
            riga[campo] = numero(d.get(campo), float, 10, 250, campo)
        if all(riga[c] is None for c in CAMPI_CIRC):
            raise Errore(400, "serve almeno una misura")
        colonne = list(riga)
        with _scrittura, self.apri() as db:
            db.execute(
                "INSERT INTO circonferenze (%s) VALUES (%s) ON CONFLICT(utente, giorno) DO UPDATE SET %s" % (
                    ", ".join(colonne), ", ".join("?" for _ in colonne),
                    ", ".join("%s = excluded.%s" % (c, c) for c in colonne if c not in ("utente", "giorno"))),
                [riga[c] for c in colonne])
            return dict(db.execute("SELECT * FROM circonferenze WHERE utente = ? AND giorno = ?", (u, giorno)).fetchone())

    def elimina(self, u, tabella, ident):
        with _scrittura, self.apri() as db:
            return db.execute("DELETE FROM %s WHERE id = ? AND utente = ?" % tabella, (ident, u)).rowcount > 0

    # ---- prodotti per codice a barre
    def prodotto(self, ean):
        with self.apri() as db:
            r = db.execute("SELECT json, preso FROM prodotti WHERE ean = ?", (ean,)).fetchone()
        # le copie salvate prima che ci fosse il resto dell'etichetta ("x") vanno richieste di nuovo
        if r and time.time() - r["preso"] < GIORNI_PRODOTTO * 86400 and '"x"' in r["json"]:
            return json.loads(r["json"])
        try:
            voce = cibo.prodotto_ean(ean)
        except cibo.Problema:
            if r:                                   # il catalogo non risponde: meglio la copia vecchia di niente
                return json.loads(r["json"])
            raise
        if voce is None:
            raise Errore(404, "Questo codice non e' nel catalogo")
        with _scrittura, self.apri() as db:
            db.execute("INSERT INTO prodotti (ean, json, preso) VALUES (?, ?, ?) "
                       "ON CONFLICT(ean) DO UPDATE SET json = excluded.json, preso = excluded.preso",
                       (ean, json.dumps(voce, ensure_ascii=False), time.time()))
        return voce

    # ---- parere scritto su un prodotto (vedi parere.py)
    def parere(self, u, ean, persona, rifai=False):
        motore = cibo.motore_ai(self.cartella, u)
        if not motore:
            raise Errore(503, "Il parere scritto non e' attivo: serve la chiave di un servizio di AI")
        with self.apri() as db:
            r = db.execute("SELECT json, motore, quando FROM pareri WHERE utente = ? AND ean = ?", (u, ean)).fetchone()
        if r and not rifai and r["motore"] == motore[0] and time.time() - r["quando"] < 90 * 86400:
            return json.loads(r["json"])
        esito = parere.scrivi(motore, self.prodotto(ean), persona)
        with _scrittura, self.apri() as db:
            db.execute("INSERT INTO pareri (utente, ean, motore, json, quando) VALUES (?, ?, ?, ?, ?) "
                       "ON CONFLICT(utente, ean) DO UPDATE SET motore = excluded.motore, json = excluded.json, quando = excluded.quando",
                       (u, ean, motore[0], json.dumps(esito, ensure_ascii=False), time.time()))
        return esito


# ---------- i file dell'app ----------
_guscio = {"chiave": None, "versione": "", "file": []}
_guscio_lucchetto = threading.Lock()


def guscio(root):
    """Versione e file dell'app, foto escluse: il service worker li mette da parte e l'app si apre da li', subito.
    La versione e' l'impronta del contenuto: cambia un file, cambia lei, e i dispositivi si aggiornano da soli."""
    voci = []
    for cartella, _, nomi in os.walk(root):
        for nome in nomi:
            pieno = os.path.join(cartella, nome)
            rel = os.path.relpath(pieno, root).replace(os.sep, "/")
            if rel.startswith("img/") or rel.startswith("icons/splash-") or rel in ("sw.js", "manifest.webmanifest"):
                continue
            st = os.stat(pieno)
            voci.append((rel, int(st.st_mtime), st.st_size))
    voci.sort()
    with _guscio_lucchetto:
        if _guscio["chiave"] != voci:
            h = hashlib.sha1()
            for rel, _, _ in voci + [("sw.js", 0, 0)]:
                h.update(rel.encode("utf-8"))
                with open(os.path.join(root, *rel.split("/")), "rb") as f:
                    h.update(f.read())
            _guscio.update(chiave=voci, versione=h.hexdigest()[:12],
                           file=["./" if rel == "index.html" else rel for rel, _, _ in voci])
        return _guscio["versione"], _guscio["file"]


class Fit(BaseHTTPRequestHandler):
    server_version = "fit"
    protocol_version = "HTTP/1.1"
    root = "public"
    dati = None
    ponte = None
    grezzo = b""     # il corpo della richiesta, letto sempre (None se era troppo grande)
    io = None        # l'account di chi fa la richiesta: {"id", "nome", "capo"}
    gettone = None   # il valore del suo cookie
    via = None       # come e' entrato: locale, porta (percorso segreto), vecchio (cookie di prima), cookie

    def log_request(self, code="-", size="-"):
        # senza la parte dopo il "?": li' dentro passano le ricerche e gli identificativi delle pesate
        path = urlsplit(self.path).path
        if path.startswith(ZITTI):
            return   # controlli di salute e attese della bilancia arrivano di continuo: farebbero solo rumore
        chi = "u%s" % self.io["id"] if self.io else "-"
        print("%s %s %s %s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), chi, self.command, path, code), flush=True)

    def log_message(self, fmt, *args):
        print("%s %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), fmt % args), flush=True)

    # ---- risposte
    def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", cache="no-store", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            for uno in (v if isinstance(v, list) else [v]):
                self.send_header(k, uno)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                   "application/json; charset=utf-8", extra=extra)

    def _leggi_corpo(self):
        """Legge il corpo di ogni richiesta, anche quando poi non serve: se restasse nel tubo, la richiesta dopo
        sulla stessa connessione verrebbe letta attaccata a lui ("{}POST /api/...") e respinta."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = -1
        if n < 0 or n > MAX_CORPO:
            self.close_connection = True   # troppo grande per leggerlo: si risponde e si chiude
            self.grezzo = None
        else:
            self.grezzo = self.rfile.read(n) if n else b""

    def _corpo(self):
        grezzo = self.grezzo
        if not grezzo:
            raise Errore(413 if grezzo is None else 400, "dimensione non valida" if grezzo is None else "manca il corpo della richiesta")
        try:
            dati = json.loads(grezzo)
        except ValueError:
            raise Errore(400, "serve JSON valido")
        if not isinstance(dati, dict):
            raise Errore(400, "serve un oggetto JSON")
        return grezzo.decode("utf-8"), dati

    # ---- chi sei
    def _riconosci(self):
        capo = lambda via: (self.dati.utente(accesso.CAPO), None, via)
        if not accesso.ACCESO:
            self.io, self.gettone, self.via = capo("locale")
        elif self.headers.get("X-Fit-Accesso") == "ok":
            self.io, self.gettone, self.via = capo("porta")
        else:
            valore = accesso.leggi_cookie(self.headers, "fitk")
            if valore and accesso.COOKIE_VECCHIO and accesso.uguali(valore, accesso.COOKIE_VECCHIO):
                self.io, self.gettone, self.via = capo("vecchio")
                self.gettone = valore
            else:
                self.io, self.gettone, self.via = self.dati.sessione(valore), valore, "cookie"

    def _biscotti(self):
        """Rinnova i cookie di chi e' dentro: cosi' la scadenza riparte a ogni apertura dell'app."""
        if self.via in ("cookie", "vecchio"):
            return {"Set-Cookie": accesso.biscotti(self.gettone, self.io["nome"])}
        return {}

    def _accedi(self, metodo):
        """La pagina del codice e il suo modulo. Risponde anche a chi e' gia' dentro e vuole cambiare account."""
        self._riconosci()
        if metodo != "POST":
            if self.io:
                return self._send(303, b"", extra={"Location": "./"})
            return self._send(200, accesso.pagina(), "text/html; charset=utf-8")
        modulo = parse_qs(self.grezzo.decode("utf-8", "replace")) if self.grezzo and len(self.grezzo) <= 2000 else {}
        chiave = modulo.get("k", [""])[0]
        macchina = bool(chiave) or "json" in (self.headers.get("Accept") or "")   # chi chiede e' uno script, non il modulo

        def rispondi(codice, testo, extra=None):
            if macchina:
                return self._json(codice, {"ok": codice < 300, "errore": testo or None}, extra)
            if codice < 300:
                return self._send(303, b"", extra=dict({"Location": "/"}, **(extra or {})))
            return self._send(codice, accesso.pagina(testo), "text/html; charset=utf-8")

        if not accesso.ACCESO:
            return rispondi(200, "")
        if accesso.troppi_sbagli():
            return rispondi(429, "Troppi tentativi sbagliati: riprova tra un'ora.")
        campo = lambda nome: modulo.get(nome, [""])[0]
        utente = self.dati.sessione(chiave, "casa") if chiave else self.dati.entra(campo("utente"), campo("password") or campo("codice"))
        if not utente:
            if not chiave:   # una chiave dell'icona scaduta non e' un tentativo di indovinare la password
                accesso.segna_sbaglio()
                # il piano e' pronto ma l'account non c'e' ancora: chi prova a entrare deve sapere che non ha sbagliato a scrivere
                if accesso.nome_utente(campo("utente")) in {a["utente"] for a in self.dati.attese()}:
                    return rispondi(401, "Questo account non è ancora attivo: lo deve attivare %s dall'app (Piano, poi Persone)." % accesso.NOME_CAPO)
            return rispondi(401, "Nome utente o password sbagliati.")
        gettone = self.dati.apri_sessione(utente["id"], da=accesso.impronta(chiave) if chiave else None)
        self.io = utente
        return rispondi(200, "", {"Set-Cookie": accesso.biscotti(gettone, utente["nome"])})

    def _passi_dal_comando(self):
        """I passi mandati dal comando dell'iPhone (app Comandi), che il cookie dell'app non ce l'ha: si fa riconoscere
        con il codice dei passi, nell'intestazione "Authorization: Bearer <codice>" o nel JSON come "codice". Il codice
        vale solo qui. Risponde e restituisce True; False se un codice non c'e' (allora vale il cookie, come sempre)."""
        auth = self.headers.get("Authorization") or ""
        codice = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        dati = None
        try:
            dati = json.loads(self.grezzo or b"{}")
        except ValueError:
            pass
        if not codice and isinstance(dati, dict):
            codice = str(dati.get("codice") or "").strip()
        if not codice:
            return False
        u = self.dati.utente_dei_passi(codice)
        if not u:
            self._json(401, {"errore": "codice dei passi sbagliato: rifallo dall'app, in Piano, Passi dall'iPhone"})
            return True
        self.io = {"id": u}   # solo per il registro
        if not isinstance(dati, dict):
            self._json(400, {"errore": "serve un oggetto JSON con i passi"})
            return True
        try:
            esito = self.dati.salva_passi(u, dati.get("passi"), dati.get("giorno"))
        except Errore as e:
            print("passi u%d: rifiutati (%s)" % (u, e.testo), flush=True)
            self._json(e.codice, {"errore": e.testo})
            return True
        print("passi u%d: %d il %s" % (u, esito["passi"], esito["giorno"]), flush=True)
        self._json(200, esito)
        return True

    def _fuori(self, metodo, path):
        """Chi non e' ancora entrato vede solo la pagina che chiede il codice."""
        if path.startswith("/api/"):
            return self._json(401, {"errore": "serve il codice di accesso"})
        if metodo in ("GET", "HEAD") and (path.startswith("/icons/") or path == "/manifest.webmanifest"):
            return self._statico(path)   # icona e nome dell'app servono anche alla pagina del codice
        if metodo in ("GET", "HEAD") and path == "/.well-known/assetlinks.json":
            return self._statico(path)   # Google lo legge senza cookie per legare l'app Android al sito
        # 401 e non 200: cosi' il service worker non scambia questa pagina per l'app e non la mette da parte
        return self._send(401, accesso.pagina(), "text/html; charset=utf-8")

    def _file_piano(self):
        """Il file del piano scritto a mano per chi fa la richiesta (server/piani/<nome utente>.json), se c'e'."""
        utente = accesso.nome_utente(self.io.get("utente"))
        percorso = os.path.join(QUI, "piani", "%s.json" % utente) if utente else None
        return percorso if percorso and os.path.isfile(percorso) else None

    def _solo_capo(self):
        if not self.io["capo"]:
            raise Errore(403, "Solo chi gestisce l'app puo' farlo")

    # ---- api
    def _api(self, metodo, path):
        u = self.io["id"]
        cartella = self.dati.cartella
        if metodo == "GET" and path == "/api/io":
            motore = cibo.motore_ai(cartella, u)
            fila = parere.fila(cartella, u)
            return self._json(200, {
                "id": u, "nome": self.io["nome"], "utente": self.io["utente"], "capo": bool(self.io["capo"]),
                # ai: l'assistente e' acceso (anche solo con l'AI della VM); motore: il servizio con la chiave che
                # risponde per primo; fila: chi risponde all'assistente, in ordine
                "bilancia": bool(self.io["capo"]), "ai": bool(fila), "motore": motore[0] if motore else None, "fila": fila,
                "piano": bool(self._file_piano()),
                "esci": self.via in ("cookie", "vecchio"),   # dal PC (percorso segreto) non c'e' niente da cui uscire
                # quanti piani gia' pronti aspettano che il capo crei l'account: l'app glielo ricorda nella schermata di oggi
                "attese": len(self.dati.attese()) if self.io["capo"] else 0,
            }, self._biscotti())
        if metodo == "POST" and path == "/api/io":
            nome = self.dati.rinomina(u, self._corpo()[1].get("nome"))
            self.io["nome"] = nome
            return self._json(200, {"ok": True, "nome": nome}, self._biscotti())
        if metodo == "POST" and path == "/api/esci":
            if self.via == "cookie":
                self.dati.chiudi_sessione(u, self.gettone)
            return self._json(200, {"ok": True}, {"Set-Cookie": accesso.biscotti_spenti()})
        if metodo == "GET" and path == "/api/piano":
            # il piano scritto a mano per questa persona (tools/build_plan.py); chi non ce l'ha lo calcola l'app dal profilo
            try:
                with open(self._file_piano() or "", "rb") as f:
                    return self._send(200, f.read(), "application/json; charset=utf-8")
            except OSError:
                return self._json(200, {})
        # ---- persone: le aggiunge e le toglie solo il capo
        if path == "/api/persone" or path.startswith("/api/persone/"):
            self._solo_capo()
            if metodo == "GET" and path == "/api/persone":
                return self._json(200, {"persone": self.dati.persone(), "attese": self.dati.attese()})
            if metodo == "POST" and path == "/api/persone":
                dati = self._corpo()[1]
                return self._json(200, self.dati.crea_persona(dati.get("nome"), dati.get("utente"), dati.get("password")))
            m = re.match(r"^/api/persone/(\d+)(/password)?$", path)
            if m and metodo == "POST" and m.group(2):
                return self._json(200, self.dati.cambia_password(int(m.group(1)), self._corpo()[1].get("password")))
            if m and metodo == "DELETE" and not m.group(2):
                self.dati.elimina_persona(int(m.group(1)))
                return self._json(200, {"ok": True})
            return self._json(404, {"errore": "non trovato"})
        # ---- stato e misure
        if metodo == "GET" and path == "/api/state":
            return self._send(200, self.dati.stato(u).encode("utf-8"), "application/json; charset=utf-8")
        if metodo == "GET" and path == "/api/state/versione":
            # telefono e PC si chiedono spesso "e' cambiato qualcosa?": basta la data, non tutto lo stato
            return self._json(200, {"updatedAt": self.dati.versione_stato(u)})
        if metodo == "PUT" and path == "/api/state":
            testo, nuovo = self._corpo()
            piu_recente = self.dati.salva_stato(u, testo, nuovo)
            if piu_recente is not None:
                return self._json(409, {"errore": "stato piu' recente sul server", "stato": piu_recente})
            return self._json(200, {"ok": True, "updatedAt": nuovo.get("updatedAt")})
        if metodo == "GET" and path == "/api/misure":
            return self._json(200, self.dati.misure(u))
        # ---- passi dall'iPhone: il codice per il comando (si vede una volta sola, quando lo si crea) e com'e' andata
        if path == "/api/passi/codice":
            if metodo == "GET":
                return self._json(200, self.dati.stato_passi(u))
            if metodo == "POST":
                return self._json(200, {"codice": self.dati.nuovo_codice_passi(u)})
            if metodo == "DELETE":
                self.dati.togli_codice_passi(u)
                return self._json(200, {"ok": True})
        if metodo == "POST" and path == "/api/passi":
            dati = self._corpo()[1]
            return self._json(200, self.dati.salva_passi(u, dati.get("passi"), dati.get("giorno")))
        if metodo == "POST" and path == "/api/pesate":
            return self._json(200, self.dati.salva_pesata(u, self._corpo()[1]))
        if metodo == "POST" and path == "/api/circonferenze":
            return self._json(200, self.dati.salva_circonferenze(u, self._corpo()[1]))
        m = re.match(r"^/api/(pesate|circonferenze)/(\d+)$", path)
        if metodo == "DELETE" and m:
            if self.dati.elimina(u, m.group(1), int(m.group(2))):
                return self._json(200, {"ok": True})
            return self._json(404, {"errore": "non trovato"})
        # ---- come si vede l'app su quel dispositivo: le misure dello schermo che manda all'avvio (main.js, diagnosi).
        # Finiscono solo nel registro: servono a capire da qui cosa succede su un telefono vero.
        if metodo == "POST" and path == "/api/diagnosi":
            print("diagnosi u%d %s" % (u, json.dumps(self._corpo()[1], ensure_ascii=True, separators=(",", ":"))[:1200]), flush=True)
            return self._json(200, {"ok": True})
        # ---- intelligenza artificiale: ognuno con la sua chiave
        if metodo == "GET" and path == "/api/funzioni":
            motore = cibo.motore_ai(cartella, u)
            return self._json(200, {"foto": bool(motore), "ai": bool(parere.fila(cartella, u)), "motore": motore[0] if motore else None})
        if metodo == "POST" and path == "/api/cibo/parere":
            dati = self._corpo()[1]
            ean = str(dati.get("ean") or "")
            if not re.fullmatch(r"\d{8,14}", ean):
                raise Errore(400, "codice non valido")
            return self._json(200, self.dati.parere(u, ean, dati.get("persona") or "", bool(dati.get("rifai"))))
        if metodo == "POST" and path == "/api/chat":
            dati = self._corpo()[1]
            # Chi risponde, in ordine. L'app chiede a uno per volta, per nome ("motore"): cosi' sa chi sta rispondendo
            # e lo fa vedere, e quando uno dice basta passa da sola al successivo ("prossimo"). Senza nome (un'app non
            # ancora aggiornata) i servizi con la chiave si provano qui, uno dopo l'altro.
            fila = parere.fila(cartella, u)
            if not fila:
                raise Errore(503, "L'assistente e' spento: serve la chiave di un servizio di AI")
            nome = dati.get("motore") if dati.get("motore") in fila else None
            motore = cibo.motore_di(cartella, u, nome) if nome else cibo.motore_ai(cartella, u)
            if not motore:   # nessuna chiave, ma c'e' l'AI della VM
                nome, motore = "locale", cibo.locale_di(u)
            lento = motore[0] == "locale"

            def chiedi():
                try:
                    return 200, assistente.rispondi(motore, u, dati.get("contesto"), dati.get("messaggi"), dati.get("immagine"),
                                                    dati.get("livello"), dati.get("ids"))
                except cibo.Problema as e:
                    if e.codice < 500 and e.remoto != 429:   # una domanda sbagliata lo e' per tutti
                        if lento:
                            return e.codice, {"errore": e.testo}
                        raise
                    # il servizio e' pieno, muto o ha risposto male: l'app sa quanto aspettare e a chi chiedere adesso
                    dopo = fila[fila.index(nome) + 1] if nome and fila.index(nome) + 1 < len(fila) else None
                    return (429 if e.remoto == 429 else e.codice), {
                        "errore": e.testo, "attesa": e.attesa, "giornaliero": e.giornaliero, "motore": nome or motore[0], "prossimo": dopo,
                        "perche": e.perche}

            if dati.get("lavoro"):
                # l'app di adesso: la domanda diventa un lavoro che il server porta in fondo da solo, un servizio dopo
                # l'altro (assistente.catena); l'app passa a chiedere a che punto e' e poi a prendere la risposta
                # "id" e' il segno della domanda: se il telefono la rimanda (rete persa a meta') riprende lo stesso lavoro
                motori = [m for m in (cibo.motore_di(cartella, u, n) for n in fila) if m]
                chiave = str(dati.get("id") or "")[:40] or None
                return self._json(202, {"lavoro": assistente.avvia(u, lambda stato: assistente.catena(motori, u, dati, stato), chiave), "fila": fila})
            if lento:   # la risposta si passa a prendere: vedi assistente.avvia
                return self._json(202, {"lavoro": assistente.avvia(u, lambda stato: chiedi()), "motore": "locale"})
            codice, risposta = chiedi()
            return self._json(codice, risposta)
        # ---- notifiche sul telefono
        if metodo == "GET" and path == "/api/notifiche/chiave":
            return self._json(200, {"chiave": spinta.chiave(cartella)[1]})
        if metodo == "POST" and path == "/api/notifiche/iscrizione":
            dati = self._corpo()[1]
            return self._json(200, {"ok": True, "promemoria": self.dati.iscrivi(u, dati.get("indirizzo"), dati.get("fuso"), dati.get("orari"), dati.get("promemoria"))})
        if metodo == "DELETE" and path == "/api/notifiche/iscrizione":
            self.dati.disiscrivi(str(self._corpo()[1].get("indirizzo") or ""), u)
            return self._json(200, {"ok": True})
        if metodo == "GET" and path == "/api/notifiche/prossime":
            return self._json(200, {"notifiche": self.dati.prossime(u)})
        if metodo == "POST" and path == "/api/notifiche/prova":
            quanti = self.dati.avvisa(u, "prova-%d" % (time.time() * 1000), "EverFit", "Le notifiche funzionano.", "./")
            return self._json(200, {"ok": quanti > 0, "telefoni": quanti})
        if metodo == "POST" and path == "/api/chat/scalda":
            # la persona ha aperto l'assistente: se puo' toccare all'AI della VM, intanto si prepara
            return self._json(200, {"ok": assistente.scalda(u, self._corpo()[1].get("contesto"))})
        m = re.match(r"^/api/chat/lavoro/([A-Za-z0-9_-]{8,40})$", path)
        if metodo == "GET" and m:
            esito = assistente.ritira(u, m.group(1))
            if esito is None:
                raise Errore(404, "Questa risposta non c'e' piu': rifai la domanda")
            if isinstance(esito, dict):
                return self._json(200, esito)
            return self._json(200, dict(esito[1], fatto=True, codice=esito[0]))
        # le chiavi si scrivono dall'app; il server dice solo se ci sono, non le restituisce mai
        if metodo == "GET" and path == "/api/ai":
            return self._json(200, parere.stato(cartella, u))
        if metodo == "POST" and path == "/api/ai/chiave":
            dati = self._corpo()[1]
            parere.salva_chiave(cartella, u, dati.get("motore"), dati.get("chiave"))
            esito = {"ok": True}
            try:   # si prova proprio la chiave appena scritta, non il servizio che risponde per primo
                esito["modello"] = parere.prova(cibo.motore_di(cartella, u, dati.get("motore"))).get("modello")
            except cibo.Problema as e:
                esito = {"ok": False, "errore": e.testo}
                if e.chiave:   # una chiave che il servizio rifiuta non si tiene
                    parere.togli_chiave(cartella, u, dati.get("motore"))
            return self._json(200, dict(esito, **parere.stato(cartella, u)))
        m = re.match(r"^/api/ai/chiave/([a-z]+)$", path)
        if metodo == "DELETE" and m:
            parere.togli_chiave(cartella, u, m.group(1))
            return self._json(200, dict({"ok": True}, **parere.stato(cartella, u)))
        if metodo == "POST" and path == "/api/ai/prova":
            try:
                quale = self._corpo()[1].get("motore")
            except Errore:
                quale = None
            # con il nome di un servizio si prova quella chiave e basta; senza, quello che risponde per primo
            motore = cibo.motore_di(cartella, u, quale) if quale else cibo.motore_ai(cartella, u)
            if not motore:
                raise Errore(503, "Non c'e' nessuna chiave")
            esito = parere.prova(motore)
            assistente.rimetti(motore[0])
            return self._json(200, esito)
        # ---- cibi per il diario
        m = re.match(r"^/api/cibo/ean/(\d{8,14})$", path)
        if metodo == "GET" and m:
            return self._json(200, self.dati.prodotto(m.group(1)))
        if metodo == "GET" and path == "/api/cibo/cerca":
            testo = " ".join(parse_qs(urlsplit(self.path).query).get("q", [""])[0].split())[:60]
            if len(testo) < 2:
                raise Errore(400, "scrivi almeno due lettere")
            return self._json(200, {"risultati": cibo.cerca(testo)})
        if metodo == "POST" and path == "/api/foto":
            dati = self._corpo()[1]
            motore = cibo.motore_ai(cartella, u)
            if not motore:
                raise Errore(503, "Il riconoscimento da foto non e' attivo per questo account")
            return self._json(200, cibo.riconosci(motore, dati.get("immagine"), dati.get("nota") or ""))
        # ---- bilancia: il telefono chiede, la sentinella sul PC esegue (vedi ponte.py)
        if path.startswith("/api/bilancia/"):
            return self._bilancia(metodo, path[len("/api/bilancia/"):])
        return self._json(404, {"errore": "non trovato"})

    def _bilancia(self, metodo, cosa):
        # la bilancia e il PC che la ascolta sono del capo: per gli altri e' come se fosse sempre spenta
        if not self.io["capo"]:
            if metodo == "GET" and cosa == "sentinella":
                return self._json(200, {"online": False, "occupata": False})
            raise Errore(403, "La bilancia e' collegata a un altro account")
        domanda = parse_qs(urlsplit(self.path).query)

        def intero(nome, base, massimo):
            valore = domanda.get(nome, [""])[0]
            return min(massimo, int(valore)) if valore.isdigit() else base

        if metodo == "GET" and cosa == "sentinella":
            return self._json(200, self.ponte.sentinella())
        if metodo == "POST" and cosa == "richiesta":
            return self._json(200, self.ponte.chiedi(self._corpo()[1].get("profilo")))
        if metodo == "GET" and cosa == "stato":
            return self._json(200, self.ponte.segui(domanda.get("id", [""])[0], intero("dopo", 0, 100000), intero("attesa", 20, 25)))
        if metodo == "POST" and cosa == "annulla":
            return self._json(200, self.ponte.annulla(self._corpo()[1].get("id")))
        if metodo == "GET" and cosa == "lavoro":
            lavoro = self.ponte.prendi(intero("attesa", 25, 30))
            return self._json(200, lavoro) if lavoro else self._send(204)
        if metodo == "POST" and cosa == "notizie":
            dati = self._corpo()[1]
            return self._json(200, self.ponte.riferisci(dati.get("id"), dati.get("evento"), dati.get("esito")))
        return self._json(404, {"errore": "non trovato"})

    def _gestisci(self, metodo):
        path = urlsplit(self.path).path
        self.io = self.gettone = self.via = None
        try:
            self._leggi_corpo()
            if path == "/api/health":
                return self._json(200, {"ok": True})
            if path == "/accedi":
                return self._accedi(metodo)
            if path == "/api/passi" and metodo == "POST" and self._passi_dal_comando():
                return
            self._riconosci()
            if self.io is None:
                return self._fuori(metodo, path)
            if not path.startswith("/api/"):
                if metodo in ("GET", "HEAD"):
                    return self._statico(path)
                return self._json(405, {"errore": "metodo non ammesso"})
            try:
                self._api("GET" if metodo == "HEAD" else metodo, path)
            except (Errore, cibo.Problema) as e:
                self._json(e.codice, {"errore": e.testo})
            except sqlite3.Error as e:
                print("errore database:", e, flush=True)
                self._json(500, {"errore": "database non disponibile"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True   # chi aspettava una risposta lunga se n'e' andato: niente da dire

    def do_GET(self):
        self._gestisci("GET")

    def do_HEAD(self):
        self._gestisci("HEAD")

    def do_PUT(self):
        self._gestisci("PUT")

    def do_POST(self):
        self._gestisci("POST")

    def do_DELETE(self):
        self._gestisci("DELETE")

    # ---- file statici
    def _statico(self, path):
        rel = posixpath.normpath(unquote(path)).lstrip("/")
        if rel in ("", "."):
            rel = "index.html"
        pieno = os.path.realpath(os.path.join(self.root, *rel.split("/")))
        base = os.path.realpath(self.root)
        if not (pieno == base or pieno.startswith(base + os.sep)) or not os.path.isfile(pieno):
            return self._send(404, b"Non trovato")
        with open(pieno, "rb") as f:
            body = f.read()
        st = os.stat(pieno)
        etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
        if rel == "sw.js":
            # il service worker porta scritta dentro la versione dell'app: cambia un file, cambia lui, e il
            # dispositivo capisce da solo che c'e' da aggiornare
            versione, file = guscio(self.root)
            body = body.replace(b"__VERSIONE__", versione.encode()).replace(b"'__FILE__'", json.dumps(file).encode())
            etag = '"%s"' % versione
        elif rel == "manifest.webmanifest" and self.io and self.via in ("cookie", "vecchio"):
            # l'icona sulla Home dell'iPhone non vede i cookie di Safari: parte con una chiave nell'indirizzo
            # (dopo il #) e la pagina del codice la scambia con un cookie suo, senza chiedere niente
            manifest = json.loads(body)
            # la query resta (l'app Android ci mette ?apk=<versione>), il # di prima no
            inizio = str(manifest.get("start_url") or "./").split("#", 1)[0]
            manifest["start_url"] = inizio + "#k=" + self.dati.chiave_casa(self.io["id"], self.gettone)
            return self._send(200, json.dumps(manifest, ensure_ascii=False).encode("utf-8"), "application/manifest+json; charset=utf-8")
        immagine = rel.startswith(("img/", "icons/"))
        cache = "public, max-age=604800" if immagine else "no-cache"
        extra = {"ETag": etag}
        if self.headers.get("If-None-Match") == etag:
            return self._send(304, b"", cache=cache, extra=extra)
        ctype = mimetypes.guess_type(pieno)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/json", "application/manifest+json"):
            ctype += "; charset=utf-8"
        self._send(200, body, ctype, cache, extra)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="public")
    ap.add_argument("--data", default="data")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    Fit.root, Fit.dati, Fit.ponte = a.root, Dati(a.data), ponte.Ponte()
    srv = ThreadingHTTPServer((a.host, a.port), Fit)
    srv.daemon_threads = True
    print("fit in ascolto su %s:%s, file in %s, database %s, accesso %s" % (
        a.host, a.port, a.root, Fit.dati.percorso, "con codice" if accesso.ACCESO else "libero (solo in locale)"), flush=True)
    # Le conversazioni con l'assistente non si tengono: una volta a settimana, la notte tra domenica e lunedi' (dalle 2
    # alle 4 dell'ora del server, che e' UTC: le 3-5 o le 4-6 in Italia), si cancellano quelle di tutti gli account.
    def pulizia():
        while True:
            time.sleep(600)
            try:
                ora = time.gmtime()
                lunedi = time.strftime("%Y-%m-%d", ora)
                if ora.tm_wday == 0 and 2 <= ora.tm_hour < 4 and Fit.dati.impostazione("chat_pulite") != lunedi:
                    print("pulizia: conversazioni cancellate per %d account" % Fit.dati.pulisci_chat(), flush=True)
                    Fit.dati.impostazione("chat_pulite", lunedi)
            except Exception as e:   # un giro storto non deve fermare quelli dopo
                print("pulizia: non riuscita (%s)" % type(e).__name__, flush=True)
    threading.Thread(target=pulizia, daemon=True).start()

    # I promemoria di pranzo e cena: un giro al minuto (vedi Dati.giro_promemoria).
    def promemoria():
        while True:
            time.sleep(60)
            try:
                Fit.dati.giro_promemoria()
            except Exception as e:
                print("promemoria: giro non riuscito (%s)" % type(e).__name__, flush=True)
    threading.Thread(target=promemoria, daemon=True).start()

    # FitAI ha risposto e nessuno e' passato a prendere la risposta (l'app e' stata chiusa): parte una notifica
    def ha_risposto(utente, numero, codice, risposta):
        if codice != 200:
            return
        testo = re.sub(r"\*\*|\s+", lambda m: "" if m.group(0) == "**" else " ", str(risposta.get("testo") or "")).strip()
        Fit.dati.avvisa(utente, "fitai-%s" % numero, "FitAI ti ha risposto", testo[:140] + ("…" if len(testo) > 140 else ""), "./?apri=fitai")
    assistente.AL_TERMINE = ha_risposto
    if cibo.LOCALE_URL:
        # l'AI che gira sulla VM: la si carica adesso e la si tiene in memoria (un colpetto ogni sei ore), cosi' quello
        # che ha gia' letto non va perso
        def sveglia():
            time.sleep(15)
            while True:
                cibo.sveglia_locale()
                time.sleep(6 * 3600)
        threading.Thread(target=sveglia, daemon=True).start()
    srv.serve_forever()


if __name__ == "__main__":
    main()
