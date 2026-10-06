/** Super admin "Needs attention". Payment review belongs to each hotel; the duty
 * person sees only orders not accepted in time, hotel items left open 15+ minutes (to chase by
 * phone), and items with no hotel (an unreadable SMS, an unknown Till), which they resolve. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { BellRing, CheckCircle2, Phone } from "lucide-react";
import { useState } from "react";

import { Badge, ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";

type Review = {
  id: string;
  type: string;
  reason: string;
  order_code: string | null;
  hotel_name: string | null;
  hotel_phone: string | null;
  amount: number | null;
  trans_code: string | null;
  order_total: number | null;
  actions: string[];
  created_at: string;
};

const LABEL: Record<string, string> = {
  refund: "Refund customer",
  accept_shortfall: "Accept anyway",
  refund_difference: "Refund the extra",
  reinstate: "Reinstate order",
  cancel_order: "Cancel order",
  dismiss: "Dismiss",
  customer_fault: "Customer's fault: no refund",
  rider_fault: "Rider's fault: refund + strike",
  hotel_fault: "Hotel's fault: refund",
  pay_rider: "Pay the rider",
  no_payment: "Don't pay",
};
const ADMIN_TYPES = ["failed_delivery", "fee_dispute"];

function minutesAgo(iso: string) {
  return Math.round((Date.now() - new Date(iso).getTime()) / 60000);
}

type Alert = { order_id: string; code: string; hotel: string; hotel_phone: string; minutes: number; auto_reject_in: number };

function DutyAlerts() {
  const q = useQuery({ queryKey: ["admin", "alerts"], queryFn: () => api.get<{ unaccepted: Alert[] }>("/admin/alerts"), refetchInterval: 15_000 });
  const list = q.data?.unaccepted ?? [];
  if (!list.length) return null;
  return (
    <section className="rounded-3xl border-2 border-bad/40 bg-bad-soft p-5">
      <h2 className="mb-3 flex items-center gap-2 text-[1rem] font-bold text-bad"><BellRing className="size-5 animate-pulse" /> Orders not accepted</h2>
      <ul className="flex flex-col gap-2">
        {list.map((a) => (
          <li key={a.order_id} className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-surface p-3 text-sm">
            <span>
              <strong>{a.hotel}</strong> · #{a.code} · waiting <strong>{a.minutes} min</strong>
              <span className="text-muted"> · auto-cancel in {a.auto_reject_in} min</span>
            </span>
            <a href={`tel:+${a.hotel_phone}`} className="flex h-9 items-center gap-1.5 rounded-xl bg-bad px-3 font-semibold text-white">
              <Phone className="size-4" /> Call hotel
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
}

type Found = {
  id: string;
  code: string;
  status: string;
  type: string;
  hotel_name: string;
  hotel_phone: string;
  customer_name: string;
  customer_phone: string;
  till_amount: number;
  items: string[];
  reason: string | null;
  rider_name: string | null;
  can_cancel: boolean;
};
const CANCEL_REASONS: [string, string][] = [
  ["customer_asked", "Customer asked"],
  ["ran_out", "Hotel ran out"],
  ["kitchen_problem", "Kitchen problem"],
  ["other", "Other"],
];

/** Support calls: look an order up by its number; cancel & refund it if the hotel can't finish. */
function FindOrder() {
  const [code, setCode] = useState("");
  const [query, setQuery] = useState("");
  const [note, setNote] = useState("");
  const found = useQuery({ queryKey: ["admin", "order", query], queryFn: () => api.get<Found>(`/admin/orders/${encodeURIComponent(query)}`), enabled: query.length >= 6, retry: false });
  const cancel = useMutation({
    mutationFn: (reason: string) => api.post(`/admin/orders/${found.data!.id}/cancel`, { reason, note: note.trim() || null }),
    onSuccess: () => found.refetch(),
  });
  const o = found.data;
  return (
    <section className="rounded-3xl border border-line bg-surface p-5">
      <form onSubmit={(e) => { e.preventDefault(); setQuery(code.replace("#", "")); }} className="flex gap-2">
        <input value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="Find an order by number, e.g. 7C37Y6" aria-label="Order number" className="money h-11 min-w-0 flex-1 rounded-xl border border-line bg-surface px-3 font-bold tracking-wider outline-none focus:border-brand" />
        <button className="h-11 rounded-xl bg-ink px-5 text-sm font-semibold text-surface">Find</button>
      </form>
      {found.error ? <p className="mt-3 text-sm text-bad">No order with that number.</p> : null}
      {o ? (
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-lg font-bold">#{o.code} · {o.hotel_name}</p>
            <Badge tone={o.can_cancel ? "warn" : "neutral"}>{o.status.replace("_", " ")}</Badge>
          </div>
          <p className="text-sm">{o.customer_name} · {o.type} · <span className="money font-semibold">{money(o.till_amount)}</span>{o.rider_name ? ` · rider ${o.rider_name}` : ""}</p>
          <p className="text-sm text-muted">{o.items.join(", ")}</p>
          {o.reason ? <p className="text-sm text-muted">Reason: {o.reason}</p> : null}
          <div className="flex flex-wrap gap-2">
            <a href={`tel:+${o.customer_phone}`} className="flex h-10 items-center gap-1.5 rounded-xl border border-line px-3 text-sm font-semibold"><Phone className="size-4" /> Customer</a>
            <a href={`tel:+${o.hotel_phone}`} className="flex h-10 items-center gap-1.5 rounded-xl border border-line px-3 text-sm font-semibold"><Phone className="size-4" /> Hotel</a>
          </div>
          {o.can_cancel ? (
            <div className="rounded-2xl bg-bad-soft/50 p-3">
              <p className="mb-2 text-sm font-semibold">Cancel & refund (everything paid goes back; the hotel sends it)</p>
              <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="Note for the customer" className="mb-2 h-10 w-full rounded-lg border border-line bg-surface px-3 text-sm" />
              <div className="flex flex-wrap gap-2">
                {CANCEL_REASONS.map(([value, label]) => (
                  <button key={value} onClick={() => cancel.mutate(value)} disabled={cancel.isPending} className="h-10 rounded-xl border border-bad/40 bg-surface px-3 text-sm font-semibold text-bad">{label}</button>
                ))}
              </div>
              <ErrorNote error={cancel.error} />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function ReviewPage() {
  const qc = useQueryClient();
  const items = useQuery({ queryKey: ["admin", "reviews"], queryFn: () => api.get<Review[]>("/admin/review-items"), refetchInterval: 15_000 });
  const resolve = useMutation({
    mutationFn: ({ id, action }: { id: string; action: string }) => api.post(`/admin/review-items/${id}/resolve`, { action }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "reviews"] }),
  });

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">Needs attention</h1>
        <p className="text-sm text-muted">Each hotel resolves its own payment problems first. After 15 minutes they show here: call the hotel, or settle it yourself. Messages that belong to no hotel are yours.</p>
      </div>
      <FindOrder />
      <DutyAlerts />
      <div className="max-w-4xl">
        <section className="rounded-3xl border border-line bg-surface p-5">
          {items.isLoading ? (
            <Skeleton className="h-40" />
          ) : items.data?.length ? (
            <ul className="flex flex-col gap-3">
              {items.data.map((r) => {
                const old = minutesAgo(r.created_at) >= 15;
                const ours = !r.hotel_name || ADMIN_TYPES.includes(r.type);
                const canAct = ours || old; // after 15 min the owner may settle a hotel's item too
                return (
                  <li key={r.id} className={clsx("rounded-2xl border p-4", old ? "border-bad/40 bg-bad-soft/40" : "border-line")}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone="warn">{r.type.replace("_", " ")}</Badge>
                        <span className="font-bold">{r.hotel_name ?? "No hotel"}</span>
                        {r.order_code ? <span className="text-muted">#{r.order_code}</span> : null}
                      </div>
                      <span className={clsx("text-xs font-semibold", old && !ours ? "text-bad" : "text-muted")}>open {minutesAgo(r.created_at)} min</span>
                    </div>
                    <p className="mt-2 text-sm">{r.reason}</p>
                    {r.amount != null ? (
                      <p className="text-sm text-muted">
                        {r.trans_code} · <span className="money">{money(r.amount)}</span>
                        {r.order_total != null ? <> of <span className="money">{money(r.order_total)}</span></> : null}
                      </p>
                    ) : null}
                    <div className="mt-3 flex flex-wrap gap-2">
                      {r.hotel_phone && !ADMIN_TYPES.includes(r.type) && !ours ? (
                        <a href={`tel:+${r.hotel_phone}`} className="flex h-10 items-center gap-1.5 rounded-xl bg-bad px-4 text-sm font-semibold text-white">
                          <Phone className="size-4" /> Call {r.hotel_name}
                        </a>
                      ) : null}
                      {canAct && r.actions.map((a) => (
                        <button key={a} onClick={() => resolve.mutate({ id: r.id, action: a })} disabled={resolve.isPending} className={clsx("h-10 rounded-xl px-4 text-sm font-semibold", a === "dismiss" ? "border border-line" : "bg-ink text-surface")}>
                          {LABEL[a] ?? a}
                        </button>
                      ))}
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="flex items-center gap-2 py-8 text-sm text-muted"><CheckCircle2 className="size-5 text-ok" /> Nothing needs you. Hotels are on top of their payments.</p>
          )}
          <ErrorNote error={resolve.error} />
        </section>
      </div>
    </div>
  );
}
