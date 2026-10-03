/** Super admin dispatch (DECISIONS D21): every delivery in progress, who has it, and assign or
 * reassign until pickup. Riders can also take open jobs themselves. Live over SSE. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Bike, Phone, UserRound } from "lucide-react";

import { ErrorNote, Skeleton } from "../components/ui";
import { api } from "../lib/api";
import { money } from "../lib/format";

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
};
type RiderBrief = { id: string; name: string; phone: string; photo_url: string | null; is_online: boolean; active_jobs: number };

const STEP: Record<string, { label: string; cls: string }> = {
  accepted: { label: "Accepted", cls: "bg-subtle text-muted" },
  preparing: { label: "Cooking", cls: "bg-warn-soft text-warn" },
  ready: { label: "Ready at hotel", cls: "bg-brand-soft text-brand" },
  picked_up: { label: "Picked up", cls: "bg-ok-soft text-ok" },
  on_the_way: { label: "On the way", cls: "bg-ok-soft text-ok" },
};
const mins = (iso: string | null) => (iso ? Math.round((Date.now() - new Date(iso).getTime()) / 60000) : null);

export function DispatchPage() {
  const qc = useQueryClient();
  const board = useQuery({ queryKey: ["admin", "dispatch"], queryFn: () => api.get<{ orders: Row[]; riders: RiderBrief[] }>("/admin/dispatch"), refetchInterval: 20_000 });
  const assign = useMutation({
    mutationFn: ({ order, rider }: { order: string; rider: string }) => api.post(`/admin/dispatch/${order}/assign`, { rider_id: rider }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin", "dispatch"] }),
  });
  const orders = board.data?.orders ?? [];
  const riders = board.data?.riders ?? [];
  const unassigned = orders.filter((o) => !o.rider_id);

  return (
    <div className="flex flex-col gap-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold">Dispatch</h1>
        <p className="text-sm text-muted">Online riders take open jobs themselves. Step in to assign or swap a rider until the food is picked up.</p>
      </div>
      <ErrorNote error={assign.error} />
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
                              {r.name} · {r.is_online ? "online" : "offline"} · {r.active_jobs} job{r.active_jobs === 1 ? "" : "s"}
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
                    <span className="block text-xs text-muted">{r.active_jobs ? `${r.active_jobs} active job${r.active_jobs === 1 ? "" : "s"}` : r.is_online ? "Free" : "Offline"}</span>
                  </span>
                  <a href={`tel:+${r.phone}`} aria-label={`Call ${r.name}`} className="flex size-9 items-center justify-center rounded-lg border border-line text-muted hover:text-brand"><Phone className="size-4" /></a>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      )}
    </div>
  );
}
