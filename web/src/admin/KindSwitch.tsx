/** Fees and delivery are set separately for food hotels and liquor stores. */
import clsx from "clsx";

export type Kind = "hotel" | "liquor";

export function KindSwitch({ kind, onChange }: { kind: Kind; onChange: (k: Kind) => void }) {
  return (
    <div role="tablist" aria-label="Settings for" className="grid w-full max-w-xs grid-cols-2 gap-1 rounded-xl bg-subtle p-1 text-sm font-semibold">
      {(
        [
          ["hotel", "Hotels"],
          ["liquor", "Liquor stores"],
        ] as const
      ).map(([k, label]) => (
        <button key={k} role="tab" aria-selected={kind === k} onClick={() => onChange(k)} className={clsx("h-9 rounded-lg", kind === k ? "bg-surface shadow-sm" : "text-muted")}>
          {label}
        </button>
      ))}
    </div>
  );
}
