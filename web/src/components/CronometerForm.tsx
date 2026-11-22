import { useMutation, useQueryClient } from "@tanstack/react-query"
import { useState } from "react"
import { put } from "../lib/api"
import { Button } from "./ui"

export default function CronometerForm({ initialEmail, onDone }: { initialEmail?: string | null; onDone?: () => void }) {
  const qc = useQueryClient()
  const [email, setEmail] = useState(initialEmail ?? "")
  const [password, setPassword] = useState("")
  const [totp, setTotp] = useState("")
  const [showTotp, setShowTotp] = useState(false)
  const save = useMutation({
    mutationFn: () => put("/api/cronometer", { username: email, password, totp: totp || null }),
    onSuccess: () => {
      setPassword("")
      qc.invalidateQueries()
      onDone?.()
    },
  })
  const field = "w-full rounded-xl border border-ln bg-s2 px-3 py-2.5 text-[14px] outline-none focus:border-ac/50"
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
      className="flex flex-col gap-2.5"
    >
      <input className={field} type="email" autoComplete="username" placeholder="Email di Cronometer" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input className={field} type="password" autoComplete="current-password" placeholder="Password di Cronometer" value={password} onChange={(e) => setPassword(e.target.value)} />
      {showTotp ? (
        <input className={field} placeholder="Chiave 2FA (base32)" value={totp} onChange={(e) => setTotp(e.target.value)} />
      ) : (
        <button type="button" onClick={() => setShowTotp(true)} className="self-start text-[11.5px] text-mu">
          Hai la verifica in due passaggi su Cronometer?
        </button>
      )}
      {save.error && <div className="text-[12px] text-er">{save.error instanceof Error ? save.error.message : String(save.error)}</div>}
      <Button kind="primary" type="submit" busy={save.isPending} disabled={!email || !password}>
        Collega
      </Button>
      <p className="text-[11px] leading-relaxed text-mu">
        Le credenziali restano sul server di EverFit, cifrate, e servono solo a leggere diario e pesate e a registrare i pasti che confermi. Cronometer non ha un'API ufficiale: si usa quella della sua app.
      </p>
    </form>
  )
}
