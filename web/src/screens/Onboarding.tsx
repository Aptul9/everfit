import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { useState } from "react"
import { useApp } from "../App"
import CronometerForm from "../components/CronometerForm"
import { Button, Card, Chip, Segmented, Spinner } from "../components/ui"
import { api, post, put, type Phase, type PhaseTemplate, type Settings } from "../lib/api"
import { n1, n2, signed } from "../lib/format"

export default function Onboarding() {
  const { boot } = useApp()
  const step = !boot.cronometer.connected ? "cronometer" : boot.needs_profile ? "profile" : "phase"
  return (
    <div className="pt-safe animate-rise px-4 pb-10">
      <div className="mt-6 mb-5">
        <img src="/logo.svg" alt="" className="mb-3 size-12 rounded-[15px]" />
        <h1 className="text-[26px] font-bold tracking-[-0.02em]">{step === "cronometer" ? "Collega Cronometer" : step === "profile" ? "Due dati per partire" : "Scegli la fase"}</h1>
        <p className="mt-1 text-[13px] text-tx2">
          {step === "cronometer"
            ? "Il diario resta su Cronometer: EverFit lo legge, stima il tuo metabolismo dal peso e ti prepara la giornata."
            : step === "profile"
            ? "Servono solo per la prima stima del metabolismo: poi la correggono il tuo peso e il tuo diario."
            : "Il target parte dal metabolismo stimato e si aggiorna ogni settimana col check-in. Tutto si cambia dopo."}
        </p>
      </div>
      {step === "cronometer" ? (
        <Card>
          <CronometerForm />
        </Card>
      ) : step === "profile" ? (
        <ProfileStep settings={boot.settings} />
      ) : (
        <PhaseStep hasWeights={boot.has_weights} />
      )}
    </div>
  )
}

function ProfileStep({ settings }: { settings: Settings }) {
  const qc = useQueryClient()
  const [p, setP] = useState(settings.profile)
  const save = useMutation({
    mutationFn: () => put("/api/settings", { ...settings, profile: p }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["bootstrap"] }),
  })
  const ok = p.height_cm && p.birth_date
  return (
    <Card>
      <Row label="Sesso">
        <Segmented className="w-40" value={p.sex} onChange={(v) => setP({ ...p, sex: v })} options={[{ value: "M", label: "Uomo" }, { value: "F", label: "Donna" }]} />
      </Row>
      <Row label="Data di nascita">
        <input type="date" value={p.birth_date ?? ""} onChange={(e) => setP({ ...p, birth_date: e.target.value || null })} className="rounded-lg border border-ln bg-s2 px-2 py-2 text-[13px]" />
      </Row>
      <Row label="Altezza">
        <span className="flex items-center gap-1">
          <input type="number" inputMode="numeric" value={p.height_cm ?? ""} onChange={(e) => setP({ ...p, height_cm: e.target.value ? Number(e.target.value) : null })} className="w-20 rounded-lg border border-ln bg-s2 px-2 py-2 text-right text-[13px]" />
          <span className="text-[12px] text-mu">cm</span>
        </span>
      </Row>
      <Row label="Allenamento">
        <Segmented
          className="w-[220px]"
          value={p.activity}
          onChange={(v) => setP({ ...p, activity: v })}
          options={[
            { value: "sedentario", label: "Poco" },
            { value: "moderato", label: "3-4/sett" },
            { value: "intenso", label: "Ogni giorno" },
          ]}
        />
      </Row>
      <Row label="Peso obiettivo" hint="facoltativo">
        <span className="flex items-center gap-1">
          <input type="number" inputMode="decimal" step={0.5} value={p.goal_weight_kg ?? ""} onChange={(e) => setP({ ...p, goal_weight_kg: e.target.value ? Number(e.target.value) : null })} className="w-20 rounded-lg border border-ln bg-s2 px-2 py-2 text-right text-[13px]" />
          <span className="text-[12px] text-mu">kg</span>
        </span>
      </Row>
      <Button kind="primary" className="mt-3 w-full" disabled={!ok} busy={save.isPending} onClick={() => save.mutate()}>
        Avanti
      </Button>
    </Card>
  )
}

function PhaseStep({ hasWeights }: { hasWeights: boolean }) {
  const qc = useQueryClient()
  const { toast } = useApp()
  const q = useQuery({ queryKey: ["phase"], queryFn: () => api<{ phase: Phase | null; templates: PhaseTemplate[] }>("/api/phase") })
  const [sel, setSel] = useState("definizione")
  const [pct, setPct] = useState(0.5)
  const start = useMutation({
    mutationFn: () => {
      const t = q.data!.templates.find((x) => x.id === sel)!
      const custom = t.kind === "deficit" && pct !== Math.abs(t.rate_pct_week)
      return post<Phase>("/api/phase", { template_id: sel, overrides: custom ? { rate_pct_week: -pct } : null })
    },
    onSuccess: () => qc.invalidateQueries(),
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  if (!q.data) return <Spinner />
  if (!hasWeights) {
    return (
      <Card>
        <b className="text-[14px]">Manca una pesata</b>
        <p className="mt-1 text-[12.5px] text-tx2">Registra il peso di stamattina su Cronometer (o collega una bilancia), poi torna qui: la fase parte dal tuo peso attuale.</p>
        <Button className="mt-3" onClick={() => post("/api/sync").then(() => qc.invalidateQueries())}>
          Ho registrato il peso
        </Button>
      </Card>
    )
  }
  const t = q.data.templates.find((x) => x.id === sel)
  return (
    <>
      {q.data.templates.map((x) => (
        <button key={x.id} onClick={() => setSel(x.id)} className={clsx("mb-2 w-full rounded-2xl border p-3.5 text-left", sel === x.id ? "border-ac/50 bg-ac/8" : "border-ln bg-s1")}>
          <div className="flex items-center justify-between">
            <b className="text-[14px]">{x.name}</b>
            <Chip>{x.source === "fuori dal libro" ? "fuori dal libro" : "dal libro"}</Chip>
          </div>
          <div className="mt-1 text-[12px] leading-relaxed text-mu">{x.description}</div>
        </button>
      ))}
      {t?.kind === "deficit" && (
        <Card className="mt-1 mb-2">
          <div className="flex justify-between text-[12.5px]">
            <span className="text-mu">Ritmo di perdita</span>
            <b>{n2(pct)}% del peso a settimana</b>
          </div>
          <input type="range" className="mt-3 w-full" min={0.25} max={1} step={0.05} value={pct} onChange={(e) => setPct(Number(e.target.value))} />
          <div className="mt-1 flex justify-between text-[10px] text-mu">
            <span>leggero</span>
            <span>il libro: 0,5–1% [p. 325]</span>
            <span>{n1(1)}%</span>
          </div>
          {pct < 0.5 && <div className="mt-2 text-[11px] text-wa">Sotto il ritmo minimo del libro ({signed(-0.5, 1)}%): più lento, ma sostenibile.</div>}
        </Card>
      )}
      <Button kind="primary" className="mt-2 w-full" busy={start.isPending} onClick={() => start.mutate()}>
        Inizia oggi
      </Button>
    </>
  )
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-ln py-3 first:border-t-0">
      <div>
        <div className="text-[13px]">{label}</div>
        {hint && <div className="text-[10.5px] text-mu">{hint}</div>}
      </div>
      {children}
    </div>
  )
}
