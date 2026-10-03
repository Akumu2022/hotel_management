/* Small shadcn-style primitives styled with the tokens in index.css (docs/UI.md section 1). */
import clsx from "clsx";
import { X } from "lucide-react";
import {
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  forwardRef,
  useEffect,
  useId,
} from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  variant = "primary",
  size = "md",
  busy,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: "sm" | "md" | "lg";
  busy?: boolean;
}) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || busy}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-xl font-semibold transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" && "h-9 px-3 text-sm",
        size === "md" && "h-11 px-4.5 text-sm",
        size === "lg" && "h-12 px-5 text-base",
        variant === "primary" && "bg-brand text-white shadow-md shadow-brand/20 hover:bg-brand-hover",
        variant === "secondary" && "border border-line bg-surface text-ink hover:bg-subtle",
        variant === "ghost" && "text-ink hover:bg-subtle",
        variant === "danger" && "border border-bad/30 bg-surface text-bad hover:bg-bad-soft",
        className,
      )}
    >
      {busy ? <span className="size-4 animate-spin rounded-full border-2 border-current border-t-transparent" /> : null}
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={clsx("rounded-2xl border border-line bg-surface", className)}>{children}</div>;
}

export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (id: string) => ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children(id)}
      {error ? (
        <p className="text-sm text-bad">{error}</p>
      ) : hint ? (
        <p className="text-sm text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

const inputClass =
  "h-12 w-full rounded-xl border border-line bg-surface px-3.5 text-[0.9375rem] outline-none placeholder:text-stone-400 focus:border-brand focus:ring-4 focus:ring-brand/10";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} {...rest} className={clsx(inputClass, className)} />;
  },
);

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...rest} className={clsx(inputClass, "h-auto min-h-20 py-2", className)} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={clsx(inputClass, className)}>
      {children}
    </select>
  );
}

/** Money input: whole shillings only. */
export function MoneyInput({
  value,
  onChange,
  ...rest
}: Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange"> & {
  value: number | "";
  onChange: (v: number | "") => void;
}) {
  return (
    <div className="relative">
      <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-sm text-muted">KES</span>
      <Input
        {...rest}
        inputMode="numeric"
        className="money pl-12"
        value={value}
        onChange={(e) => {
          const digits = e.target.value.replace(/\D/g, "");
          onChange(digits === "" ? "" : Math.min(Number(digits), 1_000_000));
        }}
      />
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={clsx(
        "relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:opacity-50",
        checked ? "bg-ok" : "bg-stone-300",
      )}
    >
      <span
        className={clsx(
          "inline-block size-5 rounded-full bg-white shadow transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}

type Tone = "ok" | "warn" | "bad" | "neutral" | "brand";

/** Status chips always carry text, never colour alone. */
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold",
        tone === "ok" && "bg-ok-soft text-ok",
        tone === "warn" && "bg-warn-soft text-warn",
        tone === "bad" && "bg-bad-soft text-bad",
        tone === "brand" && "bg-brand-soft text-brand",
        tone === "neutral" && "bg-page text-muted",
      )}
    >
      {children}
    </span>
  );
}

/** Side sheet on desktop, full-height bottom sheet on phones. */
export function Sheet({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        className="mt-auto flex max-h-[92dvh] w-full flex-col rounded-t-2xl bg-surface sm:mt-0 sm:h-full sm:max-h-none sm:max-w-lg sm:rounded-none"
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h2 className="text-lg font-semibold">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded-lg p-2 hover:bg-page">
            <X className="size-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-4">{children}</div>
        {footer ? <div className="border-t border-line p-4">{footer}</div> : null}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx("animate-pulse rounded-lg bg-line", className)} />;
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-card border border-dashed border-line bg-surface px-6 py-12 text-center">
      <p className="font-semibold">{title}</p>
      {body ? <p className="max-w-sm text-sm text-muted">{body}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : "Something went wrong";
  return <p className="rounded-lg bg-bad-soft px-3 py-2 text-sm text-bad">{msg}</p>;
}
