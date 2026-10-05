/**
 * Cashier's payment desk (spec section 6, M4): confirm M-Pesa payments by reading the Till
 * phone, record cash, work the review queue, and send refunds.
 * Never accept screenshots or forwarded messages: only the Till phone's own SMS.
 */
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, Banknote, CheckCircle2, Clock, Loader2, RotateCcw, ShieldCheck, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";

import { type TillPhone, phoneHealth } from "../components/TillPhones";
import { Badge, EmptyState, ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { useIsAdmin } from "./hooks";

type PendingOrder = {
  id: string;
  code: string;
  status: string;
  type: string;
  arrive_at?: string | null;
  payment_method: "mpesa" | "cash";
  customer_name: string;
  customer_phone: string;
  till_amount: number;
  customer_trans_code: string | null;
  items: string[];
  created_at: string;
  expires_at: string | null;
};
type Review = {
  id: string;
  type: string;
  reason: string;
  order_code: string | null;
  amount: number | null;
  trans_code: string | null;
  order_total: number | null;
  actions: string[];
  created_at: string;
};
type RefundRow = { id: string; order_code: string | null; customer_phone: string | null; amount: number; reason: string; created_at: string };

const ACTION_LABEL: Record<string, string> = {
  refund: "Refund customer",
  accept_shortfall: "Accept anyway",
  refund_difference: "Refund the extra",
  reinstate: "Reinstate order",
  cancel_order: "Cancel order",
  dismiss: "Dismiss",
};
const TYPE_LABEL: Record<string, { label: string; tone: "warn" | "bad" | "neutral" | "brand" }> = {
  underpaid: { label: "Paid too little", tone: "warn" },
  overpaid: { label: "Paid too much", tone: "brand" },
  late_payment: { label: "Paid after expiry", tone: "warn" },
  no_sms: { label: "Payment not seen", tone: "warn" },
  unmatched_sms: { label: "Unmatched payment", tone: "neutral" },
  reversal: { label: "M-Pesa reversal", tone: "bad" },
  parse_failed: { label: "Unreadable SMS", tone: "neutral" },
};

const ago = (iso: string) => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`;
};

function Section({ title, count, icon, children }: { title: string; count: number; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-[1.5rem] bg-surface p-5 shadow-sm">
      <h2 className="mb-4 flex items-center gap-2.5 text-lg font-bold">
        <span className="flex size-9 items-center justify-center rounded-xl bg-brand-soft text-brand">{icon}</span>
        {title}
        <span className="rounded-full bg-subtle px-2.5 py-0.5 text-sm font-semibold text-muted">{count}</span>
      </h2>
      {children}
    </section>
  );
}

function ConfirmCard({ o, auto }: { o: PendingOrder; auto: boolean }) {
  const qc = useQueryClient();
  const [code, setCode] = useState(o.customer_trans_code ?? "");
  const [amount, setAmount] = useState("");
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  // D28: with a working Till phone the SMS confirms the order; typing is only the fallback.
  const [manual, setManual] = useState(false);
  useEffect(() => setCode(o.customer_trans_code ?? ""), [o.customer_trans_code]);
  const refresh = () => qc.invalidateQueries({ queryKey: ["hotel", "payments"] });

  const confirm = useMutation({
    mutationFn: () => api.post<{ result: string; message: string }>(`/hotel/orders/${o.id}/confirm-payment`, { code: code.replace(/\s+/g, "").toUpperCase(), amount: Number(amount) }),
    onSuccess: (r) => {
      setResult({ ok: r.result === "paid" || r.result === "overpaid", text: r.message });
      refresh();
    },
    onError: (e) => setResult({ ok: false, text: e instanceof Error ? e.message : "Failed" }),
  });
  const cash = useMutation({ mutationFn: () => api.post(`/hotel/orders/${o.id}/cash-received`), onSuccess: refresh });
  const validCode = /^[A-Z0-9]{10}$/.test(code.replace(/\s+/g, "").toUpperCase());
  const left = o.expires_at ? Math.max(0, Math.round((new Date(o.expires_at).getTime() - Date.now()) / 60000)) : null;

  return (
    <li className="rounded-2xl border border-line p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-bold">#{o.code} · {o.customer_name}</p>
          <p className="text-sm text-muted">{o.items.join(", ")}</p>
          <p className="mt-0.5 text-xs text-muted">
            {ago(o.created_at)} · {o.type === "eat_in" ? <b className="text-warn">EAT IN{o.arrive_at ? ` · arrives ${new Intl.DateTimeFormat("en-KE", { hour: "numeric", minute: "2-digit", timeZone: "Africa/Nairobi" }).format(new Date(o.arrive_at))}` : ""}</b> : o.type}
          </p>
        </div>
        <div className="text-right">
          <p className="money text-2xl font-extrabold">{money(o.till_amount)}</p>
          {o.payment_method === "cash" ? (
            <Badge tone="neutral">Cash at counter</Badge>
          ) : o.status === "checking_payment" ? (
            <Badge tone="brand">Customer says paid</Badge>
          ) : left != null ? (
            <Badge tone={left < 5 ? "bad" : "warn"}>{left} min left</Badge>
          ) : null}
        </div>
      </div>

      {o.payment_method === "cash" ? (
        <button
          onClick={() => cash.mutate()}
          disabled={cash.isPending}
          className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-ok font-semibold text-white disabled:opacity-60"
        >
          <Banknote className="size-4" /> Cash received · {money(o.till_amount)}
        </button>
      ) : auto && !manual ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-ok-soft px-3 py-2.5 text-sm text-ok">
          <span className="flex items-center gap-2 font-medium">
            <Loader2 className="size-4 animate-spin" /> Confirms by itself when the M-Pesa SMS arrives
          </span>
          <button onClick={() => setManual(true)} className="text-xs font-semibold text-muted underline underline-offset-2 hover:text-ink">
            Enter code by hand
          </button>
        </div>
      ) : (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-xs font-medium text-muted">Copy from the Till phone's M-Pesa message:</p>
          <div className="grid grid-cols-[1fr_8rem] gap-2">
            <input
              aria-label="M-Pesa code"
              placeholder="Code e.g. SJK3ABC12D"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              className="money h-11 rounded-xl border border-line bg-surface px-3 font-bold tracking-wider uppercase outline-none placeholder:font-normal placeholder:tracking-normal focus:border-brand"
            />
            <div className="relative">
              <span className="absolute top-1/2 left-3 -translate-y-1/2 text-xs text-muted">KES</span>
              <input
                aria-label="Amount received"
                inputMode="numeric"
                placeholder={String(o.till_amount)}
                value={amount}
                onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))}
                className="money h-11 w-full rounded-xl border border-line bg-surface pr-3 pl-10 font-bold outline-none focus:border-brand"
              />
            </div>
          </div>
          <button
            onClick={() => confirm.mutate()}
            disabled={!validCode || !amount || confirm.isPending}
            className="flex h-11 items-center justify-center gap-2 rounded-xl bg-brand font-semibold text-white shadow-md shadow-brand/20 disabled:bg-line disabled:text-muted disabled:shadow-none"
          >
            <ShieldCheck className="size-4" /> Confirm payment
          </button>
        </div>
      )}
      {result ? <p className={clsx("mt-2 text-sm font-medium", result.ok ? "text-ok" : "text-bad")}>{result.text}</p> : null}
      <ErrorNote error={cash.error} />
    </li>
  );
}

function ReviewCard({ r, isAdmin }: { r: Review; isAdmin: boolean }) {
  const qc = useQueryClient();
  const [orderCode, setOrderCode] = useState("");
  const resolve = useMutation({
    mutationFn: (action: string) =>
      api.post(`/hotel/review-items/${r.id}/resolve`, action === "match_order" ? { action, order_code: orderCode } : { action }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["hotel", "payments"] });
      void qc.invalidateQueries({ queryKey: ["hotel", "orders"] });
    },
  });
  const t = TYPE_LABEL[r.type] ?? { label: r.type, tone: "neutral" as const };
  return (
    <li className="rounded-2xl border border-line p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge tone={t.tone}>{t.label}</Badge>
          {r.order_code ? <span className="font-bold">#{r.order_code}</span> : null}
        </div>
        <span className="text-xs text-muted">{ago(r.created_at)}</span>
      </div>
      <p className="mt-2 text-sm">{r.reason}</p>
      {r.amount != null || r.trans_code ? (
        <p className="mt-1 text-sm text-muted">
          {r.trans_code ? <span className="money font-semibold text-ink">{r.trans_code}</span> : null}
          {r.amount != null ? <> · received <span className="money font-semibold text-ink">{money(r.amount)}</span></> : null}
          {r.order_total != null ? <> · order total <span className="money">{money(r.order_total)}</span></> : null}
        </p>
      ) : null}
      {r.actions.includes("match_order") ? (
        <div className="mt-3 flex flex-col gap-2 rounded-xl bg-subtle p-3 sm:flex-row sm:items-center">
          <label className="text-sm font-semibold" htmlFor={`match-${r.id}`}>Which order was this for?</label>
          <input
            id={`match-${r.id}`}
            value={orderCode}
            onChange={(e) => setOrderCode(e.target.value.toUpperCase().replace(/[^A-Z0-9#]/g, ""))}
            placeholder="Order number, e.g. 7C37Y6"
            className="money h-10 min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 font-bold tracking-wider outline-none focus:border-brand"
          />
          <button onClick={() => resolve.mutate("match_order")} disabled={orderCode.replace("#", "").length < 6 || resolve.isPending} className="h-10 rounded-lg bg-brand px-4 text-sm font-semibold text-white disabled:opacity-40">
            Match to order
          </button>
        </div>
      ) : null}
      <div className="mt-3 flex flex-wrap gap-2">
        {r.actions.filter((a) => a !== "match_order").map((a) => {
          const adminOnly = a.startsWith("refund");
          const primary = a !== "dismiss";
          return (
            <button
              key={a}
              onClick={() => resolve.mutate(a)}
              disabled={resolve.isPending || (adminOnly && !isAdmin)}
              title={adminOnly && !isAdmin ? "Only the hotel admin can approve refunds" : undefined}
              className={clsx(
                "h-10 rounded-xl px-4 text-sm font-semibold disabled:opacity-40",
                primary ? "bg-ink text-surface" : "border border-line",
              )}
            >
              {ACTION_LABEL[a] ?? a}
            </button>
          );
        })}
      </div>
      <ErrorNote error={resolve.error} />
    </li>
  );
}

function RefundCard({ r }: { r: RefundRow }) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const sent = useMutation({
    mutationFn: () => api.post(`/hotel/refunds/${r.id}/sent`, { mpesa_code: code }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["hotel", "payments"] }),
  });
  return (
    <li className="rounded-2xl border border-line p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-bold">#{r.order_code} · send to {r.customer_phone ? "0" + r.customer_phone.slice(3) : "customer"}</p>
          <p className="text-sm text-muted">{r.reason}</p>
        </div>
        <p className="money text-xl font-extrabold">{money(r.amount)}</p>
      </div>
      <p className="mt-2 text-xs text-muted">Send it from the Till by M-Pesa, then enter the code M-Pesa gives you.</p>
      <div className="mt-2 flex gap-2">
        <input
          aria-label="Refund M-Pesa code"
          placeholder="M-Pesa code of the refund"
          value={code}
          onChange={(e) => setCode(e.target.value.toUpperCase())}
          className="money h-11 min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 font-bold tracking-wider uppercase outline-none placeholder:font-normal placeholder:tracking-normal focus:border-brand"
        />
        <button onClick={() => sent.mutate()} disabled={!/^[A-Z0-9]{10}$/.test(code.trim()) || sent.isPending} className="h-11 shrink-0 rounded-xl bg-brand px-4 text-sm font-semibold text-white disabled:bg-line disabled:text-muted">
          Mark sent
        </button>
      </div>
      <ErrorNote error={sent.error} />
    </li>
  );
}

export function PaymentsPage() {
  const isAdmin = useIsAdmin();
  const pending = useQuery({ queryKey: ["hotel", "payments", "pending"], queryFn: () => api.get<PendingOrder[]>("/hotel/payments/pending"), refetchInterval: 10_000 });
  const review = useQuery({ queryKey: ["hotel", "payments", "review"], queryFn: () => api.get<Review[]>("/hotel/review-items"), refetchInterval: 15_000 });
  const refunds = useQuery({ queryKey: ["hotel", "payments", "refunds"], queryFn: () => api.get<RefundRow[]>("/hotel/refunds"), refetchInterval: 30_000 });

  const phones = useQuery({ queryKey: ["hotel", "forwarder"], queryFn: () => api.get<{ devices: TillPhone[] }>("/hotel/forwarder"), refetchInterval: 60_000 });
  const health = phones.data ? phoneHealth(phones.data.devices[0]) : null;

  if (pending.isLoading) return <Skeleton className="h-64 rounded-[1.5rem]" />;

  return (
    <div className="flex flex-col gap-5">
      {health ? (
        <p className={clsx("flex items-start gap-2 rounded-2xl px-4 py-3 text-sm font-semibold", health.ok ? "bg-ok-soft text-ok" : "bg-bad-soft text-bad")}>
          <Smartphone className="mt-0.5 size-4 shrink-0" />
          <span>
            Till phone: {health.text}
            {!health.ok && isAdmin ? " Settings → Till phone." : ""}
          </span>
        </p>
      ) : null}
      <p className="flex items-start gap-2 rounded-2xl bg-warn-soft px-4 py-3 text-sm text-warn">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        Only confirm from the Till phone's own M-Pesa message. Never accept screenshots or forwarded messages.
      </p>

      <div className="grid gap-5 xl:grid-cols-2">
        <Section title="Waiting for payment" count={pending.data?.length ?? 0} icon={<Smartphone className="size-5" />}>
          {pending.error ? <ErrorNote error={pending.error} /> : null}
          {pending.data?.length ? (
            <ul className="flex flex-col gap-3">{pending.data.map((o) => <ConfirmCard key={o.id} o={o} auto={!!health?.ok} />)}</ul>
          ) : (
            <EmptyState title="All caught up" body="New orders waiting for payment appear here." />
          )}
        </Section>

        <div className="flex flex-col gap-5">
          <Section title="Needs review" count={review.data?.length ?? 0} icon={<Clock className="size-5" />}>
            {review.data?.length ? (
              <ul className="flex flex-col gap-3">{review.data.map((r) => <ReviewCard key={r.id} r={r} isAdmin={isAdmin} />)}</ul>
            ) : (
              <p className="flex items-center gap-2 text-sm text-muted"><CheckCircle2 className="size-4 text-ok" /> Nothing to review.</p>
            )}
          </Section>
          <Section title="Refunds to send" count={refunds.data?.length ?? 0} icon={<RotateCcw className="size-5" />}>
            {refunds.data?.length ? (
              <ul className="flex flex-col gap-3">{refunds.data.map((r) => <RefundCard key={r.id} r={r} />)}</ul>
            ) : (
              <p className="flex items-center gap-2 text-sm text-muted"><CheckCircle2 className="size-4 text-ok" /> No refunds waiting.</p>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}
