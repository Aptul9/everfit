import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { ArrowRight, ChevronLeft, Loader2, RotateCcw, Sparkles } from "lucide-react"
import { Fragment, type ReactNode, useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router"
import { useApp } from "../App"
import { Button, Chip } from "../components/ui"
import { api, post, type ChatEntry, type ProposalCard } from "../lib/api"
import { n0, n2, SLOT_LABEL } from "../lib/format"

const CHIPS = ["Cosa mangio stasera?", "Fammi il piano per domani", "Perché il peso è fermo?", "Cosa dice Biasci sulle proteine?", "Come sta andando questa settimana?"]

type Live = { text: string; tools: string[]; proposals: ProposalCard[]; error?: string }

export default function Coach() {
  const { boot } = useApp()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [input, setInput] = useState("")
  const [pending, setPending] = useState<string | null>(null)
  const history = useQuery({
    queryKey: ["chat"],
    queryFn: () => api<ChatEntry[]>("/api/chat"),
    // a reply still running on the server (page reloaded mid-answer) shows up by itself
    refetchInterval: (q) => {
      const d = q.state.data
      return !pending && d?.length && d[d.length - 1].role === "user" ? 3000 : false
    },
  })
  const [live, setLive] = useState<Live | null>(null)
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [history.data, live?.text, live?.tools.length, pending])

  const send = async (text: string) => {
    const msg = text.trim()
    if (!msg || pending) return
    setInput("")
    setPending(msg)
    const state: Live = { text: "", tools: [], proposals: [] }
    setLive({ ...state })
    try {
      const res = await fetch("/api/chat", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ message: msg }), credentials: "same-origin" })
      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ""
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        let idx
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const chunk = buf.slice(0, idx)
          buf = buf.slice(idx + 2)
          const line = chunk.split("\n").find((l) => l.startsWith("data:"))
          if (!line) continue
          const ev = JSON.parse(line.slice(5))
          if (ev.type === "text") state.text += ev.text
          else if (ev.type === "tool") state.tools = [...state.tools, ev.label]
          else if (ev.type === "proposal") state.proposals = [...state.proposals, ev.proposal]
          else if (ev.type === "error") state.error = ev.message
          setLive({ ...state })
        }
      }
    } catch (e) {
      state.error = e instanceof Error ? e.message : String(e)
      setLive({ ...state })
    }
    await qc.invalidateQueries({ queryKey: ["chat"] })
    setPending(null)
    setLive(state.error ? state : null)
  }

  const clear = useMutation({
    mutationFn: () => api("/api/chat", { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["chat"] }),
  })

  const entries = history.data ?? []
  return (
    <div className="flex min-h-[calc(100dvh-24px)] flex-col lg:mx-auto lg:max-w-3xl">
      <div className="sticky top-0 z-20 -mx-4 flex items-center justify-between border-b border-ln bg-bg/95 px-3 pt-2 pb-2.5 backdrop-blur">
        <button onClick={() => nav(-1)} className="grid size-9 place-items-center rounded-xl text-mu active:bg-s2" aria-label="Indietro">
          <ChevronLeft className="size-5" />
        </button>
        <div className="text-center">
          <div className="text-[15px] font-bold">Coach</div>
          <div className="text-[10.5px] text-mu">{boot.agent ? "i conti li fa il motore, non il modello" : "non configurato"}</div>
        </div>
        <button onClick={() => clear.mutate()} className="grid size-9 place-items-center rounded-xl text-mu active:bg-s2" aria-label="Nuova conversazione" title="Nuova conversazione">
          <RotateCcw className="size-[18px]" />
        </button>
      </div>

      <div className="flex-1 pt-3 pb-40">
        {!boot.agent && (
          <div className="mb-3 rounded-2xl border border-wa/30 bg-wa/8 p-3.5 text-[12.5px] text-tx2">
            Il coach non è configurato. Sul server imposta <b>ANTHROPIC_BASE_URL</b> verso Meridian (abbonamento Claude, nessuna chiave) oppure <b>ANTHROPIC_API_KEY</b>.
          </div>
        )}
        {entries.length === 0 && !pending && (
          <div className="mt-6 text-center">
            <div className="mx-auto mb-3 grid size-14 place-items-center rounded-[20px] bg-gradient-to-br from-ac2 to-mi text-bg"><Sparkles className="size-7" /></div>
            <b className="text-[15px]">Chiedimi qualcosa</b>
            <p className="mx-auto mt-1 max-w-[280px] text-[12.5px] text-mu">Leggo il tuo diario e il libro, i numeri li calcola il motore. Ogni modifica arriva come scheda da confermare.</p>
          </div>
        )}
        {entries.map((e, i) => (
          <Entry key={i} e={e} />
        ))}
        {pending && (
          <>
            <Bubble me>{pending}</Bubble>
            {live && (
              <>
                {live.tools.length > 0 && <Tools tools={live.tools} />}
                {live.text ? <Bubble>{renderMd(live.text)}</Bubble> : !live.error && <Typing />}
                {live.proposals.map((p) => (
                  <Proposal key={p.proposal_id} p={p} />
                ))}
              </>
            )}
          </>
        )}
        {live?.error && <div className="mb-3 rounded-2xl border border-er/30 bg-er/10 px-3 py-2 text-[12px] text-er">{live.error}</div>}
        <div ref={endRef} />
      </div>

      <div className="pb-safe dock z-30 bg-gradient-to-t from-bg via-bg to-transparent px-3 pt-6">
        <div className="mb-2 flex gap-1.5 overflow-x-auto">
          {CHIPS.map((c) => (
            <button key={c} onClick={() => send(c)} disabled={!!pending || !boot.agent} className="shrink-0 rounded-full border border-ln bg-s2 px-3 py-1.5 text-[11.5px] text-tx2 active:bg-s3 disabled:opacity-40">
              {c}
            </button>
          ))}
        </div>
        <form
          className="flex items-end gap-2 rounded-[20px] border border-ln bg-s1 py-1.5 pr-1.5 pl-3.5 shadow-[0_-10px_30px_rgba(10,12,15,.9)]"
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault()
                send(input)
              }
            }}
            rows={1}
            placeholder={boot.agent ? "Scrivi al coach…" : "Coach non configurato"}
            disabled={!boot.agent}
            className="max-h-32 min-h-[36px] flex-1 resize-none bg-transparent py-2 text-[14px] outline-none placeholder:text-mu"
          />
          <button type="submit" disabled={!input.trim() || !!pending} className="grid size-9 shrink-0 place-items-center rounded-xl bg-ac text-bg disabled:opacity-40" aria-label="Invia">
            {pending ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
          </button>
        </form>
      </div>
    </div>
  )
}

function Entry({ e }: { e: ChatEntry }) {
  if (e.role === "user") return <Bubble me>{e.text}</Bubble>
  if (e.role === "proposal") return <Proposal p={e.proposal} />
  return (
    <>
      {e.tools && e.tools.length > 0 && <Tools tools={e.tools} />}
      {e.text && <Bubble>{renderMd(e.text)}</Bubble>}
    </>
  )
}

function Bubble({ me, children }: { me?: boolean; children: ReactNode }) {
  return (
    <div
      className={clsx(
        "mb-2.5 max-w-[88%] animate-rise rounded-[18px] px-3.5 py-2.5 text-[13.5px] leading-relaxed whitespace-pre-wrap",
        me ? "ml-auto rounded-br-md bg-ac font-medium text-bg" : "rounded-bl-md border border-ln bg-s1",
      )}
    >
      {children}
    </div>
  )
}

function Tools({ tools }: { tools: string[] }) {
  const uniq = [...new Set(tools)]
  return (
    <div className="mb-1.5 ml-1 flex items-center gap-1.5 text-[10.5px] text-mu">
      <i className="inline-block size-1.5 rounded-full bg-ok" />
      {uniq.join(" · ")}
    </div>
  )
}

function Typing() {
  return (
    <div className="mb-2.5 inline-flex gap-1 rounded-[18px] rounded-bl-md border border-ln bg-s1 px-4 py-3">
      {[0, 1, 2].map((i) => (
        <i key={i} className="size-1.5 animate-pulse rounded-full bg-mu" style={{ animationDelay: `${i * 150}ms` }} />
      ))}
    </div>
  )
}

function Proposal({ p }: { p: ProposalCard }) {
  const qc = useQueryClient()
  const { toast } = useApp()
  const [status, setStatus] = useState(p.status ?? "open")
  const apply = useMutation({
    mutationFn: () => post(`/api/proposals/${p.proposal_id}/apply`),
    onSuccess: () => {
      setStatus("applied")
      qc.invalidateQueries({ queryKey: ["today"] })
      qc.invalidateQueries({ queryKey: ["day"] })
      qc.invalidateQueries({ queryKey: ["phase"] })
      qc.invalidateQueries({ queryKey: ["chat"] })
      toast(p.kind === "log" ? "Registrato su Cronometer" : p.kind === "plan" ? "Piano aggiornato" : "Fase aggiornata")
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  const dismiss = useMutation({
    mutationFn: () => post(`/api/proposals/${p.proposal_id}/dismiss`),
    onSuccess: () => setStatus("dismissed"),
  })
  return (
    <div className="mb-2.5 max-w-[92%] animate-rise rounded-2xl border border-ac/35 bg-ac/6 p-3">
      <div className="mb-1 flex items-center justify-between gap-2">
        <b className="text-[12.5px]">{p.summary}</b>
        {status === "applied" ? <Chip tone="ok">confermato</Chip> : status === "dismissed" ? <Chip>annullato</Chip> : <Chip tone="ac">da confermare</Chip>}
      </div>
      {p.kind === "log" && (
        <div className="text-[12px] text-tx2">
          <div className="mb-1 text-[11px] text-mu">{SLOT_LABEL[p.slot ?? ""] ?? p.slot}</div>
          {p.items?.map((i, k) => (
            <div key={k} className="flex justify-between">
              <span>{i.name}</span>
              <span className="text-mu">{n0(i.grams)} g</span>
            </div>
          ))}
          {p.total && <div className="mt-1 text-[11px] text-mu">{n0(p.total.kcal)} kcal · P {n0(p.total.protein)} · C {n0(p.total.carbs)} · G {n0(p.total.fat)}</div>}
        </div>
      )}
      {p.kind === "plan" && (
        <div className="text-[12px] text-tx2">
          {p.meals?.map((m) => (
            <div key={m.slot} className="mt-1">
              <span className="text-mu">{SLOT_LABEL[m.slot] ?? m.slot}:</span> {m.items.map((i) => `${i.name} ${n0(i.grams)} g`).join(" · ")}
            </div>
          ))}
          {p.total && <div className="mt-1 text-[11px] text-mu">{n0(p.total.kcal)} kcal · P {n0(p.total.protein)}</div>}
        </div>
      )}
      {p.kind === "phase" && (
        <div className="text-[12px] text-tx2">
          {p.template_id && <div>Nuova fase: <b>{p.template_id}</b></div>}
          {p.changes &&
            Object.entries(p.changes).map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span className="text-mu">{PHASE_FIELD[k] ?? k}</span>
                <span>
                  {p.current && k in p.current ? <span className="text-mu">{fmtV((p.current as Record<string, unknown>)[k])} → </span> : null}
                  <b className="text-ac">{fmtV(v)}</b>
                </span>
              </div>
            ))}
        </div>
      )}
      {status === "open" && (
        <div className="mt-2.5 flex gap-1.5">
          <Button kind="primary" small className="flex-1" busy={apply.isPending} onClick={() => apply.mutate()}>
            Conferma
          </Button>
          <Button small className="flex-1" busy={dismiss.isPending} onClick={() => dismiss.mutate()}>
            Annulla
          </Button>
        </div>
      )}
    </div>
  )
}

const PHASE_FIELD: Record<string, string> = {
  kcal_target: "Calorie",
  rate_kg_week: "Ritmo kg/sett",
  protein_g_per_kg: "Proteine g/kg",
  fat_g_per_kg: "Grassi g/kg",
  refeed_days_per_week: "Ricariche/sett",
  adjust_macro: "Correzioni su",
  duration_weeks: "Durata sett",
  band_kg_week: "Forbice",
}

const fmtV = (v: unknown): string => (typeof v === "number" ? (Number.isInteger(v) ? n0(v) : n2(v)) : Array.isArray(v) ? v.map(fmtV).join(" / ") : String(v))

function renderMd(text: string): ReactNode {
  const lines = text.split("\n")
  return lines.map((line, i) => {
    const bullet = /^\s*[-*•]\s+/.test(line)
    const content = inline(line.replace(/^\s*[-*•]\s+/, "").replace(/^#+\s*/, ""))
    return (
      <Fragment key={i}>
        {bullet ? (
          <span className="flex gap-1.5">
            <span className="text-mu">•</span>
            <span>{content}</span>
          </span>
        ) : (
          content
        )}
        {i < lines.length - 1 && !bullet && "\n"}
      </Fragment>
    )
  })
}

function inline(s: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /\*\*(.+?)\*\*|`(.+?)`/g
  let last = 0
  let m: RegExpExecArray | null
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index))
    out.push(m[1] ? <b key={m.index} className="font-semibold text-tx">{m[1]}</b> : <code key={m.index} className="rounded bg-s2 px-1 text-[12px]">{m[2]}</code>)
    last = m.index + m[0].length
  }
  if (last < s.length) out.push(s.slice(last))
  return out
}
