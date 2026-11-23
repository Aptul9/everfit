import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { AlertTriangle, Check, ChevronRight, CloudOff, Copy, Settings2 } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router"
import { useApp } from "../App"
import { Spark } from "../components/charts"
import { CopySheet, DayMeals, MacroBars } from "../components/meals"
import { Button, Card, Chip, ErrorBox, Ring, Spinner } from "../components/ui"
import { api, post, type Today as TodayT } from "../lib/api"
import { longDay, n0, n1, rate, SLOT_LABEL, slotNow } from "../lib/format"

export default function Today() {
  const { boot } = useApp()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ["today"], queryFn: () => api<TodayT>("/api/today") })
  const sync = useQuery({ queryKey: ["sync"], queryFn: () => api<{ pending: number; failed: number; last_error?: string | null }>("/api/sync"), refetchInterval: 20_000 })
  const [copying, setCopying] = useState(false)

  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBox error={q.error} retry={() => q.refetch()} />
  const t = q.data!
  const target = t.target_loggable
  const consumed = t.consumed
  const planned = t.planned_remaining
  const flags = t.targets?.flags ?? []
  const report = t.plan.report
  const note = report && !report.within_tolerance ? report.notes[report.notes.length - 1] : null

  return (
    <div className="animate-rise">
      <div className="mb-3.5 flex items-end justify-between gap-2 px-0.5 pt-1.5">
        <div>
          <div className="mb-0.5 text-[11px] font-medium uppercase tracking-[0.08em] text-mu">{longDay(t.day)}</div>
          <h1 className="text-[26px] font-bold tracking-[-0.02em]">Oggi</h1>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <button onClick={() => setCopying(true)} className="flex items-center gap-1.5 rounded-full border border-ln bg-s1 px-3 py-1.5 text-[11.5px] font-semibold text-tx2 active:bg-s2">
            <Copy className="size-3.5" /> Copia da un giorno
          </button>
          {t.phase && <Chip tone="ac">{t.phase.name}{t.targets?.kind === "refeed" ? " · ricarica" : ""}</Chip>}
          <button onClick={() => nav("/impostazioni")} className="grid size-9 place-items-center rounded-xl text-mu active:bg-s2 lg:hidden" aria-label="Impostazioni">
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

      <div className="flex flex-col gap-2.5 lg:grid lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:items-start lg:gap-5">
        <div className="contents lg:sticky lg:top-8 lg:flex lg:flex-col lg:gap-3">
          <div className="order-1 empty:hidden lg:order-none">
          {target && (
            <Card>
              <div className="flex items-center gap-4">
                <Ring value={consumed.kcal} max={target.kcal}>
                  <b className="text-[30px] font-bold tracking-[-0.03em]">{n0(Math.abs(target.kcal - consumed.kcal))}</b>
                  <span className="text-[11px] text-mu">{consumed.kcal > target.kcal ? "kcal sopra" : "kcal rimaste"}</span>
                </Ring>
                <div className="flex flex-1 flex-col gap-2 text-[12px]">
                  <Row label="Mangiato" value={n0(consumed.kcal)} />
                  <Row label="Target" value={n0(target.kcal)} />
                  <Row label="Metabolismo" value={`~${n0(t.expenditure.kcal)}`} />
                </div>
              </div>
              <div className="mt-4">
                <MacroBars consumed={consumed} planned={planned} target={target} />
              </div>
            </Card>
          )}
          {note && <div className="px-1 pt-2 text-[11.5px] text-mu lg:pt-0">{note}</div>}
          </div>
          <div className="order-4 empty:hidden lg:order-none">
          {t.suggestions.length > 0 && t.remaining && (
            <Card>
              <div className="flex items-center justify-between">
                <b className="text-[14px]">Ti mancano {n0(t.remaining.protein)} g di proteine</b>
              </div>
              <div className="mb-1 mt-0.5 text-[11px] text-mu">Dai tuoi alimenti, dentro le {n0(t.remaining.kcal)} kcal rimaste</div>
              {t.suggestions.map((s, i) => (
                <SuggestionRow key={i} s={s} day={t.day} />
              ))}
            </Card>
          )}
          </div>
          <div className="order-6 empty:hidden lg:order-none">
          <Card onClick={() => nav("/progressi")}>
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
          </div>
        </div>
        <div className="order-2 lg:order-none">
          <DayMeals view={t} />
        </div>
      </div>

      {copying && <CopySheet target={t.day} onClose={() => setCopying(false)} />}
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-mu">{label}</span>
      <b className="font-semibold">{value}</b>
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

function SuggestionRow({ s, day }: { s: TodayT["suggestions"][number]; day: string }) {
  const qc = useQueryClient()
  const { toast } = useApp()
  const [picking, setPicking] = useState(false)
  const [slot, setSlot] = useState(slotNow)
  const add = useMutation({
    mutationFn: async () => {
      let last: TodayT | null = null
      for (const it of s.items) last = await post<TodayT>(`/api/day/${day}/meals/${slot}/items`, { food_id: it.food_id, grams: it.grams, eaten: true })
      return last!
    },
    onSuccess: (data) => {
      qc.setQueryData(["today"], data)
      qc.setQueryData(["day", day], data)
      qc.invalidateQueries({ queryKey: ["history"] })
      toast(`Aggiunto a ${SLOT_LABEL[slot].toLowerCase()} su Cronometer`)
      setPicking(false)
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  return (
    <div className="border-t border-ln py-2.5 first:border-t-0">
      <div className="flex items-center gap-2.5">
        <div className="min-w-0 flex-1">
          <b className="block truncate text-[13px] font-semibold">{s.title}</b>
          <span className="text-[11px] text-mu">
            {n0(s.macros.protein)} g P · {n0(s.macros.kcal)} kcal · {s.tag}
          </span>
        </div>
        {!picking && (
          <Button small kind="secondary" className="!text-ac" onClick={() => setPicking(true)}>
            Aggiungi
          </Button>
        )}
      </div>
      {picking && (
        <div className="mt-2">
          <div className="mb-2 text-[11px] text-mu">In quale pasto?</div>
          <div className="flex flex-wrap gap-1.5">
            {Object.entries(SLOT_LABEL).map(([k, v]) => (
              <button key={k} onClick={() => setSlot(k)} className={clsx("rounded-full border px-3 py-1.5 text-[12px]", slot === k ? "border-ac/50 bg-ac/10 text-ac" : "border-ln bg-s2 text-tx2")}>
                {v}
              </button>
            ))}
          </div>
          <div className="mt-2 flex gap-1.5">
            <Button small kind="primary" className="flex-1" busy={add.isPending} onClick={() => add.mutate()}>
              Aggiungi a {SLOT_LABEL[slot].toLowerCase()}
            </Button>
            <Button small kind="ghost" onClick={() => setPicking(false)}>
              Annulla
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
