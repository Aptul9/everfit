export type Macros = { kcal: number; protein: number; carbs: number; fat: number }

export type Flag = { code: string; severity: "info" | "warning" | "stop"; message: string; source: string }

export type PlanItem = {
  food_id: string
  grams: number
  planned_grams: number | null
  planned_food_id: string | null
  planned_food_name?: string | null
  locked: boolean
  name: string
  role: string
  step: number
  unit_g: number | null
  unit_name: string | null
  macros: Macros
  per100: Macros
}

export type MealStatus = "planned" | "confirmed" | "modified" | "skipped" | "logged"

export type Meal = {
  slot: string
  label: string
  status: MealStatus
  locked: boolean
  items: PlanItem[]
  macros: Macros
}

export type FitReport = {
  totals: Macros
  target: Macros
  within_tolerance: boolean
  changes: { slot: string; food: string; from: number; to: number }[]
  notes: string[]
}

export type Plan = {
  day: string
  source: string
  kind: string
  target: Macros
  meals: Meal[]
  report: FitReport
}

export type Phase = {
  template_id: string
  name: string
  kind: "deficit" | "maintenance" | "surplus" | "reverse"
  modified: boolean
  start: string
  duration_weeks: number | null
  rate_kg_week: number
  band_kg_week: [number, number]
  protein_g_per_kg: number
  fat_g_per_kg: number
  refeed_days_per_week: number
  refeed_weekday: number
  adjust_macro: "carbs" | "fat" | "mixed"
  reverse_step_kcal: number
  kcal_target: number | null
}

export type PhaseTemplate = {
  id: string
  name: string
  description: string
  source: string
  builtin: boolean
  kind: Phase["kind"]
  rate_pct_week: number
  band_pct_week: number
  protein_g_per_kg: number
  fat_g_per_kg: number
  refeed_days_per_week: number
  duration_weeks: number | null
  adjust_macro: Phase["adjust_macro"]
}

export type Suggestion = { title: string; items: { food_id: string; grams: number }[]; macros: Macros; tag: string }

/** A food in a meal of the day: eaten (in the diary, `ref` s:/e:) or planned (`ref` p:). */
export type DayItem = {
  ref: string
  state: "eaten" | "planned" | "skipped"
  pending: boolean
  food_id: string
  grams: number
  planned_grams?: number | null
  name: string
  role: string
  step: number
  unit_g: number | null
  unit_name: string | null
  macros: Macros
  per100: Macros
}

export type DayMeal = {
  slot: string
  label: string
  status: "empty" | "planned" | "partial" | "eaten" | "skipped"
  skipped: boolean
  locked: boolean
  items: DayItem[]
  macros: Macros
  eaten: Macros
  planned: Macros
  count_eaten: number
  count: number
}

export type Today = {
  day: string
  phase: Phase | null
  targets: { day: string; kind: "normal" | "refeed"; macros: Macros; weekly_mean_kcal: number; flags: Flag[] } | null
  target_loggable: Macros | null
  consumed: Macros
  planned_remaining: Macros
  remaining: Macros | null
  plan: { day: string; source: string; kind: string; target: Macros | null; report: FitReport | null }
  meals: DayMeal[]
  complete: boolean
  expenditure: { kcal: number; sd: number; status: "prior" | "data" }
  weight: { trend: number | null; rate_kg_week: number | null; spark: number[] }
  suggestions: Suggestion[]
  checkin: { week_end: string; verdict: string; headline: string; has_proposal: boolean } | null
}

export type Progress = {
  weights: { day: string; weight: number | null; trend: number | null }[]
  trend: number | null
  rate: { kg_per_week: number; se: number; weighins: number } | null
  band: [number, number] | null
  projection: { cone: { week: number; center: number; low: number; high: number }[]; eta_weeks: number | null } | null
  goal: number | null
  expenditure: {
    kcal: number
    sd: number
    status: "prior" | "data"
    complete_days: number
    weighins: number
    prior: number
    prior_sd: number
    formulas: { name: string; low: number; high: number; source: string }[]
  } | null
  expenditure_series: { day: string; kcal: number | null; sd: number | null; intake: number | null; complete: boolean }[]
  weeks: { start: string; end: string; intake: number | null; expenditure: number | null }[]
  excluded: { day: string; kcal: number }[]
  weighins: number
}

export type HistoryDay = {
  day: string
  kcal: number
  macros: { protein: number; carbs: number; fat: number } | null
  target: number | null
  complete: boolean
  marked: boolean | null
  future: boolean
  meals: { slot: string; label: string; kcal: number; items: { food_id: string; name: string; grams: number; macros: Macros }[] }[]
}

export type TemplateInfo = {
  key: string
  slot: string
  name: string
  count: number
  last_seen: string
  pin: "fixed" | "use" | "hidden" | null
  items: { food_id: string; name: string; grams: number; range: [number, number] | null }[]
}

export type History = { week_start: string; days: HistoryDay[]; templates: TemplateInfo[] }

export type Reason = { text: string; ref: string }

export type Checkin = {
  week_start: string
  week_end: string
  too_early?: boolean
  first?: string
  weighins: number
  complete_days: number
  mean_intake: number | null
  adherence: number | null
  rate_kg_week: number | null
  rate_se: number | null
  expenditure: number
  expenditure_sd: number
  verdict: string
  headline: string
  proposal: {
    kcal_from: number
    kcal_to: number
    delta: number
    macros_from: Macros
    macros_to: Macros
    phase_changes: Record<string, number>
  } | null
  reasons: Reason[]
  flags: Flag[]
  decision: "accept" | "modify" | "reject" | null
  decided_kcal: number | null
  phase: Phase
}

export type CheckinPreview = {
  kcal_from: number
  kcal_to: number
  cap: number
  macros_from: Macros
  macros_to: Macros
  projected_rate: number | null
  in_band: boolean | null
}

export type WeekPreview = {
  start: string
  variety: string
  days: { day: string; kind: string; source: string; meals: Meal[]; report: FitReport }[]
  diff: { slot: string; food: string; from: number; to: number; role: string }[]
  same: { slot: string; food: string; role: string }[]
}

export type Bootstrap = {
  settings: Settings
  phase: Phase | null
  today: string
  source: string
  demo: boolean
  sync: SyncStatus
  agent: boolean
  needs_profile: boolean
  has_weights: boolean
  cronometer: { connected: boolean; username: string | null; demo: boolean }
}

export type SyncStatus = {
  source: string
  pending: number
  failed: number
  last_pull?: string
  last_error?: string | null
  last_error_at?: string
}

export type Settings = {
  profile: {
    sex: "M" | "F"
    birth_date: string | null
    height_cm: number | null
    activity: "sedentario" | "moderato" | "intenso"
    goal_weight_kg: number | null
  }
  engine: Record<string, number>
  guardrails: Record<string, number>
}

export type JsonSchema = {
  $defs: Record<string, { properties: Record<string, { description?: string; source?: string; minimum?: number; maximum?: number; exclusiveMinimum?: number; default?: unknown; title?: string }> }>
}

export type FoodHit = {
  id?: string
  cr_food_id?: number | null
  name: string
  source?: string
  measure?: string
  kcal?: number
  protein?: number
  carbs?: number
  fat?: number
  unit_g?: number | null
  unit_name?: string | null
  local?: boolean
}

export type Alternative = { food_id: string; name: string; grams: number; macros: Macros; frequent: boolean }

export type ProposalCard = {
  proposal_id: number
  kind: "log" | "phase" | "plan"
  summary: string
  status?: string
  day?: string
  slot?: string
  items?: { food_id: string; name: string; grams: number; kcal: number; protein: number }[]
  total?: Macros
  meals?: { slot: string; kcal: number; items: { name: string; grams: number }[] }[]
  template_id?: string | null
  changes?: Record<string, unknown>
  current?: Phase | null
}

/** What a coach action changed on a day, food by food, with the id to undo it. */
export type ActionReceipt = {
  action_id: number
  status: "done" | "undone"
  day: string
  title: string
  changes: {
    slot: string
    kind: "add" | "remove" | "grams" | "eaten" | "skipped" | "planned"
    state: "eaten" | "planned" | "skipped"
    name: string
    grams: number
    from: number | null
  }[]
}

export type ChatEntry =
  | { role: "user"; text: string; at?: string }
  | { role: "assistant"; text: string; tools?: string[]; at?: string }
  | { role: "proposal"; proposal: ProposalCard }
  | { role: "action"; action: ActionReceipt }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const headers: Record<string, string> = {}
  let body = init?.body
  if (init?.json !== undefined) {
    headers["content-type"] = "application/json"
    body = JSON.stringify(init.json)
  }
  const res = await fetch(path, { ...init, body, headers: { ...headers, ...(init?.headers as Record<string, string>) }, credentials: "same-origin" })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const j = await res.json()
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j)
    } catch {
      /* not json */
    }
    if (res.status === 401) window.dispatchEvent(new Event("nutri:unauthorized"))
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

export const post = <T,>(path: string, json?: unknown) => api<T>(path, { method: "POST", json: json ?? {} })
export const put = <T,>(path: string, json: unknown) => api<T>(path, { method: "PUT", json })
export const patch = <T,>(path: string, json: unknown) => api<T>(path, { method: "PATCH", json })
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" })
