/** Small shared customer pieces: toast, confirm dialog, delivery/pickup picker, category icons. */
import clsx from "clsx";
import { CheckCircle2, Gift, ShieldCheck, Truck } from "lucide-react";
import { type ReactNode, useEffect, useState, useSyncExternalStore } from "react";

import { money } from "../lib/format";
import { useT } from "../lib/i18n";
import { orderMode, useOrderMode } from "./store";
import type { Quote } from "./types";

/** "Checked by Chakula": the team has met the hotel and confirmed the Till is theirs. */
export function VerifiedBadge({ className }: { className?: string }) {
  const t = useT();
  return (
    <span title={t("The Chakula team has checked this hotel and its M-Pesa Till.")} className={clsx("inline-flex items-center gap-1 rounded-full bg-ok-soft px-2.5 py-1 text-xs font-semibold whitespace-nowrap text-ok", className)}>
      <ShieldCheck className="size-3.5" /> {t("Checked by Chakula")}
    </span>
  );
}

// --- Toast --------------------------------------------------------------------------------------

let toastState: { id: number; text: string } | null = null;
const toastListeners = new Set<() => void>();
let toastTimer: ReturnType<typeof setTimeout> | undefined;

export function toast(text: string) {
  toastState = { id: Date.now(), text };
  toastListeners.forEach((fn) => fn());
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastState = null;
    toastListeners.forEach((fn) => fn());
  }, 2200);
}

export function Toaster() {
  const t = useSyncExternalStore(
    (fn) => (toastListeners.add(fn), () => toastListeners.delete(fn)),
    () => toastState,
  );
  return (
    <div className="pointer-events-none fixed inset-x-0 top-4 z-[70] flex justify-center px-4" aria-live="polite">
      {t ? (
        <div key={t.id} className="flex animate-[toast-in_.25s_ease-out] items-center gap-2.5 rounded-full bg-ink py-2.5 pr-5 pl-3 text-sm font-medium text-white shadow-xl">
          <CheckCircle2 className="size-5 text-green-400" />
          {t.text}
        </div>
      ) : null}
    </div>
  );
}

// --- Confirm dialog -----------------------------------------------------------------------------

export function ConfirmDialog({
  open,
  emoji,
  title,
  body,
  confirm,
  cancel = "Keep it",
  danger,
  onConfirm,
  onClose,
}: {
  open: boolean;
  emoji?: string;
  title: string;
  body?: ReactNode;
  confirm: string;
  cancel?: string;
  danger?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[65] flex items-end justify-center bg-black/50 p-4 backdrop-blur-[2px] sm:items-center" onClick={onClose}>
      <div role="alertdialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()} className="w-full max-w-sm animate-[pop-in_.2s_ease-out] rounded-3xl bg-surface p-6 text-center shadow-2xl">
        {emoji ? <div className="mx-auto mb-3 flex size-16 items-center justify-center rounded-full bg-brand-soft text-3xl">{emoji}</div> : null}
        <h2 className="text-lg font-bold">{title}</h2>
        {body ? <div className="mt-1.5 text-sm text-muted">{body}</div> : null}
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row">
          <button onClick={onClose} className="h-12 flex-1 rounded-xl border border-line font-semibold hover:bg-subtle">{cancel}</button>
          <button
            onClick={() => {
              onConfirm();
              onClose();
            }}
            className={clsx("h-12 flex-1 rounded-xl font-semibold text-white", danger ? "bg-bad hover:bg-red-700" : "bg-brand hover:bg-brand-hover")}
          >
            {confirm}
          </button>
        </div>
      </div>
    </div>
  );
}

// --- "How do you want your food?" ---------------------------------------------------------------

export function ModePicker({
  riderFee,
  feeIsFrom = true,
  hotelName,
  deliveryAvailable = true,
  compact,
}: {
  riderFee?: number;
  feeIsFrom?: boolean; // the fee depends on distance until a pin is dropped
  hotelName?: string | null;
  deliveryAvailable?: boolean;
  compact?: boolean;
}) {
  const t = useT();
  const mode = useOrderMode();
  const options = [
    {
      value: "delivery" as const,
      emoji: "🛵",
      title: t("Deliver to me"),
      body: deliveryAvailable
        ? riderFee
          ? `${t("A rider brings it")} · ${feeIsFrom ? t("from") + " " : "+"}${money(riderFee)}`
          : t("A rider brings it")
        : t("Not available yet"),
      disabled: !deliveryAvailable,
    },
    {
      value: "pickup" as const,
      emoji: "🏪",
      title: t("I'll pick it up"),
      body: hotelName ? t("Collect at {hotel} · no fee", { hotel: hotelName }) : t("Collect it yourself · no fee"),
      disabled: false,
    },
    {
      // Order ahead, pay first, the food is ready when you sit down.
      value: "eat_in" as const,
      emoji: "🍽️",
      title: t("Eat in"),
      body: t("Order ahead, eat there"),
      disabled: false,
    },
  ];
  return (
    <div className={clsx("grid gap-2.5", compact ? "grid-cols-3" : "grid-cols-2 sm:grid-cols-3")} role="radiogroup" aria-label={t("How do you want your food?")}>
      {options.map((o) => {
        const active = mode === o.value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            disabled={o.disabled}
            onClick={() => orderMode.set(o.value)}
            className={clsx(
              "relative flex flex-col items-start rounded-2xl border-2 text-left transition-all",
              compact ? "gap-1 p-3" : "gap-1.5 p-4",
              active ? "border-brand bg-brand-soft shadow-sm" : "border-line bg-surface hover:border-stone-300",
              o.disabled && "cursor-not-allowed opacity-45",
            )}
          >
            <span className={clsx("absolute top-3 right-3 flex size-5 items-center justify-center rounded-full border-2", active ? "border-brand bg-brand" : "border-stone-300")}>
              {active ? <span className="size-2 rounded-full bg-surface" /> : null}
            </span>
            <span className={compact ? "text-2xl" : "text-3xl"}>{o.emoji}</span>
            <span className={clsx("font-bold", compact ? "text-sm" : "text-[0.9375rem]")}>{o.title}</span>
            <span className={clsx("leading-snug text-muted", compact ? "text-xs" : "text-xs")}>{o.body}</span>
          </button>
        );
      })}
    </div>
  );
}

// --- Category icons -----------------------------------------------------------------------------

const CATEGORY_EMOJI: [RegExp, string][] = [
  [/breakfast|morning/i, "🍳"],
  [/main|lunch|dinner|meal/i, "🍛"],
  [/drink|juice|beverage/i, "🥤"],
  [/grill|bbq|nyama|choma/i, "🔥"],
  [/side|snack|chips/i, "🍟"],
  [/veg|salad/i, "🥗"],
  [/dessert|sweet|cake/i, "🍰"],
  [/tea|coffee/i, "☕"],
  [/fish|sea/i, "🐟"],
  [/chicken/i, "🍗"],
];

export function categoryEmoji(name: string): string {
  return CATEGORY_EMOJI.find(([re]) => re.test(name))?.[1] ?? "🍽️";
}

/** Cover photo with the hotel name in bold uppercase on a dark gradient. */
export function HotelCover({
  src,
  name,
  accent,
  className,
  size = "md",
  children,
  dim,
}: {
  src: string | null;
  name: string;
  accent?: string | null;
  className?: string;
  size?: "md" | "lg";
  children?: ReactNode;
  dim?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={clsx("relative overflow-hidden", className)} style={{ background: `linear-gradient(135deg, ${accent ?? "#dc4b12"}, #18181b)` }}>
      {src && !failed ? (
        <img
          src={src}
          alt=""
          loading="lazy"
          onError={() => setFailed(true)}
          className={clsx("absolute inset-0 size-full object-cover transition-transform duration-500 group-hover:scale-105", dim && "grayscale")}
        />
      ) : null}
      <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/35 to-black/5" />
      <div className={clsx("absolute inset-x-0 bottom-0", size === "lg" ? "p-6 sm:p-8" : "p-4")}>
        <span className="mb-2 block h-1 w-10 rounded-full" style={{ background: accent ?? "#f05a22" }} />
        <h3
          className={clsx(
            "font-extrabold tracking-[0.08em] text-white uppercase drop-shadow-[0_2px_8px_rgba(0,0,0,0.5)]",
            size === "lg" ? "text-3xl leading-tight sm:text-4xl" : "text-xl leading-tight",
          )}
        >
          {name}
        </h3>
        {children}
      </div>
    </div>
  );
}

// --- Journey progress ---------------------------------------------------------------------------

const JOURNEY = ["Choose food", "Checkout", "Pay", "Track"];

/** Where the customer is in the ordering journey. `step` is 0-based. */
export function JourneySteps({ step, className }: { step: number; className?: string }) {
  const t = useT();
  return (
    <nav aria-label="Order progress" className={clsx("w-full", className)}>
      <ol className="flex items-center">
        {JOURNEY.map((label, i) => {
          const done = i < step;
          const current = i === step;
          return (
            <li key={label} className={clsx("flex items-center", i < JOURNEY.length - 1 && "flex-1")} aria-current={current ? "step" : undefined}>
              <span className="flex items-center gap-2">
                <span
                  className={clsx(
                    "flex size-7 shrink-0 items-center justify-center rounded-full text-xs font-bold transition-colors",
                    done && "bg-ok text-white",
                    current && "bg-brand text-white ring-4 ring-brand/15",
                    !done && !current && "bg-subtle text-muted",
                  )}
                >
                  {done ? "✓" : i + 1}
                </span>
                <span className={clsx("hidden text-sm font-semibold whitespace-nowrap sm:inline", current ? "text-ink" : "text-muted")}>{t(label)}</span>
              </span>
              {i < JOURNEY.length - 1 ? <span className={clsx("mx-2 h-0.5 flex-1 rounded-full sm:mx-3", done ? "bg-ok" : "bg-line")} /> : null}
            </li>
          );
        })}
      </ol>
      <p className="mt-1.5 text-xs font-medium text-muted sm:hidden">
        {t("Step {n} of {total}:", { n: step + 1, total: JOURNEY.length })} <span className="text-ink">{t(JOURNEY[step])}</span>
      </p>
    </nav>
  );
}

// --- WhatsApp support ---------------------------------------------------------------------------

const WA_ICON = (
  <svg viewBox="0 0 24 24" className="size-5" fill="currentColor" aria-hidden>
    <path d="M17.5 14.4c-.3-.1-1.7-.8-2-.9-.3-.1-.5-.1-.7.1-.2.3-.8.9-.9 1.1-.2.2-.3.2-.6.1-.3-.1-1.2-.5-2.3-1.4-.9-.8-1.4-1.7-1.6-2-.2-.3 0-.5.1-.6l.4-.5c.1-.2.2-.3.3-.5.1-.2 0-.4 0-.5l-.9-2.2c-.2-.6-.5-.5-.7-.5h-.6c-.2 0-.5.1-.8.4-.3.3-1 1-1 2.4s1 2.8 1.2 3c.1.2 2 3.1 4.9 4.3.7.3 1.2.5 1.6.6.7.2 1.3.2 1.8.1.6-.1 1.7-.7 1.9-1.4.2-.7.2-1.2.2-1.4-.1-.1-.3-.2-.6-.3zM12 2a10 10 0 0 0-8.6 15.1L2 22l5-1.3A10 10 0 1 0 12 2zm0 18.2c-1.5 0-3-.4-4.3-1.2l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 1 1 12 20.2z" />
  </svg>
);

export function whatsappLink(number: string, text: string) {
  return `https://wa.me/${number}?text=${encodeURIComponent(text)}`;
}

/** Green WhatsApp help button. Hidden until the admin sets a support number. */
export function HelpButton({ number, message, variant = "full" }: { number?: string | null; message: string; variant?: "full" | "compact" }) {
  const t = useT();
  if (!number) return null;
  if (variant === "compact") {
    return (
      <a
        href={whatsappLink(number, message)}
        target="_blank"
        rel="noreferrer"
        className="flex h-10 items-center gap-2 rounded-xl border border-[#25d366]/40 bg-[#25d366]/10 px-3 text-sm font-semibold text-[#128c4a] hover:bg-[#25d366]/20"
      >
        {WA_ICON}
        <span className="hidden sm:inline">{t("Help")}</span>
      </a>
    );
  }
  return (
    <a
      href={whatsappLink(number, message)}
      target="_blank"
      rel="noreferrer"
      className="flex items-center gap-3 rounded-2xl border border-[#25d366]/30 bg-[#25d366]/10 p-4 transition-colors hover:bg-[#25d366]/15"
    >
      <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-[#25d366] text-white shadow-md">{WA_ICON}</span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold">{t("Need help? Chat with us")}</span>
        <span className="block text-sm text-muted">{t("On WhatsApp. We usually reply within minutes.")}</span>
      </span>
    </a>
  );
}

// --- Time estimate ------------------------------------------------------------------------------

/** "20–35 min": prep plus town travel for delivery, prep only for pickup. */
export function etaText(prepMinutes: number, mode: "delivery" | "pickup" | "eat_in"): string {
  const lo = mode === "delivery" ? prepMinutes + 5 : Math.max(5, prepMinutes - 5);
  const hi = mode === "delivery" ? prepMinutes + 20 : prepMinutes + 5;
  const round5 = (n: number) => Math.round(n / 5) * 5;
  return `${round5(lo)}–${round5(hi)}`;
}

// --- Platform bonuses ------------------------------------------------------------

/** The bonus as a receipt line, e.g. "Free delivery −KES 100". */
export function BonusLine({ q }: { q: Quote | undefined }) {
  const t = useT();
  if (!q?.platform_bonus) return null;
  return (
    <div className="flex justify-between">
      <span className="flex items-center gap-1.5 font-medium text-ok">
        {q.bonus_kind === "free_delivery" ? <Truck className="size-4" /> : <Gift className="size-4" />}
        {q.bonus_kind === "free_delivery" ? t("Free delivery") : t("Stamp card reward")}
      </span>
      <span className="money font-semibold text-ok">−{money(q.platform_bonus)}</span>
    </div>
  );
}

/** "Add KES 300 more for free delivery" and stamp-card progress. */
export function BonusNudges({ q, delivery, payAllByMpesa }: { q: Quote | undefined; delivery: boolean; payAllByMpesa: boolean }) {
  const t = useT();
  if (!q) return null;
  const min = q.free_delivery_min_food;
  const short = min ? min - q.food_net : 0;
  const nudges: ReactNode[] = [];
  if (delivery && min && q.bonus_kind !== "free_delivery") {
    if (short > 0 && short <= min * 0.6) {
      nudges.push(
        <p key="free" className="flex items-center gap-2 rounded-xl bg-ok-soft px-3 py-2.5 text-sm font-medium text-ok">
          <Truck className="size-4 shrink-0" />
          {t("Add {amount} more food for free delivery", { amount: money(short) })}
        </p>,
      );
    } else if (short <= 0 && !payAllByMpesa) {
      nudges.push(
        <p key="free" className="flex items-center gap-2 rounded-xl bg-ok-soft px-3 py-2.5 text-sm font-medium text-ok">
          <Truck className="size-4 shrink-0" />
          {t("Pay delivery by M-Pesa too and it's free")}
        </p>,
      );
    }
  }
  if (q.stamp_every && (q.stamps_have > 0 || q.bonus_kind === "stamp")) {
    const ready = q.bonus_kind === "stamp";
    nudges.push(
      <div key="stamps" className="rounded-xl border border-dashed border-brand/40 bg-brand-soft/50 px-3 py-2.5 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="font-semibold">{ready ? t("Your stamp card is full!") : t("Stamp card")}</span>
          <span className="flex gap-1" aria-label={t("{have} of {every} stamps", { have: q.stamps_have, every: q.stamp_every })}>
            {Array.from({ length: q.stamp_every }, (_, i) => (
              <span key={i} className={clsx("flex size-5 items-center justify-center rounded-full text-xs", i < q.stamps_have ? "bg-brand text-white" : "border border-brand/30 bg-surface")}>
                {i < q.stamps_have ? "★" : ""}
              </span>
            ))}
          </span>
        </div>
        <p className="mt-1 text-muted">
          {ready
            ? t("{amount} off this order, on us.", { amount: money(q.platform_bonus) })
            : t("{left} more completed orders and you get {amount} off.", { left: q.stamp_every - q.stamps_have, amount: money(q.stamp_reward) })}
        </p>
      </div>,
    );
  }
  return nudges.length ? <div className="flex flex-col gap-2">{nudges}</div> : null;
}
