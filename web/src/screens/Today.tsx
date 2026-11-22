import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { AlertTriangle, Check, ChevronRight, CloudOff, Plus, RefreshCcw, Settings2, Trash2, Undo2 } from "lucide-react"
import { useMemo, useState } from "react"
import { useNavigate } from "react-router"
import { useApp } from "../App"
import { Spark } from "../components/charts"
import FoodPicker, { macrosFor, stepFor, type PickedFood } from "../components/FoodPicker"
import { Bar, Button, Card, Chip, Dot, ErrorBox, MACRO_COLORS, Ring, Sheet, Spinner, Stepper } from "../components/ui"
import { api, post, type Macros, type Meal, type PlanItem, type Today as TodayT } from "../lib/api"
import { grams, longDay, n0, n1, rate, SLOT_LABEL } from "../lib/format"

type EditItem = { food_id: string; name: string; grams: number; per100: Macros; unit_g: number | null; unit_name: string | null; step: number; planned: number | null }

const sum = (ms: Macros[]) =>
  ms.reduce((a, m) => ({ kcal: a.kcal + m.kcal, protein: a.protein + m.protein, carbs: a.carbs + m.carbs, fat: a.fat + m.fat }), { kcal: 0, protein: 0, carbs: 0, fat: 0 })

export default function Today() {
  const { boot, toast } = useApp()
  const qc = useQueryClient()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ["today"], queryFn: () => api<TodayT>("/api/today") })
  const sync = useQuery({ queryKey: ["sync"], queryFn: () => api<{ pending: number; failed: number; last_error?: string | null }>("/api/sync"), refetchInterval: 20_000 })
  const [adjust, setAdjust] = useState<Meal | null>(null)
  const [extraOpen, setExtraOpen] = useState(false)

  const act = useMutation({
    mutationFn: ({ slot, action, items }: { slot: string; action: "confirm" | "skip" | "undo"; items?: { food_id: string; grams: number }[] }) =>
      post<TodayT>(`/api/plan/${q.data!.day}/meals/${slot}/${action}`, action === "confirm" ? { items: items ?? null } : {}),
    onSuccess: (data, v) => {
      qc.setQueryData(["today"], data)
      qc.invalidateQueries({ queryKey: ["history"] })
      qc.invalidateQueries({ queryKey: ["sync"] })
      toast(v.action === "confirm" ? "Registrato su Cronometer" : v.action === "skip" ? "Pasto saltato, il resto è ribilanciato" : "Conferma annullata")
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })

  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBox error={q.error} retry={() => q.refetch()} />
  const t = q.data!
  const target = t.target_loggable
  const consumed = t.consumed
  const planned = t.planned_remaining
  const flags = t.targets?.flags ?? []

  return (
    <div className="animate-rise">
      <div className="mb-3.5 flex items-end justify-between gap-2 px-0.5 pt-1.5">
        <div>
          <div className="mb-0.5 text-[11px] font-medium uppercase tracking-[0.08em] text-mu">{longDay(t.day)}</div>
          <h1 className="text-[26px] font-bold tracking-[-0.02em]">Oggi</h1>
        </div>
        <div className="flex items-center gap-2">
          {t.phase && <Chip tone="ac">{t.phase.name}{t.targets?.kind === "refeed" ? " · ricarica" : ""}</Chip>}
          <button onClick={() => nav("/impostazioni")} className="grid size-9 place-items-center rounded-xl text-mu active:bg-s2" aria-label="Impostazioni">
            <Settings2 className="size-5" />
          </button>
        </div>
      </div>

      {boot.demo && (
        <div className="mb-3 rounded-2xl border border-mi/25 bg-mi/8 px-3.5 py-2.5 text-[12px] text-tx2">
          Modalità demo: dati di una persona simulata. Con le credenziali Cronometer l'app usa i tuoi.
        </div>
      )}

      {(sync.data?.failed ?? 0) > 0 && (
        <button onClick={() => nav("/impostazioni")} className="mb-3 flex w-full items-center gap-3 rounded-2xl border border-er/30 bg-er/10 px-3.5 py-2.5 text-left">
          <CloudOff className="size-4 text-er" />
          <span className="flex-1 text-[12px] text-tx2">{sync.data!.failed} scritture su Cronometer non riuscite</span>
          <ChevronRight className="size-4 text-mu" />
        </button>
      )}

      {t.checkin && (
        <button
          onClick={() => nav("/checkin")}
          className="mb-3 flex w-full items-center gap-3 rounded-[18px] border border-ac/30 bg-gradient-to-r from-ac/16 to-mi/6 px-3.5 py-3 text-left"
        >
          <span className="grid size-[34px] place-items-center rounded-[11px] bg-ac/18 text-ac">
            <Check className="size-[18px]" />
          </span>
          <span className="flex-1">
            <b className="block text-[13px]">Check-in settimanale pronto</b>
            <span className="text-[11px] text-mu">{t.checkin.has_proposal ? "1 proposta da rivedere" : t.checkin.headline}</span>
          </span>
          <ChevronRight className="size-5 text-mu" />
        </button>
      )}

      {flags.filter((f) => f.severity !== "info").map((f) => (
        <div key={f.code} className={clsx("mb-3 flex gap-2.5 rounded-2xl border px-3.5 py-2.5 text-[12px]", f.severity === "stop" ? "border-er/30 bg-er/10" : "border-wa/30 bg-wa/8")}>
          <AlertTriangle className={clsx("mt-0.5 size-4 shrink-0", f.severity === "stop" ? "text-er" : "text-wa")} />
          <span className="text-tx2">
            {f.message}
            {f.source && <span className="text-mu"> · {f.source}</span>}
          </span>
        </div>
      ))}

      {target && (
        <Card className="mb-3">
          <div className="flex items-center gap-4">
            <Ring value={consumed.kcal} max={target.kcal}>
              <b className="text-[30px] font-bold tracking-[-0.03em]">{n0(Math.abs(target.kcal - consumed.kcal))}</b>
              <span className="text-[11px] text-mu">{consumed.kcal > target.kcal ? "kcal sopra" : "kcal rimaste"}</span>
            </Ring>
            <div className="flex flex-1 flex-col gap-2 text-[12px]">
              <Row label="Mangiato" value={n0(consumed.kcal)} />
              <Row label="Da piano" value={n0(planned.kcal)} muted />
              <Row label="Target" value={n0(target.kcal)} />
              <Row label="Metabolismo" value={`~${n0(t.expenditure.kcal)}`} />
            </div>
          </div>
          <div className="mt-4 grid gap-[11px]">
            {(["protein", "carbs", "fat"] as const).map((k) => (
              <div key={k}>
                <div className="mb-1.5 flex justify-between text-[12px]">
                  <span>
                    <Dot color={MACRO_COLORS[k]} />
                    {k === "protein" ? "Proteine" : k === "carbs" ? "Carboidrati" : "Grassi"}
                  </span>
                  <span>
                    <b>{n0(consumed[k])}</b>
                    <span className="text-mu"> / {n0(target[k])} g</span>
                  </span>
                </div>
                <Bar
                  parts={[
                    { value: (consumed[k] / (target[k] || 1)) * 100, color: MACRO_COLORS[k] },
                    { value: (planned[k] / (target[k] || 1)) * 100, color: MACRO_COLORS[k] + "3a" },
                  ]}
                />
              </div>
            ))}
          </div>
        </Card>
      )}

      {t.plan ? (
        <div className="flex flex-col gap-2.5">
          {t.plan.meals.map((m) => (
            <MealCard
              key={m.slot}
              meal={m}
              busy={act.isPending && act.variables?.slot === m.slot}
              onConfirm={() => act.mutate({ slot: m.slot, action: "confirm" })}
              onSkip={() => act.mutate({ slot: m.slot, action: "skip" })}
              onUndo={() => act.mutate({ slot: m.slot, action: "undo" })}
              onAdjust={() => setAdjust(m)}
            />
          ))}
          {!t.plan.report.within_tolerance && t.plan.report.notes.length > 0 && (
            <div className="px-1 text-[11.5px] text-mu">{t.plan.report.notes.join(" ")}</div>
          )}
        </div>
      ) : (
        <Card>
          <b className="text-[14px]">Nessun piano per oggi</b>
          <p className="mt-1 text-[12.5px] text-tx2">
            Il piano si costruisce dai pasti che hai già nel diario di Cronometer. Quando ce ne sono, la giornata arriva già compilata.
          </p>
          <Button small className="mt-3" onClick={() => nav(`/piano/modifica/${t.day}`)}>
            Crea il piano a mano
          </Button>
        </Card>
      )}

      {t.extra.length > 0 && (
        <Card className="mt-2.5">
          <div className="mb-1 text-[14px] font-bold">Altro mangiato</div>
          {t.extra.map((e, i) => (
            <div key={i} className="flex justify-between border-t border-ln py-2 text-[12.5px] first:border-t-0">
              <span>
                {e.name} <span className="text-mu">· {SLOT_LABEL[e.slot] ?? e.slot}</span>
              </span>
              <span className="text-mu">
                {n0(e.grams)} g{e.pending ? " · in invio" : ""}
              </span>
            </div>
          ))}
        </Card>
      )}

      {t.suggestions.length > 0 && t.remaining && (
        <Card className="mt-2.5">
          <div className="flex items-center justify-between">
            <b className="text-[14px]">Ti mancano {n0(t.remaining.protein)} g di proteine</b>
          </div>
          <div className="mb-1 mt-0.5 text-[11px] text-mu">Dai tuoi alimenti, dentro le {n0(t.remaining.kcal)} kcal rimaste</div>
          {t.suggestions.map((s, i) => (
            <SuggestionRow key={i} s={s} day={t.day} />
          ))}
        </Card>
      )}

      <button
        onClick={() => setExtraOpen(true)}
        className="mt-2.5 flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-[#333b45] p-3 text-[12px] font-semibold text-mu active:bg-s1"
      >
        <Plus className="size-4" /> Ho mangiato altro
      </button>

      <Card className="mt-2.5" onClick={() => nav("/progressi")}>
        <div className="mb-2 flex items-center justify-between">
          <b className="text-[14px]">Peso</b>
          <span className="text-[11px] text-mu">trend, non la bilancia</span>
        </div>
        <div className="flex items-end justify-between">
          <div>
            <div className="text-[34px] font-bold leading-none tracking-[-0.03em]">
              {n1(t.weight.trend)}
              <span className="ml-1 text-[14px] font-medium tracking-normal text-mu">kg</span>
            </div>
            <div className="mt-2 text-[12px]">
              <RateText r={t.weight.rate_kg_week} band={t.phase?.band_kg_week} />
            </div>
          </div>
          <Spark values={t.weight.spark} />
        </div>
      </Card>

      {adjust && <AdjustSheet meal={adjust} onClose={() => setAdjust(null)} onConfirm={(items) => act.mutate({ slot: adjust.slot, action: "confirm", items }, { onSuccess: () => setAdjust(null) })} busy={act.isPending} />}
      <ExtraSheet open={extraOpen} day={t.day} onClose={() => setExtraOpen(false)} />
    </div>
  )
}

function Row({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-mu">{label}</span>
      <b className={clsx("font-semibold", muted && "text-mu")}>{value}</b>
    </div>
  )
}

export function RateText({ r, band }: { r: number | null; band?: [number, number] | null }) {
  if (r == null) return <span className="text-mu">ritmo non ancora misurabile</span>
  const inBand = band ? r >= band[0] && r <= band[1] : null
  return (
    <>
      <span className={inBand === false ? "text-wa" : "text-ok"}>{rate(r)}</span>
      <span className="text-mu"> · {inBand == null ? "ultime 2 settimane" : inBand ? "in linea" : "fuori forbice"}</span>
    </>
  )
}

const STATUS: Record<string, { label: string; tone: "ok" | "wa" | "neutral" | "mi" }> = {
  confirmed: { label: "✓ confermato", tone: "ok" },
  modified: { label: "modificato", tone: "wa" },
  skipped: { label: "saltato", tone: "neutral" },
  logged: { label: "su Cronometer", tone: "mi" },
}

function MealCard({ meal, busy, onConfirm, onSkip, onUndo, onAdjust }: { meal: Meal; busy: boolean; onConfirm: () => void; onSkip: () => void; onUndo: () => void; onAdjust: () => void }) {
  const planned = meal.status === "planned"
  const rebalanced = planned && meal.items.some((i) => i.planned_grams != null && Math.round(i.planned_grams) !== Math.round(i.grams))
  const st = STATUS[meal.status]
  return (
    <Card className={clsx(planned ? "border-ac/30" : "opacity-80", meal.status === "skipped" && "opacity-55")}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <b className="text-[14px]">{meal.label}</b>
        <span className="flex items-center gap-1.5">
          {meal.locked && planned && <Chip tone="ok">Fisso</Chip>}
          {rebalanced && <Chip tone="mi">ribilanciato</Chip>}
          {planned && !rebalanced && !meal.locked && <Chip>da confermare</Chip>}
          {st && <Chip tone={st.tone}>{st.label}</Chip>}
        </span>
      </div>
      <ItemsLine items={meal.items} />
      <div className="mt-1 text-[11px] text-mu">
        {n0(meal.macros.kcal)} kcal · P {n0(meal.macros.protein)} · C {n0(meal.macros.carbs)} · G {n0(meal.macros.fat)}
      </div>
      {planned && (
        <div className="mt-2.5 flex gap-1.5">
          <Button kind="primary" small className="flex-1" onClick={onConfirm} busy={busy}>
            <Check className="size-4" /> Mangiato
          </Button>
          <Button small className="flex-1" onClick={onAdjust}>
            Regola
          </Button>
          <Button kind="ghost" small onClick={onSkip}>
            Saltato
          </Button>
        </div>
      )}
      {(meal.status === "confirmed" || meal.status === "modified" || meal.status === "skipped") && (
        <button onClick={onUndo} className="mt-2 flex items-center gap-1 text-[11.5px] text-mu active:text-tx">
          <Undo2 className="size-3.5" /> Annulla
        </button>
      )}
    </Card>
  )
}

function ItemsLine({ items }: { items: PlanItem[] }) {
  return (
    <div className="text-[12.5px] leading-[1.55] text-tx2">
      {items.map((i, k) => {
        const changed = i.planned_grams != null && Math.round(i.planned_grams) !== Math.round(i.grams)
        const swapped = i.planned_food_id && i.planned_food_id !== i.food_id
        return (
          <span key={k}>
            {k > 0 && <span className="text-mu"> · </span>}
            {i.name}{" "}
            <b className={clsx("font-semibold", changed ? "text-c" : "text-tx")}>{grams(i.grams, i.unit_g, i.unit_name)}</b>
            {changed && <s className="ml-1 text-mu">{n0(i.planned_grams)}</s>}
            {swapped && i.planned_food_name && <span className="text-mu"> (era {i.planned_food_name})</span>}
          </span>
        )
      })}
    </div>
  )
}

function AdjustSheet({ meal, onClose, onConfirm, busy }: { meal: Meal; onClose: () => void; onConfirm: (items: { food_id: string; grams: number }[]) => void; busy: boolean }) {
  const initial: EditItem[] = meal.items.map((i) => ({
    food_id: i.food_id,
    name: i.name,
    grams: i.grams,
    per100: i.per100,
    unit_g: i.unit_g,
    unit_name: i.unit_name,
    step: i.step,
    planned: i.grams,
  }))
  const [items, setItems] = useState<EditItem[]>(initial)
  const [preset, setPreset] = useState("plan")
  const [adding, setAdding] = useState(false)
  const tot = useMemo(() => sum(items.map((i) => macrosFor(i.per100, i.grams))), [items])
  const plannedTot = useMemo(() => sum(initial.map((i) => macrosFor(i.per100, i.grams))), [meal])
  const delta = Math.round(tot.kcal - plannedTot.kcal)
  const scale = (k: number, name: string) => {
    setPreset(name)
    setItems(initial.map((i) => ({ ...i, grams: Math.max(i.step, Math.round((i.grams * k) / i.step) * i.step) })))
  }
  const add = (f: PickedFood) => {
    const step = stepFor(f.per100, f.unit_g)
    setItems([...items, { food_id: f.id, name: f.name, grams: f.unit_g ?? 100, per100: f.per100, unit_g: f.unit_g, unit_name: f.unit_name, step, planned: null }])
    setAdding(false)
  }
  return (
    <Sheet
      open
      onClose={onClose}
      title={meal.label}
      footer={
        <div className="pb-1">
          <div className="mb-3 flex items-center justify-between rounded-2xl bg-s2 px-3 py-2.5 text-[12px]">
            <span>
              <b>{n0(tot.kcal)} kcal</b>
              <span className="text-mu"> · P {n0(tot.protein)} · C {n0(tot.carbs)} · G {n0(tot.fat)}</span>
            </span>
            <span className={clsx(Math.abs(delta) < 5 ? "text-mu" : "text-c")}>{Math.abs(delta) < 5 ? "come da piano" : `${delta > 0 ? "+" : "−"}${Math.abs(delta)} sul piano`}</span>
          </div>
          <Button kind="primary" className="w-full" busy={busy} onClick={() => onConfirm(items.filter((i) => i.grams > 0).map((i) => ({ food_id: i.food_id, grams: i.grams })))}>
            Salva su Cronometer
          </Button>
        </div>
      }
    >
      {adding ? (
        <div>
          <FoodPicker onPick={add} />
          <Button kind="ghost" small className="mt-2" onClick={() => setAdding(false)}>
            Annulla
          </Button>
        </div>
      ) : (
        <>
          <div className="mb-2 flex flex-wrap gap-1.5">
            {[
              ["plan", "Come da piano", 1],
              ["half", "Metà", 0.5],
              ["more", "Un po' di più", 1.25],
              ["double", "Doppio", 2],
            ].map(([key, label, k]) => (
              <button
                key={key as string}
                onClick={() => scale(k as number, key as string)}
                className={clsx("rounded-full border px-3 py-1.5 text-[11.5px]", preset === key ? "border-ac/50 text-ac" : "border-ln bg-s2 text-tx2")}
              >
                {label}
              </button>
            ))}
          </div>
          {items.map((it, k) => (
            <div key={k} className="flex items-center gap-2 border-t border-ln py-2.5 first:border-t-0">
              <div className="min-w-0 flex-1">
                <b className="block truncate text-[13px] font-semibold">{it.name}</b>
                <span className="text-[10.5px] text-mu">
                  {n0(macrosFor(it.per100, it.grams).kcal)} kcal{it.unit_g && it.unit_name ? ` · 1 ${it.unit_name} = ${n0(it.unit_g)} g` : ""}
                </span>
              </div>
              <Stepper
                value={it.grams}
                step={it.step}
                label={it.unit_name === "porzione" ? `${n1(it.grams / 100)} p.` : undefined}
                onChange={(g) => {
                  setPreset("")
                  setItems(items.map((x, j) => (j === k ? { ...x, grams: g } : x)))
                }}
              />
              <button onClick={() => setItems(items.filter((_, j) => j !== k))} className="grid size-8 place-items-center rounded-lg text-mu active:text-er" aria-label="Rimuovi">
                <Trash2 className="size-4" />
              </button>
            </div>
          ))}
          <button onClick={() => setAdding(true)} className="mt-1 flex items-center gap-1.5 py-2 text-[12.5px] font-semibold text-ac">
            <Plus className="size-4" /> Aggiungi alimento
          </button>
        </>
      )}
    </Sheet>
  )
}

function ExtraSheet({ open, day, onClose }: { open: boolean; day: string; onClose: () => void }) {
  const qc = useQueryClient()
  const { toast } = useApp()
  const [food, setFood] = useState<PickedFood | null>(null)
  const [g, setG] = useState(100)
  const [slot, setSlot] = useState(() => {
    const h = new Date().getHours()
    return h < 11 ? "colazione" : h < 15 ? "pranzo" : h < 19 ? "spuntino" : "cena"
  })
  const save = useMutation({
    mutationFn: () => post<TodayT>(`/api/plan/${day}/extra`, { slot, food_id: food!.id, grams: g }),
    onSuccess: (data) => {
      qc.setQueryData(["today"], data)
      toast("Aggiunto su Cronometer")
      setFood(null)
      onClose()
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  const close = () => {
    setFood(null)
    onClose()
  }
  return (
    <Sheet
      open={open}
      onClose={close}
      title="Ho mangiato altro"
      footer={
        food && (
          <Button kind="primary" className="mb-1 w-full" busy={save.isPending} onClick={() => save.mutate()}>
            Aggiungi a {SLOT_LABEL[slot]}
          </Button>
        )
      }
    >
      {!food ? (
        <FoodPicker
          onPick={(f) => {
            setFood(f)
            setG(f.unit_g ?? 100)
          }}
        />
      ) : (
        <div>
          <div className="mb-3 flex items-center justify-between">
            <div>
              <b className="text-[14px]">{food.name}</b>
              <div className="text-[11px] text-mu">{n0(food.per100.kcal)} kcal per 100 g</div>
            </div>
            <button onClick={() => setFood(null)} className="flex items-center gap-1 text-[12px] text-mu">
              <RefreshCcw className="size-3.5" /> Cambia
            </button>
          </div>
          <div className="mb-3 flex items-center justify-between">
            <Stepper value={g} step={stepFor(food.per100, food.unit_g)} onChange={setG} />
            <span className="text-[12px] text-tx2">
              {n0(macrosFor(food.per100, g).kcal)} kcal · P {n0(macrosFor(food.per100, g).protein)}
            </span>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(SLOT_LABEL).map(([k, v]) => (
              <button key={k} onClick={() => setSlot(k)} className={clsx("rounded-full border px-3 py-1.5 text-[12px]", slot === k ? "border-ac/50 text-ac" : "border-ln bg-s2 text-tx2")}>
                {v}
              </button>
            ))}
          </div>
        </div>
      )}
    </Sheet>
  )
}

function SuggestionRow({ s, day }: { s: TodayT["suggestions"][number]; day: string }) {
  const qc = useQueryClient()
  const { toast } = useApp()
  const slot = (() => {
    const h = new Date().getHours()
    return h < 11 ? "colazione" : h < 15 ? "pranzo" : h < 19 ? "spuntino" : "cena"
  })()
  const add = useMutation({
    mutationFn: async () => {
      let last: TodayT | null = null
      for (const it of s.items) last = await post<TodayT>(`/api/plan/${day}/extra`, { slot, food_id: it.food_id, grams: it.grams })
      return last!
    },
    onSuccess: (data) => {
      qc.setQueryData(["today"], data)
      toast("Aggiunto su Cronometer")
    },
  })
  return (
    <div className="flex items-center gap-2.5 border-t border-ln py-2.5 first:border-t-0">
      <div className="min-w-0 flex-1">
        <b className="block truncate text-[13px] font-semibold">{s.title}</b>
        <span className="text-[11px] text-mu">
          {n0(s.macros.protein)} g P · {n0(s.macros.kcal)} kcal · {s.tag}
        </span>
      </div>
      <Button small kind="secondary" className="!text-ac" busy={add.isPending} onClick={() => add.mutate()}>
        Aggiungi
      </Button>
    </div>
  )
}
