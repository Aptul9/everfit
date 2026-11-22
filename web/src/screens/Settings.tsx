import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bell, CloudCog, RefreshCw } from "lucide-react"
import { useEffect, useState } from "react"
import { useNavigate } from "react-router"
import { useApp } from "../App"
import CronometerForm from "../components/CronometerForm"
import { Button, Card, Chip, ErrorBox, Header, Segmented, Spinner } from "../components/ui"
import { api, post, put, type JsonSchema, type Settings as SettingsT, type SyncStatus } from "../lib/api"
import { n0 } from "../lib/format"

const ENGINE_GROUPS: [string, string[]][] = [
  ["Diario e stima del metabolismo", ["logging_offset_kcal", "incomplete_threshold", "expenditure_window_days", "min_complete_days", "min_weighins", "prior_sd_kcal", "kcal_per_kg"]],
  ["Peso e ritmo", ["trend_alpha", "trend_beta", "rate_window_days"]],
  ["Check-in", ["max_weekly_change_kcal", "weeks_before_cut", "adherence_tolerance", "checkin_min_weighins", "checkin_min_complete_days"]],
  ["Piano alimentare", ["plan_kcal_tolerance"]],
]

const LABELS: Record<string, string> = {
  kcal_per_kg: "kcal per kg di peso",
  trend_alpha: "Reattività del trend",
  trend_beta: "Correzione del ritardo",
  rate_window_days: "Finestra del ritmo (giorni)",
  expenditure_window_days: "Finestra del metabolismo (giorni)",
  min_complete_days: "Giorni completi minimi",
  min_weighins: "Pesate minime",
  prior_sd_kcal: "Incertezza della formula (kcal)",
  logging_offset_kcal: "Calorie non loggate al giorno",
  incomplete_threshold: "Soglia giorno incompleto",
  max_weekly_change_kcal: "Tetto correzione settimanale (kcal)",
  checkin_min_weighins: "Pesate minime a settimana",
  checkin_min_complete_days: "Giorni completi minimi a settimana",
  adherence_tolerance: "Tolleranza aderenza",
  weeks_before_cut: "Settimane prima di tagliare",
  plan_kcal_tolerance: "Tolleranza del piano (kcal)",
  fat_min_g_per_kg: "Grassi minimi (g/kg)",
  min_kcal_per_kg: "Soglia di allarme (kcal/kg)",
  protein_max_pct_kcal: "Proteine massime (% kcal)",
  carbs_min_g_per_kg: "Carboidrati minimi (g/kg)",
  max_deficit_pct: "Deficit massimo (%)",
  max_loss_pct_week: "Perdita massima (% peso/sett)",
}

const PCT = new Set(["incomplete_threshold", "adherence_tolerance"])

export default function Settings() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const { toast, boot } = useApp()
  const q = useQuery({ queryKey: ["settings"], queryFn: () => api<{ settings: SettingsT; schema: JsonSchema }>("/api/settings") })
  const [s, setS] = useState<SettingsT | null>(null)
  useEffect(() => {
    if (q.data) setS(q.data.settings)
  }, [q.data])
  const save = useMutation({
    mutationFn: () => put<SettingsT>("/api/settings", s),
    onSuccess: (r) => {
      qc.setQueryData(["settings"], { ...q.data!, settings: r })
      qc.invalidateQueries()
      toast("Impostazioni salvate")
    },
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  if (q.isLoading || !s) return <Spinner />
  if (q.error) return <ErrorBox error={q.error} />
  const dirty = JSON.stringify(s) !== JSON.stringify(q.data!.settings)
  const defs = q.data!.schema.$defs
  const p = s.profile
  const setP = (k: keyof SettingsT["profile"], v: unknown) => setS({ ...s, profile: { ...p, [k]: v } })

  return (
    <div className="animate-rise pb-16">
      <Header title="Impostazioni" onBack={() => nav(-1)} />
      <Account />
      <Section title="Profilo">
        <Field label="Sesso">
          <Segmented className="w-36" value={p.sex} onChange={(v) => setP("sex", v)} options={[{ value: "M", label: "Uomo" }, { value: "F", label: "Donna" }]} />
        </Field>
        <Field label="Data di nascita">
          <input type="date" value={p.birth_date ?? ""} onChange={(e) => setP("birth_date", e.target.value || null)} className="rounded-lg border border-ln bg-s2 px-2 py-1.5 text-[13px]" />
        </Field>
        <Field label="Altezza (cm)">
          <Num value={p.height_cm} onChange={(v) => setP("height_cm", v)} />
        </Field>
        <Field label="Attività" hint="per la stima iniziale da formula [p. 24]">
          <Segmented
            className="w-[210px]"
            value={p.activity}
            onChange={(v) => setP("activity", v)}
            options={[
              { value: "sedentario", label: "Bassa" },
              { value: "moderato", label: "3-4/sett" },
              { value: "intenso", label: "Ogni giorno" },
            ]}
          />
        </Field>
        <Field label="Peso obiettivo (kg)" hint="facoltativo">
          <Num value={p.goal_weight_kg} onChange={(v) => setP("goal_weight_kg", v)} step={0.5} />
        </Field>
      </Section>

      {ENGINE_GROUPS.map(([title, keys]) => (
        <Section key={title} title={title}>
          {keys.map((k) => {
            const meta = defs.EngineParams.properties[k]
            return (
              <Field key={k} label={LABELS[k] ?? k} hint={meta?.description} source={meta?.source}>
                <Num
                  value={PCT.has(k) ? Math.round(s.engine[k] * 100) : s.engine[k]}
                  suffix={PCT.has(k) ? "%" : undefined}
                  step={k === "trend_alpha" || k === "trend_beta" ? 0.01 : 1}
                  onChange={(v) => v != null && setS({ ...s, engine: { ...s.engine, [k]: PCT.has(k) ? v / 100 : v } })}
                />
              </Field>
            )
          })}
        </Section>
      ))}

      <Section title="Limiti di sicurezza" note="Se un target li supera l'app non blocca: avvisa, e il check-in non propone correzioni oltre la soglia di allarme.">
        {Object.keys(s.guardrails).map((k) => {
          const meta = defs.Guardrails.properties[k]
          return (
            <Field key={k} label={LABELS[k] ?? k} hint={meta?.description} source={meta?.source}>
              <Num value={s.guardrails[k]} step={k.includes("g_per_kg") || k.includes("pct_week") ? 0.05 : 1} onChange={(v) => v != null && setS({ ...s, guardrails: { ...s.guardrails, [k]: v } })} />
            </Field>
          )
        })}
      </Section>

      <Notifications />
      <SyncCard demo={boot.demo} />

      {dirty && (
        <div className="pb-safe fixed inset-x-0 bottom-0 z-40 mx-auto flex max-w-md gap-2 bg-gradient-to-t from-bg via-bg to-transparent px-4 pt-6">
          <Button className="flex-1" onClick={() => setS(q.data!.settings)}>
            Annulla
          </Button>
          <Button kind="primary" className="flex-[2]" busy={save.isPending} onClick={() => save.mutate()}>
            Salva
          </Button>
        </div>
      )}
    </div>
  )
}

function Account() {
  const q = useQuery({ queryKey: ["auth"], queryFn: () => api<{ mode: string; ok: boolean; user: { email: string; name: string } | null }>("/api/auth") })
  if (!q.data?.user || q.data.mode !== "oidc") return null
  return (
    <Card className="mb-3 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <b className="block truncate text-[14px]">{q.data.user.name}</b>
        <span className="text-[11.5px] text-mu">{q.data.user.email} · EverID</span>
      </div>
      <Button small onClick={() => window.location.assign("/oidc/logout")}>
        Esci
      </Button>
    </Card>
  )
}

function Section({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
  return (
    <Card className="mb-3">
      <b className="text-[14px]">{title}</b>
      {note && <p className="mt-1 text-[11.5px] text-mu">{note}</p>}
      <div className="mt-1">{children}</div>
    </Card>
  )
}

function Field({ label, hint, source, children }: { label: string; hint?: string; source?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-t border-ln py-2.5 first:border-t-0">
      <div className="min-w-0">
        <div className="text-[12.5px]">{label}</div>
        {(hint || source) && (
          <div className="text-[10.5px] leading-snug text-mu">
            {hint}
            {source && <span className="text-tx2/50"> · {source}</span>}
          </div>
        )}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

function Num({ value, onChange, step = 1, suffix }: { value: number | null; onChange: (v: number | null) => void; step?: number; suffix?: string }) {
  return (
    <span className="flex items-center gap-1">
      <input
        type="number"
        inputMode="decimal"
        step={step}
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-20 rounded-lg border border-ln bg-s2 px-2 py-1.5 text-right text-[13px] outline-none focus:border-ac/50"
      />
      {suffix && <span className="text-[12px] text-mu">{suffix}</span>}
    </span>
  )
}

function b64ToBytes(b64: string) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4)
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"))
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

function Notifications() {
  const { toast } = useApp()
  const q = useQuery({ queryKey: ["push"], queryFn: () => api<{ key: string; prefs: { enabled: boolean; checkin_hour: number; meals_hour: number } }>("/api/push/key") })
  const [perm, setPerm] = useState(typeof Notification !== "undefined" ? Notification.permission : "denied")
  const supported = typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window
  const subscribe = useMutation({
    mutationFn: async () => {
      const p = await Notification.requestPermission()
      setPerm(p)
      if (p !== "granted") throw new Error("Permesso negato dal browser")
      const reg = await navigator.serviceWorker.ready
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(q.data!.key) })
      await post("/api/push/subscribe", { subscription: sub.toJSON() })
      await post("/api/push/test")
    },
    onSuccess: () => toast("Notifiche attive: ne è appena partita una di prova"),
    onError: (e) => toast(e instanceof Error ? e.message : String(e)),
  })
  const prefs = useMutation({ mutationFn: (body: Record<string, unknown>) => put("/api/push/prefs", body), onSuccess: () => q.refetch() })
  return (
    <Card className="mb-3">
      <div className="flex items-center gap-2">
        <Bell className="size-4 text-ac" />
        <b className="text-[14px]">Notifiche</b>
      </div>
      {!supported ? (
        <p className="mt-1 text-[12px] text-mu">Questo browser non supporta le notifiche push. Su iPhone funzionano solo dall'app aggiunta alla schermata Home; servono HTTPS.</p>
      ) : (
        <>
          <p className="mt-1 text-[12px] text-mu">Il check-in della domenica e un promemoria la sera se resta un pasto da confermare.</p>
          {q.data && (
            <div className="mt-1">
              <Field label="Check-in (domenica, ore)">
                <Num value={q.data.prefs.checkin_hour} onChange={(v) => v != null && prefs.mutate({ checkin_hour: v })} />
              </Field>
              <Field label="Pasti da confermare (ore)">
                <Num value={q.data.prefs.meals_hour} onChange={(v) => v != null && prefs.mutate({ meals_hour: v })} />
              </Field>
            </div>
          )}
          <Button small className="mt-2" busy={subscribe.isPending} onClick={() => subscribe.mutate()}>
            {perm === "granted" ? "Riattiva su questo dispositivo" : "Attiva su questo dispositivo"}
          </Button>
        </>
      )}
    </Card>
  )
}

function SyncCard({ demo }: { demo: boolean }) {
  const qc = useQueryClient()
  const { toast, boot } = useApp()
  const [change, setChange] = useState(false)
  const unlink = useMutation({
    mutationFn: () => api("/api/cronometer", { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries(),
  })
  const q = useQuery({ queryKey: ["sync"], queryFn: () => api<SyncStatus>("/api/sync") })
  const run = useMutation({
    mutationFn: () => post<SyncStatus>("/api/sync"),
    onSuccess: (r) => {
      qc.setQueryData(["sync"], r)
      qc.invalidateQueries({ queryKey: ["today"] })
      toast(r.last_error ? "Sincronizzazione con errori" : "Sincronizzato")
    },
  })
  const s = q.data
  return (
    <Card className="mb-3">
      <div className="flex items-center gap-2">
        <CloudCog className="size-4 text-mi" />
        <b className="text-[14px]">Cronometer</b>
        {s && <Chip tone={demo ? "mi" : !boot.cronometer.connected ? "wa" : s.last_error ? "er" : "ok"}>{demo ? "demo" : !boot.cronometer.connected ? "non collegato" : s.last_error ? "errore" : "collegato"}</Chip>}
      </div>
      {!demo && boot.cronometer.connected && (
        <div className="mt-2 flex items-center justify-between gap-2 text-[12px]">
          <span className="truncate text-tx2">{boot.cronometer.username}</span>
          <span className="flex gap-1.5">
            <Button small onClick={() => setChange(!change)}>
              Cambia account
            </Button>
            <Button small kind="ghost" busy={unlink.isPending} onClick={() => window.confirm("Scollegare Cronometer? Il diario resta su Cronometer, qui si ferma la sincronizzazione.") && unlink.mutate()}>
              Scollega
            </Button>
          </span>
        </div>
      )}
      {!demo && (change || !boot.cronometer.connected) && (
        <div className="mt-3">
          <CronometerForm initialEmail={boot.cronometer.username} onDone={() => setChange(false)} />
        </div>
      )}
      {s && (
        <div className="mt-2 text-[12px] text-tx2">
          <div className="flex justify-between border-t border-ln py-2">
            <span className="text-mu">Ultima lettura</span>
            <span>{s.last_pull ? new Date(s.last_pull).toLocaleString("it-IT", { dateStyle: "short", timeStyle: "short" }) : "mai"}</span>
          </div>
          <div className="flex justify-between border-t border-ln py-2">
            <span className="text-mu">Scritture in attesa</span>
            <span>{n0(s.pending)}</span>
          </div>
          <div className="flex justify-between border-t border-ln py-2">
            <span className="text-mu">Scritture fallite</span>
            <span className={s.failed ? "text-er" : ""}>{n0(s.failed)}</span>
          </div>
          {s.last_error && <div className="mt-1 rounded-xl bg-er/10 px-3 py-2 text-[11.5px] text-er">{s.last_error}</div>}
          <p className="mt-2 text-[11px] text-mu">L'API di Cronometer non è ufficiale: se cambia, le letture si fermano e le scritture restano in coda finché non tornano a funzionare.</p>
        </div>
      )}
      <Button small className="mt-2" busy={run.isPending} onClick={() => run.mutate()}>
        <RefreshCw className="size-3.5" /> Sincronizza ora
      </Button>
    </Card>
  )
}
