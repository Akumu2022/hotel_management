/**
 * Hotel order board (spec section 10, D.CC "Order queues" style). Live over SSE; a loud
 * repeating alert plays while any new order is waiting (D6), until someone taps Accept.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bell, BellOff, Bike, Check, ChefHat, Clock, PackageCheck, Phone, Store, UtensilsCrossed, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge, ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { useAlarmUnlocked } from "../lib/alarm";
import { useHotelSettings, useIsAdmin } from "./hooks";

/** Who paid, from the Till SMS, and whether it's the name given at checkout (D25). Someone
 * else paying is normal (a friend, a parent), so this informs; it never blocks. */
function PayerName({ name, match }: { name: string; match: number | null }) {
  const tone = match === 2 ? "text-ok" : match === 1 ? "text-muted" : match === 0 ? "text-warn" : "text-muted";
  const label = match === 2 ? "name matches" : match === 1 ? "one name matches" : match === 0 ? "different name from checkout" : "";
  return (
    <p className={`mt-1 text-xs ${tone}`}>
      💳 Paid by <span className="font-semibold">{name}</span>
      {label ? ` · ${label}` : ""}
    </p>
  );
}

type BoardOrder = {
  id: string;
  code: string;
  status: string;
  type: "delivery" | "pickup" | "eat_in";
  arrive_at?: string | null;
  payment_method: "mpesa" | "cash";
  rider_fee_mode: string;
  customer_name: string;
  customer_phone: string;
  till_amount: number;
  rider_fee: number;
  distance_km: number | null;
  items: string[];
  created_at: string;
  paid_at: string | null;
  accepted_at: string | null;
  ready_at: string | null;
  prep_minutes: number | null;
  landmark: string | null;
  reason: string | null;
  platform_bonus: number;
  payer_name: string | null;
  name_match: number | null;
  rider_name: string | null;
  rider_phone: string | null;
  rider_photo_url: string | null;
  fee_with_food: boolean;
  fee_handed: boolean;
};

const PREP = [10, 15, 20, 30, 45];
const REASONS: [string, string][] = [
  ["sold_out", "An item is sold out"],
  ["too_busy", "Kitchen too busy"],
  ["closing", "We're closing"],
  ["cannot_deliver", "Can't deliver there"],
  ["other", "Other reason"],
];
const CANCEL_REASONS: [string, string][] = [
  ["ran_out", "We ran out of an item"],
  ["kitchen_problem", "Kitchen problem (gas, power…)"],
  ["customer_asked", "The customer asked to cancel"],
  ["other", "Something else"],
];
const TIMEOUT_MIN = 10; // D6 default; the server enforces the configured value

// --- Cards --------------------------------------------------------------------------------------

function minutesSince(iso: string | null) {
  return iso ? Math.floor((Date.now() - new Date(iso).getTime()) / 60000) : 0;
}

function useTick(ms = 15000) {
  const [, set] = useState(0);
  useEffect(() => {
    const t = setInterval(() => set((n) => n + 1), ms);
    return () => clearInterval(t);
  }, [ms]);
}

function OrderCard({ o, onAction, canCancel }: { o: BoardOrder; onAction: (o: BoardOrder, a: string) => void; canCancel: boolean }) {
  useTick();
  const isNew = o.status === "paid" || o.status === "awaiting_payment";
  const waited = minutesSince(o.paid_at ?? o.created_at);
  const left = TIMEOUT_MIN - waited;
  const readyIn = o.accepted_at && o.prep_minutes ? o.prep_minutes - minutesSince(o.accepted_at) : null;

  return (
    <li className={clsx("rounded-2xl border bg-surface p-4 transition-shadow", isNew ? "border-brand shadow-lg shadow-brand/15 ring-2 ring-brand/20" : "border-line")}>
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-lg font-extrabold">#{o.code}</p>
          <p className="text-sm font-medium">{o.customer_name}</p>
        </div>
        <div className="flex flex-col items-end gap-1">
          {o.type === "eat_in" ? (
            // D28: eat in must stand out: the customer is coming to sit down at this time.
            <Badge tone="warn">
              <UtensilsCrossed className="mr-1 inline size-3.5" />
              EAT IN{o.arrive_at ? ` · arrives ${new Intl.DateTimeFormat("en-KE", { hour: "numeric", minute: "2-digit", timeZone: "Africa/Nairobi" }).format(new Date(o.arrive_at))}` : ""}
            </Badge>
          ) : (
            <Badge tone={o.type === "delivery" ? "brand" : "neutral"}>
              {o.type === "delivery" ? <Bike className="mr-1 inline size-3.5" /> : <Store className="mr-1 inline size-3.5" />}
              {o.type === "delivery" ? `Delivery${o.distance_km != null ? ` · ${o.distance_km} km` : ""}` : "Pickup"}
            </Badge>
          )}
          {o.payment_method === "cash" && !o.paid_at ? <Badge tone="warn">Cash at counter</Badge> : <Badge tone="ok">Paid</Badge>}
        </div>
      </div>

      <ul className="my-3 flex flex-col gap-1 rounded-xl bg-subtle p-3 text-sm">
        {o.items.map((it, i) => (
          <li key={i} className="font-medium">{it}</li>
        ))}
      </ul>

      <div className="flex items-center justify-between text-sm">
        <span className="money font-bold">
          {money(o.till_amount)}
          {o.platform_bonus ? <span className="ml-1.5 text-xs font-semibold text-ok">+{money(o.platform_bonus)} from Chakula</span> : null}
        </span>
        <a href={`tel:+${o.customer_phone}`} className="flex items-center gap-1 font-semibold text-brand">
          <Phone className="size-3.5" /> Call
        </a>
      </div>
      {o.landmark ? <p className="mt-1 text-xs text-muted">📍 {o.landmark}</p> : null}
      {o.payer_name ? <PayerName name={o.payer_name} match={o.name_match} /> : null}

      {isNew ? (
        <>
          <p className={clsx("mt-3 flex items-center gap-1.5 text-xs font-semibold", left <= 3 ? "text-bad" : "text-warn")}>
            <Clock className="size-3.5" />
            {left > 0 ? `Accept within ${left} min or it is cancelled automatically` : "Being cancelled: not accepted in time"}
          </p>
          <div className="mt-3 grid grid-cols-[1fr_auto] gap-2">
            <button onClick={() => onAction(o, "accept")} className="h-12 rounded-xl bg-ok text-[0.9375rem] font-bold text-white shadow-md shadow-ok/25 hover:brightness-95">
              Accept
            </button>
            <button onClick={() => onAction(o, "reject")} className="h-12 rounded-xl border border-line px-4 text-sm font-semibold text-muted hover:border-bad/40 hover:text-bad">
              Reject
            </button>
          </div>
        </>
      ) : o.status === "accepted" ? (
        <button onClick={() => onAction(o, "preparing")} className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand font-semibold text-white">
          <ChefHat className="size-4" /> Start preparing
        </button>
      ) : o.status === "preparing" ? (
        <>
          {readyIn != null ? (
            <p className={clsx("mt-3 text-xs font-semibold", readyIn < 0 ? "text-bad" : "text-muted")}>
              {readyIn >= 0 ? `Promised ready in ${readyIn} min` : `${-readyIn} min past the promised time`}
            </p>
          ) : null}
          <button onClick={() => onAction(o, "ready")} className="mt-2 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-brand font-semibold text-white">
            <Check className="size-4" /> Mark ready
          </button>
        </>
      ) : o.status === "ready" && o.type !== "delivery" ? (
        <button onClick={() => onAction(o, "collected")} className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-xl bg-ok font-semibold text-white">
          <PackageCheck className="size-4" /> {o.payment_method === "cash" && !o.paid_at ? `Cash received & handed over` : o.type === "eat_in" ? "Served to customer" : "Handed to customer"}
        </button>
      ) : null}
      {o.type === "delivery" && ["accepted", "preparing", "ready"].includes(o.status) ? (
        o.rider_name ? (
          <div className="mt-3 flex items-center gap-3 rounded-xl bg-subtle p-2.5">
            {o.rider_photo_url ? <img src={o.rider_photo_url} alt="" className="size-10 rounded-full object-cover" /> : <span className="flex size-10 items-center justify-center rounded-full bg-surface"><Bike className="size-5 text-brand" /></span>}
            <span className="min-w-0 flex-1 text-sm">
              <span className="block font-bold">Rider: {o.rider_name}</span>
              <span className="block text-muted">{o.status === "ready" ? "Coming for the food" : "Will collect when ready"}</span>
            </span>
            <a href={`tel:+${o.rider_phone}`} aria-label="Call rider" className="flex size-10 items-center justify-center rounded-lg bg-surface text-brand"><Phone className="size-4" /></a>
          </div>
        ) : (
          <p className="mt-3 rounded-xl bg-subtle px-3 py-2 text-center text-sm font-medium text-muted">{o.status === "ready" ? "Waiting for a rider to take it" : "A rider will be found"}</p>
        )
      ) : null}
      {o.type === "delivery" && o.status === "ready" && o.rider_name ? (
        <button onClick={() => onAction(o, "handed-to-rider")} className="mt-2 flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-ok px-3 py-2 font-semibold text-white">
          <PackageCheck className="size-4 shrink-0" /> {o.fee_with_food ? `Handed food + ${money(o.rider_fee)} fee to ${o.rider_name}` : `Handed to ${o.rider_name}`}
        </button>
      ) : null}
      {canCancel && ["accepted", "preparing", "ready"].includes(o.status) ? (
        <button onClick={() => onAction(o, "cancel")} className="mt-2 w-full text-center text-sm font-semibold text-muted hover:text-bad">
          Can't finish this order?
        </button>
      ) : null}
    </li>
  );
}

function Column({ title, tone, orders, onAction, empty, canCancel }: { title: string; tone: string; orders: BoardOrder[]; onAction: (o: BoardOrder, a: string) => void; empty: string; canCancel: boolean }) {
  return (
    <section className="flex min-w-0 flex-col rounded-[1.5rem] bg-surface p-4 shadow-sm">
      <h2 className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-2 font-bold">
          <span className={clsx("size-2.5 rounded-full", tone)} /> {title}
        </span>
        <span className="rounded-full bg-subtle px-2.5 py-0.5 text-sm font-bold">{orders.length}</span>
      </h2>
      {orders.length ? (
        <ul className="flex flex-col gap-3">{orders.map((o) => <OrderCard key={o.id} o={o} onAction={onAction} canCancel={canCancel} />)}</ul>
      ) : (
        <p className="rounded-xl border border-dashed border-line py-8 text-center text-sm text-muted">{empty}</p>
      )}
    </section>
  );
}

// --- Page ---------------------------------------------------------------------------------------

export function OrdersPage() {
  const qc = useQueryClient();
  const { data: settings } = useHotelSettings();
  const board = useQuery({ queryKey: ["hotel", "orders", "active"], queryFn: () => api.get<BoardOrder[]>("/hotel/orders"), refetchInterval: 30_000 });
  const done = useQuery({ queryKey: ["hotel", "orders", "done"], queryFn: () => api.get<BoardOrder[]>("/hotel/orders?view=done"), refetchInterval: 60_000 });
  const soundOn = useAlarmUnlocked();
  const isAdmin = useIsAdmin();
  const [cancelling, setCancelling] = useState<BoardOrder | null>(null);
  const [accepting, setAccepting] = useState<BoardOrder | null>(null);
  const [rejecting, setRejecting] = useState<BoardOrder | null>(null);
  const [note, setNote] = useState("");

  const refresh = useCallback(() => {
    void qc.invalidateQueries({ queryKey: ["hotel", "orders"] });
    void qc.invalidateQueries({ queryKey: ["hotel", "payments"] });
  }, [qc]);

  const orders = board.data ?? [];
  const fresh = orders.filter((o) => o.status === "paid" || o.status === "awaiting_payment");
  const kitchen = orders.filter((o) => o.status === "accepted" || o.status === "preparing");
  const ready = orders.filter((o) => o.status === "ready");

  const act = useMutation({
    mutationFn: ({ o, action, body }: { o: BoardOrder; action: string; body?: unknown }) => api.post(`/hotel/orders/${o.id}/${action}`, body),
    onSuccess: refresh,
  });
  const onAction = (o: BoardOrder, a: string) => {
    if (a === "accept") setAccepting(o);
    else if (a === "reject") {
      setNote("");
      setRejecting(o);
    } else if (a === "cancel") {
      setNote("");
      setCancelling(o);
    } else act.mutate({ o, action: a });
  };

  return (
    <div className="flex flex-col gap-5">
      {soundOn ? (
        <p className="flex items-center gap-2 text-sm font-medium text-ok">
          <Bell className="size-4" /> Alarm on: new orders keep ringing until someone accepts or rejects them.
        </p>
      ) : null}
      {settings && !settings.accepting_orders ? (
        <p className="flex items-center gap-2 rounded-2xl bg-bad-soft px-4 py-3 text-sm font-semibold text-bad">
          <BellOff className="size-4" /> You're not accepting orders. Switch it on at the top when you're ready.
        </p>
      ) : null}
      <ErrorNote error={act.error} />

      {board.isLoading ? (
        <div className="grid gap-5 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-72 rounded-[1.5rem]" />)}</div>
      ) : (
        <div className="grid items-start gap-5 lg:grid-cols-3">
          <Column title="New" tone="bg-brand animate-pulse" orders={fresh} onAction={onAction} empty="New orders appear here and ring." canCancel={isAdmin} />
          <Column title="In the kitchen" tone="bg-warn" orders={kitchen} onAction={onAction} empty="Nothing cooking." canCancel={isAdmin} />
          <Column title="Ready" tone="bg-ok" orders={ready} onAction={onAction} empty="Nothing waiting for pickup." canCancel={isAdmin} />
        </div>
      )}

      {done.data?.length ? (
        <section className="rounded-[1.5rem] bg-surface p-4 shadow-sm">
          <h2 className="mb-3 font-bold">Done today</h2>
          <ul className="divide-y divide-line text-sm">
            {done.data.map((o) => (
              <li key={o.id} className="flex items-center justify-between gap-2 py-2">
                <span>
                  <strong>#{o.code}</strong> · {o.customer_name}
                  {o.reason ? <span className="text-muted"> · {o.reason}</span> : null}
                </span>
                <Badge tone={o.status === "rejected" || o.status === "cancelled" ? "bad" : "ok"}>{o.status.replace("_", " ")}</Badge>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {/* Accept: pick prep time */}
      {accepting ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center" onClick={() => setAccepting(null)}>
          <div role="dialog" aria-modal="true" aria-label="Accept order" onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-3xl bg-surface p-6">
            <h2 className="text-xl font-bold">Accept #{accepting.code}</h2>
            <p className="mt-1 text-sm text-muted">How long until it's ready? The customer sees this.</p>
            <div className="mt-4 grid grid-cols-3 gap-2">
              {PREP.map((m) => (
                <button
                  key={m}
                  onClick={() => {
                    act.mutate({ o: accepting, action: "accept", body: { prep_minutes: m } });
                    setAccepting(null);
                  }}
                  className="h-14 rounded-xl border-2 border-line text-lg font-bold hover:border-ok hover:bg-ok-soft"
                >
                  {m} min
                </button>
              ))}
            </div>
            <button onClick={() => setAccepting(null)} className="mt-4 h-11 w-full rounded-xl text-sm font-semibold text-muted">Cancel</button>
          </div>
        </div>
      ) : null}

      {/* Cancel after accepting: hotel admin only; refunds what was paid */}
      {cancelling ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center" onClick={() => setCancelling(null)}>
          <div role="dialog" aria-modal="true" aria-label="Cancel order" onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-3xl bg-surface p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold">Cancel #{cancelling.code}?</h2>
              <button onClick={() => setCancelling(null)} aria-label="Close" className="rounded-full p-1 text-muted"><X className="size-5" /></button>
            </div>
            <p className="mt-1 text-sm text-muted">
              {cancelling.paid_at ? `The customer gets back the ${money(cancelling.till_amount)} they paid: you send it from the Payments page.` : "The customer is told why."}
              {cancelling.rider_name ? ` ${cancelling.rider_name} loses the delivery job.` : ""}
            </p>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="Note for the customer, e.g. which item" className="mt-4 h-11 w-full rounded-xl border border-line bg-surface px-3 text-sm outline-none focus:border-brand" />
            <div className="mt-3 flex flex-col gap-2">
              {CANCEL_REASONS.map(([code, label]) => (
                <button
                  key={code}
                  onClick={() => {
                    act.mutate({ o: cancelling, action: "cancel", body: { reason: code, note: note.trim() || null } });
                    setCancelling(null);
                  }}
                  className="h-11 rounded-xl border border-line text-sm font-semibold hover:border-bad/40 hover:bg-bad-soft hover:text-bad"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {/* Reject: pick a reason */}
      {rejecting ? (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 p-4 sm:items-center" onClick={() => setRejecting(null)}>
          <div role="dialog" aria-modal="true" aria-label="Reject order" onClick={(e) => e.stopPropagation()} className="w-full max-w-sm rounded-3xl bg-surface p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold">Reject #{rejecting.code}?</h2>
              <button onClick={() => setRejecting(null)} aria-label="Close" className="rounded-full p-1 text-muted"><X className="size-5" /></button>
            </div>
            <p className="mt-1 text-sm text-muted">
              {rejecting.paid_at ? "The customer has paid: a full refund is created for you to send." : "The customer is told why."}
            </p>
            <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} placeholder="Optional note, e.g. which item" className="mt-4 h-11 w-full rounded-xl border border-line bg-surface px-3 text-sm outline-none focus:border-brand" />
            <div className="mt-3 flex flex-col gap-2">
              {REASONS.map(([code, label]) => (
                <button
                  key={code}
                  onClick={() => {
                    act.mutate({ o: rejecting, action: "reject", body: { reason: code, note: note.trim() || null } });
                    setRejecting(null);
                  }}
                  className="h-11 rounded-xl border border-line text-sm font-semibold hover:border-bad/40 hover:bg-bad-soft hover:text-bad"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
