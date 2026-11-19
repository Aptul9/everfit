
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
