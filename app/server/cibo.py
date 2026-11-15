"""Cibi per il diario: prodotti cercati su Open Food Facts (per codice a barre o per nome) e,
se sul server c'e' la chiave di un servizio che sa guardare le immagini, stima di un piatto da una foto.

Solo libreria standard. Ogni prodotto viene ridotto ai campi che servono all'app:

    {"ean", "n" (nome), "marca", "kcal", "p", "c", "f" (per 100 g), "pz" (grammi di un pezzo o di una porzione),
     "pzn" (come si chiama il pezzo, singolare e plurale), "conf" (grammi della confezione),
     "img" (foto della confezione, sul sito di Open Food Facts), "fonte": "off"}

Se l'etichetta non e' nel catalogo "kcal" e' null: l'app chiede di scrivere i valori a mano.

Intelligenza artificiale (foto dei piatti, parere sui prodotti, assistente): ogni account ha le sue chiavi, in
<data>/chiavi/<id>-<motore>.key. Tre motori, in quest'ordine:
    anthropic   a pagamento, il piu' preciso
    gemini      piano gratuito di Google AI Studio
    mistral     piano gratuito di Mistral: limiti larghi, ma lascia usare solo i modelli piccoli (vedi MISTRAL_GRANDI)
Risponde il primo di cui c'e' la chiave. I piani gratuiti pero' hanno un tetto di richieste: se l'account ha la chiave
di piu' servizi, quando il primo dice "troppe richieste" o non risponde la stessa domanda passa al successivo (_in_fila).
Per il capo valgono anche le chiavi di prima degli account (<data>/<motore>.key, ANTHROPIC_API_KEY, GEMINI_API_KEY).
In fondo a tutti c'e' "locale": un modello che gira sulla VM (Ollama), senza chiave e senza limiti ma lento. Non e'
nella fila qui sopra: l'assistente lo chiede per nome quando gli altri hanno detto basta (vedi assistente.py).
"""
import base64
import functools
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "FitFuel/1.0 (app personale di dieta)"
CAMPI = ("code,product_name,product_name_it,generic_name_it,brands,quantity,product_quantity,serving_size,serving_quantity,"
         "nutriments,image_front_url,image_front_small_url,image_url,"
         "nutriscore_grade,nova_group,additives_tags,allergens_tags,traces_tags,labels_tags,categories_tags,"
         "ingredients_text_it,ingredients_text")
OFF_PRODOTTO = "https://world.openfoodfacts.org/api/v2/product/%s.json?fields=" + CAMPI
OFF_CERCA = "https://search.openfoodfacts.org/search?"
OFF_IMMAGINI = "https://images.openfoodfacts.org/"

AI_URL = os.environ.get("FIT_AI_URL", "https://api.anthropic.com/v1/messages")
AI_MODELLO = os.environ.get("FIT_MODELLO_FOTO", "claude-opus-5-5")
GEMINI_URL = os.environ.get("FIT_GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent")
GEMINI_MODELLO = os.environ.get("FIT_MODELLO_GEMINI", "gemini-3.8-flash")
# La chat va subito al modello leggero. Con il contesto di FitAI il principale va in timeout da settimane (26, 28, 30/10/2026):
# ogni prima domanda perdeva 30 secondi e intanto rispondeva Mistral, che nelle prove del 30/10 sbaglia piu' conti del
# leggero (prova_minchiate_vera.py: "pasta fresca 350 kcal per 100 g"). Con FIT_GEMINI_CHAT=principale si torna a prima.
GEMINI_CHAT_LEGGERO = os.environ.get("FIT_GEMINI_CHAT", "leggero") != "principale"
# Mistral parla come OpenAI (chat/completions); "-latest" segue da solo le versioni nuove. Il piano gratuito non lascia
# usare tutti i modelli: l'11/10/2026, con la chiave di un account appena fatto, "medium" e "small" rispondevano 429
# con un limite di ZERO richieste al minuto (chiusi, non pieni: nella console il piano risultava attivo), "large" 403,
# mentre i "ministral" rispondevano in un paio di secondi. Quindi i modelli sono una fila (_manda_mistral): prima i
# GRANDI, a cui si puo' chiedere tutto come a Gemini; poi i PICCOLI, che vanno tenuti per mano come l'AI della VM
# (istruzioni corte e risposta chiusa in uno schema: assistente.py). Un modello chiuso per quella chiave non si riprova
# per MISTRAL_CHIUSO_PER secondi.
MISTRAL_URL = os.environ.get("FIT_MISTRAL_URL", "https://api.mistral.ai/v1/chat/completions")
_elenco = lambda testo: tuple(m.strip() for m in testo.split(",") if m.strip())
MISTRAL_GRANDI = _elenco(os.environ.get("FIT_MODELLI_MISTRAL", "mistral-medium-latest,mistral-small-latest"))
MISTRAL_PICCOLI = _elenco(os.environ.get("FIT_MODELLI_MISTRAL_PICCOLI", "ministral-14b-latest,ministral-8b-latest"))
MISTRAL_CHIUSO_PER = 6 * 3600
# I modelli grandi si possono chiedere anche per un'altra strada della stessa API, "conversations": con il piano
# gratuito e' quella che risponde (provato l'11/10/2026: chat/completions chiusa, conversations aperta, con un tetto di
# 20.000 token al minuto per modello; l'uso si scala dai 10 dollari al mese compresi nel piano). Vuota = non la si usa.
# Le foto passano anche da li' (provato il 26/10/2026 con mistral_foto_conv.py: medium descrive bene il piatto): prima
# con una foto si andava ai ministral, e uno di loro ha scambiato una tavoletta di cioccolato per la barretta del piano.
MISTRAL_CONV_URL = os.environ.get("FIT_MISTRAL_CONV_URL", MISTRAL_URL.replace("/chat/completions", "/conversations") if "/chat/completions" in MISTRAL_URL else "")
# in ordine di preferenza: (nome, variabile d'ambiente che per il capo vale come chiave)
SERVIZI = (("anthropic", "ANTHROPIC_API_KEY"), ("gemini", "GEMINI_API_KEY"), ("mistral", "MISTRAL_API_KEY"))
# L'AI che gira sulla VM (Ollama, vedi deploy/docker-compose.yml). Senza indirizzo e' spenta.
LOCALE_URL = os.environ.get("FIT_LOCALE_URL", "").rstrip("/")
LOCALE_MODELLO = os.environ.get("FIT_MODELLO_LOCALE", "gemma4:e4b")
LOCALE_PER_TUTTI = os.environ.get("FIT_LOCALE_PER", "capo") == "tutti"   # di norma la usa solo chi gestisce l'app
LOCALE_FILI = int(os.environ.get("FIT_LOCALE_FILI", "3"))               # quanti core usa: il suo container ne ha tre
LOCALE_FINESTRA = int(os.environ.get("FIT_LOCALE_FINESTRA", "8192"))    # quanti token tiene a mente
LOCALE_LOTTO = int(os.environ.get("FIT_LOCALE_LOTTO", "128"))          # token letti per volta (vedi _scalda_locale)
LOCALE_SVEGLIO = os.environ.get("FIT_LOCALE_SVEGLIO", "24h")            # per quanto resta in memoria dopo una domanda
# Come il modello si ricorda quello che ha gia' letto. gemma4 riprende dal punto esatto in cui il testo cambia: tutto il
# contesto sta nel messaggio di sistema, dal piu' fermo al piu' mosso. Altri (qwen3.5) ripartono solo da segnalibri
# che il motore mette un lotto di token prima della fine di ogni richiesta: con FIT_LOCALE_SEGNALIBRI=1 le parti ferme
# si fanno leggere una per volta (resta un segnalibro alla fine di ognuna) e ADESSO va insieme alla domanda.
LOCALE_SEGNALIBRI = os.environ.get("FIT_LOCALE_SEGNALIBRI", "") == "1"
ATTESA_LOCALE = float(os.environ.get("FIT_ATTESA_LOCALE", "900"))       # la prima lettura di tutto dura minuti
MAX_FOTO = 1_500_000  # byte dell'immagine, dopo che il telefono l'ha rimpicciolita
# Quanti secondi si aspetta una risposta prima di provare altrove. Di solito l'assistente risponde in 3-7 secondi:
# se dopo mezzo minuto non ha detto niente non lo dira' piu', e chi ha fatto la domanda sta guardando il telefono.
ATTESA_ASSISTENTE = float(os.environ.get("FIT_ATTESA_ASSISTENTE", "30"))
ATTESA_ALTRO = float(os.environ.get("FIT_ATTESA_AI", "45"))   # foto dei piatti, pareri, prova della chiave
ATTESA_RISERVA = float(os.environ.get("FIT_ATTESA_RISERVA", "15"))   # il modello leggero di Gemini, quando fa da riserva


class Problema(Exception):
    """codice e testo vanno al telefono; `chiave` dice che il servizio ha rifiutato la chiave, `remoto` e' il suo codice."""

    def __init__(self, codice, testo, chiave=False, remoto=None, attesa=None, giornaliero=False, dettaglio="", perche=None, chiuso=False):
        super().__init__(testo)
        self.perche = perche   # due parole da mettere dopo il nome del servizio ("non lascia usare..."), se servono
        self.chiuso = chiuso   # il servizio non lascia usare quel modello a quell'account: riprovare non serve
        self.codice, self.testo, self.chiave, self.remoto = codice, testo, chiave, remoto
        self.dettaglio = dettaglio   # le parole del servizio, per chi deve capire che errore e' (non vanno al telefono)
        # per il limite di richieste (remoto 429): tra quanti secondi riprovare, se il servizio lo dice, e se a essere
        # finita e' la quota del giorno (allora aspettare qualche secondo non serve)
        self.attesa, self.giornaliero = attesa, giornaliero


def _scarica(url, attesa=8):
    richiesta = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(richiesta, timeout=attesa) as r:
        return json.load(r)


def _num(v):
    try:
        v = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def _grammi(valore, unita):
    v = _num(valore)
    if v is None:
        return None
    return v * {"kg": 1000, "l": 1000, "cl": 10}.get(unita.lower(), 1)


def _pulisci(testo, lungo=80):
    testo = re.sub(r"\s+", " ", str(testo or "")).strip()
    testo = re.sub(r"[\s(\[,;:\-]+$", "", testo)
    lettere = [ch for ch in testo if ch.isalpha()]
    if len(lettere) > 4 and sum(ch.isupper() for ch in lettere) > 0.6 * len(lettere):
        testo = testo.title()  # TUTTO MAIUSCOLO si legge male
    return testo[:lungo]


def _pezzi(p):
    """Grammi di un pezzo (o porzione), come chiamarlo e grammi della confezione, per quanto si riesce a capire."""
    conf = _num(p.get("product_quantity"))
    pz = _num(p.get("serving_quantity"))
    nome = ["porzione", "porzioni"]
    testo = str(p.get("quantity") or "")
    multi = re.search(r"(\d+)\s*[x×*]\s*(\d+(?:[.,]\d+)?)\s*(kg|gr|g|ml|cl|l)\b", testo, re.I)
    if multi:  # "4 x 20 g": quattro pezzi da 20 grammi
        quanti, uno = int(multi.group(1)), _grammi(multi.group(2), multi.group(3))
        if 1 < quanti <= 60 and uno:
            pz, nome = uno, ["pezzo", "pezzi"]
            conf = conf or quanti * uno
    if not conf:
        solo = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|gr|g|ml|cl|l)\b", testo, re.I)
        conf = _grammi(solo.group(1), solo.group(2)) if solo else None
    if pz is not None and not (1 <= pz <= 1500):
        pz = None
    if conf is not None and not (1 <= conf <= 20000):
        conf = None
    return (round(pz, 1) if pz else None), nome, (round(conf) if conf else None)


def _extra(p):
    """Il resto dell'etichetta, per la scheda di valutazione: valori per 100 g, voti ufficiali, allergeni, ingredienti."""
    n = p.get("nutriments") or {}

    def val(chiave):
        v = _num(n.get(chiave))
        return round(min(100.0, max(0.0, v)), 2) if v is not None else None

    def nomi(chiave, quanti):
        return [str(t).split(":", 1)[-1] for t in (p.get(chiave) or []) if isinstance(t, str)][:quanti]

    sale = val("salt_100g")
    if sale is None and _num(n.get("sodium_100g")) is not None:
        sale = round(min(100.0, _num(n["sodium_100g"]) * 2.5), 2)
    voto = str(p.get("nutriscore_grade") or "").lower()
    categorie = nomi("categories_tags", 40)
    etichette = nomi("labels_tags", 40)
    return {
        "sat": val("saturated-fat_100g"), "zuc": val("sugars_100g"), "fib": val("fiber_100g"), "sale": sale,
        "alcol": val("alcohol_100g"),
        "nutri": voto if voto in ("a", "b", "c", "d", "e") else None,
        "nova": int(p["nova_group"]) if str(p.get("nova_group") or "") in ("1", "2", "3", "4") else None,
        "additivi": [a.upper() for a in nomi("additives_tags", 20)],
        "allergeni": nomi("allergens_tags", 12), "tracce": nomi("traces_tags", 12),
        "senza_lattosio": any("lactose" in e or "lattosio" in e for e in etichette),
        "bevanda": any(c == "beverages" or c.endswith("-beverages") or c in ("waters", "juices", "sodas", "beers", "wines") for c in categorie),
        "ingredienti": _pulisci(p.get("ingredients_text_it") or p.get("ingredients_text"), 700) or None,
    }


def _kcal_100g(n, pr, ca, gr):
    """Le kcal per 100 g. Il catalogo lo scrive la gente e a volte sbaglia: il 30/10/2026 il Flexi Burger Amadori aveva
    86 kcal e 684 kJ, cioe' 164 kcal divise per 1,9 (qualcuno le ha rapportate ai 190 g della confezione). Quando kcal e
    kJ non vanno d'accordo ha ragione quello piu' vicino a quanto danno proteine, carboidrati e grassi."""
    kcal = _num(n.get("energy-kcal_100g"))
    kj = _num(n.get("energy-kj_100g")) or _num(n.get("energy_100g"))
    da_kj = kj / 4.184 if kj else None
    dai_grammi = 4 * pr + 4 * ca + 9 * gr if None not in (pr, ca, gr) else None
    if kcal is None:
        return da_kj if da_kj is not None else dai_grammi
    if da_kj is not None and dai_grammi and abs(kcal - da_kj) > max(15, da_kj * 0.15):
        return da_kj if abs(da_kj - dai_grammi) < abs(kcal - dai_grammi) else kcal
    return kcal


def normalizza(p):
    n = p.get("nutriments") or {}
    pr, ca, gr = (_num(n.get(k)) for k in ("proteins_100g", "carbohydrates_100g", "fat_100g"))
    kcal = _kcal_100g(n, pr, ca, gr)
    if kcal is not None and not (0 <= kcal <= 950):
        kcal = None
    marca = p.get("brands")
    if isinstance(marca, list):
        marca = marca[0] if marca else ""
    marca = _pulisci(str(marca or "").split(",")[0], 40)
    pz, pzn, conf = _pezzi(p)
    limita = lambda v: round(min(100.0, max(0.0, v)), 1) if v is not None else 0.0
    # la foto resta sul sito del catalogo: qui passa solo l'indirizzo, e solo se e' davvero il loro
    foto = next((u for u in (p.get("image_front_url"), p.get("image_front_small_url"), p.get("image_url"))
                 if isinstance(u, str) and u.startswith(OFF_IMMAGINI)), None)
    return {
        "ean": str(p.get("code") or ""),
        "n": _pulisci(p.get("product_name_it") or p.get("product_name") or p.get("generic_name_it")) or "Prodotto senza nome",
        "marca": marca or None,
        "kcal": round(kcal) if kcal is not None else None,
        "p": limita(pr), "c": limita(ca), "f": limita(gr),
        "pz": pz, "pzn": pzn, "conf": conf, "img": foto, "fonte": "off", "x": _extra(p),
    }


def prodotto_ean(ean):
    """Il prodotto con quel codice a barre, o None se Open Food Facts non lo conosce."""
    try:
        d = _scarica(OFF_PRODOTTO % ean)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise Problema(502, "Il catalogo dei prodotti non risponde. Riprova, oppure scrivi i valori dell'etichetta.")
    except (OSError, ValueError):
        raise Problema(502, "Il catalogo dei prodotti non risponde. Riprova, oppure scrivi i valori dell'etichetta.")
    if not d.get("product") or d.get("status") == 0:
        return None
    voce = normalizza(d["product"])
    if voce["kcal"] is None and voce["n"] == "Prodotto senza nome":
        return None  # scheda vuota: c'e' il codice ma nessuno ha mai scritto niente
    voce["ean"] = ean
    return voce


def cerca(testo):
    """Fino a dodici prodotti in commercio che corrispondono al testo, solo quelli con le calorie."""
    url = OFF_CERCA + urllib.parse.urlencode({"q": testo, "langs": "it", "page_size": 24, "fields": CAMPI})
    try:
        d = _scarica(url)
    except (OSError, ValueError):
        raise Problema(502, "La ricerca dei prodotti non risponde. Riprova tra poco.")
    visti, trovati = set(), []
    for voce in map(normalizza, d.get("hits") or []):
        chiave = (voce["n"].lower(), (voce["marca"] or "").lower())
        if voce["kcal"] is None or not voce["ean"] or voce["n"] == "Prodotto senza nome" or chiave in visti:
            continue
        visti.add(chiave)
        trovati.append(voce)
    return trovati[:12]


# ---------- foto del piatto ----------
STRUMENTO = {
    "name": "registra_pasto",
    "description": "Registra quello che si vede nella foto: gli alimenti con la stima di peso e valori nutrizionali, "
                   "oppure il codice a barre se la foto mostra una confezione.",
    "input_schema": {
        "type": "object",
        "properties": {
            "piatto": {"type": "string", "description": "Nome breve del pasto, in italiano"},
            "voci": {
                "type": "array",
                "description": "Un elemento per ogni alimento distinguibile. Vuoto se nella foto non c'e' cibo.",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string", "description": "Nome in italiano, breve"},
                        "grammi": {"type": "number", "description": "Peso stimato della porzione mangiabile, cosi' com'e' nel piatto"},
                        "kcal": {"type": "number"},
                        "proteine": {"type": "number", "description": "grammi"},
                        "carboidrati": {"type": "number", "description": "grammi"},
                        "grassi": {"type": "number", "description": "grammi"},
                    },
                    "required": ["nome", "grammi", "kcal", "proteine", "carboidrati", "grassi"],
                },
            },
            "ean": {"type": "string", "description": "Le cifre del codice a barre, solo se si leggono con certezza"},
            "sicurezza": {"type": "string", "enum": ["alta", "media", "bassa"]},
            "nota": {"type": "string", "description": "Una frase su cosa rende incerta la stima, se serve"},
        },
        "required": ["piatto", "voci", "sicurezza"],
    },
}
ISTRUZIONI = (
    "Sei un nutrizionista che stima i pasti dalle fotografie per il diario alimentare di un uomo adulto. "
    "Riconosci ogni alimento visibile e stima il peso della porzione usando piatto, posate e confezioni come riferimento. "
    "Conta anche condimenti e olio di cottura quando sono evidenti. Dai valori realistici per quella porzione, non per 100 g. "
    "Se la foto mostra una confezione con il codice a barre leggibile riporta le cifre in `ean` e lascia `voci` vuoto. "
    "Se non c'e' cibo lascia `voci` vuoto e spiegalo in `nota`. Scrivi in italiano. "
)


def _leggi(percorso):
    try:
        with open(percorso, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def percorso_chiave(cartella, utente, nome):
    return os.path.join(cartella, "chiavi", "%d-%s.key" % (int(utente), nome))


class Motore(tuple):
    """(nome, chiave) del servizio che l'account usa per primo. `riserve` sono gli altri di cui ha la chiave, nello
    stesso ordine: quando il primo e' pieno o non risponde, la domanda passa a loro (vedi _in_fila)."""
    riserve = ()


def locale_di(utente):
    """("locale", "") se quell'account puo' usare l'AI che gira sulla VM, altrimenti None."""
    return ("locale", "") if LOCALE_URL and (LOCALE_PER_TUTTI or int(utente) == 1) else None


def motore_di(cartella, utente, nome):
    """(nome, chiave) di quel servizio per quell'account, oppure None se non ne ha la chiave."""
    if nome == "locale":
        return locale_di(utente)
    variabile = dict(SERVIZI).get(nome)
    if variabile is None:
        return None
    chiave = _leggi(percorso_chiave(cartella, utente, nome))
    if not chiave and int(utente) == 1:
        chiave = os.environ.get(variabile, "").strip() or _leggi(os.path.join(cartella, nome + ".key"))
    return (nome, chiave) if chiave else None


def motore_ai(cartella, utente=1):
    """Quale servizio usa quell'account: (nome, chiave) con dietro le riserve, oppure None se non ha nessuna chiave."""
    tutti = [m for m in (motore_di(cartella, utente, nome) for nome, _ in SERVIZI) if m]
    if not tutti:
        return None
    primo = Motore(tutti[0])
    primo.riserve = tuple(tutti[1:])
    return primo


def _tipo_immagine(dati):
    if dati[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if dati[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if dati[:4] == b"RIFF" and dati[8:12] == b"WEBP":
        return "image/webp"
    return None


def immagine_buona(immagine_b64):
    """(tipo, base64) di una foto arrivata dal telefono, dopo aver controllato che sia davvero un'immagine e non troppo grande."""
    try:
        dati = base64.b64decode(str(immagine_b64 or ""), validate=True)
    except ValueError:
        raise Problema(400, "La foto non e' arrivata intera: riprova.")
    tipo = _tipo_immagine(dati)
    if not tipo or not (1000 < len(dati) <= MAX_FOTO):
        raise Problema(400, "Serve una foto JPEG o PNG, non troppo grande.")
    return tipo, base64.b64encode(dati).decode("ascii")


def _manda(url, intestazioni, corpo, attesa=75):
    """POST JSON al servizio; gli errori diventano frasi che si possono mostrare sul telefono."""
    richiesta = urllib.request.Request(url, data=json.dumps(corpo).encode("utf-8"), method="POST",
                                       headers=dict({"content-type": "application/json", "User-Agent": UA}, **intestazioni))
    try:
        with urllib.request.urlopen(richiesta, timeout=attesa) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            scritto = json.load(e)
        except Exception:
            scritto = {}
        if not isinstance(scritto, dict):
            scritto = {}
        # Google e Anthropic: {"error": {"message", "details"}}; Mistral: {"message": ...} oppure {"detail": ...}
        errore = scritto.get("error")
        if not isinstance(errore, dict):
            errore = {"message": errore or scritto.get("message") or scritto.get("detail") or ""}
        dettaglio = str(errore.get("message", ""))
        # Google dice anche quale limite e' stato superato e tra quanto riprovare
        attesa, quote = None, []
        for pezzo in errore.get("details") or []:
            if not isinstance(pezzo, dict):
                continue
            ritardo = re.fullmatch(r"(\d+(?:\.\d+)?)s", str(pezzo.get("retryDelay") or ""))
            if ritardo:
                attesa = float(ritardo.group(1))
            quote += [str(v.get("quotaId") or v.get("quotaMetric") or "") for v in pezzo.get("violations") or [] if isinstance(v, dict)]
        giornaliero = any("PerDay" in q or "per_day" in q.lower() for q in quote)
        if attesa is None and e.code == 429:   # gli altri servizi lo dicono nell'intestazione
            dopo = _num(e.headers.get("Retry-After")) if e.headers else None
            attesa = dopo if dopo is not None and 0 <= dopo <= 3600 else None
        print("AI: errore %s %s%s" % (e.code, dettaglio[:160], " | limiti: %s, riprovare tra %s s" % (quote, attesa) if e.code == 429 else ""), flush=True)
        # Mistral: un modello che il piano di quell'account non comprende (403 "tier_not_allowed", oppure 429 con un
        # limite di zero richieste al minuto) o che non esiste piu'. Non e' la chiave a essere sbagliata e aspettare non
        # serve: si passa a un altro modello (_manda_mistral).
        tipo = str(scritto.get("type") or "")
        zero = e.code == 429 and e.headers and str(e.headers.get("x-ratelimit-limit-req-minute", "")).strip() == "0"
        if zero or (e.code == 403 and (tipo == "tier_not_allowed" or "subscription tier" in dettaglio)) or (e.code in (400, 404) and tipo == "invalid_model"):
            raise Problema(429, "Con il tuo piano questo servizio non lascia usare i modelli che servono all'app.", remoto=429, giornaliero=True,
                           dettaglio=dettaglio, perche="non lascia usare i suoi modelli con questo piano", chiuso=True)
        if e.code in (401, 403) or "API key" in dettaglio or "api key" in dettaglio:
            perche = " Il servizio dice: %s" % _pulisci(dettaglio, 160) if dettaglio else ""
            raise Problema(502, "Il servizio non accetta questa chiave." + perche, chiave=True, remoto=e.code)
        if e.code == 429:
            testo = ("Per oggi le richieste gratuite di questo servizio sono finite: riprova domani." if giornaliero
                     else "Il servizio gratuito ha un limite al minuto: riprova tra poco.")
            raise Problema(429, testo, remoto=429, attesa=attesa, giornaliero=giornaliero)
        raise Problema(502, "Il servizio di AI non ha risposto bene (errore %s). Riprova." % e.code, remoto=e.code, dettaglio=dettaglio)
    except (OSError, ValueError) as e:
        # muto o irraggiungibile: nel registro resta scritto, altrimenti di questo errore non si saprebbe niente
        print("AI: nessuna risposta da %s in %s s (%s)" % (urllib.parse.urlsplit(url).netloc, attesa, type(e).__name__), flush=True)
        raise Problema(502, "Il servizio di AI non risponde. Riprova tra poco.")


def _stanco(e):
    """Il servizio ha detto "troppe richieste", e' sovraccarico o non ha risposto in tempo: vale la pena provare altrove."""
    return not e.chiave and (e.remoto is None or e.remoto == 429 or e.remoto >= 500)


def _schema_gemini(s):
    """Lo stesso schema dello strumento, scritto come lo vuole Gemini (tipi in maiuscolo)."""
    if isinstance(s, list):
        return [_schema_gemini(x) for x in s]
    if not isinstance(s, dict):
        return s
    return {k: (v.upper() if k == "type" and isinstance(v, str) else
                {n: _schema_gemini(x) for n, x in v.items()} if k == "properties" else
                _schema_gemini(v) if k == "items" else v) for k, v in s.items()}


# pensiero: il modello accetta un limite al ragionamento (thinkingConfig)? Lo si scopre alla prima richiesta.
_gemini = {"modello": GEMINI_MODELLO, "pensiero": True}


def _scegli_modello(chiave):
    """I nomi dei modelli di Google cambiano: se quello scritto qui non esiste piu', prende il Flash piu' recente
    tra quelli che la chiave puo' usare."""
    elenco = GEMINI_URL.split("/models/")[0] + "/models?pageSize=200"
    try:
        with urllib.request.urlopen(urllib.request.Request(elenco, headers={"x-goog-api-key": chiave, "User-Agent": UA}), timeout=15) as r:
            modelli = json.load(r).get("models", [])
    except (OSError, ValueError):
        return None
    stabili, altri = [], []
    for m in modelli:
        nome = str(m.get("name", "")).split("/")[-1]
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        preciso = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", nome)
        largo = re.match(r"gemini-(\d+(?:\.\d+)?)-flash", nome)
        if preciso:
            stabili.append((float(preciso.group(1)), nome))
        elif largo and not re.search(r"lite|image|tts|live|audio|native", nome):
            altri.append((float(largo.group(1)), nome))
    scelta = max(stabili or altri or [(0, None)])
    return scelta[1]


def _modello_di_riserva(chiave):
    """Il modello Flash "lite" piu' recente che la chiave puo' usare: ha limiti suoi, separati da quelli del principale."""
    if "riserva" not in _gemini:
        _gemini["riserva"] = None
        elenco = GEMINI_URL.split("/models/")[0] + "/models?pageSize=200"
        try:
            with urllib.request.urlopen(urllib.request.Request(elenco, headers={"x-goog-api-key": chiave, "User-Agent": UA}), timeout=15) as r:
                modelli = json.load(r).get("models", [])
        except (OSError, ValueError):
            modelli = []
        leggeri = []
        for m in modelli:
            nome = str(m.get("name", "")).split("/")[-1]
            versione = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash-lite", nome)
            if versione and "generateContent" in (m.get("supportedGenerationMethods") or []) and nome != _gemini["modello"]:
                leggeri.append((float(versione.group(1)), nome))
        if leggeri:
            _gemini["riserva"] = max(leggeri)[1]
        print("AI: modello di riserva: %s" % _gemini["riserva"], flush=True)
    return _gemini["riserva"]


def fermo(nome):
    """Quel servizio e' appena caduto con tutti i suoi modelli? Allora per un po' conviene chiedere prima agli altri."""
    return nome == "gemini" and time.time() < _gemini.get("fermo", 0)


def gemini_riprova():
    """Chi preme "Prova" vuole sapere com'e' adesso: Gemini torna al suo posto nella fila."""
    _gemini["fermo"], _gemini["cadute"] = 0, 0


def _ferma_gemini(*errori):
    """Principale e riserva hanno fallito tutti e due. Se almeno uno e' rimasto muto o era sovraccarico (non un limite
    di richieste, che si risolve aspettando o risponde subito di no) Gemini per un po' va in fondo alla fila: il
    13/10/2026 il principale rispondeva 503 e la riserva restava muta, e ogni domanda perdeva da mezzo minuto a un
    minuto prima di passare a Mistral. La pausa raddoppia a ogni caduta di fila: 5, 10, 20, 40, 60 minuti."""
    if not any(e.remoto is None or e.remoto >= 500 for e in errori):
        return
    _gemini["cadute"] = _gemini.get("cadute", 0) + 1
    minuti = min(60, 5 * 2 ** (_gemini["cadute"] - 1))
    _gemini["fermo"] = time.time() + minuti * 60
    print("AI: Gemini non risponde con nessun modello: per %d minuti si chiede prima agli altri servizi" % minuti, flush=True)


def _manda_gemini(chiave, corpo, attesa=ATTESA_ALTRO, leggero=False):
    def indirizzo(modello=None):
        return GEMINI_URL % (modello or _gemini["modello"]) if "%s" in GEMINI_URL else GEMINI_URL
    intestazioni = {"x-goog-api-key": chiave}
    breve = min(attesa, ATTESA_RISERVA)   # il modello leggero risponde in pochi secondi: se tace, tace
    caduta = None                         # l'errore del modello di riserva, se in questa richiesta e' gia' stato provato
    # Il modello principale ha appena detto basta o non ha risposto? Per un po' si chiede subito a quello di riserva,
    # invece di perdere ogni volta mezzo minuto ad aspettarlo (l'11/10/2026 e' rimasto muto per due domande di fila).
    # `leggero` lo fa sempre: e' la chat, vedi GEMINI_CHAT_LEGGERO.
    if "%s" in GEMINI_URL and (leggero or time.time() < _gemini.get("riposa", 0)):
        riserva = _modello_di_riserva(chiave)
        if riserva:
            try:
                risposta = _manda(indirizzo(riserva), intestazioni, corpo, breve)
                _ultimo.modello = riserva
                _gemini["cadute"] = 0
                return risposta
            except Problema as e:
                caduta = e   # nemmeno lui: si torna a provare il principale (e lui non lo si richiede una seconda volta)
    try:
        risposta = _manda(indirizzo(), intestazioni, corpo, attesa)
        _ultimo.modello = _gemini["modello"]
        _gemini["riposa"] = _gemini["cadute"] = 0
        return risposta
    except Problema as e:
        if _stanco(e) and "%s" in GEMINI_URL:
            # pieno, sovraccarico o muto il modello principale: si prova quello di riserva, che ha limiti suoi; se
            # non ce la fa nemmeno lui resta l'errore del primo
            _gemini["riposa"] = time.time() + (3600 if e.giornaliero else 600)
            riserva = None if caduta else _modello_di_riserva(chiave)
            if riserva:
                try:
                    risposta = _manda(indirizzo(riserva), intestazioni, corpo, breve)
                except Problema as secondo:
                    _ferma_gemini(e, secondo)
                    raise e
                print("AI: risposto dal modello di riserva %s (il principale riposa per %d minuti)" % (riserva, 60 if e.giornaliero else 10), flush=True)
                _ultimo.modello = riserva
                _gemini["cadute"] = 0
                return risposta
            if caduta:
                _ferma_gemini(e, caduta)
            raise
        if e.remoto != 404 or "%s" not in GEMINI_URL:
            raise
        nuovo = _scegli_modello(chiave)
        if not nuovo or nuovo == _gemini["modello"]:
            raise
        print("AI: il modello %s non c'e', passo a %s" % (_gemini["modello"], nuovo), flush=True)
        _gemini["modello"] = _ultimo.modello = nuovo
        return _manda(indirizzo(), intestazioni, corpo, attesa)


def _per_gemini(messaggi, immagine):
    """La conversazione come la vuole Gemini; la foto, se c'e', va con l'ultima domanda."""
    contenuti = [{"role": "user" if chi == "io" else "model", "parts": [{"text": testo}]} for chi, testo in messaggi]
    if immagine and contenuti and contenuti[-1]["role"] == "user":
        contenuti[-1]["parts"].insert(0, {"inline_data": {"mime_type": immagine[0], "data": immagine[1]}})
    return contenuti


def _per_anthropic(messaggi, immagine):
    contenuti = [{"role": "user" if chi == "io" else "assistant", "content": testo} for chi, testo in messaggi]
    if immagine and contenuti and contenuti[-1]["role"] == "user":
        contenuti[-1]["content"] = [{"type": "image", "source": {"type": "base64", "media_type": immagine[0], "data": immagine[1]}},
                                    {"type": "text", "text": contenuti[-1]["content"]}]
    return contenuti


def _per_mistral(istruzioni, messaggi, immagine):
    """La conversazione come la vogliono Mistral e gli altri servizi che parlano come OpenAI."""
    contenuti = [{"role": "system", "content": istruzioni}]
    contenuti += [{"role": "user" if chi == "io" else "assistant", "content": testo} for chi, testo in messaggi]
    if immagine and contenuti[-1]["role"] == "user":
        contenuti[-1]["content"] = [{"type": "text", "text": contenuti[-1]["content"]},
                                    {"type": "image_url", "image_url": "data:%s;base64,%s" % (immagine[0], immagine[1])}]
    return contenuti


_mistral_chiusi = {}   # (impronta della chiave, modello, strada) -> fino a quando non lo si riprova


def _impronta(chiave):
    return hashlib.sha256(chiave.encode("utf-8")).hexdigest()[:12]


def mistral_dimentica(chiave):
    """Chi prova la chiave ha forse appena cambiato piano: i modelli chiusi per quella chiave si ricontrollano tutti."""
    impronta = _impronta(chiave)
    for voce in [k for k in _mistral_chiusi if k[0] == impronta]:
        _mistral_chiusi.pop(voce, None)


def _manda_mistral_conv(chiave, corpo, modello, attesa):
    """La richiesta di chat/completions fatta per l'altra strada dell'API, "conversations"; la risposta torna scritta
    come quella di chat/completions, cosi' chi la legge non deve sapere da dove e' passata. Non si lascia niente in
    memoria da loro ("store" falso)."""
    messaggi = corpo.get("messages") or []
    istruzioni = "\n\n".join(m["content"] for m in messaggi if m.get("role") == "system" and isinstance(m.get("content"), str))
    voci = [{"object": "entry", "type": "message.input", "role": m["role"], "content": m["content"]} for m in messaggi if m.get("role") != "system"]
    richiesta = {"model": modello, "inputs": voci, "stream": False, "store": False,
                 "completion_args": {k: corpo[k] for k in ("temperature", "max_tokens", "response_format") if k in corpo}}
    if istruzioni:
        richiesta["instructions"] = istruzioni
    risposta = _manda(MISTRAL_CONV_URL, {"Authorization": "Bearer " + chiave}, richiesta, attesa)
    testo = ""
    for uscita in risposta.get("outputs") or []:
        if isinstance(uscita, dict) and uscita.get("type") == "message.output":
            contenuto = uscita.get("content")
            testo += contenuto if isinstance(contenuto, str) else "".join(
                str(p.get("text", "")) for p in contenuto or [] if isinstance(p, dict) and p.get("type") == "text")
    return {"model": modello, "choices": [{"message": {"role": "assistant", "content": testo}, "finish_reason": "stop"}], "usage": risposta.get("usage") or {}}


def _manda_mistral(chiave, corpo, attesa=ATTESA_ALTRO, modelli=None):
    """La stessa richiesta ai modelli di `modelli` (se non si dice niente tutti: prima i grandi, poi i piccoli), uno dopo
    l'altro, finche' uno risponde. I grandi si provano per due strade: chat/completions e, se quella per l'account e'
    chiusa, conversations (anche con una foto). Modello e strada che il piano di quell'account non comprende si
    saltano e non si riprovano per un pezzo. Se alla fine non ha risposto nessuno torna l'errore del primo che era solo
    pieno o muto (dice all'app quanto aspettare); se era tutto chiuso, un errore con `chiuso` vero."""
    intestazioni = {"Authorization": "Bearer " + chiave}
    impronta, inizio, ora = _impronta(chiave), time.time(), time.time()
    pieno = primo = None
    for modello in modelli or MISTRAL_GRANDI + MISTRAL_PICCOLI:
        strade = ["chat"] + (["conversations"] if modello in MISTRAL_GRANDI and MISTRAL_CONV_URL else [])
        for strada in strade:
            if ora < _mistral_chiusi.get((impronta, modello, strada), 0):
                continue
            if pieno is not None:
                if time.time() - inizio > attesa:   # si e' gia' aspettato abbastanza: chi ha chiesto sta guardando il telefono
                    raise pieno
                if pieno.remoto == 429 and "api.mistral.ai" in MISTRAL_URL:
                    time.sleep(1.2)   # il piano gratuito accetta una richiesta al secondo
            primo = primo or modello
            try:
                if strada == "chat":
                    risposta = _manda(MISTRAL_URL, intestazioni, dict(corpo, model=modello), attesa)
                else:
                    risposta = _manda_mistral_conv(chiave, corpo, modello, attesa)
            except Problema as e:
                if e.chiuso:
                    _mistral_chiusi[(impronta, modello, strada)] = time.time() + MISTRAL_CHIUSO_PER
                    print("AI: con questa chiave Mistral non lascia usare %s per la strada %s: per %d ore non la riprovo" % (
                        modello, strada, MISTRAL_CHIUSO_PER // 3600), flush=True)
                    continue
                if not _stanco(e):
                    raise
                pieno = pieno or e
                break   # pieno o muto: l'altra strada ha lo stesso tetto, si passa al modello dopo
            if modello != primo:
                print("AI: risposto da %s (%s era pieno o muto)" % (modello, primo), flush=True)
            _ultimo.modello = modello
            return risposta
    if pieno is not None:
        raise pieno
    raise Problema(429, "Con il tuo piano Mistral non lascia usare i modelli che servono all'app.", remoto=429, giornaliero=True,
                   perche="non lascia usare i suoi modelli con questo piano", chiuso=True)


def _scritto_mistral(risposta, cosa):
    """Il testo di una risposta di Mistral; nel registro resta quanti token e' costata."""
    uso = risposta.get("usage") or {}
    try:
        scelta = risposta["choices"][0]
        scritto = scelta["message"]["content"]
    except (KeyError, IndexError, TypeError):
        scelta, scritto = {}, ""
    if isinstance(scritto, list):   # il contenuto puo' arrivare a pezzi
        scritto = "".join(str(p.get("text", "")) for p in scritto if isinstance(p, dict) and p.get("type") == "text")
    print("AI: %s (%s), %s token letti, %s scritti, fine %s" % (
        cosa, risposta.get("model"), uso.get("prompt_tokens"), uso.get("completion_tokens"), scelta.get("finish_reason")), flush=True)
    return str(scritto or "").strip()


def _struttura(scritto, chi, fine=None):
    """Il dizionario di una risposta che doveva essere JSON; se il servizio ha risposto a parole, quelle parole."""
    esito = json_da(scritto)
    if esito is None and scritto.strip() and not scritto.lstrip().startswith(("{", "[", "```")):
        esito = {"risposta": scritto.strip(), "azioni": []}   # ha risposto a parole: va bene lo stesso
    if esito is None:
        print("AI: risposta di %s non leggibile (%d caratteri, fine %s)" % (chi, len(scritto), fine), flush=True)
    return esito


# ---- piu' servizi in fila
_ultimo = threading.local()


def chi_ha_risposto(motore):
    """Il nome del servizio che ha dato l'ultima risposta a questa richiesta: puo' essere una riserva."""
    return getattr(_ultimo, "nome", None) or motore[0]


def quale_modello():
    """Il modello che ha scritto l'ultima risposta a questa richiesta (il principale o quello di riserva), se si sa."""
    return getattr(_ultimo, "modello", None)


# ---- il modello che gira sulla VM
# Su una CPU il tempo va quasi tutto nel LEGGERE: una quindicina di token al secondo (misurato l'11/10/2026 sulla VM,
# tre core), cioe' sei-otto minuti per istruzioni e contesto interi. Il motore pero' si ricorda quello che ha gia'
# letto: se la domanda nuova comincia come la precedente, rilegge solo da dove cambia. Per questo il contesto e' in
# ordine dal piu' fermo al piu' mosso, e la parte ferma la si fa leggere prima che serva (scalda_locale).
_locale = {"pensa": True, "tappe": []}   # pensa: il motore accetta "think": false? tappe: le impronte di quelle gia' lette
_locale_uno = threading.Lock()           # una richiesta per volta: tanto il motore ne fa una per volta


def _corpo_locale(messaggi, gettoni, temperatura):
    corpo = {"model": LOCALE_MODELLO, "messages": messaggi, "stream": False, "keep_alive": LOCALE_SVEGLIO,
             "options": {"temperature": temperatura, "num_ctx": LOCALE_FINESTRA, "num_predict": gettoni, "num_thread": LOCALE_FILI}}
    if LOCALE_LOTTO > 0:
        corpo["options"]["num_batch"] = LOCALE_LOTTO
    if _locale["pensa"]:
        corpo["think"] = False   # niente ragionamento a parte: su una CPU sono decine di secondi in piu'
    return corpo


def _chiama_locale(corpo):
    try:
        return _manda(LOCALE_URL + "/api/chat", {}, corpo, ATTESA_LOCALE)
    except Problema as e:
        if e.remoto != 400 or "think" not in e.dettaglio.lower() or "think" not in corpo:
            raise
        _locale["pensa"] = False   # questo modello non ha un ragionamento da spegnere
        del corpo["think"]
        return _manda(LOCALE_URL + "/api/chat", {}, corpo, ATTESA_LOCALE)


def _scalda_locale(tappe):
    """Fa leggere al modello le parti che non cambiano. `tappe` sono testi di sistema sempre piu' lunghi, ognuno
    comincia con il precedente: le istruzioni, poi i dati della persona, poi il piano di questi giorni.
    Di norma basta l'ultima, la piu' lunga: il modello riprende da dove il testo e' cambiato. Per i modelli a
    segnalibri si leggono una per volta, e solo quelle cambiate dall'ultima volta (e quelle dopo)."""
    impronte = [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in tappe]
    for i, testo in enumerate(tappe):
        if (not LOCALE_SEGNALIBRI and i < len(tappe) - 1) or _locale["tappe"][:i + 1] == impronte[:i + 1]:
            continue
        inizio = time.time()
        risposta = _chiama_locale(_corpo_locale([{"role": "system", "content": testo}, {"role": "user", "content": "ok"}], 1, 0))
        _locale["tappe"] = impronte[:i + 1]
        print("AI: locale, letta la parte ferma %d di %d (%s token) in %.0f s" % (i + 1, len(tappe), risposta.get("prompt_eval_count"), time.time() - inizio), flush=True)


def scalda_locale(tappe):
    """Prepara il modello per una persona prima che gli arrivi una domanda (vedi assistente.scalda)."""
    if LOCALE_URL and tappe:
        with _locale_uno:
            _scalda_locale(tappe)


def sveglia_locale():
    """All'avvio e ogni tanto: carica il modello e lo tiene in memoria, senza fargli leggere niente (una richiesta
    vuota non tocca quello che si ricorda). Se Ollama non risponde non importa."""
    if not LOCALE_URL:
        return
    try:
        # le stesse opzioni delle domande vere (finestra, lotto, fili): con altre Ollama ricaricherebbe il modello da
        # capo, e quello che aveva letto andrebbe perso (visto l'11/10/2026)
        _manda(LOCALE_URL + "/api/generate", {}, {"model": LOCALE_MODELLO, "keep_alive": LOCALE_SVEGLIO, "options": _corpo_locale([], 1, 0)["options"]}, 180)
    except Problema:
        pass


def _manda_locale(istruzioni, messaggi, forma, immagine, gettoni, temperatura, cosa, tappe=None):
    """Una domanda al modello che gira sulla VM. `forma` e' lo schema JSON della risposta: il motore lo fa rispettare
    mentre il modello scrive, quindi una forma sbagliata o un identificativo che non c'e' non possono uscire.
    `tappe`: le parti di `istruzioni` che non cambiano, da far leggere prima (vedi _scalda_locale).
    Restituisce il testo scritto."""
    contenuti = [{"role": "system", "content": istruzioni}]
    contenuti += [{"role": "user" if chi == "io" else "assistant", "content": testo} for chi, testo in messaggi]
    if immagine and contenuti[-1]["role"] == "user":
        contenuti[-1]["images"] = [immagine[1]]
    corpo = _corpo_locale(contenuti, gettoni, temperatura)
    corpo["format"] = forma or "json"
    with _locale_uno:
        if tappe and LOCALE_SEGNALIBRI:   # gli altri modelli leggono quello che manca rispondendo, senza un giro in piu'
            _scalda_locale([t for t in tappe if istruzioni.startswith(t)])
        risposta = _chiama_locale(corpo)
    secondi = lambda chiave: (risposta.get(chiave) or 0) / 1e9
    print("AI: %s (locale %s), %s token in tutto, lettura %.0f s, %s scritti in %.0f s, in tutto %.0f s, fine %s" % (
        cosa, risposta.get("model"), risposta.get("prompt_eval_count"), secondi("prompt_eval_duration"),
        risposta.get("eval_count"), secondi("eval_duration"), secondi("total_duration"), risposta.get("done_reason")), flush=True)
    _ultimo.modello = LOCALE_MODELLO
    return str((risposta.get("message") or {}).get("content") or "").strip()


def _in_fila(chiedi):
    """Chi ha la chiave di piu' servizi non resta fermo quando uno dice "troppe richieste", non risponde o risponde
    in modo illeggibile: la stessa domanda passa al successivo. Se non ce la fa nessuno torna l'errore del primo, che
    e' quello che dice all'app quanto aspettare."""
    @functools.wraps(chiedi)
    def con_le_riserve(motore, *a, **k):
        fila = [tuple(motore[:2])] + [tuple(r) for r in getattr(motore, "riserve", ())]
        fila.sort(key=lambda uno: fermo(uno[0]))   # chi e' appena caduto con tutti i suoi modelli va in fondo (vedi _ferma_gemini)
        _ultimo.nome = _ultimo.modello = None
        primo = None
        for i, uno in enumerate(fila):
            try:
                esito = chiedi(uno, *a, **k)
            except Problema as e:
                if e.codice < 500 and e.remoto != 429:   # una domanda sbagliata lo e' per tutti
                    raise
                primo = primo or e
                esito = None
            if esito is not None:
                _ultimo.nome = uno[0]
                return esito
            if i < len(fila) - 1:
                print("AI: %s non ce l'ha fatta, passo a %s" % (uno[0], fila[i + 1][0]), flush=True)
        if primo:
            raise primo
        return None
    return con_le_riserve


@_in_fila
def chiedi_testo(motore, istruzioni, messaggi, gettoni=3000, immagine=None):
    """Una conversazione: `messaggi` = [("io" | "ai", testo), ...] dal piu' vecchio al piu' recente; `immagine` =
    (tipo, base64) se con l'ultima domanda c'e' una foto.
    Restituisce il testo della risposta, oppure None se il servizio non ha scritto niente."""
    nome, chiave = motore
    if nome == "gemini":
        risposta = _manda_gemini(chiave, {
            "system_instruction": {"parts": [{"text": istruzioni}]},
            "contents": _per_gemini(messaggi, immagine),
            "generationConfig": {"temperature": 0.6, "maxOutputTokens": gettoni},
        })
        try:
            pezzi = risposta["candidates"][0]["content"]["parts"]
            scritto = "".join(p.get("text", "") for p in pezzi if not p.get("thought")).strip()
        except (KeyError, IndexError, TypeError):
            scritto = ""
        if not scritto:
            print("AI: risposta di Gemini vuota: %s" % json.dumps(risposta)[:300], flush=True)
        return scritto or None
    if nome == "mistral":
        risposta = _manda_mistral(chiave, {"messages": _per_mistral(istruzioni, messaggi, immagine), "max_tokens": gettoni, "temperature": 0.6})
        return _scritto_mistral(risposta, "testo") or None
    risposta = _manda(AI_URL, {"x-api-key": chiave, "anthropic-version": "2023-06-01"}, {
        "model": AI_MODELLO, "max_tokens": min(gettoni, 1500), "system": istruzioni,
        "messages": _per_anthropic(messaggi, immagine),
    })
    return "".join(b.get("text", "") for b in risposta.get("content", []) if b.get("type") == "text").strip() or None


def json_da(testo):
    """Il dizionario scritto in un testo che dovrebbe essere JSON, anche se sta tra ``` o ha qualcosa attorno; None se non c'e'."""
    testo = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(testo or "").strip())
    for pezzo in (testo, testo[testo.find("{"):testo.rfind("}") + 1]):
        try:
            esito = json.loads(pezzo)
        except ValueError:
            continue
        if isinstance(esito, dict):
            return esito
    return None


@_in_fila
def chiedi_struttura(motore, istruzioni, messaggi, strumento, gettoni=8192, schema=True, pensiero=2048, immagine=None, tappe=None):
    """Come chiedi_testo, ma la risposta arriva nella forma descritta da `strumento` ({"name", "description",
    "input_schema"}): serve all'assistente, che oltre a rispondere dice cosa fare nell'app.
    Con `schema` falso a Gemini si chiede solo "rispondi in JSON", e la forma deve stare scritta nelle istruzioni
    (con uno schema lungo la richiesta resta appesa). `pensiero` e' quanto puo' ragionare prima di scrivere: senza
    limite, con un contesto lungo, ci mette mezzo minuto e il ragionamento si mangia lo spazio della risposta, che
    arriva tagliata a meta'.
    Restituisce il dizionario, oppure None se il servizio non ha scritto niente di leggibile."""
    nome, chiave = motore
    if nome == "gemini":
        generazione = {"temperature": 0.3, "maxOutputTokens": gettoni, "response_mime_type": "application/json"}
        if schema:
            generazione["response_schema"] = _schema_gemini(strumento["input_schema"])
        corpo = {
            "system_instruction": {"parts": [{"text": istruzioni}]},
            "contents": _per_gemini(messaggi, immagine),
            "generationConfig": generazione,
        }
        if pensiero and _gemini["pensiero"]:
            generazione["thinkingConfig"] = {"thinkingBudget": pensiero}
            try:
                risposta = _manda_gemini(chiave, corpo, ATTESA_ASSISTENTE, leggero=GEMINI_CHAT_LEGGERO)
            except Problema as e:
                if e.remoto != 400:
                    raise
                # non tutti i modelli lo accettano: da qui in poi non lo si manda piu'
                print("AI: il modello non accetta il limite al ragionamento, riprovo senza", flush=True)
                _gemini["pensiero"] = False
                del generazione["thinkingConfig"]
                risposta = _manda_gemini(chiave, corpo, ATTESA_ASSISTENTE, leggero=GEMINI_CHAT_LEGGERO)
        else:
            risposta = _manda_gemini(chiave, corpo, ATTESA_ASSISTENTE, leggero=GEMINI_CHAT_LEGGERO)
        uso = risposta.get("usageMetadata") or {}
        try:
            candidato = risposta["candidates"][0]
            scritto = "".join(p.get("text", "") for p in candidato["content"]["parts"] if not p.get("thought"))
        except (KeyError, IndexError, TypeError):
            candidato, scritto = {}, ""
        print("AI: assistente, %s token letti, %s di ragionamento, %s scritti, fine %s" % (
            uso.get("promptTokenCount"), uso.get("thoughtsTokenCount"), uso.get("candidatesTokenCount"), candidato.get("finishReason")), flush=True)
        return _struttura(scritto, "Gemini", candidato.get("finishReason"))
    if nome == "locale":
        # qui lo schema si puo' (e conviene) far rispettare: `schema` puo' essere quello fatto su misura per la persona
        forma = schema if isinstance(schema, dict) else strumento["input_schema"] if schema else None
        return _struttura(_manda_locale(istruzioni, messaggi, forma, immagine, min(gettoni, 900), 0.2, "assistente", tappe), "locale")
    if nome == "mistral":
        if isinstance(schema, dict):
            # i modelli piccoli, tenuti per mano come l'AI della VM: la risposta e' chiusa nello schema fatto su misura
            # per la persona (misurati l'11/10/2026 sulle sedici domande di prova: 15 giuste, due secondi a risposta)
            corpo = {"max_tokens": min(gettoni, 900), "temperature": 0.2,
                     "response_format": {"type": "json_schema", "json_schema": {"name": "risposta", "schema": schema, "strict": True}}}
            modelli = MISTRAL_PICCOLI
        else:
            # ai grandi come a Gemini: "rispondi in JSON" e basta, la forma sta scritta nelle istruzioni
            corpo = {"max_tokens": gettoni, "temperature": 0.3, "response_format": {"type": "json_object"}}
            modelli = MISTRAL_GRANDI
        risposta = _manda_mistral(chiave, dict(corpo, messages=_per_mistral(istruzioni, messaggi, immagine)), ATTESA_ASSISTENTE, modelli)
        scritto = _scritto_mistral(risposta, "assistente")
        return _struttura(scritto, "Mistral")
    risposta = _manda(AI_URL, {"x-api-key": chiave, "anthropic-version": "2023-06-01"}, {
        "model": AI_MODELLO, "max_tokens": gettoni, "system": istruzioni + " Rispondi sempre chiamando lo strumento.",
        "tools": [strumento], "tool_choice": {"type": "tool", "name": strumento["name"]},
        "messages": _per_anthropic(messaggi, immagine),
    })
    esito = next((b.get("input") for b in risposta.get("content", []) if b.get("type") == "tool_use"), None)
    return esito if isinstance(esito, dict) else None


@_in_fila
def chiedi_json(motore, istruzioni, testo, strumento, immagine=None, gettoni=1500):
    """Fa una domanda al servizio scelto e pretende la risposta nella forma descritta da `strumento`
    ({"name", "description", "input_schema"}). `immagine` = (tipo, base64) se c'e' una foto da guardare.
    Restituisce il dizionario con la risposta, oppure None se non si riesce a leggerla."""
    nome, chiave = motore
    if nome == "gemini":
        parti = [{"inline_data": {"mime_type": immagine[0], "data": immagine[1]}}] if immagine else []
        risposta = _manda_gemini(chiave, {
            "system_instruction": {"parts": [{"text": istruzioni + " Rispondi solo con il JSON richiesto."}]},
            "contents": [{"role": "user", "parts": parti + [{"text": testo}]}],
            "generationConfig": {"response_mime_type": "application/json", "response_schema": _schema_gemini(strumento["input_schema"])},
        })
        try:
            pezzi = risposta["candidates"][0]["content"]["parts"]
            return json.loads("".join(p.get("text", "") for p in pezzi if not p.get("thought")))
        except (KeyError, IndexError, TypeError, ValueError):
            print("AI: risposta di Gemini non leggibile: %s" % json.dumps(risposta)[:300], flush=True)
            return None
    if nome == "locale":
        return json_da(_manda_locale(istruzioni + " Rispondi solo con il JSON richiesto.", [("io", testo)], strumento["input_schema"],
                                     immagine, gettoni, 0.2, strumento["name"]))
    if nome == "mistral":
        forma = " Rispondi solo con un oggetto JSON che rispetta questo schema: " + json.dumps(strumento["input_schema"], ensure_ascii=False)
        risposta = _manda_mistral(chiave, {"messages": _per_mistral(istruzioni + forma, [("io", testo)], immagine), "max_tokens": gettoni,
                                           "temperature": 0.2, "response_format": {"type": "json_object"}})
        return json_da(_scritto_mistral(risposta, strumento["name"]))
    contenuto = [{"type": "image", "source": {"type": "base64", "media_type": immagine[0], "data": immagine[1]}}] if immagine else []
    risposta = _manda(AI_URL, {"x-api-key": chiave, "anthropic-version": "2023-06-01"}, {
        "model": AI_MODELLO, "max_tokens": gettoni, "system": istruzioni + " Rispondi sempre chiamando lo strumento.",
        "tools": [strumento], "tool_choice": {"type": "tool", "name": strumento["name"]},
        "messages": [{"role": "user", "content": contenuto + [{"type": "text", "text": testo}]}],
    })
    return next((b.get("input") for b in risposta.get("content", []) if b.get("type") == "tool_use"), None)


def riconosci(motore, immagine_b64, nota=""):
    """Fa guardare la foto al servizio scelto e restituisce
    {"piatto", "voci": [{n, g, kcal, p, c, f}], "ean", "sicurezza", "nota"}."""
    try:
        dati = base64.b64decode(str(immagine_b64 or ""), validate=True)
    except ValueError:
        raise Problema(400, "La foto non e' arrivata intera: riprova.")
    tipo = _tipo_immagine(dati)
    if not tipo or not (1000 < len(dati) <= MAX_FOTO):
        raise Problema(400, "Serve una foto JPEG o PNG, non troppo grande.")
    testo = "Cosa c'e' in questa foto? Stima alimenti, pesi e valori nutrizionali."
    if nota:
        testo += " Nota di chi ha mangiato: " + str(nota)[:200]
    b64 = base64.b64encode(dati).decode("ascii")
    esito = chiedi_json(motore, ISTRUZIONI, testo, STRUMENTO, immagine=(tipo, b64))
    if not isinstance(esito, dict):
        raise Problema(502, "Non sono riuscito a leggere la foto. Riprova con piu' luce.")

    def entro(v, massimo):
        v = _num(v)
        return round(min(massimo, max(0.0, v)), 1) if v is not None else 0.0

    voci = []
    for x in (esito.get("voci") or [])[:12]:
        if not isinstance(x, dict) or not str(x.get("nome") or "").strip():
            continue
        voci.append({"n": _pulisci(x["nome"], 60), "g": round(entro(x.get("grammi"), 3000)), "kcal": round(entro(x.get("kcal"), 4000)),
                     "p": entro(x.get("proteine"), 400), "c": entro(x.get("carboidrati"), 600), "f": entro(x.get("grassi"), 400)})
    ean = re.sub(r"\D", "", str(esito.get("ean") or ""))
    return {
        "piatto": _pulisci(esito.get("piatto"), 60) or "Pasto", "voci": voci,
        "ean": ean if len(ean) in (8, 12, 13) else None,
        "sicurezza": esito.get("sicurezza") if esito.get("sicurezza") in ("alta", "media", "bassa") else "media",
        "nota": _pulisci(esito.get("nota"), 200) or None,
    }
