import { Download, X } from "lucide-react"
import { useEffect, useState } from "react"

// The Android app opens /?apk=<versionCode>. Once a day the installed version is compared with the one published
// on servizi.everbright.it, which allows this origin in CORS for that JSON only.
const FEED = "https://servizi.everbright.it/download/EverFit-Android.json"
const APK = "https://servizi.everbright.it/download/EverFit-Android.apk"
const DAY = 86_400_000

export default function UpdateBanner() {
  const [latest, setLatest] = useState<string | null>(null)
  useEffect(() => {
    const param = new URLSearchParams(window.location.search).get("apk")
    if (param && /^\d+$/.test(param)) localStorage.setItem("apk", param)
    const installed = Number(localStorage.getItem("apk") ?? 0)
    if (!installed) return
    const dismissed = Number(localStorage.getItem("apk-dismissed") ?? 0)
    const checked = Number(localStorage.getItem("apk-checked") ?? 0)
    if (Date.now() - checked < DAY && !param) return
    localStorage.setItem("apk-checked", String(Date.now()))
    fetch(FEED, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((j: { versionCode?: number; version?: string } | null) => {
        if (j?.versionCode && j.versionCode > installed && j.versionCode !== dismissed) setLatest(`${j.version ?? ""} (${j.versionCode})`)
      })
      .catch(() => undefined)
  }, [])
  if (!latest) return null
  return (
    <div className="fixed inset-x-0 bottom-24 z-40 mx-auto max-w-md px-4">
      <div className="flex animate-rise items-center gap-3 rounded-2xl border border-ac/30 bg-s1/95 px-3.5 py-3 shadow-xl backdrop-blur">
        <Download className="size-5 shrink-0 text-ac" />
        <a href={APK} className="flex-1 text-[12.5px]">
          <b className="block">Nuova versione dell'app</b>
          <span className="text-mu">Tocca per scaricare la {latest}</span>
        </a>
        <button
          aria-label="Chiudi"
          className="grid size-8 place-items-center text-mu"
          onClick={() => {
            localStorage.setItem("apk-dismissed", latest.match(/\((\d+)\)/)?.[1] ?? "0")
            setLatest(null)
          }}
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  )
}
