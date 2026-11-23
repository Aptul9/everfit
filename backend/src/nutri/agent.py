"""The coach in the chat.

The model reads data, runs the engine and explains. It never does arithmetic
itself, and it never writes: every change (a phase, a plan, a diary entry)
comes back as a proposal card the owner confirms.
"""

import asyncio
import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .book import Book
from .engine.plan import Item, Meal, fit_day, totals
from .engine.targets import Macros
from .llm import Final, Messages
from .service import CoachError, macros_dict
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
- Non scrivi mai niente direttamente. Ogni modifica (registrare cibo, cambiare fase o target, cambiare il \
piano) la proponi con lo strumento proponi_*: l'utente vede una scheda e conferma lui. Dopo una proposta \
dillo in una riga, senza ripetere i numeri della scheda.
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

Oggi è {today}. Fonte dati: {source}.

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
    "proponi_registrazione": "proposta preparata",
    "proponi_fase": "proposta preparata",
    "proponi_piano": "proposta preparata",
}

ITEM = {
    "type": "object",
    "properties": {"food_id": {"type": "string"}, "grams": {"type": "number"}},
    "required": ["food_id", "grams"],
}
TOOLS = [
    {
        "name": "oggi",
        "description": "Target, mangiato, rimanente e piano della giornata.",
        "input_schema": {
            "type": "object",
            "properties": {"day": {"type": "string", "description": "YYYY-MM-DD"}},
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
        "name": "proponi_registrazione",
        "description": "Propone di registrare alimenti su Cronometer.",
        "input_schema": {
            "type": "object",
            "properties": {
                "slot": {"type": "string", "enum": ["colazione", "pranzo", "spuntino", "cena"]},
                "items": {"type": "array", "items": ITEM},
                "day": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["slot", "items", "summary"],
        },
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
        "description": "Propone un piano alimentare per un giorno, che sostituisce quello "
        "attuale. I grammi passali già calcolati con calcola_pasto.",
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
        return SYSTEM.format(today=self.cfg.today().isoformat(), source=self.app.source.name, story=story)

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
        """Returns (result for the model, proposal card for the UI or None)."""
        today = self.cfg.today()
        c = self.coach
        if name == "oggi":
            d = date.fromisoformat(args["day"]) if args.get("day") else today
            v = c.today(d, today)
            return {
                k: v[k]
                for k in (
                    "day",
                    "targets",
                    "target_loggable",
                    "consumed",
                    "remaining",
                    "expenditure",
                    "weight",
                )
            } | {
                "meals": [
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
                    for m in v["meals"]
                ]
            }, None
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
        if name == "proponi_registrazione":
            items = self._food_items(args["items"])
            d = args.get("day") or today.isoformat()
            card = self._proposal(
                "log",
                {
                    "day": d,
                    "slot": args["slot"],
                    "items": [
                        {
                            "food_id": i.food.id,
                            "name": i.food.name,
                            "grams": i.grams,
                            **macros_dict(i.macros()),
                        }
                        for i in items
                    ],
                    "total": macros_dict(totals([Meal("x", items)])),
                },
                args["summary"],
            )
            return {"ok": "proposta mostrata all'utente", "proposal_id": card["proposal_id"]}, card
        if name == "proponi_fase":
            payload = {"template_id": args.get("template_id"), "changes": args.get("changes") or {}}
            p = c.phase()
            payload["current"] = p and p.model_dump(mode="json")
            card = self._proposal("phase", payload, args["summary"])
            return {"ok": "proposta mostrata all'utente", "proposal_id": card["proposal_id"]}, card
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
            return {"ok": "proposta mostrata all'utente", "proposal_id": card["proposal_id"]}, card
        raise CoachError(f"strumento {name} sconosciuto")

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
        said = False
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
                    out, card = self.run_tool(u["name"], u.get("input") or {})
                    if card:
                        yield {"type": "proposal", "proposal": card}
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
                    if isinstance(res, dict) and res.get("proposal_id"):
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


@router.post("/api/proposals/{pid}/dismiss")
def dismiss(pid: int, request: Request):
    return _agent(request).dismiss(pid)
