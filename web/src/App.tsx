import { useQuery, useQueryClient } from "@tanstack/react-query"
import clsx from "clsx"
import { CalendarDays, House, ListChecks, Settings2, Sparkles, TrendingUp } from "lucide-react"
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
      <Shell wide>
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
      <Shell wide>
        <Sidebar />
        <main className="pt-safe px-4 pb-32 lg:pl-[calc(var(--sidebar)+2rem)] lg:pr-8 lg:pb-12 lg:pt-8">
          <div className="lg:mx-auto lg:max-w-5xl">
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
          </div>
        </main>
        <UpdateBanner />
        <TabBar />
        <Toast message={message} onDone={() => setMessage(null)} />
      </Shell>
    </AppCtx.Provider>
  )
}

function Shell({ children, wide }: { children: React.ReactNode; wide?: boolean }) {
  return <div className={clsx("relative mx-auto min-h-dvh w-full bg-bg", !wide && "max-w-md")}>{children}</div>
}

const SIDE = [
  { to: "/", label: "Oggi", icon: House },
  { to: "/storico", label: "Storico", icon: CalendarDays },
  { to: "/progressi", label: "Progressi", icon: TrendingUp },
  { to: "/piano", label: "Piano", icon: ListChecks },
  { to: "/impostazioni", label: "Impostazioni", icon: Settings2 },
]

function Sidebar() {
  const { boot } = useApp()
  return (
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-[var(--sidebar)] flex-col border-r border-ln bg-[#0c0f13] px-4 py-6 lg:flex">
      <div className="mb-8 flex items-center gap-3 px-2">
        <img src="/logo.svg" alt="" className="size-9 rounded-[11px]" />
        <div>
          <div className="text-[16px] font-bold tracking-[-0.01em]">EverFit</div>
          <div className="text-[11px] text-mu">{boot.phase?.name ?? "coach nutrizionale"}</div>
        </div>
      </div>
      <NavLink
        to="/coach"
        className={({ isActive }) =>
          clsx(
            "mb-4 flex items-center gap-2.5 rounded-2xl px-3.5 py-3 text-[13.5px] font-bold transition",
            isActive ? "bg-gradient-to-br from-ac2 to-mi text-bg" : "border border-ac/30 bg-ac/10 text-ac hover:bg-ac/15",
          )
        }
      >
        <Sparkles className="size-[18px]" /> Chiedi al coach
      </NavLink>
      <nav className="flex flex-col gap-1">
        {SIDE.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            end={t.to === "/"}
            className={({ isActive }) =>
              clsx(
                "flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-[13.5px] font-medium transition-colors",
                isActive ? "bg-s2 text-tx" : "text-mu hover:bg-s1 hover:text-tx",
              )
            }
          >
            <t.icon className="size-[18px]" strokeWidth={1.8} />
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto rounded-2xl border border-ln bg-s1 p-3.5 text-[11.5px] leading-relaxed text-mu">
        Diario su Cronometer{boot.cronometer.username ? ` · ${boot.cronometer.username}` : ""}. Metodo di Project Nutrition, conti fatti dal motore.
      </div>
    </aside>
  )
}

function TabBar() {
  const loc = useLocation()
  const nav = useNavigate()
  if (loc.pathname.startsWith("/coach") || loc.pathname.startsWith("/piano/modifica")) return null
  return (
    <nav className="pb-safe fixed inset-x-0 bottom-0 z-40 mx-auto max-w-md border-t border-ln bg-[#0e1115]/95 backdrop-blur-xl lg:hidden">
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
