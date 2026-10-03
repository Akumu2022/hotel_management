/**
 * What the hotel owes the platform (M7, DECISIONS D24). Customers pay the hotel's own Till, so
 * each week the hotel sends the commission and service fees (plus rider fees it held) to the
 * platform's M-Pesa number, then enters the M-Pesa code here. It counts once the super admin
 * sees the money arrive. Overdue or over the limit = orders paused until it's paid.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ChevronDown, Clock, Copy, Receipt, Send, Smartphone } from "lucide-react";
import { useState } from "react";

import { Badge, ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";

export type WeekTotals = { commission: number; service_fee: number; rider_fees_held: number; credits: number; sales: number; paid: number };
export type StatementRow = {
  id: string;
  week_start: string;
  week_end: string;
  sales: number;
  commission: number;
  service_fees: number;
  rider_fees_held: number;
  credits: number;
  opening_balance: number;
  paid_during_week: number;
  amount_due: number;
  left_to_pay: number;
  due_date: string;
  status: "open" | "paid" | "overdue";
};
export type SettlementRow = { id: string; hotel_id: string; hotel_name: string | null; amount: number; mpesa_code: string; status: "pending" | "confirmed" | "rejected"; note: string | null; created_at: string; confirmed_at: string | null };
export type HotelBilling = {
  hotel_id: string;
  hotel_name: string;
  pay_to: string;
  due_now: number;
  due_date: string | null;
  overdue: boolean;
  balance: number;
  this_week: WeekTotals;
  pending_claims: number;
  unpaid_limit: number;
  paused_for_billing: boolean;
  statements: StatementRow[];
  payments: SettlementRow[];
};

const day = new Intl.DateTimeFormat("en-KE", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
const dayTime = new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "Africa/Nairobi" });
/** "2026-10-08" (a Kenya date) -> "Thu, 8 Oct" */
export const dateLabel = (d: string) => day.format(new Date(`${d}T00:00:00Z`));
export const stampLabel = (iso: string) => dayTime.format(new Date(iso));
const dayMonth = new Intl.DateTimeFormat("en-KE", { day: "numeric", month: "short", timeZone: "UTC" });
/** "2026-09-21", "2026-09-27" -> "21 – 27 Sept" (or "28 Sept – 4 Oct") */
export const weekLabel = (a: string, b: string) => {
  const [x, y] = [new Date(`${a}T00:00:00Z`), new Date(`${b}T00:00:00Z`)];
  return x.getUTCMonth() === y.getUTCMonth() ? `${x.getUTCDate()} – ${dayMonth.format(y)}` : `${dayMonth.format(x)} – ${dayMonth.format(y)}`;
};
/** 254742554713 -> 0742 554 713 */
export const localPhone = (p: string) => ("0" + p.slice(3)).replace(/^(\d{4})(\d{3})(\d{3})$/, "$1 $2 $3");

export const STATEMENT_BADGE = {
  paid: { tone: "ok", label: "Paid" },
  open: { tone: "warn", label: "Due" },
  overdue: { tone: "bad", label: "Overdue" },
} as const;
export const PAYMENT_BADGE = {
  pending: { tone: "warn", label: "Checking" },
  confirmed: { tone: "ok", label: "Received" },
  rejected: { tone: "bad", label: "Not received" },
} as const;

function CopyNumber({ phone }: { phone: string }) {
  const [copied, setCopied] = useState(false);
  const local = localPhone(phone);
  return (
    <button
      onClick={() => {
        void navigator.clipboard?.writeText(local.replace(/\s/g, "")).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="group flex items-center gap-2 rounded-xl bg-white/15 px-3 py-2 text-left hover:bg-white/25"
    >
      <span className="money text-2xl font-extrabold tracking-wide">{local}</span>
      {copied ? <CheckCircle2 className="size-5" /> : <Copy className="size-5 opacity-80" />}
    </button>
  );
}

function PayForm({ due, onDone }: { due: number; onDone: () => void }) {
  const [code, setCode] = useState("");
  const [amount, setAmount] = useState("");
  const clean = code.replace(/\s+/g, "").toUpperCase();
  const send = useMutation({
    mutationFn: () => api.post("/hotel/billing/payments", { mpesa_code: clean, amount: Number(amount) }),
    onSuccess: () => {
      setCode("");
      setAmount("");
      onDone();
    },
  });
  const valid = /^[A-Z0-9]{8,12}$/.test(clean) && Number(amount) > 0;
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) send.mutate();
      }}
      className="flex flex-col gap-3"
    >
      <p className="text-sm font-semibold">Already sent it? Enter the M-Pesa message details</p>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_8.5rem_auto]">
        <input
          aria-label="M-Pesa code"
          placeholder="Code e.g. TJK3ABC12D"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          className="money h-12 min-w-0 rounded-xl border border-line bg-surface px-3.5 font-bold tracking-wider uppercase outline-none placeholder:font-normal placeholder:tracking-normal placeholder:normal-case focus:border-brand"
        />
        <div className="relative">
          <span className="absolute top-1/2 left-3.5 -translate-y-1/2 text-xs text-muted">KES</span>
          <input
            aria-label="Amount sent"
            inputMode="numeric"
            placeholder={due ? String(due) : "Amount"}
            value={amount}
            onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))}
            className="money h-12 w-full rounded-xl border border-line bg-surface pr-3 pl-11 font-bold outline-none focus:border-brand"
          />
        </div>
        <button disabled={!valid || send.isPending} className="flex h-12 items-center justify-center gap-2 rounded-xl bg-brand px-5 font-semibold whitespace-nowrap text-white shadow-md shadow-brand/25 disabled:opacity-40">
          <Send className="size-4" /> I've paid
        </button>
      </div>
      <ErrorNote error={send.error} />
      {send.isSuccess ? <p className="rounded-lg bg-ok-soft px-3 py-2 text-sm text-ok">Thanks. We'll confirm as soon as it shows on our M-Pesa.</p> : null}
    </form>
  );
}

function Tile({ label, value, tone }: { label: string; value: number; tone?: "ok" | "bad" }) {
  return (
    <div className="rounded-2xl border border-line p-4">
      <p className="text-sm text-muted">{label}</p>
      <p className={clsx("money mt-1 text-lg font-extrabold whitespace-nowrap sm:text-xl", tone === "ok" && "text-ok", tone === "bad" && "text-bad")}>{money(value)}</p>
    </div>
  );
}

function Line({ label, value, sign, strong }: { label: string; value: number; sign?: "+" | "−"; strong?: boolean }) {
  return (
    <div className={clsx("flex items-center justify-between py-1.5", strong && "border-t border-line pt-2.5 font-bold")}>
      <span className={strong ? "" : "text-muted"}>{label}</span>
      <span className="money">{sign && value ? `${sign} ` : ""}{money(value)}</span>
    </div>
  );
}

export function StatementCard({ s }: { s: StatementRow }) {
  const [open, setOpen] = useState(false);
  const b = STATEMENT_BADGE[s.status];
  return (
    <li className="rounded-2xl border border-line">
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-3 p-4 text-left">
        <span className="hidden size-10 shrink-0 items-center justify-center rounded-xl bg-brand-soft text-brand sm:flex"><Receipt className="size-5" /></span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold">{weekLabel(s.week_start, s.week_end)}</span>
          <span className="block text-sm text-muted">Sales {money(s.sales)} · due {dateLabel(s.due_date)}</span>
        </span>
        <span className="shrink-0 text-right">
          <span className="money block font-extrabold">{money(s.amount_due)}</span>
          <Badge tone={b.tone}>{s.status !== "paid" && s.left_to_pay < s.amount_due ? `${money(s.left_to_pay)} left` : b.label}</Badge>
        </span>
        <ChevronDown className={clsx("size-5 shrink-0 text-muted transition-transform", open && "rotate-180")} />
      </button>
      {open ? (
        <div className="border-t border-line px-4 py-3 text-sm">
          <Line label="Brought forward" value={s.opening_balance} />
          <Line label="Commission" value={s.commission} sign="+" />
          <Line label="Service fees" value={s.service_fees} sign="+" />
          {s.rider_fees_held ? <Line label="Rider fees you kept for weekly riders" value={s.rider_fees_held} sign="+" /> : null}
          {s.credits ? <Line label="Credits (refunds, bonuses, failed deliveries)" value={s.credits} sign="−" /> : null}
          {s.paid_during_week ? <Line label="Paid during the week" value={s.paid_during_week} sign="−" /> : null}
          <Line label="Amount due" value={s.amount_due} strong />
          <p className="mt-2 text-xs text-muted">Commission is worked out on each order when it's paid, never on the weekly total.</p>
        </div>
      ) : null}
    </li>
  );
}

export function PaymentRow({ p, showHotel }: { p: SettlementRow; showHotel?: boolean }) {
  const b = PAYMENT_BADGE[p.status];
  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <span className="min-w-0 flex-1">
        <span className="money block font-bold tracking-wide">{showHotel && p.hotel_name ? `${p.hotel_name} · ` : ""}{p.mpesa_code}</span>
        <span className="block text-xs text-muted">{stampLabel(p.created_at)}{p.note ? ` · ${p.note}` : ""}</span>
      </span>
      <span className="money font-bold">{money(p.amount)}</span>
      <Badge tone={b.tone}>{b.label}</Badge>
    </li>
  );
}

export function BillingPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["hotel", "billing"], queryFn: () => api.get<HotelBilling>("/hotel/billing"), refetchInterval: 60_000 });
  if (q.isLoading) return <Skeleton className="h-64 rounded-[1.75rem]" />;
  if (q.error || !q.data) return <ErrorNote error={q.error} />;
  const b = q.data;
  const w = b.this_week;
  const thisWeekOwed = w.commission + w.service_fee + w.rider_fees_held - w.credits;

  return (
    <div className="flex flex-col gap-5">
      {b.paused_for_billing ? (
        <div className="flex items-start gap-3 rounded-3xl border-2 border-bad/40 bg-bad-soft p-4 text-bad">
          <AlertTriangle className="mt-0.5 size-5 shrink-0" />
          <p className="text-sm font-semibold">Your shop is paused: customers can't order until the amount below is paid and confirmed. It reopens by itself.</p>
        </div>
      ) : null}

      <section className="grid gap-5 lg:grid-cols-[1.1fr_1fr]">
        <div className={clsx("flex flex-col gap-4 rounded-[1.75rem] p-6 text-white shadow-lg", b.overdue ? "bg-bad shadow-bad/25" : b.due_now ? "bg-gradient-to-br from-brand to-brand-accent shadow-brand/25" : "bg-ok shadow-ok/25")}>
          <div>
            <p className="text-sm font-medium text-white/85">{b.due_now ? (b.overdue ? "Overdue" : "Amount due") : "You're all paid up"}</p>
            <p className="money text-4xl font-extrabold md:text-5xl">{money(b.due_now)}</p>
            {b.due_date ? (
              <p className="mt-1 flex items-center gap-1.5 text-sm text-white/90"><Clock className="size-4" /> {b.overdue ? "Was due" : "Pay by"} {dateLabel(b.due_date)}</p>
            ) : (
              <p className="mt-1 text-sm text-white/90">Statements come every Monday for the week before.</p>
            )}
            {b.pending_claims ? <p className="mt-2 inline-block rounded-lg bg-white/20 px-2.5 py-1 text-sm font-semibold">{money(b.pending_claims)} sent, waiting for confirmation</p> : null}
          </div>
          <div className="rounded-2xl bg-black/10 p-4">
            <p className="flex items-center gap-2 text-sm font-semibold"><Smartphone className="size-4" /> M-Pesa Send Money to</p>
            <div className="mt-2"><CopyNumber phone={b.pay_to} /></div>
            <p className="mt-2 text-xs text-white/80">Send from any phone, then enter the code below. Tap the number to copy it.</p>
          </div>
        </div>

        <div className="flex flex-col gap-4 rounded-[1.75rem] bg-surface p-6 shadow-sm">
          <PayForm due={b.due_now} onDone={() => void qc.invalidateQueries({ queryKey: ["hotel", "billing"] })} />
          <div className="border-t border-line pt-4">
            <p className="mb-3 text-sm font-semibold">This week so far <span className="font-normal text-muted">(on next Monday's statement)</span></p>
            <div className="grid grid-cols-2 gap-3">
              <Tile label="Sales" value={w.sales} />
              <Tile label="Owed for this week" value={Math.max(thisWeekOwed, 0)} />
            </div>
            <p className="mt-2 text-xs text-muted">Commission {money(w.commission)} · service fees {money(w.service_fee)}{w.rider_fees_held ? ` · rider fees ${money(w.rider_fees_held)}` : ""}{w.credits ? ` · credits −${money(w.credits)}` : ""}</p>
          </div>
        </div>
      </section>

      <section className="rounded-[1.75rem] bg-surface p-5 shadow-sm">
        <h2 className="mb-4 text-lg font-bold">Weekly statements</h2>
        {b.statements.length ? (
          <ul className="flex flex-col gap-3">{b.statements.map((s) => <StatementCard key={s.id} s={s} />)}</ul>
        ) : (
          <p className="rounded-2xl border border-dashed border-line py-8 text-center text-sm text-muted">No statements yet. Your first one arrives the Monday after your first sale.</p>
        )}
      </section>

      <section className="rounded-[1.75rem] bg-surface p-5 shadow-sm">
        <h2 className="mb-1 text-lg font-bold">Your payments</h2>
        {b.payments.length ? (
          <ul className="divide-y divide-line">{b.payments.map((p) => <PaymentRow key={p.id} p={p} />)}</ul>
        ) : (
          <p className="py-6 text-center text-sm text-muted">No payments yet.</p>
        )}
      </section>
    </div>
  );
}
