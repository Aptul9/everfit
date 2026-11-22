import clsx from "clsx"
import { Loader2, Minus, Plus, X } from "lucide-react"
import { type ReactNode, useEffect, useState } from "react"

export function Card({ className, children, onClick }: { className?: string; children: ReactNode; onClick?: () => void }) {
  return (
    <div
      onClick={onClick}
      className={clsx(
        "rounded-[22px] border border-ln bg-s1 p-4",
        onClick && "cursor-pointer transition-colors active:bg-s2",
        className,
      )}
    >
      {children}
    </div>
  )
}

type Tone = "neutral" | "ac" | "ok" | "wa" | "er" | "mi"
const TONES: Record<Tone, string> = {
  neutral: "bg-s2 text-tx border-ln",
  ac: "bg-ac/12 text-ac border-ac/25",
  ok: "bg-ok/12 text-ok border-ok/25",
  wa: "bg-wa/12 text-wa border-wa/25",
  er: "bg-er/12 text-er border-er/25",
  mi: "bg-mi/12 text-mi border-mi/25",
}

export function Chip({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-1 text-[11px] font-semibold",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}

type BtnKind = "primary" | "secondary" | "ghost" | "danger"
export function Button({
  kind = "secondary",
  children,
  onClick,
  disabled,
  busy,
  className,
  type = "button",
  small,
}: {
  kind?: BtnKind
  children: ReactNode
  onClick?: () => void
  disabled?: boolean
  busy?: boolean
  className?: string
  type?: "button" | "submit"
  small?: boolean
}) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || busy}
      className={clsx(
        "inline-flex select-none items-center justify-center gap-1.5 rounded-[14px] font-bold transition active:scale-[0.97] disabled:pointer-events-none disabled:opacity-40",
        small ? "px-3 py-2 text-[12px]" : "px-4 py-3 text-[13px]",
        kind === "primary" && "bg-ac text-bg",
        kind === "secondary" && "border border-ln bg-s2 text-tx",
        kind === "ghost" && "text-mu",
        kind === "danger" && "border border-er/30 bg-er/10 text-er",
        className,
      )}
    >
      {busy && <Loader2 className="size-4 animate-spin" />}
      {children}
    </button>
  )
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
}: {
  options: { value: T; label: ReactNode }[]
  value: T
  onChange: (v: T) => void
  className?: string
}) {
  return (
    <div className={clsx("flex gap-0.5 rounded-xl bg-s2 p-[3px]", className)} role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "flex-1 rounded-[9px] px-2 py-1.5 text-center text-[11.5px] font-semibold transition",
            o.value === value ? "bg-s3 text-tx" : "text-mu",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Sheet({
  open,
  onClose,
  title,
  children,
  footer,
}: {
  open: boolean
  onClose: () => void
  title?: ReactNode
  children: ReactNode
  footer?: ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose()
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center">
      <div className="absolute inset-0 animate-fade bg-black/60" onClick={onClose} />
      <div className="pb-safe relative flex max-h-[88dvh] w-full max-w-md animate-sheet flex-col rounded-t-[26px] border-t border-ln bg-[#14181e]">
        <div className="mx-auto mt-2.5 mb-1 h-1 w-10 rounded-full bg-[#39414c]" />
        {title && (
          <div className="flex items-center justify-between px-4 pt-1 pb-2">
            <div className="text-[15px] font-bold">{title}</div>
            <button onClick={onClose} className="grid size-8 place-items-center rounded-full text-mu active:bg-s2" aria-label="Chiudi">
              <X className="size-4" />
            </button>
          </div>
        )}
        <div className="overflow-y-auto px-4 pb-3">{children}</div>
        {footer && <div className="border-t border-ln px-4 pt-3">{footer}</div>}
      </div>
    </div>
  )
}

export function Stepper({
  value,
  step,
  onChange,
  label,
  min = 0,
}: {
  value: number
  step: number
  onChange: (v: number) => void
  label?: string
  min?: number
}) {
  return (
    <div className="flex items-center rounded-xl border border-ln bg-s2">
      <button
        className="grid h-9 w-8 place-items-center text-tx active:text-ac disabled:opacity-30"
        onClick={() => onChange(Math.max(min, value - step))}
        disabled={value - step < min}
        aria-label="Meno"
      >
        <Minus className="size-4" />
      </button>
      <span className="min-w-[54px] text-center text-[13px] font-bold">{label ?? `${Math.round(value)} g`}</span>
      <button className="grid h-9 w-8 place-items-center text-tx active:text-ac" onClick={() => onChange(value + step)} aria-label="Più">
        <Plus className="size-4" />
      </button>
    </div>
  )
}

export function Ring({ value, max, size = 128, stroke = 12, children }: { value: number; max: number; size?: number; stroke?: number; children?: ReactNode }) {
  const [shown, setShown] = useState(0)
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(Math.max(0, Math.min(1, max ? value / max : 0))))
    return () => cancelAnimationFrame(id)
  }, [value, max])
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const over = max > 0 && value > max
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <defs>
          <linearGradient id="ring-g" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#D4FA7C" />
            <stop offset="1" stopColor="#7BE3B0" />
          </linearGradient>
        </defs>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#1A1F26" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={over ? "#F7C052" : "url(#ring-g)"}
          strokeWidth={stroke}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          strokeDasharray={`${shown * c} ${c}`}
          opacity={shown > 0.005 ? 1 : 0}
          style={{ transition: "stroke-dasharray 1s cubic-bezier(.2,.8,.2,1)" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">{children}</div>
    </div>
  )
}

export function Bar({ parts, height = 8 }: { parts: { value: number; color: string }[]; height?: number }) {
  return (
    <div className="flex overflow-hidden rounded-full bg-s2" style={{ height }}>
      {parts.map((p, i) => (
        <i
          key={i}
          className="block h-full transition-[width] duration-700 ease-out"
          style={{ width: `${Math.max(0, Math.min(100, p.value))}%`, background: p.color }}
        />
      ))}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-mu">
      <Loader2 className="size-5 animate-spin" />
      {label && <span className="text-sm">{label}</span>}
    </div>
  )
}

export function ErrorBox({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <Card className="border-er/30">
      <div className="text-sm font-semibold text-er">Qualcosa non va</div>
      <div className="mt-1 text-[12.5px] text-tx2">{error instanceof Error ? error.message : String(error)}</div>
      {retry && (
        <Button small className="mt-3" onClick={retry}>
          Riprova
        </Button>
      )}
    </Card>
  )
}

export function Header({ eyebrow, title, right, onBack }: { eyebrow?: ReactNode; title: ReactNode; right?: ReactNode; onBack?: () => void }) {
  return (
    <div className="mb-3.5 flex items-end justify-between gap-2 px-0.5 pt-1.5">
      <div className="min-w-0">
        {onBack && (
          <button onClick={onBack} className="mb-1 text-[12px] text-mu active:text-tx">
            ‹ Indietro
          </button>
        )}
        {eyebrow && <div className="mb-0.5 text-[11px] font-medium uppercase tracking-[0.08em] text-mu">{eyebrow}</div>}
        <h1 className="truncate text-[26px] font-bold tracking-[-0.02em]">{title}</h1>
      </div>
      {right}
    </div>
  )
}

export function Dot({ color }: { color: string }) {
  return <i className="mr-1.5 inline-block size-2 rounded-full align-middle" style={{ background: color }} />
}

export const MACRO_COLORS = { protein: "#FF7A6B", carbs: "#F7C052", fat: "#A08FFF" }

export function Toast({ message, onDone }: { message: string | null; onDone: () => void }) {
  useEffect(() => {
    if (!message) return
    const t = setTimeout(onDone, 3200)
    return () => clearTimeout(t)
  }, [message, onDone])
  if (!message) return null
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-28 z-[60] flex justify-center px-6">
      <div className="animate-rise rounded-2xl border border-ln bg-s2/95 px-4 py-2.5 text-[13px] font-medium shadow-xl backdrop-blur">{message}</div>
    </div>
  )
}
