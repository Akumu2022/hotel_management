/**
 * Super admin billing: hotel payments to confirm against the platform's own
 * M-Pesa messages, what each hotel owes, and rider payouts. A claimed payment counts only once
 * confirmed here; confirming can lift an unpaid-balance pause at once.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BellRing, Bike, Building2, CheckCircle2, Send, Smartphone, XCircle } from "lucide-react";
import { useState } from "react";

import { Badge, ErrorNote, Sheet, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { type HotelBilling, type SettlementRow, PaymentRow, StatementCard, dateLabel, localPhone, stampLabel } from "../hotel/BillingPage";

type HotelRow = { hotel_id: string; hotel_name: string; status: string; pause_reason: string | null; due_now: number; due_date: string | null; overdue: boolean; balance: number };
type Overview = { pay_to: string; total_due: number; hotels: HotelRow[]; pending: SettlementRow[]; recent: SettlementRow[] };
type Payout = { id: string; amount: number; mpesa_code: string; paid_at: string };
type RiderRow = { rider_id: string; name: string; phone: string; owed: number; last_payout: Payout | null };

const KEY = ["admin", "billing"];

function Panel({ title, icon, count, children, className }: { title: string; icon: React.ReactNode; count?: number; children: React.ReactNode; className?: string }) {
  return (
    <section className={clsx("rounded-[1.5rem] border border-line bg-surface p-5", className)}>
      <h2 className="mb-4 flex items-center gap-2.5 text-lg font-bold">
        <span className="flex size-9 items-center justify-center rounded-xl bg-brand-soft text-brand">{icon}</span>
        {title}
        {count != null ? <span className="rounded-full bg-subtle px-2.5 py-0.5 text-sm font-semibold text-muted">{count}</span> : null}
      </h2>
      {children}
    </section>
  );
}

function ClaimCard({ p }: { p: SettlementRow }) {
  const qc = useQueryClient();
  const [amount, setAmount] = useState(String(p.amount));
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const done = () => qc.invalidateQueries({ queryKey: KEY });
  const confirm = useMutation({
    mutationFn: () => api.post(`/admin/billing/payments/${p.id}/confirm`, Number(amount) !== p.amount ? { amount: Number(amount) } : {}),
    onSuccess: done,
  });
  const reject = useMutation({ mutationFn: () => api.post(`/admin/billing/payments/${p.id}/reject`, { note }), onSuccess: done });
  return (
    <li className="min-w-0 rounded-2xl border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-bold">{p.hotel_name}</p>
          <p className="money text-lg font-extrabold tracking-wider">{p.mpesa_code}</p>
          <p className="text-xs text-muted">Claimed {stampLabel(p.created_at)}</p>
        </div>
        <p className="money text-2xl font-extrabold">{money(p.amount)}</p>
      </div>
      <p className="mt-3 text-xs font-medium text-muted">Check your M-Pesa messages for this code. Change the amount if the message shows a different one.</p>
      {rejecting ? (
        <div className="mt-2 flex flex-col gap-2 sm:flex-row">
          <input
            autoFocus
            aria-label="Why it was not received"
            placeholder="e.g. No such payment on our M-Pesa"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            className="h-11 flex-1 rounded-xl border border-line bg-surface px-3 text-sm outline-none focus:border-brand"
          />
          <div className="flex gap-2">
            <button onClick={() => reject.mutate()} disabled={note.trim().length < 2 || reject.isPending} className="h-11 flex-1 rounded-xl bg-bad px-4 text-sm font-semibold text-white disabled:opacity-40">Tell the hotel</button>
            <button onClick={() => setRejecting(false)} className="h-11 rounded-xl border border-line px-4 text-sm font-semibold">Back</button>
          </div>
        </div>
      ) : (
        <div className="mt-2 grid grid-cols-[7rem_minmax(0,1fr)_auto] gap-2">
          <div className="relative">
            <span className="absolute top-1/2 left-3 -translate-y-1/2 text-xs text-muted">KES</span>
            <input aria-label="Amount received" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} className="money h-11 w-full rounded-xl border border-line bg-surface pr-2 pl-10 font-bold outline-none focus:border-brand" />
          </div>
          <button onClick={() => confirm.mutate()} disabled={!Number(amount) || confirm.isPending} className="flex h-11 items-center justify-center gap-2 rounded-xl bg-ok px-3 text-sm font-semibold text-white disabled:opacity-40">
            <CheckCircle2 className="size-4" /> Received
          </button>
          <button onClick={() => setRejecting(true)} aria-label="Not received" title="Not received" className="flex size-11 items-center justify-center rounded-xl border border-bad/30 text-bad hover:bg-bad-soft">
            <XCircle className="size-5" />
          </button>
        </div>
      )}
      <ErrorNote error={confirm.error ?? reject.error} />
    </li>
  );
}

function HotelSheet({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: [...KEY, "hotel", id], queryFn: () => api.get<HotelBilling>(`/admin/billing/hotels/${id}`), enabled: !!id });
  const b = q.data;
  return (
    <Sheet open={!!id} title={b?.hotel_name ?? "Hotel"} onClose={onClose}>
      {!b ? (
        <Skeleton className="h-48" />
      ) : (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl border border-line p-4">
              <p className="text-sm text-muted">Due now</p>
              <p className={clsx("money text-xl font-extrabold", b.overdue && "text-bad")}>{money(b.due_now)}</p>
            </div>
            <div className="rounded-2xl border border-line p-4">
              <p className="text-sm text-muted">Balance incl. this week</p>
              <p className="money text-xl font-extrabold">{money(b.balance)}</p>
            </div>
          </div>
          <ul className="flex flex-col gap-3">{b.statements.map((s) => <StatementCard key={s.id} s={s} />)}</ul>
          {!b.statements.length ? <p className="text-center text-sm text-muted">No statements yet.</p> : null}
          <div>
            <h3 className="font-bold">Payments</h3>
            <ul className="divide-y divide-line">{b.payments.map((p) => <PaymentRow key={p.id} p={p} />)}</ul>
            {!b.payments.length ? <p className="py-4 text-center text-sm text-muted">None yet.</p> : null}
          </div>
        </div>
      )}
    </Sheet>
  );
}

function PayRider({ r }: { r: RiderRow }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [code, setCode] = useState("");
  const [amount, setAmount] = useState(String(r.owed));
  const clean = code.replace(/\s+/g, "").toUpperCase();
  const pay = useMutation({
    mutationFn: () => api.post(`/admin/billing/riders/${r.rider_id}/payouts`, { mpesa_code: clean, amount: Number(amount) }),
    onSuccess: () => {
      setOpen(false);
      setCode("");
      return qc.invalidateQueries({ queryKey: [...KEY, "riders"] });
    },
  });
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-brand-soft font-bold text-brand">{r.name.slice(0, 1)}</span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold">{r.name}</span>
          <span className="block text-xs text-muted">{localPhone(r.phone)}{r.last_payout ? ` · last paid ${money(r.last_payout.amount)} on ${stampLabel(r.last_payout.paid_at)}` : ""}</span>
        </span>
        <span className={clsx("money font-extrabold", r.owed ? "text-ink" : "text-muted")}>{money(r.owed)}</span>
        {r.owed ? (
          <button onClick={() => { setAmount(String(r.owed)); setOpen(!open); }} className="h-9 rounded-xl bg-brand px-3.5 text-sm font-semibold text-white">Pay</button>
        ) : <Badge tone="ok">Paid up</Badge>}
      </div>
      {open ? (
        <form onSubmit={(e) => { e.preventDefault(); pay.mutate(); }} className="mt-3 flex flex-col gap-2 rounded-2xl bg-page p-3">
          <p className="text-xs text-muted">Send by M-Pesa to {localPhone(r.phone)}, then enter the code from your confirmation message.</p>
          <div className="grid grid-cols-[1fr_8rem_auto] gap-2">
            <input aria-label="M-Pesa code" placeholder="M-Pesa code" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} className="money h-11 rounded-xl border border-line bg-surface px-3 font-bold tracking-wider outline-none focus:border-brand" />
            <input aria-label="Amount paid" inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} className="money h-11 rounded-xl border border-line bg-surface px-3 font-bold outline-none focus:border-brand" />
            <button disabled={!/^[A-Z0-9]{8,12}$/.test(clean) || !Number(amount) || pay.isPending} className="flex h-11 items-center gap-1.5 rounded-xl bg-ok px-3.5 text-sm font-semibold text-white disabled:opacity-40"><Send className="size-4" /> Paid</button>
          </div>
          <ErrorNote error={pay.error} />
        </form>
      ) : null}
    </li>
  );
}

export function AdminBillingPage() {
  const q = useQuery({ queryKey: KEY, queryFn: () => api.get<Overview>("/admin/billing"), refetchInterval: 30_000 });
  const riders = useQuery({ queryKey: [...KEY, "riders"], queryFn: () => api.get<RiderRow[]>("/admin/billing/riders"), refetchInterval: 60_000 });
  const [hotel, setHotel] = useState<string | null>(null);
  if (q.isLoading) return <div className="p-6"><Skeleton className="h-64 rounded-3xl" /></div>;
  if (!q.data) return <div className="p-6"><ErrorNote error={q.error} /></div>;
  const o = q.data;
  const owing = o.hotels.filter((h) => h.due_now || h.balance > 0 || h.pause_reason);
  const ridersOwed = (riders.data ?? []).reduce((s, r) => s + r.owed, 0);

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-extrabold">Billing</h1>
        <p className="flex items-center gap-1.5 text-sm text-muted"><Smartphone className="size-4" /> Hotels send to {localPhone(o.pay_to)} (change it under Delivery)</p>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[
          { label: "Due from hotels", value: money(o.total_due) },
          { label: "Payments to confirm", value: String(o.pending.length), alert: o.pending.length > 0 },
          { label: "Hotels overdue", value: String(o.hotels.filter((h) => h.overdue).length), alert: o.hotels.some((h) => h.overdue) },
          { label: "Owed to riders", value: money(ridersOwed) },
        ].map((t) => (
          <div key={t.label} className={clsx("rounded-2xl border p-4", t.alert ? "border-bad/40 bg-bad-soft" : "border-line bg-surface")}>
            <p className="text-sm text-muted">{t.label}</p>
            <p className={clsx("money mt-1 text-2xl font-extrabold", t.alert && "text-bad")}>{t.value}</p>
          </div>
        ))}
      </div>

      {o.pending.length ? (
        <Panel title="Hotel payments to confirm" icon={<BellRing className="size-5" />} count={o.pending.length} className="border-2 border-brand/40">
          <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">{o.pending.map((p) => <ClaimCard key={p.id} p={p} />)}</ul>
        </Panel>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-2">
        <Panel title="Hotels" icon={<Building2 className="size-5" />} count={o.hotels.length}>
          <ul className="divide-y divide-line">
            {(owing.length ? owing : o.hotels).map((h) => (
              <li key={h.hotel_id}>
                <button onClick={() => setHotel(h.hotel_id)} className="flex w-full items-center gap-3 py-3 text-left">
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold">{h.hotel_name}</span>
                    <span className="block text-xs text-muted">
                      {h.due_date ? `${h.overdue ? "Was due" : "Due"} ${dateLabel(h.due_date)}` : "Nothing due"} · this week {money(Math.max(h.balance - h.due_now, 0))}
                    </span>
                  </span>
                  <span className="money font-extrabold">{money(h.due_now)}</span>
                  {h.status === "paused" ? <Badge tone="bad">Paused</Badge> : h.overdue ? <Badge tone="bad">Overdue</Badge> : h.due_now ? <Badge tone="warn">Due</Badge> : <Badge tone="ok">Paid up</Badge>}
                </button>
              </li>
            ))}
          </ul>
          {owing.length && owing.length < o.hotels.length ? <p className="pt-2 text-xs text-muted">{o.hotels.length - owing.length} other hotels owe nothing.</p> : null}
        </Panel>

        <Panel title="Rider payouts" icon={<Bike className="size-5" />}>
          {riders.isLoading ? (
            <Skeleton className="h-24" />
          ) : riders.data?.length ? (
            <ul className="divide-y divide-line">{riders.data.map((r) => <PayRider key={r.rider_id} r={r} />)}</ul>
          ) : (
            <p className="rounded-2xl border border-dashed border-line py-8 text-center text-sm text-muted">No rider is owed anything. Weekly-paid fees and compensation show here.</p>
          )}
        </Panel>
      </div>

      {o.recent.length ? (
        <Panel title="Recent hotel payments" icon={<CheckCircle2 className="size-5" />}>
          <ul className="divide-y divide-line">{o.recent.map((p) => <PaymentRow key={p.id} p={p} showHotel />)}</ul>
        </Panel>
      ) : null}

      <HotelSheet id={hotel} onClose={() => setHotel(null)} />
    </div>
  );
}
