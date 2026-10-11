/** The owner's view of one hotel: how it is doing, whether it may be dodging commission,
 * and the controls to fix its details, including the exact map location. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { AlertTriangle, ArrowLeft, Banknote, CheckCircle2, MapPin, Pause, Play, Store } from "lucide-react";
import { Suspense, lazy, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Stars } from "../components/accounts";
import { ErrorBoundary, MapFailed } from "../components/ErrorBoundary";
import { Badge, Button, ErrorNote, Field, Input, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { StaffList, VerifyPanel, type Hotel } from "./HotelsPage";

const MapPicker = lazy(() => import("../customer/MapPicker"));

type Flag = { level: "high" | "medium" | "info"; title: string; detail: string };
type Overview = {
  hotel: Hotel & { commission_percent: number | null; accepting_orders: boolean; pause_reason: string | null };
  stats: {
    paid_orders: number;
    completed: number;
    rejected_or_cancelled: number;
    sales: number;
    commission: number;
    avg_order: number;
    median_accept_minutes: number | null;
    last_7_days: number;
    previous_7_days: number;
  };
  flags: Flag[];
  location_check: { samples: number; lat: number; lng: number; off_by_m: number | null } | null;
  billing: { due_now: number; due_date: string | null; overdue: boolean; unpaid_limit: number; balance: number; pending_claims: number };
  recent_orders: {
    id: string;
    code: string;
    status: string;
    type: string;
    items_total: number;
    order_discount: number;
    food_net: number;
    commission: number;
    created_at: string;
    paid: boolean;
    reason: string | null;
  }[];
  changes: { at: string; action: string; what: string[] }[];
};

const KEY = (id: string) => ["admin", "hotel", id];

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "bad" | "warn" }) {
  return (
    <div className="rounded-2xl border border-line bg-surface p-3">
      <p className="text-xs font-medium text-muted">{label}</p>
      <p className={clsx("money mt-0.5 text-xl font-bold", tone === "bad" && "text-bad", tone === "warn" && "text-warn")}>{value}</p>
      {sub ? <p className="text-xs text-muted">{sub}</p> : null}
    </div>
  );
}

function Flags({ flags }: { flags: Flag[] }) {
  if (!flags.length)
    return (
      <p className="flex items-center gap-2 rounded-2xl border border-line bg-surface px-4 py-3 text-sm font-medium text-ok">
        <CheckCircle2 className="size-4" /> Nothing unusual in the last 30 days.
      </p>
    );
  return (
    <ul className="flex flex-col gap-2">
      {flags.map((f) => (
        <li key={f.title} className={clsx("rounded-2xl border px-4 py-3", f.level === "high" ? "border-bad/30 bg-bad-soft" : "border-warn/30 bg-warn-soft")}>
          <p className={clsx("flex items-center gap-2 text-sm font-bold", f.level === "high" ? "text-bad" : "text-warn")}>
            <AlertTriangle className="size-4" /> {f.title}
          </p>
          <p className="mt-0.5 text-sm text-ink">{f.detail}</p>
        </li>
      ))}
    </ul>
  );
}

function LocationPanel({ data, onSaved }: { data: Overview; onSaved: () => void }) {
  const { hotel, location_check: check } = data;
  const saved = hotel.lat != null && hotel.lng != null ? { lat: hotel.lat, lng: hotel.lng } : null;
  const [pin, setPin] = useState(saved);
  useEffect(() => setPin(saved), [hotel.lat, hotel.lng]); // eslint-disable-line react-hooks/exhaustive-deps
  const save = useMutation({
    mutationFn: (p: { lat: number; lng: number }) =>
      api.patch(`/admin/hotels/${hotel.id}`, { lat: +p.lat.toFixed(6), lng: +p.lng.toFixed(6) }),
    onSuccess: onSaved,
  });
  const changed = pin && (pin.lat !== saved?.lat || pin.lng !== saved?.lng);
  return (
    <section className="rounded-3xl border border-line bg-surface p-4">
      <h2 className="flex items-center gap-2 font-bold"><MapPin className="size-4 text-brand" /> Location</h2>
      <p className="mt-0.5 mb-3 text-xs text-muted">Delivery fees and "hotels near you" use this pin. Search the place, switch to satellite, and put it on the door.</p>
      {check && check.off_by_m != null && check.off_by_m > 150 ? (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl bg-warn-soft px-3 py-2 text-sm">
          <span>Riders collected about <b>{check.off_by_m} m</b> from this pin across {check.samples} pickups.</span>
          <Button variant="secondary" onClick={() => setPin({ lat: check.lat, lng: check.lng })}>Use where riders collect</Button>
        </div>
      ) : null}
      <Suspense fallback={<Skeleton className="h-72" />}>
        <ErrorBoundary fallback={(retry) => <MapFailed retry={retry} />}>
          <MapPicker value={pin} onChange={setPin} checkZone={false} height="h-80" precise />
        </ErrorBoundary>
      </Suspense>
      {changed ? (
        <div className="mt-3 flex items-center gap-3">
          <Button busy={save.isPending} onClick={() => save.mutate(pin!)}>Save location</Button>
          <Button variant="ghost" onClick={() => setPin(saved)}>Undo</Button>
        </div>
      ) : null}
      <ErrorNote error={save.error} />
    </section>
  );
}

function DetailsPanel({ data, onSaved }: { data: Overview; onSaved: () => void }) {
  const h = data.hotel;
  const [name, setName] = useState(h.name);
  const [phone, setPhone] = useState(h.phone);
  const [till, setTill] = useState(h.till_number);
  const [commission, setCommission] = useState(h.commission_percent == null ? "" : String(h.commission_percent));
  const save = useMutation({
    mutationFn: () =>
      api.patch(`/admin/hotels/${h.id}`, {
        name: name.trim(),
        phone: phone.trim(),
        till_number: till.trim(),
        commission_percent: commission.trim() === "" ? null : Number(commission),
      }),
    onSuccess: onSaved,
  });
  return (
    <section className="rounded-3xl border border-line bg-surface p-4">
      <h2 className="flex items-center gap-2 font-bold"><Store className="size-4 text-brand" /> Hotel details</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <Field label="Name">{(id) => <Input id={id} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <Field label="Phone (2547…)">{(id) => <Input id={id} value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="numeric" />}</Field>
        <Field label="Till number">{(id) => <Input id={id} value={till} onChange={(e) => setTill(e.target.value)} inputMode="numeric" />}</Field>
        <Field label="Commission % (blank = platform default)">{(id) => <Input id={id} value={commission} onChange={(e) => setCommission(e.target.value)} inputMode="decimal" />}</Field>
      </div>
      <p className="mt-2 text-xs text-muted">Changing the Till removes the "Checked" badge until you verify it again. Every change is recorded below.</p>
      <ErrorNote error={save.error} />
      <div className="mt-3"><Button onClick={() => save.mutate()} busy={save.isPending}>Save details</Button></div>
    </section>
  );
}

export function HotelDetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: KEY(id), queryFn: () => api.get<Overview>(`/admin/hotels/${id}/overview`), enabled: !!id });
  const refresh = () => Promise.all([qc.invalidateQueries({ queryKey: KEY(id) }), qc.invalidateQueries({ queryKey: ["admin", "hotels"] })]);
  const setStatus = useMutation({
    mutationFn: (status: "active" | "paused") => api.patch(`/admin/hotels/${id}`, { status, pause_reason: status === "paused" ? "Paused by the owner" : null }),
    onSuccess: refresh,
  });

  if (q.isLoading) return <div className="mx-auto max-w-4xl p-4 sm:p-6"><Skeleton className="h-64 rounded-3xl" /></div>;
  if (!q.data) return <div className="mx-auto max-w-4xl p-4 sm:p-6"><ErrorNote error={q.error} /></div>;
  const d = q.data;
  const h = d.hotel;
  const s = d.stats;
  const trend = s.previous_7_days ? Math.round((100 * (s.last_7_days - s.previous_7_days)) / s.previous_7_days) : null;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-5 p-4 sm:p-6">
      <Link to="/admin/hotels" className="inline-flex w-fit items-center gap-1 text-sm font-semibold text-muted hover:text-ink"><ArrowLeft className="size-4" /> All hotels</Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">{h.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted">
            {h.status === "paused" ? <Badge tone="warn">Paused</Badge> : <Badge tone="ok">Active</Badge>}
            {h.verified ? <Badge tone="ok">Checked</Badge> : <Badge tone="warn">Not checked</Badge>}
            <Stars rating={h.rating} count={h.rating_count} />
            <span className="money">{h.phone}</span>
          </p>
        </div>
        {h.status === "paused" ? (
          <Button onClick={() => setStatus.mutate("active")} busy={setStatus.isPending}><Play className="size-4" /> Resume orders</Button>
        ) : (
          <Button variant="secondary" onClick={() => setStatus.mutate("paused")} busy={setStatus.isPending}><Pause className="size-4" /> Pause orders</Button>
        )}
      </div>
      <ErrorNote error={setStatus.error} />

      <section className="flex flex-col gap-2">
        <h2 className="font-bold">Things to look at</h2>
        <Flags flags={d.flags} />
      </section>

      <section>
        <h2 className="mb-2 font-bold">Last 30 days</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Tile label="Paid orders" value={String(s.paid_orders)} sub={`${s.completed} completed`} />
          <Tile label="Sales (food)" value={money(s.sales)} sub={s.avg_order ? `avg ${money(s.avg_order)}` : undefined} />
          <Tile label="Commission earned" value={money(s.commission)} />
          <Tile label="This week vs last" value={`${s.last_7_days} / ${s.previous_7_days}`} sub={trend == null ? undefined : `${trend > 0 ? "+" : ""}${trend}%`} tone={trend != null && trend <= -50 ? "warn" : undefined} />
          <Tile label="Rejected / cancelled" value={String(s.rejected_or_cancelled)} />
          <Tile label="Accepts in" value={s.median_accept_minutes == null ? "—" : `${s.median_accept_minutes} min`} sub="median after payment" />
          <Tile label="Owes you now" value={money(d.billing.due_now)} sub={d.billing.due_date ? `due ${d.billing.due_date}` : undefined} tone={d.billing.overdue ? "bad" : undefined} />
          <Tile label="Unpaid balance" value={money(d.billing.balance)} sub={`limit ${money(d.billing.unpaid_limit)}`} />
        </div>
        <Link to="/admin/billing" className="mt-2 inline-flex items-center gap-1 text-sm font-semibold text-brand"><Banknote className="size-4" /> Billing and payments</Link>
      </section>

      <LocationPanel data={d} onSaved={refresh} />
      <DetailsPanel key={`${h.name}-${h.phone}-${h.till_number}-${h.commission_percent}`} data={d} onSaved={refresh} />
      <VerifyPanel key={`${h.till_number}-${h.till_name}-${h.verified}`} hotel={h} />
      <StaffList hotel={h} />

      <section className="rounded-3xl border border-line bg-surface p-4">
        <h2 className="font-bold">Recent orders</h2>
        {d.recent_orders.length === 0 ? <p className="mt-2 text-sm text-muted">No orders in the last 30 days.</p> : (
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[34rem] text-left text-sm">
              <thead className="text-xs text-muted"><tr><th className="py-1.5 pr-3">Code</th><th className="pr-3">When</th><th className="pr-3">Type</th><th className="pr-3">Status</th><th className="pr-3 text-right">Food</th><th className="pr-3 text-right">Discount</th><th className="text-right">Commission</th></tr></thead>
              <tbody>
                {d.recent_orders.map((o) => (
                  <tr key={o.id} className="border-t border-line align-top">
                    <td className="money py-1.5 pr-3 font-semibold">{o.code}</td>
                    <td className="pr-3 text-muted">{new Date(o.created_at).toLocaleString("en-KE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                    <td className="pr-3">{o.type.replace("_", " ")}</td>
                    <td className="pr-3">{o.status.replace(/_/g, " ")}{!o.paid ? <span className="text-muted"> (unpaid)</span> : null}{o.reason ? <span className="block text-xs text-muted">{o.reason}</span> : null}</td>
                    <td className="money pr-3 text-right">{money(o.food_net)}</td>
                    <td className="money pr-3 text-right">{o.order_discount ? money(o.order_discount) : "—"}</td>
                    <td className="money text-right">{o.status === "delivered" || o.status === "collected" ? money(o.commission) : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="rounded-3xl border border-line bg-surface p-4">
        <h2 className="font-bold">Change log</h2>
        {d.changes.length === 0 ? <p className="mt-2 text-sm text-muted">No changes recorded.</p> : (
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {d.changes.map((c, i) => (
              <li key={i} className="flex flex-wrap gap-x-3 text-muted">
                <span>{new Date(c.at).toLocaleString("en-KE", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span>
                <span className="text-ink">{c.action.replace(".", " ")}{c.what.length ? `: ${c.what.join(", ").replace(/_/g, " ")}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
