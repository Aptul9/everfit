import { useQuery } from "@tanstack/react-query"
import { Loader2, Search } from "lucide-react"
import { useEffect, useState } from "react"
import { api, post, type FoodHit, type Macros } from "../lib/api"
import { n0 } from "../lib/format"

export type PickedFood = { id: string; name: string; per100: Macros; unit_g: number | null; unit_name: string | null }

type FoodRow = { id: string; name: string; kcal: number; protein: number; carbs: number; fat: number; unit_g: number | null; unit_name: string | null }

const toPicked = (r: FoodRow): PickedFood => ({
  id: r.id,
  name: r.name,
  per100: { kcal: r.kcal, protein: r.protein, carbs: r.carbs, fat: r.fat },
  unit_g: r.unit_g,
  unit_name: r.unit_name,
})

export default function FoodPicker({ onPick, autoFocus = true }: { onPick: (f: PickedFood) => void; autoFocus?: boolean }) {
  const [q, setQ] = useState("")
  const [debounced, setDebounced] = useState("")
  const [importing, setImporting] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 300)
    return () => clearTimeout(t)
  }, [q])
  const res = useQuery({
    queryKey: ["food-search", debounced],
    queryFn: () => api<FoodHit[]>(`/api/foods/search?q=${encodeURIComponent(debounced)}`),
    enabled: debounced.length >= 2,
  })

  const pick = async (h: FoodHit) => {
    setError(null)
    if (h.local && h.id) {
      onPick({ id: h.id, name: h.name, per100: { kcal: h.kcal ?? 0, protein: h.protein ?? 0, carbs: h.carbs ?? 0, fat: h.fat ?? 0 }, unit_g: h.unit_g ?? null, unit_name: h.unit_name ?? null })
      return
    }
    if (!h.cr_food_id) return
    setImporting(String(h.cr_food_id))
    try {
      const row = await post<FoodRow>("/api/foods/import", { cr_food_id: h.cr_food_id })
      onPick(toPicked(row))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setImporting(null)
    }
  }

  return (
    <div>
      <label className="flex items-center gap-2 rounded-2xl border border-ln bg-s1 px-3 py-2.5">
        <Search className="size-4 text-mu" />
        <input
          autoFocus={autoFocus}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Cerca tra i tuoi alimenti e su Cronometer"
          className="w-full bg-transparent text-[14px] outline-none placeholder:text-mu"
        />
        {res.isFetching && <Loader2 className="size-4 animate-spin text-mu" />}
      </label>
      {error && <div className="mt-2 text-[12px] text-er">{error}</div>}
      <div className="mt-2 max-h-[46dvh] overflow-y-auto">
        {(res.data ?? []).map((h, i) => (
          <button
            key={`${h.id ?? h.cr_food_id}-${i}`}
            onClick={() => pick(h)}
            className="flex w-full items-center gap-3 border-t border-ln py-2.5 text-left first:border-t-0 active:bg-s2"
          >
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-semibold">{h.name}</div>
              <div className="text-[11px] text-mu">
                {h.local ? `già usato · ${n0(h.kcal)} kcal/100 g` : `Cronometer${h.source ? ` · ${h.source}` : ""}`}
              </div>
            </div>
            {importing === String(h.cr_food_id) ? <Loader2 className="size-4 animate-spin text-mu" /> : <span className="text-[12px] font-semibold text-ac">Scegli</span>}
          </button>
        ))}
        {debounced.length >= 2 && res.data?.length === 0 && <div className="py-6 text-center text-[13px] text-mu">Nessun risultato</div>}
      </div>
    </div>
  )
}

export function macrosFor(per100: Macros, grams: number): Macros {
  const k = grams / 100
  return { kcal: per100.kcal * k, protein: per100.protein * k, carbs: per100.carbs * k, fat: per100.fat * k }
}

export function stepFor(per100: Macros, unitG: number | null, role?: string) {
  if (unitG) return unitG >= 100 ? unitG / 2 : unitG
  if (per100.kcal >= 500) return 5
  if (role === "veg" || per100.kcal < 45) return 50
  if (per100.kcal >= 150) return 10
  return 25
}
