import { useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { CalendarDays, House, ListChecks, Sparkles, TrendingUp } from "lucide-react"
import { createContext, useCallback, useContext, useEffect, useState } from "react"
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router"
import { Spinner, Toast } from "./components/ui"
import UpdateBanner from "./components/UpdateBanner"
import { api, type Bootstrap } from "./lib/api"
import Checkin from "./screens/Checkin"
import Coach from "./screens/Coach"
import History from "./screens/History"
import Login from "./screens/Login"
import Onboarding from "./screens/Onboarding"
import Plan from "./screens/Plan"
import PlanEditor from "./screens/PlanEditor"
import Progress from "./screens/Progress"
import Settings from "./screens/Settings"
import Today from "./screens/Today"

type Ctx = { boot: Bootstrap; toast: (m: string) => void }
const AppCtx = createContext<Ctx | null>(null)
export const useApp = () => useContext(AppCtx)!

const TABS = [
  { to: "/", label: "Oggi", icon: House },
  { to: "/storico", label: "Storico", icon: CalendarDays },
  { to: "/coach", label: "Coach", icon: Sparkles, fab: true },
  { to: "/progressi", label: "Progressi", icon: TrendingUp },
  { to: "/piano", label: "Piano", icon: ListChecks },
]

export default function App() {
  const qc = useQueryClient()
  const [unauth, setUnauth] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const toast = useCallback((m: string) => setMessage(m), [])
  const auth = useQuery({ queryKey: ["auth"], queryFn: () => api<{ mode: string; ok: boolean }>("/api/auth") })
  const boot = useQuery({
    queryKey: ["bootstrap"],
    queryFn: () => api<Bootstrap>("/api/bootstrap"),
    enabled: !!auth.data?.ok,
  })

  useEffect(() => {
    const on = () => setUnauth(true)
    window.addEventListener("nutri:unauthorized", on)
    return () => window.removeEventListener("nutri:unauthorized", on)
  }, [])

  if (auth.isLoading) return <Shell><Spinner /></Shell>
  if (unauth || (auth.data && !auth.data.ok)) {
    return (
      <Shell>
        <Login mode={auth.data?.mode ?? "oidc"} onDone={() => { setUnauth(false); auth.refetch(); qc.invalidateQueries() }} />
      </Shell>
    )
  }
  if (!boot.data) return <Shell>{boot.error ? <div className="p-6 text-er">{String(boot.error)}</div> : <Spinner />}</Shell>
  if (!boot.data.cronometer.connected || boot.data.needs_profile || !boot.data.phase) {
    return (
      <Shell>
        <AppCtx.Provider value={{ boot: boot.data, toast }}>
          <Onboarding />
          <Toast message={message} onDone={() => setMessage(null)} />
        </AppCtx.Provider>
      </Shell>
    )
  }
  return (
    <AppCtx.Provider value={{ boot: boot.data, toast }}>
      <Shell>
        <main className="pt-safe px-4 pb-32">
          <Routes>
            <Route path="/" element={<Today />} />
            <Route path="/storico" element={<History />} />
            <Route path="/progressi" element={<Progress />} />
            <Route path="/piano" element={<Plan />} />
            <Route path="/piano/modifica/:day" element={<PlanEditor />} />
            <Route path="/checkin" element={<Checkin />} />
            <Route path="/coach" element={<Coach />} />
            <Route path="/impostazioni" element={<Settings />} />
            <Route path="*" element={<Today />} />
          </Routes>
        </main>
        <UpdateBanner />
        <TabBar />
        <Toast message={message} onDone={() => setMessage(null)} />
      </Shell>
    </AppCtx.Provider>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="relative mx-auto min-h-dvh w-full max-w-md bg-bg">{children}</div>
}

function TabBar() {
  const loc = useLocation()
  const nav = useNavigate()
  if (loc.pathname.startsWith("/coach") || loc.pathname.startsWith("/piano/modifica")) return null
  return (
    <nav className="pb-safe fixed inset-x-0 bottom-0 z-40 mx-auto max-w-md border-t border-ln bg-[#0e1115]/95 backdrop-blur-xl">
      <div className="flex items-start justify-around px-1.5 pt-2">
        {TABS.map((t) =>
          t.fab ? (
            <button
              key={t.to}
              onClick={() => nav(t.to)}
              aria-label="Coach AI"
              className="-mt-6 grid size-[54px] place-items-center rounded-[19px] bg-gradient-to-br from-ac2 to-mi text-bg shadow-[0_10px_26px_rgba(150,240,120,.35)] transition active:scale-95"
            >
              <t.icon className="size-6" strokeWidth={2} />
            </button>
          ) : (
            <NavLink
              key={t.to}
              to={t.to}
              end={t.to === "/"}
              className={({ isActive }) =>
                clsx("flex w-[60px] flex-col items-center gap-1 text-[10px] transition-colors", isActive ? "text-ac" : "text-mu")
              }
            >
              <t.icon className="size-[22px]" strokeWidth={1.8} />
              {t.label}
            </NavLink>
          ),
        )}
      </div>
    </nav>
  )
}
