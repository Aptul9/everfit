"""The coach in the chat.

The model reads data, runs the engine and explains. It never does arithmetic
itself. On meals and foods it acts: the change runs at once and comes back as a
receipt the owner can undo. A phase, the targets or a whole-day plan still come
back as a proposal card the owner confirms.
"""

import asyncio
import json
import logging
from datetime import date, timedelta
from functools import partial

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .book import Book
from .engine.plan import Item, Meal, fit_day, totals
from .engine.targets import Macros
from .llm import Final, Messages
from .service import SLOT_LABEL, CoachError, macros_dict
from .store import now

log = logging.getLogger(__name__)
router = APIRouter()
MAX_STEPS = 10
HISTORY_MESSAGES = 30
_running: set[asyncio.Task] = set()

SYSTEM = """Sei il coach nutrizionale personale del proprietario di questa app. Rispondi in italiano, \
in modo diretto e concreto, come un amico competente: frasi brevi, niente elenchi lunghi se non servono.

Regole che non si negoziano:
- I numeri (calorie, macro, grammi, ritmi, metabolismo) li ottieni SOLO dagli strumenti. Non fare conti a \
mente: se ti serve un totale o una porzione usa calcola_pasto o macro_di.
- Sui pasti e sugli alimenti agisci, non consigli: aggiungi, cambi grammi, elimini, segni mangiato, salti, \
copi pasti da un giorno all'altro con gli strumenti diretti. L'app mostra sotto ogni azione una ricevuta \
con Annulla, quindi non chiedere conferma prima.
- Quando l'utente chiede una cosa precisa falla alla lettera: stessi alimenti, stessi grammi, nessun \
ricalcolo, niente calcola_pasto, niente consigli che non ha chiesto. "Fai che oggi sia come ieri" è \
copia_pasti da ieri a oggi, non una lista di cose da aggiungere.
- Dopo un'azione rispondi con una sola riga breve su cosa hai fatto, senza ripetere la ricevuta.
- Per cambiare o togliere un alimento usa il ref che ti dà lo strumento oggi (anche per altri giorni).
- Le date le ricavi tu da oggi: ieri, domani, mercoledì scorso diventano YYYY-MM-DD.
- Fase, target e piano dell'intera giornata restano proposte: proponi_fase e proponi_piano mostrano una \
scheda che l'utente conferma. Dopo una proposta dillo in una riga, senza ripetere i numeri della scheda.
- La storia dell'utente (sotto) vale più di qualsiasi deduzione dai numeri. Dove dice DA COMPILARE è un \
buco: chiedi, non riempirlo.
- Il metodo è quello del libro Project Nutrition di Andrea Biasci (2016). Quando citi il libro usa la \
pagina stampata, [p. N]. Il testo dei capitoli è OCR: i numeri vanno presi da method/ o tables/.
- LARN, EFSA e ISSN decidono i limiti di sicurezza; il libro decide la strategia. Su vitamina D, grassi \
saturi, digiuno intermittente, dolcificanti, proteine e reni dai la posizione del libro e dì che la \
letteratura si è mossa.
- Se il libro non dice una cosa, dillo invece di inventare una regola a suo nome.
- Non annunciare i passaggi ("prima guardo..."): usa gli strumenti in silenzio, poi rispondi. L'app \
mostra già quali strumenti hai usato.
- Per un alimento nuovo: cerca_alimento, poi dettagli_alimento con il cr_food_id per importarlo.
- Niente diagnosi mediche. Davanti a segnali di disturbo alimentare, sintomi o esami alterati, consiglia \
un medico.

Oggi è {weekday} {today}. Fonte dati: {source}.

# Storia dell'utente (data/story.md)

{story}
"""

TOOL_LABELS = {
    "oggi": "giornata letta",
    "progressi": "peso e metabolismo letti",
    "storico": "storico letto",
    "check_in": "check-in letto",
    "fase_e_impostazioni": "fase letta",
    "cerca_alimento": "Cronometer cercato",
    "dettagli_alimento": "alimento letto",
    "calcola_pasto": "conti fatti dal motore",
    "macro_di": "conti fatti dal motore",
    "pasti_tipo": "abitudini lette",
    "indice_libro": "indice del libro",
    "pagine_libro": "libro letto",
    "metodo": "metodo letto",
    "proponi_fase": "proposta preparata",
    "proponi_piano": "proposta preparata",
    "aggiungi_alimento": "alimento aggiunto",
    "modifica_grammi": "grammi cambiati",
    "elimina_alimento": "alimento tolto",
    "segna_mangiato": "segnato come mangiato",
    "salta_pasto": "pasto saltato",
    "ripristina_pasto": "pasto ripristinato",
    "copia_pasti": "pasti copiati",
}

WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
SLOTS = ["colazione", "pranzo", "spuntino", "cena"]
DAY = {"type": "string", "description": "YYYY-MM-DD; se manca, oggi"}
SLOT = {"type": "string", "enum": SLOTS}

ITEM = {
    "type": "object",
    "properties": {"food_id": {"type": "string"}, "grams": {"type": "number"}},
    "required": ["food_id", "grams"],
}
TOOLS = [
    {
        "name": "oggi",
        "description": "Una giornata: target, mangiato, rimanente e i quattro pasti con gli alimenti. Ogni "
        "alimento ha ref (per modificarlo o toglierlo), state (eaten = mangiato e su Cronometer, planned = da "
        "piano, skipped = saltato) e grammi.",
        "input_schema": {"type": "object", "properties": {"day": DAY}},
    },
    {
        "name": "aggiungi_alimento",
        "description": "Aggiunge un alimento a un pasto, subito. eaten true se l'ha già mangiato (va su "
        "Cronometer), false per metterlo nel piano da confermare. food_id da cerca_alimento.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": DAY,
                "slot": SLOT,
                "food_id": {"type": "string"},
                "grams": {"type": "number"},
                "eaten": {"type": "boolean"},
            },
            "required": ["slot", "food_id", "grams", "eaten"],
        },
    },
    {
        "name": "modifica_grammi",
        "description": "Cambia i grammi di un alimento (ref da oggi). Se era già su Cronometer, lì viene "
        "sostituito con i nuovi grammi.",
        "input_schema": {
            "type": "object",
            "properties": {"day": DAY, "ref": {"type": "string"}, "grams": {"type": "number"}},
            "required": ["ref", "grams"],
        },
    },
    {
        "name": "elimina_alimento",
        "description": "Toglie un alimento (ref da oggi): dal piano, o dal diario e da Cronometer se mangiato.",
        "input_schema": {
            "type": "object",
            "properties": {"day": DAY, "ref": {"type": "string"}},
            "required": ["ref"],
        },
    },
    {
        "name": "segna_mangiato",
        "description": "Segna come mangiati gli alimenti da piano di un pasto, con i loro grammi: vanno su "
        "Cronometer. Senza refs tutto quello che resta del pasto.",
        "input_schema": {
            "type": "object",
            "properties": {"day": DAY, "slot": SLOT, "refs": {"type": "array", "items": {"type": "string"}}},
            "required": ["slot"],
        },
    },
    {
        "name": "salta_pasto",
        "description": "Il resto di un pasto non si mangia; il resto della giornata si adegua.",
        "input_schema": {"type": "object", "properties": {"day": DAY, "slot": SLOT}, "required": ["slot"]},
    },
    {
        "name": "ripristina_pasto",
        "description": "Rimette da mangiare un pasto saltato.",
        "input_schema": {"type": "object", "properties": {"day": DAY, "slot": SLOT}, "required": ["slot"]},
    },
    {
        "name": "copia_pasti",
        "description": "Copia nel giorno target quello che è stato mangiato nel giorno source, stessi alimenti "
        "e stessi grammi, senza ricalcoli: è anche 'oggi come ieri' o 'ripeti martedì'. I copiati vanno da "
        "confermare; nei pasti del target il piano viene sostituito e gli alimenti già mangiati restano. "
        "Senza slots copia tutti i pasti.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "YYYY-MM-DD"},
                "target": DAY,
                "slots": {"type": "array", "items": SLOT},
            },
            "required": ["source"],
        },
    },
    {
        "name": "progressi",
        "description": "Trend del peso, ritmo, metabolismo stimato con incertezza, medie "
        "settimanali di mangiato e consumato, giorni esclusi.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "storico",
        "description": "Cosa ha mangiato in una settimana, giorno per giorno e pasto per pasto.",
        "input_schema": {
            "type": "object",
            "properties": {"week_start": {"type": "string", "description": "lunedì, YYYY-MM-DD"}},
        },
    },
    {
        "name": "check_in",
        "description": "Ultimo check-in settimanale: indicatori, verdetto, proposta, motivi.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fase_e_impostazioni",
        "description": "Fase attiva, modelli di fase disponibili, profilo e parametri del motore.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "pasti_tipo",
        "description": "Pasti ricorrenti riconosciuti dal diario, con frequenza.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cerca_alimento",
        "description": "Cerca alimenti tra quelli già usati e su Cronometer. Restituisce "
        "id locali (food_id) o cr_food_id da passare a dettagli_alimento.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "dettagli_alimento",
        "description": "Valori per 100 g di un alimento. Con cr_food_id lo importa "
        "da Cronometer e restituisce il food_id da usare.",
        "input_schema": {
            "type": "object",
            "properties": {"food_id": {"type": "string"}, "cr_food_id": {"type": "integer"}},
        },
    },
    {
        "name": "macro_di",
        "description": "Totale di calorie e macro di una lista di alimenti con grammi.",
        "input_schema": {
            "type": "object",
            "properties": {"items": {"type": "array", "items": ITEM}},
            "required": ["items"],
        },
    },
    {
        "name": "calcola_pasto",
        "description": "Adatta i grammi di un pasto a un obiettivo di calorie e "
        "proteine con le regole del motore (proteine prima, poi carboidrati, porzioni arrotondate). Se ometti "
        "l'obiettivo usa il rimanente di oggi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {"type": "array", "items": ITEM},
                "kcal": {"type": "number"},
                "protein": {"type": "number"},
            },
            "required": ["items"],
        },
    },
    {
        "name": "indice_libro",
        "description": "Cerca nell'indice di Project Nutrition: voce, pagina stampata, file.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "pagine_libro",
        "description": "Testo OCR di al massimo 4 pagine stampate di un capitolo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file": {"type": "string"},
                "first": {"type": "integer"},
                "last": {"type": "integer"},
            },
            "required": ["file", "first", "last"],
        },
    },
    {
        "name": "metodo",
        "description": "Legge un file distillato e verificato: method/, tables/ o external/. "
        "Senza nome elenca i file.",
        "input_schema": {"type": "object", "properties": {"name": {"type": "string"}}},
    },
    {
        "name": "proponi_fase",
        "description": "Propone di cambiare fase (template_id e date) o parametri della "
        "fase attiva (changes: kcal_target, rate_kg_week, band_kg_week, protein_g_per_kg, fat_g_per_kg, "
        "refeed_days_per_week, adjust_macro, duration_weeks).",
        "input_schema": {
            "type": "object",
            "properties": {
                "template_id": {"type": "string"},
                "changes": {"type": "object"},
                "summary": {"type": "string"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "proponi_piano",
        "description": "Propone un piano nuovo per un'intera giornata, che sostituisce quello attuale, quando "
        "l'utente chiede di costruirne uno. Per copiare un giorno o cambiare singoli alimenti usa gli strumenti "
        "diretti.",
        "input_schema": {
            "type": "object",
            "properties": {
                "day": {"type": "string"},
                "summary": {"type": "string"},
                "meals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"slot": {"type": "string"}, "items": {"type": "array", "items": ITEM}},
                        "required": ["slot", "items"],
                    },
                },
            },
            "required": ["day", "meals", "summary"],
        },
    },
]


ACTIONS = {
    "aggiungi_alimento",
    "modifica_grammi",
    "elimina_alimento",
    "segna_mangiato",
    "salta_pasto",
    "ripristina_pasto",
    "copia_pasti",
}


def _shown(card: dict) -> dict:
    return {"type": "proposal", "proposal": card}


def _day_label(d: date, today: date) -> str:
    rel = {0: "oggi", -1: "ieri", 1: "domani"}.get((d - today).days)
    return rel or f"{WEEKDAYS[d.weekday()]} {d.day}"


def _change_line(ch: dict) -> str:
    where = SLOT_LABEL.get(ch["slot"], ch["slot"])
    g = f"{round(ch['grams'])} g"
    what = {
        "add": "aggiunto " + ("mangiato" if ch["state"] == "eaten" else "da confermare"),
        "remove": "tolto",
        "grams": f"da {round(ch['from'] or 0)} a {round(ch['grams'])} g",
        "eaten": "mangiato",
        "skipped": "saltato",
        "planned": "di nuovo da mangiare",
    }[ch["kind"]]
    return f"{where}: {ch['name']} {g} {what}" if ch["kind"] != "grams" else f"{where}: {ch['name']} {what}"


def _meals_brief(view: dict) -> list[dict]:
    return [
        {
            "slot": m["slot"],
            "status": m["status"],
            "kcal": m["macros"]["kcal"],
            "items": [
                {
                    "ref": i["ref"],
                    "state": i["state"],
                    "food_id": i["food_id"],
                    "name": i["name"],
                    "grams": i["grams"],
                }
                for i in m["items"]
            ],
        }
        for m in view["meals"]
    ]


class Agent:
    def __init__(self, app):
        self.app = app
        self.cfg = app.cfg
        self.coach = app.coach
        self.store = app.store
        self.book = Book(app.cfg.corpus_dir)
        self.client = None
        if self.cfg.agent_base_url or self.cfg.agent_api_key:
            self.client = Messages(self.cfg.agent_base_url, self.cfg.agent_api_key)

    def available(self) -> bool:
        return self.client is not None

    def system(self) -> str:
        story = "(file mancante)"
        if self.cfg.story_path.exists():
            story = self.cfg.story_path.read_text(encoding="utf-8")
        today = self.cfg.today()
        return SYSTEM.format(
            weekday=WEEKDAYS[today.weekday()],
            today=today.isoformat(),
            source=self.app.source.name,
            story=story,
        )

    # tools

    def _food_items(self, items: list[dict]) -> list[Item]:
        foods = self.coach.foods()
        out = []
        for i in items:
            f = foods.get(i["food_id"])
            if f is None:
                raise CoachError(
                    f"food_id {i['food_id']!r} sconosciuto: usa cerca_alimento e dettagli_alimento"
                )
            out.append(Item(f, float(i["grams"])))
        return out

    def _proposal(self, kind: str, payload: dict, summary: str) -> dict:
        pid = self.store.x(
            "insert into proposals(created,kind,payload) values(?,?,?)",
            now(),
            kind,
            json.dumps({**payload, "summary": summary}),
        )
        return {"proposal_id": pid, "kind": kind, "summary": summary, **payload}

    def run_tool(self, name: str, args: dict) -> tuple[dict | list | str, dict | None]:
        """Returns (result for the model, event for the UI: a proposal card or an action receipt, or None)."""
        today = self.cfg.today()
        c = self.coach
        if name == "oggi":
            d = date.fromisoformat(args["day"]) if args.get("day") else today
            v = c.today(d, today)
            keys = ("day", "targets", "target_loggable", "consumed", "remaining", "expenditure", "weight")
            return {k: v[k] for k in keys} | {"meals": _meals_brief(v)}, None
        if name == "progressi":
            p = c.progress(today, 42)
            return {
                k: p[k]
                for k in (
                    "trend",
                    "rate",
                    "band",
                    "projection",
                    "goal",
                    "expenditure",
                    "weeks",
                    "excluded",
                    "weighins",
                )
            }, None
        if name == "storico":
            ws = (
                date.fromisoformat(args["week_start"])
                if args.get("week_start")
                else today - timedelta(days=today.weekday())
            )
            h = c.history(ws, today)
            return {
                "days": [
                    {k: d[k] for k in ("day", "kcal", "macros", "target", "complete", "meals")}
                    for d in h["days"]
                ]
            }, None
        if name == "check_in":
            return c.checkin(today) or "Nessuna fase attiva.", None
        if name == "fase_e_impostazioni":
            p = c.phase()
            return {
                "phase": p and p.model_dump(mode="json"),
                "settings": c.settings().model_dump(mode="json"),
                "templates": [t.model_dump(mode="json") for t in c.phase_templates()],
            }, None
        if name == "pasti_tipo":
            return [{k: v for k, v in t.items() if k != "_t"} for t in c.templates(today)], None
        if name == "cerca_alimento":
            q = args["query"]
            local = [
                {"food_id": r["id"], "name": r["name"], "kcal_100g": r["kcal"]}
                for r in self.store.q("select * from foods where name like ? limit 8", f"%{q}%")
            ]
            try:
                remote = self.app.source.search(q)[:10]
            except Exception as exc:
                remote = [{"errore": str(exc)}]
            return {"gia_usati": local, "cronometer": remote}, None
        if name == "dettagli_alimento":
            if args.get("cr_food_id"):
                info = self.app.source.food(int(args["cr_food_id"]))
                self.store.put_food(info.row())
                fid = info.id
            else:
                fid = args.get("food_id")
            f = c.foods().get(fid)
            if f is None:
                raise CoachError("alimento non trovato")
            return {
                "food_id": f.id,
                "name": f.name,
                "per_100g": {"kcal": f.kcal, "protein": f.protein, "carbs": f.carbs, "fat": f.fat},
                "unita": f.unit_name and {"nome": f.unit_name, "grammi": f.unit_g},
                "ruolo": f.role,
            }, None
        if name == "macro_di":
            items = self._food_items(args["items"])
            return {
                "totale": macros_dict(totals([Meal("x", items)])),
                "per_alimento": [
                    {"food_id": i.food.id, "grams": i.grams, **macros_dict(i.macros())} for i in items
                ],
            }, None
        if name == "calcola_pasto":
            items = self._food_items(args["items"])
            if args.get("kcal") is None:
                rem = c.today(today, today).get("remaining") or {}
                kcal, protein = rem.get("kcal", 0), rem.get("protein", 0)
            else:
                kcal, protein = args["kcal"], args.get("protein")
            meal = Meal("x", items)
            cur = meal.macros()
            target = Macros(kcal, protein if protein is not None else cur.protein, cur.carbs, cur.fat)
            fitted, rep = fit_day([meal], target, 40)
            return {
                "items": [
                    {"food_id": i.food.id, "name": i.food.name, "grams": i.grams, **macros_dict(i.macros())}
                    for i in fitted[0].items
                ],
                "totale": rep.totals.__dict__,
                "obiettivo": {"kcal": round(kcal), "protein": protein},
                "note": rep.notes,
            }, None
        if name == "indice_libro":
            return self.book.index(args["query"]), None
        if name == "pagine_libro":
            return self.book.pages(args["file"], int(args["first"]), int(args["last"])), None
        if name == "metodo":
            if not args.get("name"):
                return self.book.references(), None
            return self.book.reference(args["name"]), None
        if name in ACTIONS:
            return self._action(name, args, today)
        if name == "proponi_fase":
            payload = {"template_id": args.get("template_id"), "changes": args.get("changes") or {}}
            p = c.phase()
            payload["current"] = p and p.model_dump(mode="json")
            card = self._proposal("phase", payload, args["summary"])
            return {"ok": "proposta mostrata all'utente", "proposal_id": card["proposal_id"]}, _shown(card)
        if name == "proponi_piano":
            meals = []
            for m in args["meals"]:
                items = self._food_items(m["items"])
                meals.append(
                    {
                        "slot": m["slot"],
                        "items": [
                            {
                                "food_id": i.food.id,
                                "name": i.food.name,
                                "grams": i.grams,
                                **macros_dict(i.macros()),
                            }
                            for i in items
                        ],
                        "kcal": round(sum(i.macros().kcal for i in items)),
                    }
                )
            all_items = [
                Item(f, g)
                for f, g in ((c.foods()[i["food_id"]], i["grams"]) for m in meals for i in m["items"])
            ]
            card = self._proposal(
                "plan",
                {"day": args["day"], "meals": meals, "total": macros_dict(totals([Meal("x", all_items)]))},
                args["summary"],
            )
            return {"ok": "proposta mostrata all'utente", "proposal_id": card["proposal_id"]}, _shown(card)
        raise CoachError(f"strumento {name} sconosciuto")

    def _action(self, name: str, args: dict, today: date) -> tuple[dict, dict]:
        """Run a meal or food change at once, through the same service methods the app uses."""
        c = self.coach
        day = date.fromisoformat(args.get("target") or args.get("day") or today.isoformat())
        slot = args.get("slot")
        if slot is not None and slot not in SLOTS:
            raise CoachError(f"pasto {slot!r} sconosciuto: {', '.join(SLOTS)}")
        meal = SLOT_LABEL.get(slot or "", "")
        when = _day_label(day, today)
        if name == "aggiungi_alimento":
            f = c.foods().get(args["food_id"])
            if f is None:
                raise CoachError(f"food_id {args['food_id']!r} sconosciuto: usa cerca_alimento")
            eaten = bool(args.get("eaten"))
            title = f"{f.name} in {meal.lower()} {when}, {'mangiato' if eaten else 'da confermare'}"
            run = partial(c.add_item, day, slot, f.id, float(args["grams"]), today, eaten)
        elif name == "modifica_grammi":
            title = f"Grammi cambiati {when}"
            run = partial(c.update_item, day, args["ref"], float(args["grams"]), today)
        elif name == "elimina_alimento":
            title = f"Alimento tolto {when}"
            run = partial(c.delete_item, day, args["ref"], today)
        elif name == "segna_mangiato":
            title = f"{meal} {when} segnato come mangiato"
            run = partial(c.confirm_items, day, slot, today, args.get("refs"))
        elif name == "salta_pasto":
            title = f"{meal} {when} saltato"
            run = partial(c.skip_meal, day, slot, today)
        elif name == "ripristina_pasto":
            title = f"{meal} {when} di nuovo da mangiare"
            run = partial(c.undo_meal, day, slot, today)
        else:
            source = date.fromisoformat(args["source"])
            slots = args.get("slots") or None
            what = "tutti i pasti" if slots is None else ", ".join(SLOT_LABEL[s].lower() for s in slots)
            title = f"Copiato {what} da {_day_label(source, today)} in {when}, stessi grammi"
            if slots is None:
                run = partial(c.repeat_day, source, day, today)
            else:
                run = partial(c.copy_meals, source, day, slots, today)

        c.plan(day, today)  # a plan built on first view is not part of the change
        before = c.snapshot(day)
        view = run()
        after = c.snapshot(day)
        changes = c.changes(before, after)
        receipt = {"day": day.isoformat(), "title": title, "changes": changes}
        aid = self.store.x(
            "insert into actions(created,day,receipt,before,after) values(?,?,?,?,?)",
            now(),
            day.isoformat(),
            json.dumps(receipt),
            json.dumps(before),
            json.dumps(after),
        )
        receipt = {"action_id": aid, "status": "done", **receipt}
        return {
            "fatto": title,
            "action_id": aid,
            "modifiche": [_change_line(ch) for ch in changes] or ["nessuna modifica"],
            "pasti": _meals_brief(view),
        }, {"type": "action", "action": receipt}

    def undo(self, aid: int) -> dict:
        """Annulla under a receipt: the day goes back to how it was before that action. Only while
        nothing changed the day since, so a later edit is never lost."""
        rows = self.store.q("select * from actions where id=?", aid)
        if not rows:
            raise CoachError("Azione inesistente")
        if rows[0]["status"] != "done":
            raise CoachError("Azione già annullata")
        day = date.fromisoformat(rows[0]["day"])
        c = self.coach
        if c.day_state(c.snapshot(day)) != c.day_state(json.loads(rows[0]["after"])):
            raise CoachError("La giornata è cambiata dopo questa azione: annullala a mano dai pasti.")
        view = c.restore(day, json.loads(rows[0]["before"]), self.cfg.today())
        self.store.x("update actions set status='undone' where id=?", aid)
        self.app.syncer.push()
        return {"ok": True, "day": day.isoformat(), "view": view}

    # conversation

    def history(self) -> list[dict]:
        """The last turns, repaired into a sequence the API accepts: it starts on a user text, roles
        alternate, and every tool_use is answered by its tool_result. A turn cut short (a crash, a
        restart) would otherwise poison every later request."""
        rows = self.store.q("select role, content from chat order by id desc limit ?", HISTORY_MESSAGES)
        raw = [{"role": r["role"], "content": json.loads(r["content"])} for r in reversed(rows)]
        while raw and not (raw[0]["role"] == "user" and isinstance(raw[0]["content"], str)):
            raw.pop(0)

        def blocks(c):
            return [{"type": "text", "text": c}] if isinstance(c, str) else list(c)

        msgs: list[dict] = []
        for i, m in enumerate(raw):
            if m["role"] == "assistant":
                uses = {b["id"] for b in m["content"] if b.get("type") == "tool_use"}
                nxt = raw[i + 1] if i + 1 < len(raw) else None
                answered = {
                    b.get("tool_use_id")
                    for b in (blocks(nxt["content"]) if nxt and nxt["role"] == "user" else [])
                    if b.get("type") == "tool_result"
                }
                if uses - answered:
                    continue
            if msgs and msgs[-1]["role"] == m["role"]:
                msgs[-1] = {"role": m["role"], "content": blocks(msgs[-1]["content"]) + blocks(m["content"])}
            else:
                msgs.append(m)
        # tool_results whose tool_use was dropped above are orphans
        for k, m in enumerate(msgs):
            if m["role"] == "user" and not isinstance(m["content"], str):
                prev = msgs[k - 1] if k else None
                ids = {b["id"] for b in prev["content"] if b.get("type") == "tool_use"} if prev else set()
                kept = [
                    b for b in m["content"] if b.get("type") != "tool_result" or b.get("tool_use_id") in ids
                ]
                m["content"] = kept or [{"type": "text", "text": "(continua)"}]
        return msgs

    def save(self, role: str, content) -> None:
        self.store.x("insert into chat(created,role,content) values(?,?,?)", now(), role, json.dumps(content))

    async def stream(self, text: str):
        if self.client is None:
            yield {
                "type": "error",
                "message": "Coach non configurato: imposta ANTHROPIC_BASE_URL (Meridian) "
                "o ANTHROPIC_API_KEY.",
            }
            return
        self.save("user", text)
        messages = self.history()
        system = [{"type": "text", "text": self.system(), "cache_control": {"type": "ephemeral"}}]
        said = acted = False
        for _ in range(MAX_STEPS):
            final = Final()
            first = True
            try:
                async for delta in self.client.stream(
                    final,
                    model=self.cfg.agent_model,
                    max_tokens=2048,
                    system=system,
                    tools=TOOLS,
                    messages=messages,
                ):
                    if first and said:
                        delta = "\n\n" + delta  # a turn after tool calls starts a new paragraph
                    first = False
                    said = True
                    yield {"type": "text", "text": delta}
            except Exception as exc:
                log.exception("agent call failed")
                yield {
                    "type": "error",
                    "message": f"Il coach non risponde: {type(exc).__name__}: {exc}"[:400],
                }
                return
            content = final.content
            if not content:
                yield {"type": "error", "message": "Risposta vuota dal modello."}
                return
            self.save("assistant", content)
            messages.append({"role": "assistant", "content": content})
            uses = [b for b in content if b["type"] == "tool_use"]
            if final.stop_reason != "tool_use" or not uses:
                break
            results = []
            for u in uses:
                yield {"type": "tool", "name": u["name"], "label": TOOL_LABELS.get(u["name"], u["name"])}
                try:
                    out, event = self.run_tool(u["name"], u.get("input") or {})
                    if event:
                        acted = acted or event["type"] == "action"
                        yield event
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": u["id"],
                            "content": json.dumps(out, ensure_ascii=False, default=str)[:20000],
                        }
                    )
                except Exception as exc:
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": u["id"],
                            "is_error": True,
                            "content": f"{type(exc).__name__}: {exc}",
                        }
                    )
            self.save("user", results)
            messages.append({"role": "user", "content": results})
        if acted:
            await asyncio.to_thread(self.app.syncer.push)
        yield {"type": "done"}

    def apply(self, pid: int) -> dict:
        rows = self.store.q("select * from proposals where id=?", pid)
        if not rows:
            raise CoachError("Proposta inesistente")
        if rows[0]["status"] != "open":
            raise CoachError("Proposta già gestita")
        p = json.loads(rows[0]["payload"])
        today = self.cfg.today()
        kind = rows[0]["kind"]
        if kind == "log":
            d = date.fromisoformat(p["day"])
            for i in p["items"]:
                self.coach.log_extra(d, p["slot"], i["food_id"], i["grams"], today)
        elif kind == "phase":
            if p.get("template_id"):
                self.coach.start_phase(p["template_id"], today, p.get("changes") or None)
            else:
                self.coach.update_phase(p["changes"], today)
        elif kind == "plan":
            meals = [
                {
                    "slot": m["slot"],
                    "status": "planned",
                    "locked": False,
                    "items": [
                        {
                            "food_id": i["food_id"],
                            "grams": i["grams"],
                            "planned_grams": i["grams"],
                            "planned_food_id": i["food_id"],
                            "locked": False,
                        }
                        for i in m["items"]
                    ],
                }
                for m in p["meals"]
            ]
            self.coach.save_plan(date.fromisoformat(p["day"]), meals)
        self.store.x("update proposals set status='applied' where id=?", pid)
        if kind == "log":
            self.app.syncer.push()
        return {"ok": True, "kind": kind}

    def dismiss(self, pid: int) -> dict:
        self.store.x("update proposals set status='dismissed' where id=? and status='open'", pid)
        return {"ok": True}


class ChatBody(BaseModel):
    message: str


def _agent(request: Request) -> Agent:
    return request.app.state.app.agent


@router.post("/api/chat")
async def chat(body: ChatBody, request: Request):
    agent = _agent(request)
    if not body.message.strip():
        raise HTTPException(400, "messaggio vuoto")

    # The turn runs on its own task: if the phone locks or the page reloads mid-answer, the agent still
    # finishes and saves the reply, which the chat shows on the next load.
    queue: asyncio.Queue = asyncio.Queue()

    async def run():
        try:
            async for ev in agent.stream(body.message.strip()):
                await queue.put(ev)
        finally:
            await queue.put(None)

    task = asyncio.create_task(run())
    _running.add(task)
    task.add_done_callback(_running.discard)

    async def gen():
        while (ev := await queue.get()) is not None:
            yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )


@router.get("/api/chat")
def chat_history(request: Request):
    """The conversation as the UI shows it: text turns, tool steps and proposal cards."""
    agent = _agent(request)
    store = agent.store
    out = []
    open_props = {r["id"]: r["status"] for r in store.q("select id, status from proposals")}
    for r in store.q("select role, content, created from chat order by id"):
        content = json.loads(r["content"])
        if r["role"] == "user" and isinstance(content, str):
            out.append({"role": "user", "text": content, "at": r["created"]})
        elif r["role"] == "assistant":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            tools = [TOOL_LABELS.get(b["name"], b["name"]) for b in content if b.get("type") == "tool_use"]
            if text or tools:
                out.append({"role": "assistant", "text": text, "tools": tools, "at": r["created"]})
        elif r["role"] == "user":
            for b in content:
                if b.get("type") == "tool_result" and not b.get("is_error"):
                    try:
                        res = json.loads(b["content"])
                    except ValueError, TypeError:
                        continue
                    if isinstance(res, dict) and res.get("action_id"):
                        act = store.q("select receipt, status from actions where id=?", res["action_id"])
                        if act:
                            receipt = json.loads(act[0]["receipt"])
                            action = {"action_id": res["action_id"], "status": act[0]["status"], **receipt}
                            out.append({"role": "action", "action": action})
                    elif isinstance(res, dict) and res.get("proposal_id"):
                        pr = store.q("select * from proposals where id=?", res["proposal_id"])
                        if pr:
                            payload = json.loads(pr[0]["payload"])
                            out.append(
                                {
                                    "role": "proposal",
                                    "proposal": {
                                        "proposal_id": pr[0]["id"],
                                        "kind": pr[0]["kind"],
                                        "status": open_props.get(pr[0]["id"]),
                                        **payload,
                                    },
                                }
                            )
    return out


@router.delete("/api/chat")
def chat_clear(request: Request):
    _agent(request).store.x("delete from chat")
    return {"ok": True}


@router.post("/api/proposals/{pid}/apply")
def apply(pid: int, request: Request):
    return _agent(request).apply(pid)


@router.post("/api/actions/{aid}/undo")
def undo(aid: int, request: Request):
    return _agent(request).undo(aid)


@router.post("/api/proposals/{pid}/dismiss")
def dismiss(pid: int, request: Request):
    return _agent(request).dismiss(pid)
