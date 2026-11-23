import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { Check, ChevronLeft, ChevronRight, Plus, RefreshCcw, Trash2, Undo2 } from "lucide-react"
import { useEffect, useState } from "react"
import { useApp } from "../App"
import { api, del, patch, post, type DayItem, type DayMeal, type History, type Macros, type Today } from "../lib/api"
import { addDays, monday, n0, n1, range, signed, SLOT_LABEL, weekday, weekdayLong } from "../lib/format"
import FoodPicker, { macrosFor, stepFor, type PickedFood } from "./FoodPicker"
import { Bar, Button, Card, Chip, Dot, MACRO_COLORS, Ring, Segmented, Sheet, Spinner, Stepper } from "./ui"

const MACROS = [
  ["protein", "P", "Proteine"],
  ["carbs", "C", "Carboidrati"],
  ["fat", "G", "Grassi"],
] as const

const sum = (ms: Macros[]) =>
  ms.reduce((a, m) => ({ kcal: a.kcal + m.kcal, protein: a.protein + m.protein, carbs: a.carbs + m.carbs, fat: a.fat + m.fat }), { kcal: 0, protein: 0, carbs: 0, fat: 0 })

export function MacroPills({ m, small }: { m: Macros; small?: boolean }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {MACROS.map(([k, letter]) => (
        <span
          key={k}
          className={clsx("inline-flex items-baseline gap-[3px] rounded-full font-semibold", small ? "px-1.5 py-px text-[10.5px]" : "px-2 py-[3px] text-[11.5px]")}
          style={{ background: MACRO_COLORS[k] + "1f", color: MACRO_COLORS[k] }}
        >
          {letter} {n0(m[k])}
          <span className="font-medium text-mu">g</span>
        </span>
      ))}
    </span>
  )
}

/** The three macros as shares of the calories they bring. */
export function SplitBar({ m, className }: { m: Macros; className?: string }) {
  const k = { protein: m.protein * 4, carbs: m.carbs * 4, fat: m.fat * 9 }
  const tot = k.protein + k.carbs + k.fat
  return (
    <div className={clsx("flex h-1 gap-px overflow-hidden rounded-full bg-s2", className)}>
      {tot > 0 && MACROS.map(([key]) => <i key={key} className="block h-full" style={{ width: `${(k[key] / tot) * 100}%`, background: MACRO_COLORS[key] }} />)}
    </div>
  )
}

export function MacroBars({ consumed, planned, target }: { consumed: Macros; planned?: Macros; target: Macros }) {
  return (
    <div className="grid gap-[11px]">
      {MACROS.map(([k, , name]) => {
        const over = consumed[k] - target[k]
        return (
          <div key={k}>
            <div className="mb-1.5 flex justify-between text-[12px]">
              <span>
                <Dot color={MACRO_COLORS[k]} />
                {name}
              </span>
              <span>
                <b>{n0(consumed[k])}</b>
                <span className="text-mu"> / {n0(target[k])} g</span>
                {over >= 1 && <b className="ml-1.5" style={{ color: MACRO_COLORS[k] }}>+{n0(over)}</b>}
              </span>
            </div>
            <Bar
              parts={[
                { value: (consumed[k] / (target[k] || 1)) * 100, color: MACRO_COLORS[k] },
                ...(planned ? [{ value: (planned[k] / (target[k] || 1)) * 100, color: MACRO_COLORS[k] + "3a" }] : []),
              ]}
            />
          </div>
        )
      })}
    </div>
  )
}

/** Eaten against target for any day: the ring and the three macro bars. */
export function DaySummary({ view }: { view: Today }) {
  const t = view.target_loggable
  const c = view.consumed
  if (!t) return <b className="text-[18px]">{n0(c.kcal)} kcal</b>
  const left = t.kcal - c.kcal
  return (
    <div className="flex items-center gap-4">
      <Ring value={c.kcal} max={t.kcal} size={116} stroke={11}>
        <b className="text-[24px] font-bold leading-none tracking-[-0.03em]">{n0(c.kcal)}</b>
        <span className="mt-1 text-[10.5px] text-mu">di {n0(t.kcal)} kcal</span>
        <span className={clsx("mt-0.5 text-[10.5px] font-semibold", left < 0 ? "text-wa" : "text-mi")}>{left < 0 ? `+${n0(-left)} sopra` : `${n0(left)} rimaste`}</span>
      </Ring>
      <div className="min-w-0 flex-1">
        <MacroBars consumed={c} planned={view.planned_remaining} target={t} />
      </div>
    </div>
  )
}

export type DayAction =
  | { kind: "confirm" | "skip" | "undo"; slot: string }
  | { kind: "add"; slot: string; food_id: string; grams: number; eaten: boolean }
  | { kind: "update"; ref: string; grams: number; eaten: boolean }
  | { kind: "delete"; ref: string; eaten: boolean }
  | { kind: "copy"; source: string; slots: string[] }

function send(day: string, a: DayAction): Promise<Today> {
  switch (a.kind) {
    case "confirm":
    case "skip":
    case "undo":
      return post<Today>(`/api/plan/${day}/meals/${a.slot}/${a.kind}`, {})
    case "add":
      return post<Today>(`/api/day/${day}/meals/${a.slot}/items`, { food_id: a.food_id, grams: a.grams, eaten: a.eaten })
    case "update":
      return patch<Today>(`/api/day/${day}/items/${encodeURIComponent(a.ref)}`, { grams: a.grams })
    case "delete":
      return del<Today>(`/api/day/${day}/items/${encodeURIComponent(a.ref)}`)
    case "copy":
      return post<Today>(`/api/day/${day}/copy`, { source: a.source, slots: a.slots })
  }
}

function done(a: DayAction): string {
  switch (a.kind) {
    case "confirm":
      return "Registrato su Cronometer"
    case "skip":
      return "Saltato: il resto della giornata si adegua"
    case "undo":
      return "Pasto ripristinato"
    case "add":
      return a.eaten ? `Aggiunto a ${SLOT_LABEL[a.slot].toLowerCase()} su Cronometer` : `Aggiunto al piano di ${SLOT_LABEL[a.slot].toLowerCase()}`
    case "update":
      return a.eaten ? "Grammi aggiornati anche su Cronometer" : "Grammi aggiornati"
    case "delete":
      return a.eaten ? "Eliminato anche da Cronometer" : "Tolto dal piano"
    case "copy":
      return a.slots.length === 1 ? "Pasto copiato, stesse quantità" : `${a.slots.length} pasti copiati, stesse quantità`
  }
}

/** Every change to a day answers with the whole day: it lands in both the Oggi and the week caches. */
export function useDayAction(day: string) {
  const qc = useQueryClient()
  const { boot, toast } = useApp()
  return useMutation({
    mutationFn: (a: DayAction) => send(day, a),
    onSuccess: (data, a) => {
      qc.setQueryData(["day", day], data)
      if (day === boot.today) qc.setQueryData(["today"], data)
      qc.invalidateQueries({ queryKey: ["history"] })
      qc.invalidateQueries({ queryKey: ["sync"] })
      toast(done(a))
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
}

const gramsText = (i: { grams: number; unit_name: string | null }) => (i.unit_name === "porzione" ? `${n1(i.grams / 100)} porz.` : `${n0(i.grams)} g`)
const servingProps = (unitName: string | null) => (unitName === "porzione" ? { factor: 100, unit: "porz." } : {})

export function DayMeals({ view }: { view: Today }) {
  const act = useDayAction(view.day)
  const [edit, setEdit] = useState<DayItem | null>(null)
  const [adding, setAdding] = useState<string | null>(null)
  const v = act.variables
  const busy = (slot: string, kind: string) => act.isPending && !!v && "slot" in v && v.slot === slot && v.kind === kind
  return (
    <>
      <div className="flex flex-col gap-2.5">
        {view.meals.map((m) => (
          <MealCard
            key={m.slot}
            meal={m}
            busy={(kind) => busy(m.slot, kind)}
            onAct={(kind) => act.mutate({ kind, slot: m.slot })}
            onEdit={setEdit}
            onDelete={(i) => act.mutate({ kind: "delete", ref: i.ref, eaten: i.state === "eaten" })}
            onAdd={() => setAdding(m.slot)}
          />
        ))}
      </div>
      {edit && (
        <ItemSheet
          item={edit}
          busy={act.isPending}
          onClose={() => setEdit(null)}
          onSave={(grams) => act.mutate({ kind: "update", ref: edit.ref, grams, eaten: edit.state === "eaten" }, { onSuccess: () => setEdit(null) })}
          onDelete={() => act.mutate({ kind: "delete", ref: edit.ref, eaten: edit.state === "eaten" }, { onSuccess: () => setEdit(null) })}
        />
      )}
      {adding && (
        <AddSheet
          day={view.day}
          slot={adding}
          busy={act.isPending}
          onClose={() => setAdding(null)}
          onAdd={(food_id, grams, eaten) => act.mutate({ kind: "add", slot: adding, food_id, grams, eaten }, { onSuccess: () => setAdding(null) })}
        />
      )}
    </>
  )
}

function MealChip({ meal }: { meal: DayMeal }) {
  switch (meal.status) {
    case "eaten":
      return <Chip tone="mi">{meal.items.some((i) => i.pending) ? "in invio" : "su Cronometer"}</Chip>
    case "planned":
      return meal.locked ? <Chip tone="ok">Fisso</Chip> : <Chip>da confermare</Chip>
    case "partial":
      return (
        <Chip tone="ac">
          {meal.count_eaten} di {meal.count} mangiato
        </Chip>
      )
    case "skipped":
      return <Chip>saltato</Chip>
    default:
      return null
  }
}

function MealCard({
  meal,
  busy,
  onAct,
  onEdit,
  onDelete,
  onAdd,
}: {
  meal: DayMeal
  busy: (kind: string) => boolean
  onAct: (kind: "confirm" | "skip" | "undo") => void
  onEdit: (i: DayItem) => void
  onDelete: (i: DayItem) => void
  onAdd: () => void
}) {
  const left = meal.items.filter((i) => i.state === "planned").length
  const some = meal.count_eaten > 0
  return (
    <Card className={clsx(left > 0 && "border-ac/25")}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <b className="text-[15px]">{meal.label}</b>
          <MealChip meal={meal} />
        </div>
        {meal.count > 0 && (
          <b className="shrink-0 text-[16px] tracking-[-0.01em]">
            {n0(meal.macros.kcal)}
            <span className="ml-1 text-[11px] font-medium text-mu">kcal</span>
          </b>
        )}
      </div>
      {meal.count > 0 && (
        <div className="mt-2">
          <MacroPills m={meal.macros} />
          <SplitBar m={meal.macros} className="mt-2" />
        </div>
      )}
      <div className="mt-1.5">
        {meal.items.length === 0 && <div className="py-1.5 text-[12.5px] text-mu">Ancora niente</div>}
        {meal.items.map((i) => (
          <FoodRow key={i.ref} item={i} onEdit={() => onEdit(i)} onDelete={() => onDelete(i)} />
        ))}
      </div>
      {left > 0 && (
        <div className="mt-2 flex gap-1.5">
          <Button kind="primary" small className="flex-1" busy={busy("confirm")} onClick={() => onAct("confirm")}>
            <Check className="size-4" /> {some ? "Mangiato il resto" : "Mangiato"}
          </Button>
          <Button small busy={busy("skip")} onClick={() => onAct("skip")}>
            {some ? "Salta il resto" : "Saltato"}
          </Button>
        </div>
      )}
      <div className="mt-1 flex items-center justify-between">
        <button onClick={onAdd} className="flex items-center gap-1.5 py-1.5 text-[12.5px] font-semibold text-ac">
          <Plus className="size-4" /> Aggiungi a {meal.label.toLowerCase()}
        </button>
        {meal.skipped && meal.items.some((i) => i.state === "skipped") && (
          <button onClick={() => onAct("undo")} className="flex items-center gap-1 py-1.5 text-[11.5px] text-mu active:text-tx">
            <Undo2 className="size-3.5" /> Annulla salto
          </button>
        )}
      </div>
    </Card>
  )
}

function FoodRow({ item, onEdit, onDelete }: { item: DayItem; onEdit: () => void; onDelete: () => void }) {
  const [armed, setArmed] = useState(false)
  useEffect(() => {
    if (!armed) return
    const t = setTimeout(() => setArmed(false), 3000)
    return () => clearTimeout(t)
  }, [armed])
  const eaten = item.state === "eaten"
  return (
    <div className="flex items-center gap-2 border-t border-ln py-2 first:border-t-0">
      <div className={clsx("min-w-0 flex-1", !eaten && "opacity-55")}>
        <div className="flex items-center gap-1.5">
          <span className={clsx("truncate text-[13px] font-semibold", item.state === "skipped" && "line-through")}>{item.name}</span>
          {item.state === "planned" && <span className="shrink-0 rounded-full border border-dashed border-mu/60 px-1.5 text-[9.5px] font-semibold text-mu">da piano</span>}
          {item.pending && <span className="shrink-0 text-[10px] font-semibold text-mi">in invio</span>}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-mu">{n0(item.macros.kcal)} kcal</span>
          <MacroPills m={item.macros} small />
        </div>
      </div>
      <button
        onClick={onEdit}
        className={clsx("shrink-0 rounded-full border px-2.5 py-1 text-[12px] font-bold active:scale-95", eaten ? "border-ln bg-s2 text-tx" : "border-dashed border-[#3a434e] text-tx2")}
        aria-label={`Modifica ${item.name}`}
      >
        {gramsText(item)}
      </button>
      <button
        onClick={() => (eaten && !armed ? setArmed(true) : onDelete())}
        className={clsx("grid h-8 shrink-0 place-items-center rounded-lg", armed ? "bg-er/12 px-2 text-[11px] font-bold text-er" : "w-8 text-mu active:text-er")}
        aria-label={`Elimina ${item.name}`}
      >
        {armed ? "Elimina?" : <Trash2 className="size-4" />}
      </button>
    </div>
  )
}

function MacroBox({ m, delta }: { m: Macros; delta?: number }) {
  return (
    <div className="rounded-2xl bg-s2 px-3.5 py-3">
      <div className="flex items-baseline justify-between">
        <b className="text-[22px] tracking-[-0.02em]">
          {n0(m.kcal)} <span className="text-[12px] font-medium text-mu">kcal</span>
        </b>
        {delta != null && Math.abs(delta) >= 1 && <span className="text-[12px] font-semibold text-c">{signed(delta)} kcal</span>}
      </div>
      <div className="mt-2">
        <MacroPills m={m} />
      </div>
      <SplitBar m={m} className="mt-2.5" />
    </div>
  )
}

function ItemSheet({ item, busy, onClose, onSave, onDelete }: { item: DayItem; busy: boolean; onClose: () => void; onSave: (g: number) => void; onDelete: () => void }) {
  const [g, setG] = useState(item.grams)
  const m = macrosFor(item.per100, g)
  const changed = Math.round(g * 10) !== Math.round(item.grams * 10)
  const where =
    item.state === "eaten" ? (item.pending ? "Mangiato · in invio a Cronometer" : "Mangiato · su Cronometer") : item.state === "skipped" ? "Da piano · saltato" : "Da piano, non ancora mangiato"
  return (
    <Sheet
      open
      onClose={onClose}
      title={item.name}
      footer={
        <div className="mb-1 flex gap-2">
          <Button kind="danger" className="flex-1" disabled={busy} onClick={onDelete}>
            <Trash2 className="size-4" /> Elimina
          </Button>
          <Button kind="primary" className="flex-[2]" busy={busy} disabled={!changed || g <= 0} onClick={() => onSave(g)}>
            Salva
          </Button>
        </div>
      }
    >
      <div className="mb-4 text-[12px] text-mu">{where}</div>
      <div className="flex flex-col items-center gap-2">
        <Stepper large live value={g} step={item.step} onChange={setG} {...servingProps(item.unit_name)} />
        {item.unit_g && item.unit_name && item.unit_name !== "porzione" && (
          <div className="text-[11px] text-mu">
            1 {item.unit_name} = {n0(item.unit_g)} g
          </div>
        )}
      </div>
      <div className="mt-4">
        <MacroBox m={m} delta={changed ? m.kcal - item.macros.kcal : undefined} />
      </div>
      {item.state === "eaten" && changed && <p className="mt-3 text-[11.5px] text-mu">Su Cronometer la voce viene sostituita con i nuovi grammi.</p>}
    </Sheet>
  )
}

function AddSheet({ day, slot, busy, onClose, onAdd }: { day: string; slot: string; busy: boolean; onClose: () => void; onAdd: (food_id: string, grams: number, eaten: boolean) => void }) {
  const { boot } = useApp()
  const future = day > boot.today
  const [food, setFood] = useState<PickedFood | null>(null)
  const [g, setG] = useState(100)
  const [eaten, setEaten] = useState(!future)
  const label = SLOT_LABEL[slot]
  return (
    <Sheet
      open
      onClose={onClose}
      title={`Aggiungi a ${label.toLowerCase()}`}
      footer={
        food && (
          <Button kind="primary" className="mb-1 w-full" busy={busy} disabled={g <= 0} onClick={() => onAdd(food.id, g, eaten)}>
            {eaten ? `Aggiungi a ${label.toLowerCase()} come mangiato` : `Aggiungi al piano di ${label.toLowerCase()}`}
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
          <div className="mb-4 flex items-center justify-between">
            <div className="min-w-0">
              <b className="block truncate text-[14px]">{food.name}</b>
              <div className="text-[11px] text-mu">{n0(food.per100.kcal)} kcal per 100 g</div>
            </div>
            <button onClick={() => setFood(null)} className="flex shrink-0 items-center gap-1 text-[12px] text-mu">
              <RefreshCcw className="size-3.5" /> Cambia
            </button>
          </div>
          <div className="flex justify-center">
            <Stepper large live value={g} step={stepFor(food.per100, food.unit_g)} onChange={setG} {...servingProps(food.unit_name)} />
          </div>
          <div className="mt-4">
            <MacroBox m={macrosFor(food.per100, g)} />
          </div>
          {!future && (
            <Segmented
              className="mt-3"
              value={eaten ? "y" : "n"}
              onChange={(v) => setEaten(v === "y")}
              options={[
                { value: "y", label: "Già mangiato" },
                { value: "n", label: "Da mangiare" },
              ]}
            />
          )}
        </div>
      )}
    </Sheet>
  )
}

/** Copy meals of another day into `target`, with the same grams; they land as planned, to confirm. */
export function CopySheet({ target, onClose }: { target: string; onClose: () => void }) {
  const { boot } = useApp()
  const [week, setWeek] = useState(() => monday(target))
  const [source, setSource] = useState<string | null>(null)
  const [slots, setSlots] = useState<string[]>([])
  const hist = useQuery({ queryKey: ["history", week], queryFn: () => api<History>(`/api/history?week_start=${week}`) })
  const view = useQuery({ queryKey: ["day", target], queryFn: () => api<Today>(`/api/today?day=${target}`) })
  const act = useDayAction(target)
  const src = hist.data?.days.find((d) => d.day === source)
  const who = target === boot.today ? "di oggi" : `di ${weekdayLong(target)}`
  const pick = (day: string) => {
    setSource(day)
    // a meal already eaten on the target would get a second one on top: it stays unticked until asked
    const eatenHere = new Set(view.data?.meals.filter((m) => m.count_eaten > 0).map((m) => m.slot))
    setSlots(hist.data?.days.find((d) => d.day === day)?.meals.map((m) => m.slot).filter((s) => !eatenHere.has(s)) ?? [])
  }
  const chosen = src ? src.meals.filter((m) => slots.includes(m.slot)) : []
  const copied = sum(chosen.flatMap((m) => m.items.map((i) => i.macros)))
  const v = view.data
  const projected = v ? v.consumed.kcal + v.meals.reduce((a, m) => a + (chosen.some((c) => c.slot === m.slot) ? 0 : m.planned.kcal), 0) + copied.kcal : 0
  const delta = v?.target_loggable ? projected - v.target_loggable.kcal : null
  const n = chosen.length
  return (
    <Sheet
      open
      onClose={onClose}
      title={<span className="first-letter:uppercase">Copia in {target === boot.today ? "oggi" : weekdayLong(target)}</span>}
      footer={
        <div className="mb-1">
          {n > 0 && (
            <div className="mb-3 flex items-center justify-between rounded-2xl bg-s2 px-3 py-2.5 text-[12px]">
              <span>
                Copi <b>{n0(copied.kcal)} kcal</b>
              </span>
              {delta != null && (
                <span className={clsx("font-semibold", Math.abs(delta) <= 50 ? "text-ok" : delta > 0 ? "text-c" : "text-tx2")}>
                  {Math.abs(delta) <= 50 ? `in linea col target ${who}` : `${signed(delta)} sul target ${who}`}
                </span>
              )}
            </div>
          )}
          <Button
            kind="primary"
            className="w-full"
            disabled={n === 0}
            busy={act.isPending}
            onClick={() => act.mutate({ kind: "copy", source: source!, slots: chosen.map((m) => m.slot) }, { onSuccess: onClose })}
          >
            {n === 0 ? "Scegli i pasti da copiare" : `Copia ${n} ${n === 1 ? "pasto" : "pasti"}, stesse quantità`}
          </Button>
        </div>
      }
    >
      <div className="mb-2 flex items-center justify-between text-[11px] text-mu">
        <button onClick={() => setWeek(addDays(week, -7))} className="grid size-7 place-items-center rounded-lg active:bg-s2" aria-label="Settimana precedente">
          <ChevronLeft className="size-4" />
        </button>
        <span>Da quale giorno · {range(week, addDays(week, 6))}</span>
        <button
          onClick={() => setWeek(addDays(week, 7))}
          disabled={week >= monday(target)}
          className="grid size-7 place-items-center rounded-lg active:bg-s2 disabled:opacity-30"
          aria-label="Settimana successiva"
        >
          <ChevronRight className="size-4" />
        </button>
      </div>
      {hist.isLoading && <Spinner />}
      <div className="grid grid-cols-7 gap-1">
        {hist.data?.days.map((d) => {
          const off = d.day === target || d.meals.length === 0
          return (
            <button
              key={d.day}
              disabled={off}
              onClick={() => pick(d.day)}
              className={clsx(
                "flex flex-col items-center rounded-xl border py-1.5 text-[10.5px] disabled:opacity-30",
                source === d.day ? "border-ac/60 bg-ac/12 text-ac" : "border-ln bg-s2 text-tx2",
              )}
            >
              {weekday(d.day)}
              <b className="text-[15px]">{new Date(d.day + "T12:00").getDate()}</b>
              <span className="text-[9.5px] text-mu">{d.day === target ? "qui" : d.meals.length ? n0(d.kcal) : "–"}</span>
            </button>
          )
        })}
      </div>
      {!src && hist.data && <div className="py-6 text-center text-[12.5px] text-mu">Scegli un giorno: quelli senza niente registrato non si possono copiare.</div>}
      {src && (
        <div className="mt-3">
          {src.meals.map((m) => {
            const on = slots.includes(m.slot)
            const here = v?.meals.find((x) => x.slot === m.slot)
            const tot = sum(m.items.map((i) => i.macros))
            return (
              <button
                key={m.slot}
                onClick={() => setSlots(on ? slots.filter((s) => s !== m.slot) : [...slots, m.slot])}
                className={clsx("mb-2 flex w-full gap-3 rounded-2xl border p-3 text-left", on ? "border-ac/40 bg-ac/[0.06]" : "border-ln bg-s1")}
              >
                <span className={clsx("mt-0.5 grid size-5 shrink-0 place-items-center rounded-md border", on ? "border-ac bg-ac text-bg" : "border-[#3a434e]")}>
                  {on && <Check className="size-3.5" strokeWidth={3} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex items-center justify-between gap-2">
                    <b className="text-[13.5px]">{m.label}</b>
                    <b className="text-[13px]">
                      {n0(tot.kcal)} <span className="text-[10.5px] font-medium text-mu">kcal</span>
                    </b>
                  </span>
                  <span className="mt-1.5 block">
                    <MacroPills m={tot} small />
                  </span>
                  <span className="mt-1.5 block text-[11.5px] leading-[1.6] text-tx2">
                    {m.items.map((i, k) => (
                      <span key={k}>
                        {k > 0 && <span className="text-mu"> · </span>}
                        {i.name} <b className="font-semibold text-tx">{n0(i.grams)} g</b>
                      </span>
                    ))}
                  </span>
                  {here && here.count_eaten > 0 && (
                    <span className={clsx("mt-1 block text-[10.5px]", on ? "text-c" : "text-mu")}>
                      {SLOT_LABEL[m.slot]} ha già {here.count_eaten} {here.count_eaten === 1 ? "alimento mangiato, che resta" : "alimenti mangiati, che restano"}
                      {here.count > here.count_eaten ? ": il resto del piano si sostituisce" : ": questi si aggiungono"}
                    </span>
                  )}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </Sheet>
  )
}
