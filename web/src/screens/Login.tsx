import { useState } from "react"
import { Button } from "../components/ui"
import { post } from "../lib/api"

export default function Login({ mode, onDone }: { mode: string; onDone: () => void }) {
  const [user, setUser] = useState("")
  const [pw, setPw] = useState("")
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const next = window.location.pathname + window.location.search
  const field = "rounded-2xl border border-ln bg-s1 px-4 py-3 text-[15px] outline-none focus:border-ac/50"
  if (mode !== "oidc") {
    return (
      <div className="pt-safe flex min-h-dvh flex-col justify-center px-6">
        <img src="/icon-192.png" alt="" className="mb-5 size-14 rounded-[18px]" />
        <h1 className="text-[26px] font-bold tracking-[-0.02em]">EverFit</h1>
        <p className="mt-2 rounded-2xl border border-er/30 bg-er/10 p-3.5 text-[13px] text-tx2">
          L'accesso non è configurato su questo server: nessun dato viene mostrato finché non lo è.
        </p>
      </div>
    )
  }
  return (
    <form
      className="pt-safe flex min-h-dvh flex-col justify-center px-6"
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
      <img src="/icon-192.png" alt="" className="mb-5 size-14 rounded-[18px]" />
      <h1 className="text-[26px] font-bold tracking-[-0.02em]">EverFit</h1>
      <p className="mt-1 mb-6 text-[13px] text-mu">Accedi con il tuo account Everbright.</p>
      <div className="flex flex-col gap-2.5">
        <input className={field} autoComplete="username" autoCapitalize="none" placeholder="Nome utente o email" value={user} onChange={(e) => setUser(e.target.value)} />
        <input className={field} type="password" autoComplete="current-password" placeholder="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
      </div>
      {err && <div className="mt-2 text-[12.5px] text-er">{err}</div>}
      <Button kind="primary" type="submit" className="mt-4" busy={busy} disabled={!user || !pw}>
        Entra
      </Button>
      <a href={`/oidc/login?next=${encodeURIComponent(next)}`} className="mt-4 text-center text-[12px] text-mu">
        Altre opzioni di accesso
      </a>
    </form>
  )
}
