import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { ChevronRight, Pencil } from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router"
import { useApp } from "../App"
import { Button, Card, Chip, ErrorBox, Header, Segmented, Sheet, Spinner, Stepper } from "../components/ui"
import { api, patch, post, type Phase, type PhaseTemplate, type Today, type WeekPreview } from "../lib/api"
import { addDays, longDay, n0, n1, n2, shortDay, signed, SLOT_LABEL } from "../lib/format"

const WEEKDAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
const KIND_LABEL = { deficit: "perdita", maintenance: "mantenimento", surplus: "aumento", reverse: "risalita" }

export default function Plan() {
  const { boot } = useApp()
  const nav = useNavigate()
  const loc = useLocation()
  const weekRef = useRef<HTMLDivElement>(null)
  const q = useQuery({ queryKey: ["phase"], queryFn: () => api<{ phase: Phase; templates: PhaseTemplate[] }>("/api/phase") })
  const today = useQuery({ queryKey: ["today"], queryFn: () => api<Today>("/api/today") })
  useEffect(() => {
    if (loc.hash === "#settimana" && q.data) setTimeout(() => weekRef.current?.scrollIntoView({ behavior: "smooth" }), 50)
  }, [loc.hash, q.data])
  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBox error={q.error} retry={() => q.refetch()} />
  const { phase, templates } = q.data!
  return (
    <div className="animate-rise">
      <Header eyebrow="Fase attiva" title="Piano" />
      <PhaseCard phase={phase} templates={templates} weight={today.data?.weight.trend ?? null} expenditure={today.data?.expenditure.kcal ?? null} />
      <Card className="mb-3" onClick={() => nav(`/piano/modifica/${boot.today}`)}>
        <div className="flex items-center gap-3">
          <Pencil className="size-4 text-ac" />
          <div className="flex-1">
            <b className="text-[13.5px]">Modifica il piano di oggi</b>
            <div className="text-[11.5px] text-mu">grammi, sostituzioni, lucchetti, ribilancia</div>
          </div>
          <ChevronRight className="size-4 text-mu" />
        </div>
      </Card>
      <Card className="mb-3" onClick={() => nav(`/piano/modifica/${addDays(boot.today, 1)}`)}>
        <div className="flex items-center gap-3">
          <Pencil className="size-4 text-mu" />
          <div className="flex-1">
            <b className="text-[13.5px]">Piano di domani</b>
            <div className="text-[11.5px] text-mu first-letter:uppercase">{longDay(addDays(boot.today, 1))}</div>
          </div>
          <ChevronRight className="size-4 text-mu" />
        </div>
      </Card>
      <div ref={weekRef}>
        <WeekPlan />
      </div>
    </div>
  )
}

function PhaseCard({ phase, templates, weight, expenditure }: { phase: Phase; templates: PhaseTemplate[]; weight: number | null; expenditure: number | null }) {
  const qc = useQueryClient()
  const { toast } = useApp()
  const nav = useNavigate()
  const [rateV, setRateV] = useState(phase.rate_kg_week)
  const [picker, setPicker] = useState(false)
  useEffect(() => setRateV(phase.rate_kg_week), [phase.rate_kg_week])
  const tpl = templates.find((t) => t.id === phase.template_id)
  const save = useMutation({
    mutationFn: (changes: Partial<Phase>) => patch<Phase>("/api/phase", changes),
    onSuccess: () => {
      qc.invalidateQueries()
      toast("Fase aggiornata")
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  const sliderRange = phase.kind === "deficit" ? [-1.0, -0.1] : phase.kind === "surplus" ? [0.1, 0.6] : null
  const loss = phase.kind === "deficit"
  const week = Math.floor((new Date().getTime() - new Date(phase.start + "T00:00").getTime()) / (7 * 86400000)) + 1
  const pctW = weight ? (Math.abs(rateV) / weight) * 100 : null
  return (
    <Card className="mb-3">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div>
          <b className="text-[16px]">{phase.name}</b>
          <div className="text-[11.5px] text-mu">
            settimana {week}
            {phase.duration_weeks ? ` di ${phase.duration_weeks}` : ""} · dal {shortDay(phase.start)}
          </div>
        </div>
        <Chip tone={phase.modified ? "wa" : "neutral"}>{tpl?.builtin ? "modello del libro" : "modello tuo"}{phase.modified ? " · modificato" : ""}</Chip>
      </div>
      {tpl && <p className="mb-2 text-[11.5px] leading-relaxed text-mu">{tpl.description} <span className="text-tx2/60">· {tpl.source}</span></p>}

      {sliderRange && (
        <div className="mt-3">
          <div className="flex justify-between text-[12.5px]">
            <span className="text-mu">Ritmo di {loss ? "perdita" : "aumento"}</span>
            <b>
              {n2(Math.abs(rateV))} kg/sett{pctW ? <span className="font-normal text-mu"> · {n2(pctW)}%</span> : null}
            </b>
          </div>
          <input
            type="range"
            className="mt-3 w-full"
            min={Math.abs(loss ? sliderRange[1] : sliderRange[0])}
            max={Math.abs(loss ? sliderRange[0] : sliderRange[1])}
            step={0.05}
            value={Math.abs(rateV)}
            onChange={(e) => setRateV((loss ? -1 : 1) * Number(e.target.value))}
            onPointerUp={() => rateV !== phase.rate_kg_week && save.mutate({ rate_kg_week: rateV })}
            onKeyUp={() => rateV !== phase.rate_kg_week && save.mutate({ rate_kg_week: rateV })}
          />
          <div className="flex justify-between text-[10px] text-mu">
            <span>più lento</span>
            <span>il libro: 0,5–1% del peso [p. 325]</span>
            <span>più veloce</span>
          </div>
        </div>
      )}

      <div className="mt-3">
        <Param label="Calorie target (media)" value={`${n0(phase.kcal_target)} kcal`} hint={expenditure ? `metabolismo ~${n0(expenditure)} · si aggiorna col check-in` : undefined} />
        <Param label="Forbice del ritmo" value={`${signed(phase.band_kg_week[0], 2)} / ${signed(phase.band_kg_week[1], 2)}`} />
        <ParamStep label="Proteine" value={phase.protein_g_per_kg} step={0.1} unit="g/kg" onChange={(v) => save.mutate({ protein_g_per_kg: Math.round(v * 10) / 10 })} />
        <ParamStep label="Grassi" value={phase.fat_g_per_kg} step={0.05} unit="g/kg" min={0.3} onChange={(v) => save.mutate({ fat_g_per_kg: Math.round(v * 100) / 100 })} />
        <Param label="Carboidrati" value="il resto" />
        <div className="flex items-center justify-between border-t border-ln py-2.5 text-[12.5px]">
          <span className="text-mu">Correzioni su</span>
          <Segmented
            className="w-[190px]"
            value={phase.adjust_macro}
            onChange={(v) => save.mutate({ adjust_macro: v })}
            options={[
              { value: "carbs", label: "Carbo" },
              { value: "fat", label: "Grassi" },
              { value: "mixed", label: "Misto" },
            ]}
          />
        </div>
        {phase.kind === "deficit" && (
          <div className="flex items-center justify-between border-t border-ln py-2.5 text-[12.5px]">
            <span className="text-mu">Ricariche a settimana</span>
            <div className="flex items-center gap-2">
              <Stepper value={phase.refeed_days_per_week} step={1} label={String(phase.refeed_days_per_week)} onChange={(v) => save.mutate({ refeed_days_per_week: Math.min(3, v) })} />
              {phase.refeed_days_per_week > 0 && (
                <select
                  value={phase.refeed_weekday}
                  onChange={(e) => save.mutate({ refeed_weekday: Number(e.target.value) })}
                  className="rounded-lg border border-ln bg-s2 px-2 py-2 text-[12px]"
                >
                  {WEEKDAYS.map((w, i) => (
                    <option key={w} value={i}>
                      {w}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
        )}
        {phase.refeed_days_per_week > 0 && phase.kind === "deficit" && (
          <div className="pb-1 text-[11px] text-mu">Il giorno di ricarica si mangia a metabolismo, gli altri compensano: il deficit si conta sulla settimana [p. 326].</div>
        )}
        <ParamStep
          label="Durata"
          value={phase.duration_weeks ?? 0}
          step={1}
          unit="sett"
          min={0}
          display={phase.duration_weeks ? `${phase.duration_weeks} sett` : "libera"}
          onChange={(v) => save.mutate({ duration_weeks: v || null })}
        />
      </div>
      <div className="mt-3 flex gap-2">
        <Button small className="flex-1" onClick={() => setPicker(true)}>
          Cambia fase
        </Button>
        <Button small kind="ghost" onClick={() => nav("/impostazioni")}>
          Parametri del motore ›
        </Button>
      </div>
      <PhasePicker open={picker} onClose={() => setPicker(false)} templates={templates} current={phase.template_id} />
    </Card>
  )
}

function Param({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="border-t border-ln py-2.5 text-[12.5px] first:border-t-0">
      <div className="flex justify-between">
        <span className="text-mu">{label}</span>
        <b className="font-semibold">{value}</b>
      </div>
      {hint && <div className="mt-0.5 text-right text-[10.5px] text-mu">{hint}</div>}
    </div>
  )
}

function ParamStep({ label, value, step, unit, min = 0, onChange, display }: { label: string; value: number; step: number; unit: string; min?: number; onChange: (v: number) => void; display?: string }) {
  return (
    <div className="flex items-center justify-between border-t border-ln py-2 text-[12.5px]">
      <span className="text-mu">{label}</span>
      <Stepper value={value} step={step} min={min} onChange={onChange} label={display ?? `${step < 0.1 ? n2(value) : n1(value)} ${unit}`} />
    </div>
  )
}

function PhasePicker({ open, onClose, templates, current }: { open: boolean; onClose: () => void; templates: PhaseTemplate[]; current: string }) {
  const qc = useQueryClient()
  const { toast } = useApp()
  const [sel, setSel] = useState<string | null>(null)
  const start = useMutation({
    mutationFn: (id: string) => post<Phase>("/api/phase", { template_id: id }),
    onSuccess: (p) => {
      qc.invalidateQueries()
      toast(`Fase ${p.name} iniziata oggi`)
      onClose()
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Cambia fase"
      footer={
        <Button kind="primary" className="mb-1 w-full" disabled={!sel} busy={start.isPending} onClick={() => sel && start.mutate(sel)}>
          Inizia oggi
        </Button>
      }
    >
      <p className="mb-2 text-[12px] text-mu">La nuova fase parte da oggi, con il target calcolato dal metabolismo stimato. La fase attuale finisce nello storico.</p>
      {templates.map((t) => (
        <button
          key={t.id}
          onClick={() => setSel(t.id)}
          className={clsx("mb-2 w-full rounded-2xl border p-3 text-left", sel === t.id ? "border-ac/50 bg-ac/8" : "border-ln bg-s1")}
        >
          <div className="flex items-center justify-between">
            <b className="text-[13.5px]">{t.name}</b>
            <span className="flex gap-1">
              {t.id === current && <Chip tone="ac">attiva</Chip>}
              <Chip>{KIND_LABEL[t.kind]}</Chip>
            </span>
          </div>
          <div className="mt-1 text-[11.5px] leading-relaxed text-mu">{t.description}</div>
          <div className="mt-1 text-[10.5px] text-mu">
            {t.rate_pct_week ? `${signed(t.rate_pct_week, 2)}% peso/sett · ` : ""}proteine {n1(t.protein_g_per_kg)} g/kg · grassi {n2(t.fat_g_per_kg)} g/kg · {t.source}
          </div>
        </button>
      ))}
    </Sheet>
  )
}

function WeekPlan() {
  const qc = useQueryClient()
  const { toast } = useApp()
  const [variety, setVariety] = useState<"same" | "alternative">("same")
  const [preview, setPreview] = useState<WeekPreview | null>(null)
  const gen = useMutation({
    mutationFn: () => post<WeekPreview>("/api/week/preview", { variety }),
    onSuccess: setPreview,
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  const apply = useMutation({
    mutationFn: () => post<{ saved: number }>("/api/week/apply", { variety }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["today"] })
      toast(`Piano salvato per ${r.saved} giorni`)
      setPreview(null)
    },
  })
  return (
    <Card className="mb-3">
      <div className="mb-1 flex items-center justify-between">
        <b className="text-[14px]">Prossima settimana dalle abitudini</b>
        <Chip tone="ac">indicativo</Chip>
      </div>
      <p className="mb-2.5 text-[12px] text-mu">Stessi alimenti della tua settimana, porzioni ricalcolate sul target di ogni giorno.</p>
      <Segmented
        className="mb-2.5"
        value={variety}
        onChange={(v) => {
          setVariety(v)
          setPreview(null)
        }}
        options={[
          { value: "same", label: "Uguale" },
          { value: "alternative", label: "Qualche cambio" },
        ]}
      />
      {!preview ? (
        <Button className="w-full" busy={gen.isPending} onClick={() => gen.mutate()}>
          Genera anteprima
        </Button>
      ) : (
        <>
          {preview.diff.length > 0 ? (
            <div className="mb-2 grid grid-cols-[1fr_auto_auto] items-center gap-x-3 gap-y-1.5 text-[12px]">
              {preview.diff.slice(0, 8).map((d, i) => (
                <div key={i} className="contents">
                  <span className="truncate text-mu">
                    {d.food} <span className="text-[10.5px]">· {SLOT_LABEL[d.slot]?.toLowerCase()}</span>
                  </span>
                  <span className="text-right text-mu">{n0(d.from)} g</span>
                  <span className="text-right font-bold text-ac">{n0(d.to)} g</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="mb-2 text-[12px] text-mu">Le porzioni restano quasi uguali: la settimana scorsa era già in target.</div>
          )}
          {preview.same.length > 0 && (
            <div className="mb-2 text-[11.5px] text-mu">
              Invariati: {[...new Set(preview.same.map((s) => s.food))].slice(0, 6).join(", ")}
              {preview.same.length > 6 ? "…" : ""}
            </div>
          )}
          <div className="mb-2 flex gap-1 overflow-x-auto">
            {preview.days.map((d) => (
              <div key={d.day} className={clsx("min-w-[64px] rounded-xl border px-2 py-1.5 text-center text-[10.5px]", d.report.within_tolerance ? "border-ln" : "border-wa/40")}>
                <div className="text-mu capitalize">{new Intl.DateTimeFormat("it-IT", { weekday: "short" }).format(new Date(d.day + "T12:00"))}</div>
                <div className="font-bold">{n0(d.report.totals.kcal)}</div>
                {d.kind === "refeed" && <div className="text-ac">ricarica</div>}
              </div>
            ))}
          </div>
          <div className="flex gap-2">
            <Button kind="primary" className="flex-1" busy={apply.isPending} onClick={() => apply.mutate()}>
              Usa questo piano
            </Button>
            <Button onClick={() => setPreview(null)}>Annulla</Button>
          </div>
        </>
      )}
    </Card>
  )
}
