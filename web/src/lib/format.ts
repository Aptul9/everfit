const nf0 = new Intl.NumberFormat("it-IT", { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat("it-IT", { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat("it-IT", { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const n0 = (v: number | null | undefined) => (v == null ? "–" : nf0.format(Math.round(v)))
export const n1 = (v: number | null | undefined) => (v == null ? "–" : nf1.format(v))
export const n2 = (v: number | null | undefined) => (v == null ? "–" : nf2.format(v))

export const signed = (v: number, digits = 0) => {
  const s = digits === 2 ? nf2.format(Math.abs(v)) : digits === 1 ? nf1.format(Math.abs(v)) : nf0.format(Math.abs(Math.round(v)))
  return (v > 0 ? "+" : v < 0 ? "−" : "±") + s
}

export const rate = (v: number | null | undefined) => (v == null ? "–" : `${signed(v, 2)} kg/sett`)

export const parseDay = (s: string) => {
  const [y, m, d] = s.split("-").map(Number)
  return new Date(y, m - 1, d)
}

export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`

export const addDays = (s: string, n: number) => {
  const d = parseDay(s)
  d.setDate(d.getDate() + n)
  return iso(d)
}

const dayFmt = new Intl.DateTimeFormat("it-IT", { weekday: "long", day: "numeric", month: "short" })
const shortFmt = new Intl.DateTimeFormat("it-IT", { day: "numeric", month: "short" })
const wdFmt = new Intl.DateTimeFormat("it-IT", { weekday: "short" })

export const longDay = (s: string) => dayFmt.format(parseDay(s))
export const shortDay = (s: string) => shortFmt.format(parseDay(s))
export const weekday = (s: string) => wdFmt.format(parseDay(s)).replace(".", "")

export const range = (a: string, b: string) => `${parseDay(a).getDate()} – ${shortDay(b)}`

export const grams = (g: number, unitG?: number | null, unitName?: string | null) => {
  if (unitG && unitName && unitName !== "porzione") {
    const units = g / unitG
    if (Math.abs(units - Math.round(units)) < 0.01 && units >= 1) {
      const u = Math.round(units)
      return `${u} ${u === 1 ? unitName : pluralIt(unitName)} · ${n0(g)} g`
    }
  }
  if (unitName === "porzione") return `${n1(g / 100)} porz.`
  return `${n0(g)} g`
}

function pluralIt(w: string) {
  if (w.endsWith("o")) return w.slice(0, -1) + "i"
  if (w.endsWith("a")) return w.slice(0, -1) + "e"
  if (w.endsWith("e")) return w.slice(0, -1) + "i"
  return w
}

export const SLOT_LABEL: Record<string, string> = {
  colazione: "Colazione",
  pranzo: "Pranzo",
  spuntino: "Spuntino",
  cena: "Cena",
}
