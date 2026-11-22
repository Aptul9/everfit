import { useQuery } from "@tanstack/react-query"
import { Info, TriangleAlert } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router"
import { ExpenditureChart, WeekBars, WeightChart } from "../components/charts"
import { Card, Chip, Dot, ErrorBox, Header, Segmented, Spinner } from "../components/ui"
import { api, type Progress as ProgressT } from "../lib/api"
import { addDays, n0, n1, rate, shortDay, signed } from "../lib/format"
import { useApp } from "../App"

const RANGES = [
  { value: "28", label: "4S" },
  { value: "42", label: "6S" },
  { value: "91", label: "3M" },
  { value: "182", label: "6M" },
  { value: "365", label: "1A" },
]

export default function Progress() {
  const [tab, setTab] = useState<"peso" | "metab">("peso")
  const [days, setDays] = useState("42")
  const q = useQuery({ queryKey: ["progress", days], queryFn: () => api<ProgressT>(`/api/progress?days=${days}`) })
  return (
    <div className="animate-rise">
      <Header eyebrow="Trend e stima adattiva" title="Progressi" />
      <Segmented className="mb-2 lg:hidden" value={tab} onChange={setTab} options={[{ value: "peso", label: "Peso" }, { value: "metab", label: "Metabolismo" }]} />
      <Segmented className="mb-3 lg:max-w-md" value={days} onChange={setDays} options={RANGES} />
      {q.isLoading && <Spinner />}
      {q.error && <ErrorBox error={q.error} retry={() => q.refetch()} />}
      {q.data && (
        <div className="lg:grid lg:grid-cols-2 lg:items-start lg:gap-5">
          <div className={tab === "peso" ? "" : "hidden lg:block"}>
            <Weight p={q.data} />
          </div>
          <div className={tab === "metab" ? "" : "hidden lg:block"}>
            <Metab p={q.data} />
          </div>
        </div>
      )}
    </div>
  )
}

function Weight({ p }: { p: ProgressT }) {
  const { boot } = useApp()
  const nav = useNavigate()
  const first = p.weights.find((w) => w.trend != null)?.trend
  const last = p.trend
  const lastPoint = [...p.weights].reverse().find((w) => w.weight != null)
  const dev = lastPoint && lastPoint.trend != null && lastPoint.weight != null ? lastPoint.weight - lastPoint.trend : null
  const inBand = p.rate && p.band ? p.rate.kg_per_week >= p.band[0] && p.rate.kg_per_week <= p.band[1] : null
  const eta = p.projection?.eta_weeks
  if (!p.weighins) {
    return (
      <Card>
        <b className="text-[14px]">Nessuna pesata nel periodo</b>
        <p className="mt-1 text-[12.5px] text-tx2">Pesati ogni mattina, a digiuno, e registra il peso su Cronometer (o collega una bilancia smart). Il trend parte dalla prima pesata.</p>
      </Card>
    )
  }
  return (
    <>
      <Card className="mb-3">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[34px] font-bold leading-none tracking-[-0.03em]">
              {n1(last)}
              <span className="ml-1 text-[14px] font-medium tracking-normal text-mu">kg</span>
            </div>
            {first != null && last != null && (
              <div className="mt-2 text-[12px]">
                <span className={last - first <= 0 ? "text-ok" : "text-c"}>{signed(last - first, 1)} kg</span>
                <span className="text-mu"> nel periodo</span>
              </div>
            )}
          </div>
          <div className="text-right">
            {p.rate ? <Chip tone={inBand === false ? "wa" : "ok"}>{rate(p.rate.kg_per_week)}</Chip> : <Chip>ritmo n/d</Chip>}
            {p.band && <div className="mt-1.5 text-[11px] text-mu">forbice {signed(p.band[0], 2)} / {signed(p.band[1], 2)}</div>}
          </div>
        </div>
        <div className="mt-3">
          <WeightChart data={p.weights} projection={p.projection?.cone} goal={p.goal} />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-3 text-[10.5px] text-mu">
          <span><Dot color="#56606D" />pesata</span>
          <span><Dot color="#B8F35A" />trend</span>
          {p.projection && <span><Dot color="rgba(184,243,90,.3)" />proiezione</span>}
          <span className="ml-auto">tocca il grafico per i valori</span>
        </div>
      </Card>
      {dev != null && Math.abs(dev) >= 0.4 && lastPoint && (
        <Card className="mb-3 flex gap-3">
          <span className="grid size-[34px] shrink-0 place-items-center rounded-[11px] bg-wa/15 text-wa">
            <Info className="size-[18px]" />
          </span>
          <div>
            <b className="text-[13px]">
              {lastPoint.day === boot.today ? "Stamattina" : shortDay(lastPoint.day)} {n1(lastPoint.weight)} kg: {signed(dev, 1)} sul trend
            </b>
            <div className="mt-1 text-[12px] text-mu">
              Nell'arco di pochi giorni il peso si muove per acqua e glicogeno: sale, carboidrati, allenamento, ciclo. Conta la linea, non il punto [p. 13, p. 25].
            </div>
          </div>
        </Card>
      )}
      <div className="mb-3 grid grid-cols-2 gap-2.5">
        <Card className="!p-3">
          <div className="text-[11px] text-mu">Obiettivo</div>
          <div className="mt-1 text-[21px] font-bold tracking-[-0.02em]">{p.goal ? `${n1(p.goal)} kg` : "–"}</div>
          <div className="text-[11px] text-mu">
            {!p.goal ? (
              <button className="text-ac" onClick={() => nav("/impostazioni")}>imposta</button>
            ) : eta ? (
              `al ritmo attuale ~ ${shortDay(addDays(boot.today, Math.round(eta * 7)))}`
            ) : (
              "ritmo non verso l'obiettivo"
            )}
          </div>
        </Card>
        <Card className="!p-3">
          <div className="text-[11px] text-mu">Pesate</div>
          <div className="mt-1 text-[21px] font-bold tracking-[-0.02em]">
            {p.weighins}/{p.weights.length}
          </div>
          <div className="text-[11px] text-mu">{p.rate ? `± ${n1(p.rate.se)} kg/sett di incertezza` : "servono più dati"}</div>
        </Card>
      </div>
    </>
  )
}

function Metab({ p }: { p: ProgressT }) {
  const e = p.expenditure
  if (!e) return null
  return (
    <>
      <Card className="mb-3">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-[34px] font-bold leading-none tracking-[-0.03em]">
              {n0(e.kcal)}
              <span className="ml-1 text-[14px] font-medium tracking-normal text-mu">kcal/g</span>
            </div>
            <div className="mt-2 text-[12px] text-mu">
              ± {n0(e.sd)} · {e.status === "data" ? `da ${e.complete_days} giorni completi e ${e.weighins} pesate` : "solo stima da formula"}
            </div>
          </div>
          {e.status === "data" ? <Chip tone={e.sd < 150 ? "ok" : "wa"}>{e.sd < 150 ? "affidabile" : "in assestamento"}</Chip> : <Chip tone="wa">da formula</Chip>}
        </div>
        <div className="mt-3">
          <ExpenditureChart data={p.expenditure_series} prior={e.prior} />
        </div>
        <div className="mt-1.5 flex flex-wrap gap-3 text-[10.5px] text-mu">
          <span><Dot color="#7BE3B0" />stima</span>
          <span><Dot color="rgba(123,227,176,.3)" />incertezza 95%</span>
          <span><Dot color="rgba(242,244,247,.4)" />mangiato</span>
          <span><i className="mr-1.5 inline-block size-2 rounded-full border-[1.5px] border-c align-middle" />incompleto</span>
        </div>
      </Card>
      <Card className="mb-3">
        <div className="mb-2 flex items-center justify-between">
          <b className="text-[14px]">Mangiato e consumato</b>
          <span className="text-[11px] text-mu">media al giorno</span>
        </div>
        <WeekBars weeks={p.weeks} />
        <div className="mt-1 flex gap-3 text-[10.5px] text-mu">
          <span><Dot color="#B8F35A" />mangiato</span>
          <span><Dot color="rgba(123,227,176,.45)" />consumato (stima)</span>
        </div>
      </Card>
      {p.excluded.length > 0 && (
        <Card className="mb-3 flex gap-3">
          <span className="grid size-[34px] shrink-0 place-items-center rounded-[11px] bg-wa/15 text-wa">
            <TriangleAlert className="size-[18px]" />
          </span>
          <div>
            <b className="text-[13px]">{p.excluded.length} giorni esclusi dalla stima</b>
            <div className="mt-1 text-[12px] text-mu">
              Diario troppo basso per essere completo: {p.excluded.slice(-4).map((x) => `${shortDay(x.day)} (${n0(x.kcal)})`).join(", ")}. Se erano completi, segnali come completi su Cronometer.
            </div>
          </div>
        </Card>
      )}
      <Card>
        <b className="text-[14px]">Da dove parte la stima</b>
        <p className="mt-1 text-[12px] text-mu">
          Il libro dà più formule e dice di verificarle sul peso [p. 25]. Si parte da queste, poi i tuoi dati correggono: {n0(e.prior)} ± {n0(e.prior_sd)} kcal.
        </p>
        {e.formulas.map((f) => (
          <div key={f.name} className="mt-2 flex justify-between border-t border-ln pt-2 text-[12px]">
            <span>{f.name}</span>
            <span className="text-mu">
              {n0(f.low)}–{n0(f.high)} kcal
            </span>
          </div>
        ))}
      </Card>
    </>
  )
}
