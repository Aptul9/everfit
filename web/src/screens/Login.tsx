import { CalendarCheck, Flame, Sparkles, TrendingDown } from "lucide-react"
import { useState } from "react"
import { Button } from "../components/ui"
import { post } from "../lib/api"

const FEATURES = [
  { icon: TrendingDown, title: "Il tuo metabolismo, misurato", text: "Dal trend del peso e dal diario, non da una formula." },
  { icon: CalendarCheck, title: "La giornata già compilata", text: "I pasti di sempre nelle porzioni giuste: confermi e basta." },
  { icon: Flame, title: "Check-in ogni settimana", text: "Il piano si corregge da solo, tu approvi." },
  { icon: Sparkles, title: "Un coach in chat", text: "Cosa mangio stasera, perché il peso è fermo, cosa dice il libro." },
]

export default function Login({ mode, onDone }: { mode: string; onDone: () => void }) {
  const [user, setUser] = useState("")
  const [pw, setPw] = useState("")
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const field =
    "w-full rounded-2xl border border-ln bg-bg/60 px-4 py-3.5 text-[15px] outline-none transition placeholder:text-mu focus:border-ac/60 focus:bg-bg"

  return (
    <div className="relative min-h-dvh overflow-hidden">
      <div aria-hidden className="pointer-events-none absolute -top-40 -left-32 size-[520px] rounded-full bg-ac/15 blur-[120px]" />
      <div aria-hidden className="pointer-events-none absolute -right-40 bottom-[-180px] size-[560px] rounded-full bg-mi/12 blur-[130px]" />

      <div className="pt-safe relative mx-auto flex min-h-dvh max-w-6xl flex-col px-6 pb-10 lg:flex-row lg:items-center lg:gap-16 lg:px-12">
        <section className="pt-10 lg:flex-1 lg:pt-0">
          <div className="flex items-center gap-3">
            <img src="/logo.svg" alt="" className="size-12 rounded-[15px] shadow-[0_12px_40px_rgba(184,243,90,.25)]" />
            <span className="text-[22px] font-bold tracking-[-0.02em]">EverFit</span>
          </div>
          <h1 className="mt-8 max-w-xl text-[34px] leading-[1.08] font-bold tracking-[-0.03em] lg:text-[52px]">
            Mangia secondo <span className="bg-gradient-to-r from-ac2 to-mi bg-clip-text text-transparent">i tuoi numeri</span>,
            non secondo una tabella.
          </h1>
          <p className="mt-4 max-w-lg text-[14.5px] leading-relaxed text-tx2 lg:text-[16px]">
            Il diario resta su Cronometer. EverFit lo legge, capisce quanto consumi davvero e ti prepara la giornata con il
            metodo di Project Nutrition.
          </p>
          <ul className="mt-8 hidden gap-3 sm:grid sm:grid-cols-2 lg:max-w-xl">
            {FEATURES.map((f) => (
              <li key={f.title} className="rounded-2xl border border-ln bg-s1/70 p-4 backdrop-blur">
                <f.icon className="mb-2.5 size-5 text-ac" strokeWidth={1.9} />
                <b className="block text-[13.5px]">{f.title}</b>
                <span className="text-[12.5px] leading-snug text-mu">{f.text}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="mt-10 w-full lg:mt-0 lg:w-[420px] lg:shrink-0">
          <div className="rounded-[28px] border border-ln bg-s1/85 p-6 shadow-[0_30px_80px_rgba(0,0,0,.45)] backdrop-blur-xl lg:p-8">
            {mode === "oidc" ? (
              <form
                onSubmit={async (e) => {
                  e.preventDefault()
                  setBusy(true)
                  setErr(null)
                  try {
                    await post("/api/auth/login", { username: user, password: pw })
                    onDone()
                  } catch (e) {
                    setErr(e instanceof Error ? e.message : String(e))
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                <h2 className="text-[20px] font-bold tracking-[-0.01em]">Bentornato</h2>
                <p className="mt-1 mb-6 text-[13px] text-mu">Entra con il tuo account Everbright.</p>
                <div className="flex flex-col gap-3">
                  <input className={field} autoComplete="username" autoCapitalize="none" placeholder="Nome utente o email" value={user} onChange={(e) => setUser(e.target.value)} />
                  <input className={field} type="password" autoComplete="current-password" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
                </div>
                {err && <div className="mt-3 rounded-xl border border-er/30 bg-er/10 px-3 py-2 text-[12.5px] text-er">{err}</div>}
                <Button kind="primary" type="submit" className="mt-5 w-full !py-3.5 !text-[14px]" busy={busy} disabled={!user || !pw}>
                  Entra
                </Button>
              </form>
            ) : (
              <p className="rounded-2xl border border-er/30 bg-er/10 p-3.5 text-[13px] text-tx2">
                L'accesso non è configurato su questo server: nessun dato viene mostrato finché non lo è.
              </p>
            )}
          </div>
          <p className="mt-4 text-center text-[11.5px] text-mu">Un solo account per tutti i servizi Everbright.</p>
        </section>
      </div>
    </div>
  )
}
