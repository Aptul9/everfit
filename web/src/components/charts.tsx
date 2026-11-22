import { useMemo, useRef, useState, type PointerEvent } from "react"
import { n0, n1, shortDay } from "../lib/format"

const GRID = "#1F252D"
const LABEL = "#6B7583"

type Pt = { x: number; y: number }
const path = (pts: Pt[]) => pts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ")

function useHover(n: number, left: number, width: number) {
  const ref = useRef<SVGSVGElement>(null)
  const [i, setI] = useState<number | null>(null)
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const svg = ref.current
    if (!svg || n < 2) return
    const r = svg.getBoundingClientRect()
    const vx = ((e.clientX - r.left) / r.width) * 300
    const k = Math.round(((vx - left) / width) * (n - 1))
    setI(Math.max(0, Math.min(n - 1, k)))
  }
  return { ref, i, onMove, onLeave: () => setI(null) }
}

function niceTicks(lo: number, hi: number, count = 3) {
  const span = hi - lo
  const step = [0.5, 1, 2, 5, 10, 50, 100, 200, 250, 500].find((s) => span / s <= count + 1) ?? 1000
  const out = []
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v)
  return out
}

export function WeightChart({
  data,
  projection,
  goal,
}: {
  data: { day: string; weight: number | null; trend: number | null }[]
  projection?: { week: number; center: number; low: number; high: number }[] | null
  goal?: number | null
}) {
  const W = 300, H = 190, L = 30, R = 8, T = 10, B = 22
  const n = data.length
  const extra = projection ? 21 : 0
  const vals = [
    ...data.flatMap((d) => [d.weight, d.trend]).filter((v): v is number => v != null),
    ...(projection ?? []).flatMap((c) => [c.low, c.high]),
    ...(goal ? [goal] : []),
  ]
  const lo = Math.floor((Math.min(...vals) - 0.3) * 2) / 2
  const hi = Math.ceil((Math.max(...vals) + 0.3) * 2) / 2
  const x = (i: number) => L + (i / Math.max(1, n - 1 + extra)) * (W - L - R)
  const y = (v: number) => T + ((hi - v) / (hi - lo || 1)) * (H - T - B)
  const hover = useHover(n, L, ((n - 1) / Math.max(1, n - 1 + extra)) * (W - L - R))
  const trendPts = data.flatMap((d, i) => (d.trend == null ? [] : [{ x: x(i), y: y(d.trend) }]))
  const last = data.length ? data[data.length - 1] : null
  const lastTrend = [...data].reverse().find((d) => d.trend != null)?.trend
  const ticks = niceTicks(lo, hi)
  const labels = [0, Math.round((n - 1) / 3), Math.round((2 * (n - 1)) / 3), n - 1]
  const h = hover.i != null ? data[hover.i] : null
  if (!vals.length) return <div className="py-10 text-center text-sm text-mu">Nessuna pesata nel periodo</div>
  return (
    <svg
      ref={hover.ref}
      viewBox={`0 0 ${W} ${H}`}
      className="block w-full touch-none select-none"
      onPointerMove={hover.onMove}
      onPointerDown={hover.onMove}
      onPointerLeave={hover.onLeave}
    >
      <defs>
        <linearGradient id="wg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#B8F35A" stopOpacity=".22" />
          <stop offset="1" stopColor="#B8F35A" stopOpacity="0" />
        </linearGradient>
      </defs>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={GRID} />
          <text x={L - 6} y={y(v) + 3} textAnchor="end" fontSize="9" fill={LABEL}>
            {n1(v).replace(",0", "")}
          </text>
        </g>
      ))}
      {goal != null && goal >= lo && goal <= hi && (
        <g>
          <line x1={L} x2={W - R} y1={y(goal)} y2={y(goal)} stroke="#B8F35A" strokeOpacity=".5" strokeDasharray="3 4" />
          <text x={W - R} y={y(goal) - 5} textAnchor="end" fontSize="9" fill="#B8F35A">
            obiettivo {n1(goal)}
          </text>
        </g>
      )}
      {trendPts.length > 1 && (
        <path d={`${path(trendPts)} L${trendPts[trendPts.length - 1].x} ${H - B} L${trendPts[0].x} ${H - B} Z`} fill="url(#wg)" />
      )}
      {projection && lastTrend != null && projection.length > 1 && (
        <g>
          <path
            d={`M${x(n - 1)} ${y(lastTrend)} ${projection
              .slice(1)
              .map((c) => `L${x(n - 1 + c.week * 7)} ${y(c.low)}`)
              .join(" ")} ${[...projection]
              .slice(1)
              .reverse()
              .map((c) => `L${x(n - 1 + c.week * 7)} ${y(c.high)}`)
              .join(" ")} Z`}
            fill="#B8F35A"
            fillOpacity=".1"
          />
          <path
            d={`M${x(n - 1)} ${y(lastTrend)} ${projection.slice(1).map((c) => `L${x(n - 1 + c.week * 7)} ${y(c.center)}`).join(" ")}`}
            stroke="#B8F35A"
            strokeOpacity=".6"
            strokeDasharray="4 4"
            strokeWidth="1.5"
            fill="none"
          />
        </g>
      )}
      {data.map((d, i) => (d.weight != null && i < n - 1 ? <circle key={d.day} cx={x(i)} cy={y(d.weight)} r="2.2" fill="#56606D" /> : null))}
      {trendPts.length > 1 && <path d={path(trendPts)} stroke="#B8F35A" strokeWidth="2.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />}
      {last?.weight != null && <circle cx={x(n - 1)} cy={y(last.weight)} r="3.5" fill="#0A0C0F" stroke="#F2F4F7" strokeWidth="1.5" />}
      {lastTrend != null && <circle cx={x(n - 1)} cy={y(lastTrend)} r="4" fill="#B8F35A" />}
      {labels.map((i, k) => (
        <text key={k} x={x(i)} y={H - 6} fontSize="9" fill={LABEL} textAnchor={k === 0 ? "start" : k === 3 && !extra ? "end" : "middle"}>
          {k === 3 ? "oggi" : data[i] ? shortDay(data[i].day) : ""}
        </text>
      ))}
      {extra > 0 && (
        <text x={W - R} y={H - 6} fontSize="9" fill={LABEL} textAnchor="end">
          +3 sett
        </text>
      )}
      {h && hover.i != null && (
        <g>
          <line x1={x(hover.i)} x2={x(hover.i)} y1={T} y2={H - B} stroke="#F2F4F7" strokeOpacity=".25" />
          <rect x={Math.min(Math.max(x(hover.i) - 46, L), W - R - 92)} y={T} width="92" height="30" rx="7" fill="#1A1F26" stroke="#2A313B" />
          <text x={Math.min(Math.max(x(hover.i), L + 46), W - R - 46)} y={T + 12} textAnchor="middle" fontSize="9" fill="#8D97A5">
            {shortDay(h.day)}
          </text>
          <text x={Math.min(Math.max(x(hover.i), L + 46), W - R - 46)} y={T + 24} textAnchor="middle" fontSize="10" fill="#F2F4F7" fontWeight="600">
            {h.weight != null ? `${n1(h.weight)} · ` : ""}trend {n1(h.trend)}
          </text>
        </g>
      )}
    </svg>
  )
}

export function ExpenditureChart({
  data,
  prior,
}: {
  data: { day: string; kcal: number | null; sd: number | null; intake: number | null; complete: boolean }[]
  prior?: number
}) {
  const W = 300, H = 180, L = 34, R = 8, T = 10, B = 20
  const n = data.length
  const vals = data.flatMap((d) => [d.kcal != null && d.sd != null ? d.kcal + d.sd * 1.5 : null, d.kcal != null && d.sd != null ? d.kcal - d.sd * 1.5 : null, d.intake]).filter((v): v is number => v != null)
  const hover = useHover(n, L, W - L - R)
  const { lo, hi } = useMemo(() => {
    if (!vals.length) return { lo: 1500, hi: 3000 }
    return { lo: Math.floor((Math.min(...vals) - 100) / 100) * 100, hi: Math.ceil((Math.max(...vals) + 100) / 100) * 100 }
  }, [vals.join()])
  if (!vals.length) return <div className="py-10 text-center text-sm text-mu">Servono dati per la stima</div>
  const x = (i: number) => L + (i / Math.max(1, n - 1)) * (W - L - R)
  const y = (v: number) => T + ((hi - v) / (hi - lo)) * (H - T - B)
  const est = data.flatMap((d, i) => (d.kcal == null ? [] : [{ x: x(i), y: y(d.kcal), i }]))
  const up = data.flatMap((d, i) => (d.kcal == null || d.sd == null ? [] : [{ x: x(i), y: y(d.kcal + 1.96 * d.sd) }]))
  const down = data.flatMap((d, i) => (d.kcal == null || d.sd == null ? [] : [{ x: x(i), y: y(d.kcal - 1.96 * d.sd) }])).reverse()
  const ticks = niceTicks(lo, hi)
  const labels = [0, Math.round((n - 1) / 3), Math.round((2 * (n - 1)) / 3), n - 1]
  const h = hover.i != null ? data[hover.i] : null
  return (
    <svg ref={hover.ref} viewBox={`0 0 ${W} ${H}`} className="block w-full touch-none select-none" onPointerMove={hover.onMove} onPointerDown={hover.onMove} onPointerLeave={hover.onLeave}>
      {ticks.map((v) => (
        <g key={v}>
          <line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={GRID} />
          <text x={L - 6} y={y(v) + 3} textAnchor="end" fontSize="9" fill={LABEL}>
            {n0(v)}
          </text>
        </g>
      ))}
      {up.length > 1 && <path d={`${path(up)} ${down.map((p) => `L${p.x} ${p.y}`).join(" ")} Z`} fill="#7BE3B0" fillOpacity=".14" />}
      {data.map((d, i) =>
        d.intake == null ? null : d.complete ? (
          <circle key={d.day} cx={x(i)} cy={y(d.intake)} r="2" fill="#F2F4F7" fillOpacity=".4" />
        ) : (
          <circle key={d.day} cx={x(i)} cy={y(Math.max(lo, d.intake))} r="2.4" fill="none" stroke="#F7C052" strokeWidth="1.3" />
        ),
      )}
      {est.length > 1 && <path d={path(est)} stroke="#7BE3B0" strokeWidth="2.5" fill="none" strokeLinecap="round" />}
      {prior != null && est.length > 0 && (
        <g>
          <circle cx={L} cy={y(prior)} r="4" fill="#0A0C0F" stroke="#7BE3B0" strokeWidth="2" />
          <text x={L + 8} y={y(prior) + 14} fontSize="9" fill="#C9D1DB">
            stima da formula
          </text>
        </g>
      )}
      {est.length > 0 && <circle cx={est[est.length - 1].x} cy={est[est.length - 1].y} r="4" fill="#7BE3B0" />}
      {labels.map((i, k) => (
        <text key={k} x={x(i)} y={H - 5} fontSize="9" fill={LABEL} textAnchor={k === 0 ? "start" : k === 3 ? "end" : "middle"}>
          {k === 3 ? "oggi" : data[i] ? shortDay(data[i].day) : ""}
        </text>
      ))}
      {h && hover.i != null && (
        <g>
          <line x1={x(hover.i)} x2={x(hover.i)} y1={T} y2={H - B} stroke="#F2F4F7" strokeOpacity=".25" />
          <rect x={Math.min(Math.max(x(hover.i) - 52, L), W - R - 104)} y={T} width="104" height="30" rx="7" fill="#1A1F26" stroke="#2A313B" />
          <text x={Math.min(Math.max(x(hover.i), L + 52), W - R - 52)} y={T + 12} textAnchor="middle" fontSize="9" fill="#8D97A5">
            {shortDay(h.day)}
            {h.intake != null ? ` · mangiato ${n0(h.intake)}` : ""}
          </text>
          <text x={Math.min(Math.max(x(hover.i), L + 52), W - R - 52)} y={T + 24} textAnchor="middle" fontSize="10" fill="#F2F4F7" fontWeight="600">
            {h.kcal != null ? `${n0(h.kcal)} ± ${n0(h.sd)} kcal` : "–"}
          </text>
        </g>
      )}
    </svg>
  )
}

export function WeekBars({ weeks }: { weeks: { start: string; intake: number | null; expenditure: number | null }[] }) {
  const W = 300, H = 130, B = 20, T = 18
  const max = Math.max(2600, ...weeks.flatMap((w) => [w.intake ?? 0, w.expenditure ?? 0])) * 1.05
  const y = (v: number) => T + (1 - v / max) * (H - T - B)
  const gw = W / Math.max(1, weeks.length)
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full">
      {weeks.map((w, k) => {
        const cx = gw * k + gw / 2
        const bw = Math.min(20, gw / 3)
        return (
          <g key={w.start}>
            {w.intake != null && <rect x={cx - bw - 2} y={y(w.intake)} width={bw} height={H - B - y(w.intake)} rx="5" fill="#B8F35A" fillOpacity=".9" />}
            {w.expenditure != null && <rect x={cx + 2} y={y(w.expenditure)} width={bw} height={H - B - y(w.expenditure)} rx="5" fill="#7BE3B0" fillOpacity=".35" />}
            {w.intake != null && w.expenditure != null && (
              <text x={cx} y={Math.min(y(w.intake), y(w.expenditure)) - 6} textAnchor="middle" fontSize="9.5" fontWeight="600" fill="#C9D1DB">
                {w.intake - w.expenditure > 0 ? "+" : "−"}
                {n0(Math.abs(w.intake - w.expenditure))}
              </text>
            )}
            <text x={cx} y={H - 5} textAnchor="middle" fontSize="9" fill={LABEL}>
              {shortDay(w.start)}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export function Spark({ values, width = 130, height = 44 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) return null
  const mn = Math.min(...values) - 0.1, mx = Math.max(...values) + 0.1
  const x = (i: number) => 2 + (i / (values.length - 1)) * (width - 6)
  const y = (v: number) => 4 + ((mx - v) / (mx - mn)) * (height - 8)
  const pts = values.map((v, i) => ({ x: x(i), y: y(v) }))
  return (
    <svg width={width} height={height}>
      <defs>
        <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#B8F35A" stopOpacity=".25" />
          <stop offset="1" stopColor="#B8F35A" stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${path(pts)} L${pts[pts.length - 1].x} ${height} L${pts[0].x} ${height} Z`} fill="url(#sg)" />
      <path d={path(pts)} stroke="#B8F35A" strokeWidth="2" fill="none" strokeLinecap="round" />
      <circle cx={pts[pts.length - 1].x} cy={pts[pts.length - 1].y} r="3" fill="#B8F35A" />
    </svg>
  )
}

export function DayBars({
  days,
  onPick,
  selected,
}: {
  days: { day: string; kcal: number; target: number | null; complete: boolean; future: boolean }[]
  onPick: (day: string) => void
  selected?: string | null
}) {
  const W = 300, H = 112, B = 18, T = 10
  const target = days.find((d) => d.target)?.target ?? null
  const max = Math.max(target ?? 0, ...days.map((d) => d.kcal)) * 1.12 || 2500
  const y = (v: number) => T + (1 - v / max) * (H - T - B)
  const gw = W / 7
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block w-full">
      {days.map((d, i) => {
        const cx = gw * i + gw / 2
        const over = d.target != null && d.kcal > d.target * 1.12
        const fill = d.future ? "none" : !d.complete ? "none" : over ? "#F7C052" : "#B8F35A"
        const h = Math.max(2, H - B - y(d.kcal))
        return (
          <g key={d.day} onClick={() => !d.future && onPick(d.day)} className="cursor-pointer">
            <rect x={cx - gw / 2} y={0} width={gw} height={H} fill="transparent" />
            <rect
              x={cx - 11}
              y={H - B - h}
              width="22"
              height={h}
              rx="6"
              fill={fill}
              fillOpacity={selected && selected !== d.day ? 0.45 : 0.9}
              stroke={d.complete || d.future ? "none" : "#56606D"}
              strokeDasharray="3 3"
            />
            <text x={cx} y={H - 4} textAnchor="middle" fontSize="9" fill={selected === d.day ? "#F2F4F7" : LABEL} fontWeight={selected === d.day ? 700 : 400}>
              {new Intl.DateTimeFormat("it-IT", { weekday: "narrow" }).format(new Date(d.day + "T12:00"))}
            </text>
          </g>
        )
      })}
      {target && (
        <g>
          <line x1="0" x2={W} y1={y(target)} y2={y(target)} stroke="#F2F4F7" strokeOpacity=".45" strokeDasharray="4 4" />
          <text x={W - 2} y={y(target) - 4} textAnchor="end" fontSize="9" fill="#C9D1DB">
            target {n0(target)}
          </text>
        </g>
      )}
    </svg>
  )
}
