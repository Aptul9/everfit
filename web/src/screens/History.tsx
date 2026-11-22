import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { ChevronLeft, ChevronRight, Copy, Lock, Pin } from "lucide-react"
import { useState } from "react"
import { useNavigate } from "react-router"
import { useApp } from "../App"
import { DayBars } from "../components/charts"
import { CopySheet, DayMeals, DaySummary } from "../components/meals"
import { Button, Card, Chip, ErrorBox, Header, Sheet, Spinner } from "../components/ui"
import { api, post, type History as HistoryT, type HistoryDay, type TemplateInfo, type Today as TodayT } from "../lib/api"
import { addDays, longDay, monday, n0, range, SLOT_LABEL, weekday } from "../lib/format"

export default function History() {
  const { boot } = useApp()
  const [week, setWeek] = useState(() => monday(boot.today))
  const [open, setOpen] = useState<HistoryDay | null>(null)
  const nav = useNavigate()
  const q = useQuery({ queryKey: ["history", week], queryFn: () => api<HistoryT>(`/api/history?week_start=${week}`) })
  const isCurrent = week === monday(boot.today)

  return (
    <div className="animate-rise">
      <Header eyebrow="Cosa hai mangiato" title="Storico" />
      <div className="mb-3 flex items-center gap-1 rounded-xl bg-s2 p-[3px]">
        <button onClick={() => setWeek(addDays(week, -7))} className="grid h-8 w-10 place-items-center rounded-[9px] text-mu active:bg-s3" aria-label="Settimana precedente">
          <ChevronLeft className="size-4" />
        </button>
        <div className="flex-1 rounded-[9px] bg-s3 py-1.5 text-center text-[12px] font-semibold">{range(week, addDays(week, 6))}</div>
        <button
          onClick={() => setWeek(addDays(week, 7))}
          disabled={isCurrent}
          className="grid h-8 w-10 place-items-center rounded-[9px] text-mu active:bg-s3 disabled:opacity-30"
          aria-label="Settimana successiva"
        >
          <ChevronRight className="size-4" />
        </button>
      </div>
      {q.isLoading && <Spinner />}
      {q.error && <ErrorBox error={q.error} retry={() => q.refetch()} />}
      {q.data && (
        <div className="lg:grid lg:grid-cols-2 lg:items-start lg:gap-5">
          <div>
          <Card className="mb-3">
            <DayBars days={q.data.days} onPick={(d) => setOpen(q.data!.days.find((x) => x.day === d) ?? null)} selected={open?.day} />
            <div className="mt-1 flex flex-wrap gap-3 text-[10.5px] text-mu">
              <span><i className="mr-1 inline-block size-2 rounded-sm bg-ac align-middle" />nel target</span>
              <span><i className="mr-1 inline-block size-2 rounded-sm bg-c align-middle" />sopra</span>
              <span><i className="mr-1 inline-block size-2 rounded-sm border border-dashed border-mu align-middle" />incompleto, escluso dalle stime</span>
            </div>
          </Card>
          <Card className="mb-3 !py-1">
            {q.data.days
              .filter((d) => !d.future)
              .map((d) => (
                <button key={d.day} onClick={() => setOpen(d)} className="flex w-full items-center gap-3 border-t border-ln py-2.5 text-left first:border-t-0">
                  <div className="w-9 text-[11px] leading-tight text-mu">
                    {weekday(d.day)}
                    <b className="block text-[15px] text-tx">{new Date(d.day + "T12:00").getDate()}</b>
                  </div>
                  <div className="min-w-0 flex-1 truncate text-[11.5px] text-tx2">
                    {d.meals.length ? d.meals.map((m) => m.items.slice(0, 2).map((i) => i.name.split(" ")[0]).join(" e ")).join(" · ") : <span className="text-mu">vuoto</span>}
                  </div>
                  <DayKcal d={d} />
                </button>
              ))}
          </Card>
          </div>
          <div>
          <Templates templates={q.data.templates} />
          <Button className="mt-3 w-full" onClick={() => nav("/piano#settimana")}>
            Piano della prossima settimana dalle abitudini
          </Button>
          </div>
        </div>
      )}
      {open && <DaySheet day={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function DayKcal({ d }: { d: HistoryDay }) {
  const { boot } = useApp()
  if (d.day === boot.today) return <div className="text-right text-[12px] font-bold">{n0(d.kcal)}<span className="block text-[10px] font-medium text-mi">in corso</span></div>
  const over = d.target != null && d.complete && d.kcal > d.target * 1.12
  return (
    <div className={clsx("text-right text-[12px] font-bold", !d.complete ? "text-mu" : over ? "text-c" : "")}>
      {n0(d.kcal)}
      <span className="block text-[10px] font-medium">{!d.complete ? "incompleto" : over ? `+${n0(d.kcal - d.target!)}` : "✓"}</span>
    </div>
  )
}

function DaySheet({ day, onClose }: { day: HistoryDay; onClose: () => void }) {
  const { boot, toast } = useApp()
  const qc = useQueryClient()
  const [copying, setCopying] = useState(false)
  const q = useQuery({ queryKey: ["day", day.day], queryFn: () => api<TodayT>(`/api/today?day=${day.day}`) })
  const repeat = useMutation({
    mutationFn: (target: string) => post<TodayT>("/api/plan/repeat", { source: day.day, target }),
    onSuccess: (data, target) => {
      qc.setQueryData(["day", target], data)
      if (target === boot.today) qc.setQueryData(["today"], data)
      qc.invalidateQueries({ queryKey: ["history"] })
      toast(`Copiato in ${target === boot.today ? "oggi" : "domani"}, stesse quantità: da confermare`)
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  const isToday = day.day === boot.today
  const eaten = q.data ? q.data.meals.some((m) => m.count_eaten > 0) : day.meals.length > 0
  return (
    <Sheet
      open
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          <span className="first-letter:uppercase">{longDay(day.day)}</span>
          {isToday ? <Chip tone="mi">in corso</Chip> : day.future ? null : day.complete ? <Chip tone="ok">completo</Chip> : <Chip>incompleto</Chip>}
        </span>
      }
      footer={
        <div className="mb-1 flex flex-col gap-2">
          {day.day < boot.today && eaten && (
            <div className="flex gap-2">
              <Button className="flex-1" small busy={repeat.isPending && repeat.variables === boot.today} onClick={() => repeat.mutate(boot.today)}>
                Ripeti oggi
              </Button>
              <Button className="flex-1" small busy={repeat.isPending && repeat.variables !== boot.today} onClick={() => repeat.mutate(addDays(boot.today, 1))}>
                Ripeti domani
              </Button>
            </div>
          )}
          <Button small kind="ghost" onClick={() => setCopying(true)}>
            <Copy className="size-4" /> Copia da un giorno
          </Button>
        </div>
      }
    >
      {q.isLoading && <Spinner />}
      {q.error && <ErrorBox error={q.error} retry={() => q.refetch()} />}
      {q.data && (
        <>
          <div className="mb-3 rounded-[22px] border border-ln bg-s1 p-4">
            <DaySummary view={q.data} />
          </div>
          <DayMeals view={q.data} />
        </>
      )}
      {copying && <CopySheet target={day.day} onClose={() => setCopying(false)} />}
    </Sheet>
  )
}

function Templates({ templates }: { templates: TemplateInfo[] }) {
  const qc = useQueryClient()
  const { toast } = useApp()
  const pin = useMutation({
    mutationFn: ({ key, mode }: { key: string; mode: TemplateInfo["pin"] }) => post("/api/templates/pin", { key, mode }),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["history"] })
      qc.invalidateQueries({ queryKey: ["today"] })
      toast(v.mode === "fixed" ? "Fisso: non verrà più ridimensionato" : v.mode === "use" ? "Entra nei piani" : v.mode === "hidden" ? "Escluso dai piani" : "Tornato automatico")
    },
  })
  if (!templates.length) {
    return (
      <Card>
        <b className="text-[14px]">I tuoi pasti tipo</b>
        <p className="mt-1 text-[12px] text-mu">Compariranno quando ci saranno almeno due pasti simili nel diario.</p>
      </Card>
    )
  }
  return (
    <Card>
      <div className="mb-1 flex items-center justify-between">
        <b className="text-[14px]">I tuoi pasti tipo</b>
        <span className="text-[11px] text-mu">ultime 6 settimane</span>
      </div>
      {templates.map((t) => (
        <div key={t.key} className="border-t border-ln py-2.5 first:border-t-0">
          <div className="flex items-start gap-2">
            <div className="min-w-0 flex-1">
              <b className="block text-[12.5px]">
                {SLOT_LABEL[t.slot] ?? t.slot} · {t.name}
              </b>
              <span className="text-[10.5px] text-mu">
                {t.count} volte
                {t.items
                  .filter((i) => i.range && i.range[1] - i.range[0] >= 10)
                  .slice(0, 1)
                  .map((i) => ` · ${i.name.split(" ")[0].toLowerCase()} ${n0(i.range![0])}–${n0(i.range![1])} g`)}
              </span>
            </div>
          </div>
          <div className="mt-1.5 flex gap-1.5">
            {([
              ["fixed", "Fisso", Lock],
              ["use", "Usa", Pin],
              ["hidden", "Escludi", null],
            ] as const).map(([mode, label, Icon]) => (
              <button
                key={mode}
                onClick={() => pin.mutate({ key: t.key, mode: t.pin === mode ? null : mode })}
                className={clsx(
                  "flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] font-semibold",
                  t.pin === mode ? (mode === "hidden" ? "border-er/40 text-er" : "border-ac/50 bg-ac/10 text-ac") : "border-ln text-mu",
                )}
              >
                {Icon && <Icon className="size-3" />}
                {label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </Card>
  )
}
