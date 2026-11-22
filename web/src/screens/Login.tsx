import { Button } from "../components/ui"

export default function Login({ mode }: { mode: string }) {
  const next = window.location.pathname + window.location.search
  return (
    <div className="pt-safe flex min-h-dvh flex-col justify-center px-6">
      <img src="/icon-192.png" alt="" className="mb-5 size-14 rounded-[18px]" />
      <h1 className="text-[26px] font-bold tracking-[-0.02em]">EverFit</h1>
      {mode === "oidc" ? (
        <>
          <p className="mt-1 mb-6 text-[13px] text-mu">Il tuo coach nutrizionale. Si entra con l'account Everbright.</p>
          <Button kind="primary" onClick={() => window.location.assign(`/oidc/login?next=${encodeURIComponent(next)}`)}>
            Accedi con EverID
          </Button>
        </>
      ) : (
        <p className="mt-2 rounded-2xl border border-er/30 bg-er/10 p-3.5 text-[13px] text-tx2">
          L'accesso con EverID non è configurato su questo server: nessun dato viene mostrato finché non lo è.
        </p>
      )}
    </div>
  )
}
