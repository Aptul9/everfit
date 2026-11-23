import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { useEffect, useState } from "react"
import { useNavigate } from "react-router"
import { useApp } from "../App"
import { Button, Card, Chip, ErrorBox, Header, MACRO_COLORS, Segmented, Spinner } from "../components/ui"
import { api, post, type Checkin as CheckinT, type CheckinPreview, type Macros } from "../lib/api"
import { n0, range, rate, shortDay, signed } from "../lib/format"

const VERDICT_TONE: Record<string, "ok" | "wa" | "er" | "neutral"> = {
  ok: "ok",
  too_fast_loss: "wa",
  too_slow_loss: "wa",
  too_fast_gain: "wa",
  too_slow_gain: "wa",
  hold_before_cut: "neutral",
  hold: "neutral",
  reverse_step: "ok",
  low_adherence: "wa",
  insufficient_data: "neutral",
  stop: "er",
}

const VERDICT_LABEL: Record<string, string> = {
  ok: "in linea",
  hold_before_cut: "si aspetta",
  hold: "si tiene",
  low_adherence: "aderenza",
  insufficient_data: "dati scarsi",
  stop: "fermo",
}

export default function Checkin() {
  const nav = useNavigate()
  const q = useQuery({ queryKey: ["checkin"], queryFn: () => api<CheckinT | null>("/api/checkin") })
  const [editing, setEditing] = useState(false)
  if (q.isLoading) return <Spinner />
  if (q.error) return <ErrorBox error={q.error} retry={() => q.refetch()} />
  const c = q.data
  if (!c) return null
  if (c.too_early) {
    return (
      <div className="animate-rise lg:mx-auto lg:max-w-3xl">
        <Header title="Check-in" onBack={() => nav(-1)} />
        <Card>
          <b className="text-[14px]">Il primo check-in arriva {shortDay(c.first!)}</b>
          <p className="mt-1 text-[12.5px] text-tx2">Serve almeno una settimana dall'inizio della fase. Intanto: pesata ogni mattina e pasti confermati.</p>
        </Card>
      </div>
    )
  }
  const inBand = c.rate_kg_week != null && c.phase.band_kg_week[0] <= c.rate_kg_week && c.rate_kg_week <= c.phase.band_kg_week[1]
  return (
    <div className="animate-rise lg:mx-auto lg:max-w-3xl">
      <Header eyebrow={`Settimana ${range(c.week_start, c.week_end)}`} title="Check-in" onBack={() => nav(-1)} />
      <div className="mb-3 grid grid-cols-2 gap-2.5">
        <Kpi label="Ritmo del peso" value={c.rate_kg_week == null ? "–" : `${signed(c.rate_kg_week, 2)} kg`} foot={<Chip tone={c.rate_kg_week == null ? "neutral" : inBand ? "ok" : "wa"}>{c.rate_kg_week == null ? "n/d" : inBand ? "nella forbice" : "fuori forbice"}</Chip>} />
        <Kpi label="Aderenza" value={c.adherence == null ? "–" : `${Math.round(c.adherence * 100)}%`} foot={<span className="text-[11px] text-mu">{c.mean_intake ? `media ${n0(c.mean_intake)} su ${n0(c.phase.kcal_target)}` : "nessun giorno completo"}</span>} />
        <Kpi label="Diario" value={`${c.complete_days}/7`} foot={<span className="text-[11px] text-mu">giorni completi</span>} />
        <Kpi label="Pesate" value={`${c.weighins}/7`} foot={<span className="text-[11px] text-mu">metabolismo ~{n0(c.expenditure)} ± {n0(c.expenditure_sd)}</span>} />
      </div>
      <Card className="mb-3">
        <div className="mb-2 flex items-center justify-between gap-2">
          <b className="text-[14.5px]">{c.headline}</b>
          {c.decision ? <Chip tone="ok">{c.decision === "accept" ? "accettato" : c.decision === "modify" ? "modificato" : "rifiutato"}</Chip> : <Chip tone={VERDICT_TONE[c.verdict] ?? "neutral"}>{c.proposal ? "da confermare" : VERDICT_LABEL[c.verdict] ?? "nessuna modifica"}</Chip>}
        </div>
        {c.proposal && !editing && <Diff from={c.proposal.macros_from} to={c.proposal.macros_to} />}
        <div className="rounded-[14px] bg-s2 px-3 py-2.5 text-[12px] text-tx2">
          <b className="text-tx">Perché</b>
          <ul className="mt-1.5 list-disc space-y-1 pl-4">
            {c.reasons.map((r, i) => (
              <li key={i}>
                {r.text}
                {r.ref && <span className="text-mu"> {r.ref}</span>}
              </li>
            ))}
          </ul>
        </div>
        {c.flags.filter((f) => f.severity !== "info").map((f) => (
          <div key={f.code} className="mt-2 text-[11.5px] text-wa">
            {f.message} {f.source && <span className="text-mu">· {f.source}</span>}
          </div>
        ))}
        {!c.decision && (editing ? <Modify c={c} onCancel={() => setEditing(false)} /> : <Actions c={c} onModify={() => setEditing(true)} />)}
        {c.decision && c.decided_kcal != null && <div className="mt-3 text-[12px] text-mu">Target in vigore: {n0(c.decided_kcal)} kcal al giorno.</div>}
      </Card>
      {c.proposal && !c.decision && <div className="px-1 text-[11px] text-mu">Dopo l'ok i target dei prossimi giorni si aggiornano e i piani si ricalcolano. Su Cronometer i target non vengono toccati.</div>}
    </div>
  )
}

function Kpi({ label, value, foot }: { label: string; value: string; foot: React.ReactNode }) {
  return (
    <div className="rounded-[18px] border border-ln bg-s1 p-3">
      <div className="text-[11px] text-mu">{label}</div>
      <div className="mt-1 mb-1 text-[21px] font-bold tracking-[-0.02em]">{value}</div>
      {foot}
    </div>
  )
}

function Diff({ from, to }: { from: Macros; to: Macros }) {
  const rows: [string, keyof Macros, string][] = [
    ["Calorie", "kcal", ""],
    ["Proteine", "protein", " g"],
    ["Carboidrati", "carbs", " g"],
    ["Grassi", "fat", " g"],
  ]
  return (
    <div className="my-3 grid grid-cols-[1fr_auto_auto_auto] items-center gap-x-3 gap-y-2 text-[12.5px]">
      {rows.map(([l, k, u]) => {
        const d = Math.round(to[k] - from[k])
        return (
          <div key={k} className="contents">
            <span className="text-mu">{l}</span>
            <span className="text-right text-mu">
              {n0(from[k])}
              {u}
            </span>
            <span className={clsx("text-right font-bold", d ? "text-ac" : "text-tx")}>
              {n0(to[k])}
              {u}
            </span>
            <span className="w-10 text-right text-[11px] text-mu" style={d && k !== "kcal" ? { color: MACRO_COLORS[k] } : undefined}>
              {d ? signed(d) : "="}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function useDecide() {
  const qc = useQueryClient()
  const { toast } = useApp()
  const nav = useNavigate()
  return useMutation({
    mutationFn: ({ week_end, ...body }: { week_end: string; decision: string; kcal?: number; adjust_macro?: string }) => post<CheckinT>(`/api/checkin/${week_end}/decide`, body),
    onSuccess: (r) => {
      qc.setQueryData(["checkin"], r)
      qc.invalidateQueries({ queryKey: ["today"] })
      qc.invalidateQueries({ queryKey: ["phase"] })
      toast(r.decision === "reject" ? "Proposta rifiutata, target invariato" : "Target aggiornato")
      nav("/")
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
}

function Actions({ c, onModify }: { c: CheckinT; onModify: () => void }) {
  const decide = useDecide()
  if (!c.proposal) {
    return (
      <div className="mt-3 flex gap-2">
        <Button kind="primary" className="flex-1" busy={decide.isPending} onClick={() => decide.mutate({ week_end: c.week_end, decision: "accept" })}>
          Ok, proseguo
        </Button>
        <Button className="flex-1" onClick={onModify}>
          Cambia comunque
        </Button>
      </div>
    )
  }
  return (
    <div className="mt-3 flex gap-2">
      <Button kind="primary" className="flex-1" busy={decide.isPending && decide.variables?.decision === "accept"} onClick={() => decide.mutate({ week_end: c.week_end, decision: "accept" })}>
        Accetta
      </Button>
      <Button className="flex-1" onClick={onModify}>
        Modifica
      </Button>
      <Button kind="ghost" busy={decide.isPending && decide.variables?.decision === "reject"} onClick={() => decide.mutate({ week_end: c.week_end, decision: "reject" })}>
        Rifiuta
      </Button>
    </div>
  )
}

function Modify({ c, onCancel }: { c: CheckinT; onCancel: () => void }) {
  const current = c.phase.kcal_target ?? 0
  const [kcal, setKcal] = useState(c.proposal?.kcal_to ?? current)
  const [adjust, setAdjust] = useState(c.phase.adjust_macro)
  const [pv, setPv] = useState<CheckinPreview | null>(null)
  const decide = useDecide()
  useEffect(() => {
    const t = setTimeout(() => {
      post<CheckinPreview>(`/api/checkin/${c.week_end}/preview`, { kcal, adjust_macro: adjust }).then(setPv).catch(() => setPv(null))
    }, 150)
    return () => clearTimeout(t)
  }, [kcal, adjust, c.week_end])
  const cap = pv?.cap ?? 150
  const d = kcal - current
  return (
    <div className="mt-3 border-t border-ln pt-3">
      <div className="text-[11px] uppercase tracking-[0.08em] text-mu">Calorie al giorno</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-[30px] font-bold tracking-[-0.03em]">{n0(kcal)}</span>
        <span className={clsx("font-bold", d ? "text-ac" : "text-mu")}>{signed(d)}</span>
      </div>
      <input type="range" className="mt-3 w-full" min={current - cap} max={current + cap} step={25} value={kcal} onChange={(e) => setKcal(Number(e.target.value))} />
      <div className="flex justify-between text-[10px] text-mu">
        <span>−{cap}</span>
        <span>{c.proposal ? `proposta coach: ${signed(c.proposal.delta)}` : "attuale"}</span>
        <span>+{cap}</span>
      </div>
      {pv?.projected_rate != null && (
        <div className="mt-3 flex items-center justify-between text-[12px]">
          <span className="text-mu">Ritmo stimato</span>
          <span>
            <b>{rate(pv.projected_rate)}</b> <Chip tone={pv.in_band ? "ok" : "wa"}>{pv.in_band ? "nella forbice" : "fuori forbice"}</Chip>
          </span>
        </div>
      )}
      <div className="mt-3 mb-2 text-[12px] text-mu">Su cosa metti la differenza</div>
      <Segmented
        value={adjust}
        onChange={setAdjust}
        options={[
          { value: "carbs", label: "Carboidrati" },
          { value: "fat", label: "Grassi" },
          { value: "mixed", label: "Misto" },
        ]}
      />
      {pv && <Diff from={pv.macros_from} to={pv.macros_to} />}
      <div className="text-[11px] leading-relaxed text-mu">Il cursore si ferma al tetto della correzione settimanale (si cambia in Impostazioni). Le proteine restano al target della fase.</div>
      <div className="mt-3 flex gap-2">
        <Button className="flex-1" onClick={onCancel}>
          Annulla
        </Button>
        <Button kind="primary" className="flex-1" busy={decide.isPending} onClick={() => decide.mutate({ week_end: c.week_end, decision: "modify", kcal, adjust_macro: adjust })}>
          Conferma
        </Button>
      </div>
    </div>
  )
}
