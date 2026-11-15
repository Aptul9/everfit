"""Il parere scritto su un prodotto e le chiavi dei servizi di AI.

Il giudizio a semaforo lo calcola l'app con regole fisse (public/js/giudizio.js) e c'e' sempre. Qui, se sul
server c'e' una chiave, si chiede in piu' a un modello di scrivere due righe sul prodotto per quella persona:
il "parere". Usa lo stesso motore delle foto (cibo.motore_ai) e viene tenuto in memoria per codice a barre.

Le chiavi sono di ciascun account: <data>/chiavi/<id>-gemini.key, <id>-mistral.key e <id>-anthropic.key. Le scrive dall'app chi
usa quell'account (Piano -> Intelligenza artificiale); il server non le restituisce mai, dice solo se ci sono.
"""
import json
import os
import re

import cibo
from cibo import Problema

MOTORI = tuple(nome for nome, _ in cibo.SERVIZI)

STRUMENTO = {
    "name": "scrivi_parere",
    "description": "Scrive il parere su un prodotto confezionato per la persona descritta.",
    "input_schema": {
        "type": "object",
        "properties": {
            "riassunto": {"type": "string", "description": "Due o tre frasi: come sta questo prodotto rispetto agli obiettivi della persona"},
            "forti": {"type": "array", "items": {"type": "string"}, "description": "Da zero a quattro punti di forza, brevi"},
            "deboli": {"type": "array", "items": {"type": "string"}, "description": "Da zero a quattro punti deboli, brevi"},
            "consigli": {"type": "array", "items": {"type": "string"}, "description": "Da uno a tre consigli pratici: quando, quanto, o cosa scegliere al suo posto"},
        },
        "required": ["riassunto", "forti", "deboli", "consigli"],
    },
}
ISTRUZIONI = (
    "Sei un nutrizionista sportivo che commenta un prodotto confezionato per una persona precisa. "
    "Scrivi in italiano, dandole del tu, con frasi brevi e concrete, senza allarmismi e senza moralismi. "
    "Usa solo i dati che ricevi: non inventare valori, premi, opinioni di altri clienti o recensioni. "
    "Se un dato manca dillo in poche parole invece di supporlo. Ragiona sulla porzione realistica, non solo sui 100 grammi."
)


def _righe(valore, quante, lunghe):
    if not isinstance(valore, list):
        return []
    return [cibo._pulisci(x, lunghe) for x in valore if isinstance(x, str) and x.strip()][:quante]


def scrivi(motore, prodotto, persona):
    """{"riassunto", "forti", "deboli", "consigli", "motore"} per quel prodotto e quella persona."""
    fatti = {k: prodotto.get(k) for k in ("n", "marca", "kcal", "p", "c", "f", "pz", "conf")}
    fatti.update({k: v for k, v in (prodotto.get("x") or {}).items() if v not in (None, [], False, "")})
    testo = ("PERSONA\n%s\n\nPRODOTTO (kcal, p = proteine, c = carboidrati, f = grassi, sat = grassi saturi, zuc = zuccheri, "
             "fib = fibre, sale: tutti per 100 g; pz = grammi di un pezzo o di una porzione; conf = grammi della confezione; "
             "nutri = Nutri-Score; nova = gruppo NOVA)\n%s" % (cibo._pulisci(persona, 900), json.dumps(fatti, ensure_ascii=False)))
    esito = cibo.chiedi_json(motore, ISTRUZIONI, testo, STRUMENTO, gettoni=900)
    if not isinstance(esito, dict) or not str(esito.get("riassunto") or "").strip():
        raise Problema(502, "Non sono riuscito a scrivere il parere. Riprova.")
    return {
        "riassunto": cibo._pulisci(esito["riassunto"], 500),
        "forti": _righe(esito.get("forti"), 4, 180), "deboli": _righe(esito.get("deboli"), 4, 180),
        "consigli": _righe(esito.get("consigli"), 3, 240), "motore": cibo.chi_ha_risposto(motore),
    }


# ---------- chiavi: ogni account ha le sue ----------
def fila(cartella, utente):
    """Chi risponde all'assistente di quell'account, in ordine: i servizi di cui ha la chiave e, in fondo, l'AI che
    gira sulla VM se la puo' usare."""
    motore = cibo.motore_ai(cartella, utente)
    nomi = [motore[0]] + [r[0] for r in motore.riserve] if motore else []
    return nomi + (["locale"] if cibo.locale_di(utente) else [])


def stato(cartella, utente):
    """Quali chiavi ha quell'account (non il loro valore), quale motore usa e quali ha di riserva, in ordine."""
    motore = cibo.motore_ai(cartella, utente)
    return {"motore": motore[0] if motore else None, "fila": fila(cartella, utente),
            "chiavi": {m: bool(cibo.motore_di(cartella, utente, m)) for m in MOTORI}}


def salva_chiave(cartella, utente, motore, chiave):
    chiave = str(chiave or "").strip()
    if motore not in MOTORI:
        raise Problema(400, "Servizio sconosciuto")
    if not re.fullmatch(r"[A-Za-z0-9_\-.]{20,300}", chiave):
        raise Problema(400, "Questa non sembra una chiave: copiala intera, senza spazi.")
    percorso = cibo.percorso_chiave(cartella, utente, motore)
    os.makedirs(os.path.dirname(percorso), mode=0o700, exist_ok=True)
    provvisorio = percorso + ".tmp"
    with open(os.open(provvisorio, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        f.write(chiave + "\n")
    os.replace(provvisorio, percorso)


def togli_chiave(cartella, utente, motore):
    if motore not in MOTORI:
        raise Problema(400, "Servizio sconosciuto")
    percorsi = [cibo.percorso_chiave(cartella, utente, motore)]
    if int(utente) == 1:
        percorsi.append(os.path.join(cartella, motore + ".key"))   # la chiave di prima degli account era del capo
    for percorso in percorsi:
        try:
            os.remove(percorso)
        except OSError:
            pass


PROVA = {"name": "rispondi", "description": "Risponde alla prova.",
         "input_schema": {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}}


def prova(motore):
    """Una domanda minuscola al servizio: se la chiave non va, l'errore dice perche'. `modello` e' quello che ha
    risposto (con Mistral dipende dal piano: vedi cibo.MISTRAL_GRANDI)."""
    if motore[0] == "mistral":
        cibo.mistral_dimentica(motore[1])
    if motore[0] == "gemini":
        cibo.gemini_riprova()
    esito = cibo.chiedi_json(motore, "Questa e' una prova di collegamento.", "Rispondi con ok = true.", PROVA, gettoni=100)
    if not isinstance(esito, dict):
        raise Problema(502, "Il servizio ha risposto in modo strano. Riprova.")
    return {"ok": True, "motore": motore[0], "modello": cibo.quale_modello()}
