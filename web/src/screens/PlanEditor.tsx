import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { ArrowLeftRight, Lock, LockOpen, Plus, Trash2 } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router"
import { useApp } from "../App"
import FoodPicker, { macrosFor, stepFor, type PickedFood } from "../components/FoodPicker"
import { Bar, Button, Chip, ErrorBox, Sheet, Spinner, Stepper } from "../components/ui"
import { ApiError, api, post, put, type Alternative, type FitReport, type Macros, type Meal, type Plan } from "../lib/api"
import { longDay, n0, SLOT_LABEL } from "../lib/format"

type EItem = {
  food_id: string
  name: string
  grams: number
  locked: boolean
  per100: Macros
  unit_g: number | null
  unit_name: string | null
  step: number
  role: string
  planned_grams: number | null
  planned_food_id: string | null
}
type EMeal = { slot: string; label: string; status: Meal["status"]; locked: boolean; items: EItem[] }

const SLOTS = ["colazione", "pranzo", "spuntino", "cena"]

const fromPlan = (p: Plan | { meals: Meal[] }): EMeal[] =>
  p.meals.map((m) => ({
    slot: m.slot,
    label: m.label ?? SLOT_LABEL[m.slot] ?? m.slot,
    status: m.status,
    locked: m.locked,
    items: m.items.map((i) => ({
      food_id: i.food_id,
      name: i.name,
      grams: i.grams,
      locked: i.locked,
      per100: i.per100,
      unit_g: i.unit_g,
      unit_name: i.unit_name,
      step: i.step,
      role: i.role,
      planned_grams: i.planned_grams,
      planned_food_id: i.planned_food_id,
    })),
  }))

const toBody = (ms: EMeal[]) =>
  ms.map((m) => ({
    slot: m.slot,
    status: m.status,
    locked: m.locked,
    items: m.items.map((i) => ({ food_id: i.food_id, grams: i.grams, locked: i.locked, planned_grams: i.planned_grams, planned_food_id: i.planned_food_id })),
  }))

const total = (ms: EMeal[]) =>
  ms
    .filter((m) => m.status !== "skipped")
    .flatMap((m) => m.items.map((i) => macrosFor(i.per100, i.grams)))
    .reduce((a, b) => ({ kcal: a.kcal + b.kcal, protein: a.protein + b.protein, carbs: a.carbs + b.carbs, fat: a.fat + b.fat }), { kcal: 0, protein: 0, carbs: 0, fat: 0 })

export default function PlanEditor() {
  const { day = "" } = useParams()
  const nav = useNavigate()
  const qc = useQueryClient()
  const { toast } = useApp()
  const q = useQuery({
    queryKey: ["plan", day],
    queryFn: async () => {
      try {
        return await api<Plan>(`/api/plan/${day}`)
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null
        throw e
      }
    },
  })
  const [meals, setMeals] = useState<EMeal[]>([])
  const [target, setTarget] = useState<Macros | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [swap, setSwap] = useState<{ m: number; i: number } | null>(null)
  const [adding, setAdding] = useState<number | null>(null)
  const [askPin, setAskPin] = useState(false)

  useEffect(() => {
    if (q.data) {
      setMeals(fromPlan(q.data))
      setTarget(q.data.target)
    } else if (q.data === null) {
      setMeals(SLOTS.map((s) => ({ slot: s, label: SLOT_LABEL[s], status: "planned", locked: false, items: [] })))
    }
  }, [q.data])

  const tot = useMemo(() => total(meals), [meals])
  const dirty = q.data ? JSON.stringify(toBody(meals)) !== JSON.stringify(toBody(fromPlan(q.data))) : meals.some((m) => m.items.length)
  const tol = 50
  const off = target ? tot.kcal - target.kcal : 0
  const ok = target ? Math.abs(off) <= tol : true

  const fit = useMutation({
    mutationFn: () => post<{ meals: Meal[]; report: FitReport }>(`/api/plan/${day}/fit`, { meals: toBody(meals) }),
    onSuccess: (r) => {
      setMeals(fromPlan(r))
      setNotes(r.report.notes)
      if (!r.report.within_tolerance) toast("Con questi blocchi il target non si raggiunge del tutto")
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  const save = useMutation({
    mutationFn: async (pinAlways: boolean) => {
      await put(`/api/plan/${day}`, { meals: toBody(meals) })
      if (pinAlways) {
        for (const m of meals.filter((m) => m.locked && m.items.length)) {
          const key = `${m.slot}:${[...new Set(m.items.map((i) => i.food_id))].sort().join("+")}`
          await post("/api/templates/pin", { key, mode: "fixed" })
        }
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["today"] })
      qc.invalidateQueries({ queryKey: ["day", day] })
      qc.invalidateQueries({ queryKey: ["plan", day] })
      toast("Piano salvato")
      nav(-1)
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })

  const update = (mi: number, fn: (m: EMeal) => EMeal) => setMeals(meals.map((m, k) => (k === mi ? fn(m) : m)))
  const updateItem = (mi: number, ii: number, fn: (i: EItem) => EItem) => update(mi, (m) => ({ ...m, items: m.items.map((x, k) => (k === ii ? fn(x) : x)) }))

  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBox error={q.error} retry={() => q.refetch()} />

  return (
    <div className="animate-rise pb-24 lg:mx-auto lg:max-w-3xl">
      <div className="mb-2 flex items-center justify-between pt-1.5">
        <button className="text-[13px] text-mu" onClick={() => (dirty ? setMeals(q.data ? fromPlan(q.data) : []) : nav(-1))}>
          {dirty ? "Annulla modifiche" : "‹ Indietro"}
        </button>
        <h1 className="text-[17px] font-bold">Modifica piano</h1>
        <button className={clsx("text-[13px] font-semibold", ok ? "text-mu" : "text-ac")} onClick={() => fit.mutate()} disabled={fit.isPending || !target}>
          {fit.isPending ? "…" : "Ribilancia"}
        </button>
      </div>
      <div className="sticky top-0 z-20 -mx-4 mb-2.5 border-b border-ln bg-bg/95 px-4 pt-2 pb-2.5 backdrop-blur">
        <div className="mb-1 text-[11px] text-mu first-letter:uppercase">{longDay(day)}</div>
        <div className="mb-1.5 flex items-center justify-between text-[12px]">
          <span>
            <b className="text-[15px]">{n0(tot.kcal)}</b>
            <span className="text-mu">{target ? ` / ${n0(target.kcal)} kcal` : " kcal"}</span>
          </span>
          {target && <Chip tone={ok ? "ok" : "wa"}>{ok ? "in target" : `${off > 0 ? "+" : "−"}${n0(Math.abs(off))} sul target`}</Chip>}
        </div>
        {target && <Bar parts={[{ value: (tot.kcal / target.kcal) * 100, color: ok ? "#B8F35A" : "#F7C052" }]} />}
        <div className="mt-1.5 flex justify-between text-[11px] text-mu">
          <span>P {n0(tot.protein)}{target ? ` / ${n0(target.protein)}` : ""}</span>
          <span>C {n0(tot.carbs)} g</span>
          <span>G {n0(tot.fat)}{target ? ` / ${n0(target.fat)}` : ""}</span>
        </div>
      </div>

      {meals.map((m, mi) => {
        const readOnly = m.status !== "planned"
        const kcal = m.items.reduce((a, i) => a + macrosFor(i.per100, i.grams).kcal, 0)
        return (
          <div key={m.slot} className={clsx("mb-2.5 rounded-[18px] border border-ln bg-s1 px-3 py-2.5", (m.locked || readOnly) && "opacity-75")}>
            <div className="mb-0.5 flex items-center justify-between">
              <b className="text-[13.5px]">{m.label}</b>
              <span className="flex items-center gap-1.5">
                {readOnly && <Chip tone="ok">{m.status === "skipped" ? "saltato" : "confermato"}</Chip>}
                {!readOnly && (
                  <button
                    onClick={() => update(mi, (x) => ({ ...x, locked: !x.locked }))}
                    className={clsx("flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10.5px] font-semibold", m.locked ? "border-ac/40 bg-ac/10 text-ac" : "border-ln text-mu")}
                  >
                    {m.locked ? <Lock className="size-3" /> : <LockOpen className="size-3" />} {m.locked ? "bloccato" : "blocca"}
                  </button>
                )}
                <span className="text-[11px] text-mu">{n0(kcal)} kcal</span>
              </span>
            </div>
            {m.items.length === 0 && <div className="py-2 text-[12px] text-mu">Vuoto</div>}
            {m.items.map((it, ii) => {
              const changed = it.planned_grams != null && Math.round(it.planned_grams) !== Math.round(it.grams)
              const swapped = it.planned_food_id && it.planned_food_id !== it.food_id
              return (
                <div key={ii} className="flex items-center gap-1.5 border-t border-ln py-2 first:border-t-0">
                  <div className="min-w-0 flex-1">
                    <b className={clsx("block truncate text-[12.5px] font-semibold", (changed || swapped) && "text-c")}>{it.name}</b>
                    <span className="text-[10.5px] text-mu">
                      {swapped ? "sostituito" : changed ? `proposto ${n0(it.planned_grams)} g` : `${n0(macrosFor(it.per100, it.grams).kcal)} kcal`}
                    </span>
                  </div>
                  {!readOnly && !m.locked && (
                    <>
                      <button onClick={() => setSwap({ m: mi, i: ii })} className="grid size-7 place-items-center rounded-lg text-mu active:bg-s2" aria-label="Sostituisci">
                        <ArrowLeftRight className="size-[15px]" />
                      </button>
                      <button
                        onClick={() => updateItem(mi, ii, (x) => ({ ...x, locked: !x.locked }))}
                        className={clsx("grid size-7 place-items-center rounded-lg", it.locked ? "bg-ac/10 text-ac" : "text-mu active:bg-s2")}
                        aria-label="Blocca"
                      >
                        <Lock className="size-[15px]" />
                      </button>
                    </>
                  )}
                  <div className={clsx((readOnly || m.locked) && "pointer-events-none opacity-50")}>
                    <Stepper
                      value={it.grams}
                      step={it.step}
                      {...(it.unit_name === "porzione" ? { factor: 100, unit: "p." } : {})}
                      onChange={(g) => updateItem(mi, ii, (x) => ({ ...x, grams: g }))}
                    />
                  </div>
                  {!readOnly && !m.locked && (
                    <button onClick={() => update(mi, (x) => ({ ...x, items: x.items.filter((_, k) => k !== ii) }))} className="grid size-7 place-items-center text-mu active:text-er" aria-label="Rimuovi">
                      <Trash2 className="size-[15px]" />
                    </button>
                  )}
                </div>
              )
            })}
            {!readOnly && !m.locked && (
              <button onClick={() => setAdding(mi)} className="mt-0.5 flex items-center gap-1 py-1.5 text-[12px] font-semibold text-ac">
                <Plus className="size-3.5" /> Aggiungi
              </button>
            )}
          </div>
        )
      })}
      {notes.length > 0 && <div className="mb-2 px-1 text-[11.5px] text-mu">{notes.join(" ")}</div>}
      <div className="px-1 text-[11px] leading-relaxed text-mu">
        Ribilancia muove solo ciò che non è bloccato: prima le proteine, poi i grassi aggiunti se in eccesso, poi i carboidrati. Verdure e lucchetti non si toccano. Il piano è indicativo: puoi salvarlo anche fuori target.
      </div>

      <div className="pb-safe dock z-30 flex gap-2 bg-gradient-to-t from-bg via-bg to-transparent px-4 pt-6">
        <Button className="flex-1" onClick={() => nav(-1)}>
          Chiudi
        </Button>
        <Button kind="primary" className="flex-[2]" busy={save.isPending} disabled={!dirty} onClick={() => (meals.some((m) => m.locked && m.items.length) ? setAskPin(true) : save.mutate(false))}>
          Usa questo piano
        </Button>
      </div>

      {swap && (
        <SwapSheet
          item={meals[swap.m].items[swap.i]}
          slot={meals[swap.m].slot}
          onClose={() => setSwap(null)}
          onPick={(f, g) => {
            updateItem(swap.m, swap.i, (x) => ({
              ...x,
              food_id: f.id,
              name: f.name,
              grams: g,
              per100: f.per100,
              unit_g: f.unit_g,
              unit_name: f.unit_name,
              step: stepFor(f.per100, f.unit_g),
              planned_food_id: x.planned_food_id ?? x.food_id,
            }))
            setSwap(null)
          }}
        />
      )}
      <Sheet open={adding != null} onClose={() => setAdding(null)} title={`Aggiungi a ${adding != null ? meals[adding].label : ""}`}>
        <FoodPicker
          onPick={(f: PickedFood) => {
            if (adding == null) return
            const step = stepFor(f.per100, f.unit_g)
            update(adding, (m) => ({
              ...m,
              items: [...m.items, { food_id: f.id, name: f.name, grams: f.unit_g ?? 100, locked: false, per100: f.per100, unit_g: f.unit_g, unit_name: f.unit_name, step, role: "", planned_grams: null, planned_food_id: null }],
            }))
            setAdding(null)
          }}
        />
      </Sheet>
      <Sheet
        open={askPin}
        onClose={() => setAskPin(false)}
        title="Blocchi i pasti sempre?"
        footer={
          <div className="mb-1 flex gap-2">
            <Button className="flex-1" busy={save.isPending && save.variables === false} onClick={() => save.mutate(false)}>
              Solo questo piano
            </Button>
            <Button kind="primary" className="flex-1" busy={save.isPending && save.variables === true} onClick={() => save.mutate(true)}>
              Blocca sempre
            </Button>
          </div>
        }
      >
        <p className="text-[12.5px] text-tx2">
          Hai bloccato {meals.filter((m) => m.locked && m.items.length).map((m) => m.label.toLowerCase()).join(" e ")}. Vale solo per questo piano, oppure diventa un pasto fisso che i piani futuri non ridimensionano?
        </p>
      </Sheet>
    </div>
  )
}

function SwapSheet({ item, slot, onClose, onPick }: { item: EItem; slot: string; onClose: () => void; onPick: (f: PickedFood, grams: number) => void }) {
  const [search, setSearch] = useState(false)
  const alts = useQuery({
    queryKey: ["alts", item.food_id, item.grams],
    queryFn: () => post<Alternative[]>("/api/foods/alternatives", { food_id: item.food_id, grams: item.grams, slot }),
  })
  const key = item.role === "protein" ? "protein" : item.role === "fat" ? "fat" : item.role === "carb" || item.role === "fruit" ? "carbs" : "kcal"
  return (
    <Sheet open onClose={onClose} title={`Sostituisci ${item.name.toLowerCase()}`}>
      {!search ? (
        <>
          <div className="mb-1 text-[11px] text-mu">
            stessi {key === "protein" ? "grammi di proteine" : key === "carbs" ? "carboidrati" : key === "fat" ? "grassi" : "calorie"} di {n0(item.grams)} g
          </div>
          {alts.isLoading && <Spinner />}
          {alts.data?.map((a) => (
            <button
              key={a.food_id}
              onClick={async () => {
                const per100 = { kcal: (a.macros.kcal / a.grams) * 100, protein: (a.macros.protein / a.grams) * 100, carbs: (a.macros.carbs / a.grams) * 100, fat: (a.macros.fat / a.grams) * 100 }
                onPick({ id: a.food_id, name: a.name, per100, unit_g: null, unit_name: null }, a.grams)
              }}
              className="flex w-full items-center gap-3 border-t border-ln py-2.5 text-left first:border-t-0"
            >
              <div className="min-w-0 flex-1">
                <b className="block truncate text-[13px]">{a.name}</b>
                <span className="text-[10.5px] text-mu">
                  {n0(a.macros.kcal)} kcal · P {n0(a.macros.protein)} · C {n0(a.macros.carbs)} · G {n0(a.macros.fat)}
                  {a.frequent ? " · lo mangi" : ""}
                </span>
              </div>
              <span className="font-bold text-ac">{n0(a.grams)} g</span>
            </button>
          ))}
          {alts.data?.length === 0 && <div className="py-4 text-center text-[12.5px] text-mu">Nessun alimento equivalente tra quelli che usi</div>}
          <button onClick={() => setSearch(true)} className="mt-1 w-full border-t border-ln py-3 text-left text-[13px] font-semibold text-mu">
            Cerca su Cronometer…
          </button>
        </>
      ) : (
        <FoodPicker
          onPick={(f) => {
            const want = key === "kcal" ? macrosFor(item.per100, item.grams).kcal : macrosFor(item.per100, item.grams)[key]
            const per = key === "kcal" ? f.per100.kcal : f.per100[key]
            const step = stepFor(f.per100, f.unit_g)
            const g = per > 0 ? Math.max(step, Math.round(((want / per) * 100) / step) * step) : item.grams
            onPick(f, g)
          }}
        />
      )}
    </Sheet>
  )
}
