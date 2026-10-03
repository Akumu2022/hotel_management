/** Super admin dispatch (DECISIONS D21): every delivery in progress, who has it, and assign or
 * reassign until pickup. Riders can also take open jobs themselves. Live over SSE. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bike, CheckCircle2, Phone, UserRound, X, XCircle } from "lucide-react";
import { Suspense, lazy, useEffect, useRef, useState } from "react";

import { ErrorBoundary, MapFailed } from "../components/ErrorBoundary";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";

const DispatchMap = lazy(() => import("./DispatchMap"));

type Row = {
  id: string;
  code: string;
  status: string;
  hotel_name: string;
  customer_name: string;
  landmark: string | null;
  distance_km: number | null;
  rider_fee: number;
  rider_fee_mode: string;
  rider_id: string | null;
  rider_name: string | null;
  accepted_at: string | null;
  ready_at: string | null;
  assigned_at: string | null;
  rider_seen: boolean;
  picked_up_at: string | null;
  hotel_lat: number | null;
  hotel_lng: number | null;
  lat: number | null;
  lng: number | null;
};
type RiderBrief = {
  id: string;
  name: string;
  phone: string;
  photo_url: string | null;
  is_online: boolean;
  active_jobs: number;
  last_code: string | null;
  last_status: string | null;
  last_at: string | null;
  lat: number | null;
  lng: number | null;
  accuracy_m: number | null;
  location_at: string | null;
  live: boolean;
};
type Finished = { id: string; code: string; status: "delivered" | "failed_delivery"; hotel_name: string; customer_name: string; rider_id: string | null; rider_name: string | null; picked_up_at: string | null; closed_at: string };

const clock = new Intl.DateTimeFormat("en-KE", { hour: "2-digit", minute: "2-digit", timeZone: "Africa/Nairobi" });
const ago = (iso: string) => {
  const m = mins(iso) ?? 0;
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : `at ${clock.format(new Date(iso))}`;
};

/** What dispatch needs to know about a rider at a glance (owner, D25). */
function riderState(r: RiderBrief): { label: string; cls: string } {
  if (r.active_jobs) return { label: `On ${r.active_jobs} job${r.active_jobs === 1 ? "" : "s"}`, cls: "bg-warn-soft text-warn" };
  if (r.is_online) return { label: "Free · ready for a job", cls: "bg-ok-soft text-ok" };
  return { label: "Offline", cls: "bg-subtle text-muted" };
}

/** A green notice when a delivery finishes while this screen is open: the rider is free again. */
function useJustFinished(finished: Finished[] | undefined) {
  const seen = useRef<Set<string> | null>(null);
  const [notice, setNotice] = useState<Finished[]>([]);
  useEffect(() => {
    if (!finished) return;
    if (seen.current === null) {
      seen.current = new Set(finished.map((f) => f.id)); // what was already done before opening
      return;
    }
    const fresh = finished.filter((f) => !seen.current!.has(f.id));
    fresh.forEach((f) => seen.current!.add(f.id));
    if (fresh.length) setNotice((n) => [...fresh, ...n].slice(0, 3));
  }, [finished]);
  return [notice, (id: string) => setNotice((n) => n.filter((f) => f.id !== id))] as const;
}

const STEP: Record<string, { label: string; cls: string }> = {
  accepted: { label: "Accepted", cls: "bg-subtle text-muted" },
  preparing: { label: "Cooking", cls: "bg-warn-soft text-warn" },
  ready: { label: "Ready at hotel", cls: "bg-brand-soft text-brand" },
  picked_up: { label: "Picked up", cls: "bg-ok-soft text-ok" },
  on_the_way: { label: "On the way", cls: "bg-ok-soft text-ok" },
};
function mins(iso: string | null) {
  return iso ? Math.round((Date.now() - new Date(iso).getTime()) / 60000) : null;
}

export function DispatchPage() {
  const qc = useQueryClient();
  const board = useQuery({ queryKey: ["admin", "dispatch"], queryFn: () => api.get<{ orders: Row[]; riders: RiderBrief[]; finished: Finished[] }>("/admin/dispatch"), refetchInterval: 20_000 });
  const assign = useMutation({
    mutationFn: ({ order, rider }: { order: string; rider: string }) => api.post(`/admin/dispatch/${order}/assign`, { rider_id: rider }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "dispatch"] }),
  });
  const orders = board.data?.orders ?? [];
  const riders = board.data?.riders ?? [];
  const unassigned = orders.filter((o) => !o.rider_id);
  const finished = board.data?.finished ?? [];
  const [notice, dismiss] = useJustFinished(board.data?.finished);

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">Dispatch</h1>
        <p className="text-sm text-muted">Online riders take open jobs themselves. Step in to assign or swap a rider until the food is picked up.</p>
      </div>
      {notice.map((f) => (
        <div key={f.id} role="status" className={clsx("flex items-center gap-3 rounded-2xl px-4 py-3 text-sm font-semibold", f.status === "delivered" ? "bg-ok text-white" : "bg-bad text-white")}>
          {f.status === "delivered" ? <CheckCircle2 className="size-5 shrink-0" /> : <XCircle className="size-5 shrink-0" />}
          <span className="flex-1">
            {f.status === "delivered" ? `${f.rider_name ?? "The rider"} delivered #${f.code} to ${f.customer_name}. They're free for the next job.` : `#${f.code} could not be delivered (${f.rider_name ?? "rider"}). Check Needs attention.`}
          </span>
          <button onClick={() => dismiss(f.id)} aria-label="Dismiss" className="rounded-lg p-1 hover:bg-white/20"><X className="size-4" /></button>
        </div>
      ))}
      <ErrorNote error={assign.error} />
      {board.data ? (
        <ErrorBoundary fallback={(retry) => <MapFailed retry={retry} />}>
          <Suspense fallback={<Skeleton className="h-[26rem] rounded-3xl" />}>
            <DispatchMap orders={orders} riders={riders} />
          </Suspense>
        </ErrorBoundary>
      ) : null}
      {board.isLoading ? (
        <Skeleton className="h-64 rounded-3xl" />
      ) : (
        <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="flex flex-col gap-3">
            {unassigned.length ? (
              <p className="rounded-2xl bg-warn-soft px-4 py-3 text-sm font-semibold text-warn">
                {unassigned.length} deliver{unassigned.length === 1 ? "y has" : "ies have"} no rider yet.
              </p>
            ) : null}
            {orders.length === 0 ? (
              <p className="rounded-3xl border border-dashed border-line py-12 text-center text-sm text-muted">No deliveries in progress.</p>
            ) : (
              orders.map((o) => {
                const late = o.status === "ready" && !o.rider_id && (mins(o.ready_at) ?? 0) >= 5;
                const canAssign = ["accepted", "preparing", "ready"].includes(o.status);
                return (
                  <article key={o.id} className={clsx("rounded-3xl border bg-surface p-4", late ? "border-bad/50 ring-2 ring-bad/20" : "border-line")}>
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div>
                        <p className="text-lg font-bold">#{o.code} · {o.hotel_name}</p>
                        <p className="text-sm text-muted">To {o.customer_name}{o.landmark ? ` · ${o.landmark}` : ""}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className={clsx("rounded-full px-3 py-1 text-sm font-semibold", STEP[o.status]?.cls)}>{STEP[o.status]?.label ?? o.status}</span>
                        <span className="money rounded-full bg-subtle px-3 py-1 text-sm font-bold">{money(o.rider_fee)}{o.rider_fee_mode === "cash" ? " cash" : ""}</span>
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
                      <span className="flex items-center gap-1.5 font-semibold">
                        <Bike className="size-4 text-brand" /> {o.rider_name ?? <span className="text-bad">No rider</span>}
                      </span>
                      {o.rider_id && !o.rider_seen ? <span className="rounded-full bg-warn-soft px-2 py-0.5 text-xs font-semibold text-warn">Not seen yet: ringing</span> : null}
                      {o.picked_up_at && ["picked_up", "on_the_way"].includes(o.status) && (mins(o.picked_up_at) ?? 0) >= 45 ? <span className="font-semibold text-bad">{mins(o.picked_up_at)} min on the road</span> : null}
                      {o.distance_km != null ? <span className="text-muted">{o.distance_km} km</span> : null}
                      {late ? <span className="font-semibold text-bad">Waiting {mins(o.ready_at)} min at the hotel</span> : null}
                      {canAssign ? (
                        <select
                          aria-label={`Assign a rider to #${o.code}`}
                          value=""
                          onChange={(e) => e.target.value && assign.mutate({ order: o.id, rider: e.target.value })}
                          className="ml-auto h-10 rounded-xl border border-line bg-surface px-3 text-sm font-semibold"
                        >
                          <option value="">{o.rider_id ? "Swap rider…" : "Assign rider…"}</option>
                          {riders.filter((r) => r.id !== o.rider_id).map((r) => (
                            <option key={r.id} value={r.id}>
                              {r.name} · {r.active_jobs ? `${r.active_jobs} job${r.active_jobs === 1 ? "" : "s"}` : r.is_online ? "free" : "offline"}
                            </option>
                          ))}
                        </select>
                      ) : null}
                    </div>
                  </article>
                );
              })
            )}
          </section>

          <aside className="rounded-3xl border border-line bg-surface p-4">
            <h2 className="mb-3 font-bold">Riders ({riders.filter((r) => r.is_online).length} online)</h2>
            {riders.length === 0 ? <p className="text-sm text-muted">No approved riders yet. Review applications under Riders.</p> : null}
            <ul className="flex flex-col gap-2">
              {riders.map((r) => (
                <li key={r.id} className="flex items-center gap-3 rounded-2xl p-2 hover:bg-subtle">
                  <span className="relative">
                    {r.photo_url ? <img src={r.photo_url} alt="" className="size-10 rounded-full object-cover" /> : <span className="flex size-10 items-center justify-center rounded-full bg-subtle"><UserRound className="size-5 text-muted" /></span>}
                    <span className={clsx("absolute -right-0.5 -bottom-0.5 size-3.5 rounded-full ring-2 ring-surface", r.is_online ? "bg-ok" : "bg-line")} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold">{r.name}</span>
                    <span className={clsx("mt-0.5 inline-block rounded-full px-2 py-0.5 text-xs font-semibold", riderState(r).cls)}>{riderState(r).label}</span>
                    {r.last_code && r.last_at ? (
                      <span className="mt-0.5 block text-xs text-muted">
                        {r.last_status === "delivered" ? "Delivered" : "Failed"} #{r.last_code} {ago(r.last_at)}
                      </span>
                    ) : null}
                  </span>
                  <a href={`tel:+${r.phone}`} aria-label={`Call ${r.name}`} className="flex size-9 items-center justify-center rounded-lg border border-line text-muted hover:text-brand"><Phone className="size-4" /></a>
                </li>
              ))}
            </ul>
            <h2 className="mt-5 mb-2 font-bold">Just finished</h2>
            {finished.length === 0 ? <p className="text-sm text-muted">Deliveries completed in the last 12 hours show here.</p> : null}
            <ul className="flex flex-col divide-y divide-line">
              {finished.slice(0, 12).map((f) => (
                <li key={f.id} className="flex items-start gap-2.5 py-2.5 text-sm">
                  {f.status === "delivered" ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-ok" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-bad" />}
                  <span className="min-w-0 flex-1">
                    <span className="block font-semibold">#{f.code} · {f.hotel_name}</span>
                    <span className="block text-xs text-muted">
                      {f.status === "delivered" ? "Delivered" : "Failed"} by {f.rider_name ?? "—"} {ago(f.closed_at)}
                      {f.picked_up_at ? ` · ${Math.max(1, Math.round((new Date(f.closed_at).getTime() - new Date(f.picked_up_at).getTime()) / 60000))} min on the road` : ""}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      )}
    </div>
  );
}
